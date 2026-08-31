"""Offline tests. All model/database interactions are mocked, not executed."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from src.common.selection_input import BOUNDS, Selections, parse_request
from src.finance.calculator import CostReference, calculate_finances, classify, load_reference, subtract
from src.finance.schema import MoneyRange

ROOT = Path(__file__).resolve().parents[1]


def selection_payload(**overrides):
    values = dict(purpose="work", age=27, employment="employed", education="graduated",
                  current_region="gyeonggi", target_region="seoul", housing="monthly",
                  timeline="quarter", income_status="current", income_band="200_250",
                  cash_band="1000_1500", fixed_band="none", priorities=["safety"])
    values.update(overrides)
    return {"schema_version": "2", "selections": values}


def reference(**overrides):
    amounts = dict(deposit=5000000, moving=500000, brokerage=200000, setup=300000,
                   rent=600000, management=100000, living=900000, reserve=2000000, savings=200000)
    amounts.update(overrides)
    return CostReference(reference_id="unit-test-only", target_region="서울특별시", housing_preference="월세",
                         reviewed_on=date(2026, 1, 1), valid_until=date(2099, 1, 1),
                         assumptions=["단위 테스트 전용 가상 비용. 실사용 금지"],
                         sources=[{"title": "unit-test fixture", "url": "https://example.invalid/fixture"}],
                         amounts={k: MoneyRange.exact(v) for k,v in amounts.items()})


class SelectionTests(unittest.TestCase):
    def test_range_never_becomes_midpoint(self):
        s = parse_request(selection_payload()).situation
        self.assertIsNone(s.available_cash_krw)
        self.assertEqual(s.cash_range.model_dump(), {"lower": 10000000, "upper": 14999999})
        self.assertIsNone(s.monthly_income_krw)

    def test_money_bands_are_contiguous(self):
        for table in BOUNDS.values():
            entries = list(table.values())
            if entries[0] == (0, 0):
                entries = entries[1:]  # "none" is a state, not a continuous income band.
            for left, right in zip(entries, entries[1:]):
                self.assertEqual(left[1]+1, right[0])

    def test_invalid_code_and_unknown_fields_rejected(self):
        for fields in ({"housing":"invented"}, {"free_text":"hello"}, {"priorities":["safety","safety"]}, {"age":True}):
            with self.assertRaises(ValidationError):
                parse_request(selection_payload(**fields))

    def test_income_none_is_not_unknown(self):
        none = parse_request(selection_payload(income_status="none", income_band="unknown")).situation
        unknown = parse_request(selection_payload(income_status="unknown", income_band="unknown")).situation
        self.assertEqual(none.monthly_income_krw, 0)
        self.assertIsNone(unknown.monthly_income_krw)
        with self.assertRaises(ValidationError):
            parse_request(selection_payload(income_status="none"))

    def test_legacy_input_preserved(self):
        payload = json.loads((ROOT / "examples/inputs/real_rag_input.json").read_text(encoding="utf-8"))
        result = calculate_finances(parse_request(payload).situation)
        self.assertEqual(result.amounts["known_monthly_cost_krw"].lower, 1650000)
        self.assertEqual(result.amounts["after_known_monthly_cost_krw"].lower, 550000)
        self.assertEqual(result.initial_status, "정보 부족")  # no brokerage/setup provided


class FinanceTests(unittest.TestCase):
    def test_no_reference_no_invented_cost(self):
        result = calculate_finances(parse_request(selection_payload(fixed_band="unknown")).situation)
        self.assertEqual(result.scope, "unavailable")
        self.assertEqual(result.monthly_status, "정보 부족")
        self.assertNotIn("known_monthly_cost_krw", result.amounts)

    def test_complete_reference_keeps_interval_and_reserve(self):
        result = calculate_finances(parse_request(selection_payload()).situation, reference())
        self.assertEqual(result.scope, "complete")
        self.assertEqual(result.amounts["after_known_monthly_cost_krw"].lower, 400000)
        self.assertEqual(result.amounts["after_known_monthly_cost_krw"].upper, 899999)
        self.assertEqual(result.amounts["deposit_capacity_krw"].lower, 7000000)

    def test_deficit_generates_query_hint(self):
        result = calculate_finances(parse_request(selection_payload()).situation, reference(rent=4000000))
        self.assertEqual(result.monthly_status, "가정 범위 전체에서 부족")
        self.assertTrue(any("월 적자" in h for h in result.query_hints))

    def test_missing_personal_obligations_cannot_be_estimated(self):
        result = calculate_finances(parse_request(selection_payload(fixed_band="unknown")).situation, reference(fixed=0))
        self.assertEqual(result.monthly_status, "정보 부족")
        self.assertIn("fixed", result.missing)

    def test_planned_income_not_guaranteed(self):
        result = calculate_finances(parse_request(selection_payload(income_status="planned")).situation, reference())
        self.assertNotIn("regular_income_krw", result.amounts)
        self.assertEqual(result.monthly_status, "정보 부족")

    def test_unbounded_subtraction_and_zero_boundary(self):
        self.assertIsNone(subtract(MoneyRange(lower=0), MoneyRange(lower=0)))
        self.assertEqual(classify(MoneyRange(lower=-1, upper=0), True), "구간에 따라 달라짐")
        self.assertEqual(classify(MoneyRange.exact(0), True), "가정 범위 전체에서 비음수 잔액")
        with self.assertRaises(ValidationError):
            MoneyRange(lower=10, upper=9)

    def test_expired_and_wrong_region_reference_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refs.json"
            ref = reference().model_dump(mode="json")
            ref.update(reviewed_on="2000-01-01", valid_until="2001-01-01")
            path.write_text(json.dumps({"schema_version":"1","references":[ref]}),encoding="utf-8")
            self.assertIsNone(load_reference(parse_request(selection_payload()).situation, path))


class PipelineTests(unittest.TestCase):
    def test_report_checks_only_selected_corpora(self):
        from langchain_core.documents import Document
        from src.retrieval import hybrid_pipeline as hp
        requested=[]
        def settings(name):
            requested.append(name)
            return SimpleNamespace(validate=Mock(), collection_name=name)
        candidate=hp.ChannelCandidate(Document(page_content="계약 이사 사례", metadata={"source_file":"fixture.pdf","page_number":1,"chunk_id":"fixture"}))
        with patch.object(hp.IngestSettings,"for_corpus",side_effect=settings), patch.object(hp,"count_collection_rows",return_value=1), patch.object(hp,"check_database"), patch.object(hp,"create_embeddings"), patch.object(hp,"create_elasticsearch_client"), patch.object(hp,"count_index_documents",return_value=1), patch.object(hp,"open_collection"), patch.object(hp,"_retrieve_vector_channel",return_value=[candidate]), patch.object(hp,"_retrieve_keyword_channel",return_value=[]):
            result=hp.retrieve_hybrid_evidence(parse_request(selection_payload()).situation)
        self.assertEqual(requested,["guides","cases"])
        self.assertEqual({e.corpus for e in result.retrieved_context},{"guides","cases"})
        self.assertIsNotNone(result.financial_result)

    def test_policy_service_never_calculates_or_generates(self):
        from src import services
        with tempfile.TemporaryDirectory() as tmp, patch("src.retrieval.hybrid_pipeline.retrieve_evidence",return_value=[]) as retrieval, patch.object(services,"prepare_finances",side_effect=AssertionError("must not calculate")), patch("src.generation.report_generator.generate_narrative_report",side_effect=AssertionError("must not generate")):
            result=services.search_policies(selection_payload(),output_root=Path(tmp))
        self.assertEqual(result["policies"],[])
        self.assertEqual(retrieval.call_args.kwargs["corpora"],("policies",))

    def test_queries_use_financial_findings_not_midpoint(self):
        from src.retrieval.rag_pipeline import build_search_queries
        from src.retrieval.keyword_query_builder import build_structured_keyword_queries
        s=parse_request(selection_payload(employment="unemployed",target_region="busan")).situation
        finance=calculate_finances(s,reference(rent=4000000))
        queries=build_search_queries(s,corpora=("guides","cases"),financial_result=finance)
        self.assertNotIn("policies",queries)
        self.assertIn("월 적자"," ".join(queries["guides"]))
        policy=" ".join(build_structured_keyword_queries(s,corpora=("policies",))["policies"])
        self.assertNotIn("서울",policy)
        self.assertNotIn("근로 청년 저축",policy)


class TestPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.test_page import build_handler
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),build_handler())
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2)

    def test_page_and_options_and_offline_calculation(self):
        with urllib.request.urlopen(self.base) as response:
            self.assertIn("나의 상황",response.read().decode())
        with urllib.request.urlopen(self.base+"/api/options") as response:
            options=json.load(response)
        request=urllib.request.Request(self.base+"/api/calculate",data=json.dumps(selection_payload()).encode(),headers={"Content-Type":"application/json","Origin":self.base,"X-CSRF-Token":options["csrf"]})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.load(response)["scope"],"partial")
        request.full_url=self.base+"/api/report"
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,403)

    def test_files_and_cross_origin_are_blocked(self):
        for endpoint in ("/.env","/../../.env"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base+endpoint)
            self.assertEqual(error.exception.code,404)
        request=urllib.request.Request(self.base+"/api/calculate",data=b"{}",headers={"Content-Type":"application/json","Origin":"https://example.invalid"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,403)


if __name__ == "__main__":
    unittest.main()
