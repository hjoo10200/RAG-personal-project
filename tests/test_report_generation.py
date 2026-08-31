"""Local tests for report assembly rules without calling the OpenAI API."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.generation.report_generator import (
    _validate_draft_lengths,
    _validate_evidence_usage,
    _validate_no_duplicate_sentences,
    _validate_personalization,
)
from src.generation.report_schema import (
    GenerationRequest,
    NarrativeDraft,
    NarrativeReport,
    RetrievedEvidence,
    UserSituation,
)


def _paragraph(topic: str, count: int) -> str:
    return " ".join(
        f"{topic}에서는 {index}번째 상황에 맞는 확인 기준과 다음 행동을 구체적으로 설명합니다."
        for index in range(1, count + 1)
    )


class ReportGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = GenerationRequest(
            situation=UserSituation(
                purpose="취업",
                age=27,
                employment_status="재직 중",
                education_status="대학교 졸업",
                is_homeowner=False,
                current_region="경기도 수원시",
                target_region="서울특별시",
                monthly_income_krw=2_200_000,
                available_cash_krw=10_000_000,
                move_timeline="3개월 이내",
                housing_preference="월세",
                priorities=["통근시간", "월 고정비", "안전"],
                additional_context="첫 자취입니다.",
                target_deposit_krw=5_000_000,
                target_monthly_rent_krw=600_000,
                expected_management_fee_krw=100_000,
                other_monthly_fixed_cost_krw=300_000,
                monthly_debt_payment_krw=0,
                estimated_food_cost_krw=350_000,
                estimated_transport_cost_krw=150_000,
                estimated_utilities_and_communications_krw=150_000,
                estimated_moving_cost_krw=500_000,
            ),
            retrieved_context=[
                RetrievedEvidence(
                    corpus="guides",
                    source_file="guide.pdf",
                    page_number=1,
                    content="계약과 이사 안내",
                ),
                RetrievedEvidence(
                    corpus="cases",
                    source_file="case.pdf",
                    page_number=1,
                    content="청년 독립 사례",
                ),
                RetrievedEvidence(
                    corpus="policies",
                    source_file="policy.pdf",
                    page_number=1,
                    content="서울 청년 월세 지원",
                ),
            ],
        )

    def _draft(self) -> NarrativeDraft:
        return NarrativeDraft(
            report_title="서울 취업 이동을 위한 첫 자취 계획",
            independence_assessment="조건 확인 후 독립이 적절함",
            assessment_paragraph=_paragraph("독립 판단", 9),
            assessment_evidence_ids=["C1"],
            execution_plan_paragraph=_paragraph("서울특별시 월세 계약과 이사", 20),
            execution_evidence_ids=["G1", "C1"],
            risk_paragraph=_paragraph("보증금과 안전 위험", 11),
            risk_evidence_ids=["G1"],
        )

    def test_internal_evidence_ids_cover_each_corpus(self) -> None:
        _validate_draft_lengths(self._draft())
        _validate_evidence_usage(
            self._draft(),
            {"G1": "guides", "C1": "cases", "P1": "policies"},
        )

    def test_user_report_accepts_personalization_without_citations(self) -> None:
        draft = self._draft()
        body = (
            "## 1. 지금 독립해도 되는지\n\n"
            "현재 판단은 **조건 확인 후 독립이 적절함**입니다. 취업을 위해 경기도 수원시에서 "
            "서울특별시로 3개월 이내 이동하는 재직 중인 사용자이며, 월세와 통근시간을 함께 "
            "판단합니다. 월 소득 220만원과 계산 후 잔액 55만원을 계약 조건에 반영합니다. "
            + draft.assessment_paragraph
            + "\n\n## 2. 나에게 맞는 집 찾기·계약·이사 순서\n\n"
            + draft.execution_plan_paragraph
            + "\n\n## 3. 내 상황에서 조심할 점\n\n"
            + draft.risk_paragraph
        )
        report = NarrativeReport(
            report_title=draft.report_title,
            report_body_markdown=body,
        )
        _validate_personalization(report.report_body_markdown, self.request)
        _validate_no_duplicate_sentences(report.report_body_markdown)

    def test_user_report_rejects_visible_source(self) -> None:
        body = "## 1. 판단\n\n[출처: guide.pdf, p.1] " + ("계약 이사 위험 지원정책입니다. " * 80)
        with self.assertRaises(ValidationError):
            NarrativeReport(report_title="잘못된 보고서", report_body_markdown=body)


if __name__ == "__main__":
    unittest.main()
