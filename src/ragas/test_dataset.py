"""Create a project-specific RAGAS test dataset from the active PDF corpus.

The output deliberately contains two kinds of samples:

1. RAGAS-generated document-grounding probes for retrieval and faithfulness tests.
2. Manually curated structured situations matching this project's real RAG input.

Run with ``--manual-only`` to validate the local corpus and create the end-to-end
scenario rows without making OpenAI API calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from dotenv import load_dotenv
from langchain_core.documents import Document

from src.config import CORPUS_NAMES, PROJECT_ROOT, GenerationSettings, get_corpus_config
from src.generation.report_schema import RagRequest, UserSituation
from src.ingestion.pdf_pipeline import discover_pdfs, load_pdf_pages


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "ragas"
DEFAULT_JSONL_OUTPUT = DEFAULT_OUTPUT_DIR / "ragas_test_dataset.jsonl"
DEFAULT_CSV_OUTPUT = DEFAULT_OUTPUT_DIR / "ragas_test_dataset.csv"
DEFAULT_TIKTOKEN_CACHE = PROJECT_ROOT / "storage" / "cache" / "tiktoken"

CATEGORY_BY_SYNTHESIZER = {
    "single_hop_specific_query_synthesizer": "single_hop_specific",
    "multi_hop_specific_query_synthesizer": "multi_hop_specific",
    "multi_hop_abstract_query_synthesizer": "multi_hop_abstract",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--testset-size",
        type=int,
        default=12,
        help="RAGAS가 자동 생성할 문서 기반 질문 수(기본 12)",
    )
    parser.add_argument(
        "--max-pages-per-pdf",
        type=int,
        default=8,
        help="비용 통제를 위해 PDF 한 개에서 사용할 최대 텍스트 페이지 수",
    )
    parser.add_argument(
        "--min-page-chars",
        type=int,
        default=250,
        help="자동 생성 자료로 사용할 페이지의 최소 글자 수",
    )
    parser.add_argument(
        "--generator-model",
        default=os.getenv(
            "RAGAS_TESTSET_MODEL",
            os.getenv("RAGAS_GENERATOR_MODEL", GenerationSettings().model),
        ),
        help="질문·기준 답변 생성 모델(기본: 실제 RAG 보고서 생성 모델)",
    )
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        help="RAGAS 지식 그래프 구성용 임베딩 모델",
    )
    parser.add_argument(
        "--manual-only",
        action="store_true",
        help="OpenAI/RAGAS 자동 생성 없이 수동 종단 간 사례만 저장",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_JSONL_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    return parser.parse_args()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _evenly_spaced(items: list[Document], limit: int) -> list[Document]:
    """Select deterministic pages across an entire PDF, not only its front matter."""
    if limit <= 0:
        raise ValueError("max-pages-per-pdf는 1 이상이어야 합니다.")
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[len(items) // 2]]
    indices = {
        round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)
    }
    return [items[index] for index in sorted(indices)]


def load_active_documents(
    *, max_pages_per_pdf: int, min_page_chars: int
) -> tuple[list[Document], list[Document]]:
    """Return a generation sample and all text-rich pages for reference curation."""
    if min_page_chars < 1:
        raise ValueError("min-page-chars는 1 이상이어야 합니다.")

    selected: list[Document] = []
    all_text_pages: list[Document] = []
    for corpus in CORPUS_NAMES:
        config = get_corpus_config(corpus)
        pdf_paths = discover_pdfs(config.pdf_dir)
        loaded_pages = load_pdf_pages(pdf_paths, PROJECT_ROOT, corpus)

        by_source: dict[str, list[Document]] = {}
        for page in loaded_pages:
            normalized = _normalize_text(page.page_content)
            if len(normalized) < min_page_chars:
                continue
            page.page_content = normalized
            by_source.setdefault(str(page.metadata["source_file"]), []).append(page)
            all_text_pages.append(page)

        for pdf_path in pdf_paths:
            pages = by_source.get(pdf_path.name, [])
            if not pages:
                raise ValueError(
                    f"평가 데이터 생성에 사용할 텍스트 페이지가 없습니다: {pdf_path.name}"
                )
            chosen = _evenly_spaced(pages, max_pages_per_pdf)
            selected.extend(chosen)
            print(
                f"[select] corpus={corpus} source={pdf_path.name} "
                f"usable={len(pages)} selected={len(chosen)}"
            )

    if not selected:
        raise ValueError("평가 데이터 생성에 사용할 문서 페이지가 없습니다.")
    return selected, all_text_pages


def _find_contexts(
    documents: list[Document],
    *,
    source_files: Iterable[str],
    keywords: Iterable[str],
    limit: int = 3,
) -> list[str]:
    """Pick real page contexts for a curated scenario without fragile indices."""
    sources = set(source_files)
    terms = tuple(keywords)
    candidates = [
        document
        for document in documents
        if str(document.metadata.get("source_file")) in sources
    ]
    if not candidates:
        raise ValueError(f"수동 평가 사례의 근거 문서를 찾지 못했습니다: {sorted(sources)}")

    ranked = sorted(
        candidates,
        key=lambda document: (
            sum(document.page_content.count(term) for term in terms),
            len(document.page_content),
        ),
        reverse=True,
    )
    return [document.page_content[:2200] for document in ranked[:limit]]


def _situation_as_user_input(situation: UserSituation) -> str:
    """Represent the structured UI values as the text seen by RAGAS metrics."""
    priority_text = ", ".join(situation.priorities)
    return (
        f"만 {situation.age}세 {situation.employment_status} 청년이 "
        f"{situation.purpose} 때문에 {situation.current_region}에서 "
        f"{situation.target_region}로 {situation.move_timeline}에 "
        f"{situation.housing_preference} 자취를 시작하려고 합니다. "
        f"월 소득은 {situation.monthly_income_krw:,}원, 사용 가능한 자금은 "
        f"{situation.available_cash_krw:,}원이고 우선순위는 {priority_text}입니다. "
        f"추가 상황은 다음과 같습니다: {situation.additional_context} "
        "지금 독립이 적절한지, 집 찾기·계약·이사 순서, 주의할 위험과 "
        "우선 확인할 지원정책을 개인 상황에 맞춰 보고서로 설명해 주세요."
    )


def _manual_case(
    *,
    case_id: str,
    situation_payload: dict[str, Any],
    reference: str,
    reference_contexts: list[str],
    evaluation_focus: str,
) -> dict[str, Any]:
    situation = UserSituation.model_validate(situation_payload)
    RagRequest(situation=situation)
    return {
        "sample_id": case_id,
        "dataset_role": "end_to_end_scenario",
        "query_category": "structured_situation",
        "persona_name": "첫 자취 준비 청년",
        "user_input": _situation_as_user_input(situation),
        "reference": reference,
        "reference_contexts": reference_contexts,
        "situation_json": situation.model_dump(),
        "evaluation_focus": evaluation_focus,
        "synthesizer_name": "manual_project_scenario",
        "reference_generation_model": "human_curated",
    }


def build_manual_cases(documents: list[Document]) -> list[dict[str, Any]]:
    """Build representative and failure-oriented cases for the real UI schema."""
    housing_and_moving = _find_contexts(
        documents,
        source_files=(
            "standard_housing_lease_contract_2023.pdf",
            "housing_lease_protection_guide_2020.pdf",
            "easylaw_moving_guide_2026.pdf",
        ),
        keywords=("임대차", "계약", "등기", "수리", "이사", "보증금"),
    )
    lived_experience = _find_contexts(
        documents,
        source_files=(
            "youth_housing_job_access_interviews_2023.pdf",
            "youth_one_person_household_living_cost_2022.pdf",
            "youth_one_person_living_risk_interviews_2023.pdf",
        ),
        keywords=("주거비", "생활비", "통근", "안전", "1인 가구"),
    )
    seoul_policy = _find_contexts(
        documents,
        source_files=(
            "seoul_youth_moving_brokerage_support_2026.pdf",
            "seoul_youth_monthly_rent_notice_2026.pdf",
            "seoul_youth_monthly_rent_faq_2026.pdf",
            "seoul_hope_double_youth_account_notice_2026.pdf",
        ),
        keywords=("신청", "지원", "서울", "월세", "이사비", "자격"),
    )
    student_policy = _find_contexts(
        documents,
        source_files=(
            "kosaf_housing_stability_scholarship_plan_2026.pdf",
            "lh_seoul_youth_purchase_rental_notice_2026_2nd.pdf",
        ),
        keywords=("대학생", "주거", "학자금", "임대", "신청"),
    )

    base_optional = {
        "target_deposit_krw": None,
        "target_monthly_rent_krw": None,
        "expected_management_fee_krw": None,
        "other_monthly_fixed_cost_krw": None,
        "monthly_debt_payment_krw": None,
        "estimated_food_cost_krw": None,
        "estimated_transport_cost_krw": None,
        "estimated_utilities_and_communications_krw": None,
        "estimated_moving_cost_krw": None,
    }

    return [
        _manual_case(
            case_id="scenario_employed_suwon_to_seoul",
            situation_payload={
                **base_optional,
                "purpose": "취업 통근",
                "age": 27,
                "employment_status": "재직 중",
                "education_status": "대학교 졸업",
                "is_homeowner": False,
                "current_region": "경기도 수원시",
                "target_region": "서울특별시",
                "monthly_income_krw": 2_200_000,
                "available_cash_krw": 10_000_000,
                "move_timeline": "3개월 이내",
                "housing_preference": "월세 원룸",
                "priorities": ["통근시간", "월 고정비", "안전"],
                "additional_context": "첫 자취이며 보증금과 계약 위험이 걱정됩니다.",
                "target_deposit_krw": 5_000_000,
                "target_monthly_rent_krw": 600_000,
                "expected_management_fee_krw": 100_000,
                "estimated_moving_cost_krw": 500_000,
            },
            reference=(
                "통근시간 단축이라는 독립 목적을 기준으로 조건부 진행 판단을 내려야 합니다. "
                "보고서는 서울 후보지와 매물을 동일 기준으로 비교하고, 현장 하자·임대인·권리관계·"
                "관리비·수리 책임·특약을 확인한 뒤 계약하며, 이사업체 견적과 이사 당일 인계를 "
                "시간 순서로 설명해야 합니다. 월세 외 관리비와 초기비용 위험을 짚고 서울 청년 "
                "월세 및 중개보수·이사비 정책은 전입·연령·소득·주택 조건을 확인해야 한다고 "
                "설명하되 자격을 확정해서는 안 됩니다."
            ),
            reference_contexts=housing_and_moving + lived_experience + seoul_policy,
            evaluation_focus="개인화, 실행 순서, 계약 안전, 서울 정책 근거성",
        ),
        _manual_case(
            case_id="scenario_jobseeker_low_cash_urgent_move",
            situation_payload={
                **base_optional,
                "purpose": "구직과 면접 접근성",
                "age": 24,
                "employment_status": "구직 중",
                "education_status": "대학교 졸업",
                "is_homeowner": False,
                "current_region": "충청남도 천안시",
                "target_region": "서울특별시",
                "monthly_income_krw": 0,
                "available_cash_krw": 2_500_000,
                "move_timeline": "1개월 이내",
                "housing_preference": "월세 또는 공공임대",
                "priorities": ["초기비용", "구직 접근성", "안전"],
                "additional_context": "소득이 생기기 전에도 서울로 먼저 가야 하는지 고민됩니다.",
            },
            reference=(
                "현재 소득과 짧은 준비기간 때문에 즉시 민간 월세 계약을 확정하기보다 이동 시기나 "
                "주거 조건을 조정하는 판단이 우선입니다. 구직 접근성의 이익과 보증금·월 고정비·"
                "비상자금 소진 위험을 함께 설명하고, 공공임대 가능성과 정책 자격을 확인하는 동안 "
                "단기 이동 대안을 검토해야 합니다. 근거에 없는 적정 주거비 비율이나 정책 수혜를 "
                "만들어서는 안 됩니다."
            ),
            reference_contexts=lived_experience + housing_and_moving + seoul_policy,
            evaluation_focus="독립 연기·조건 조정 판단, 불확실성 표현, 환각 방지",
        ),
        _manual_case(
            case_id="scenario_graduate_student_to_seoul",
            situation_payload={
                **base_optional,
                "purpose": "대학원 진학",
                "age": 28,
                "employment_status": "시간제 근로",
                "education_status": "대학원 입학 예정",
                "is_homeowner": False,
                "current_region": "대전광역시",
                "target_region": "서울특별시",
                "monthly_income_krw": 1_200_000,
                "available_cash_krw": 7_000_000,
                "move_timeline": "4개월 이내",
                "housing_preference": "학교 인근 월세 또는 공공임대",
                "priorities": ["학교 접근성", "주거비", "학업 지속"],
                "additional_context": "학기 중 근로시간이 줄어들 가능성이 있습니다.",
            },
            reference=(
                "학교 접근성뿐 아니라 학기 중 소득 감소 가능성을 판단 조건으로 반영해야 합니다. "
                "학교 인근 월세와 교통비를 포함한 외곽 주거를 비교하고 계약·이사 절차를 설명해야 "
                "합니다. 대학생·대학원생 여부, 원거리 진학, 소득 등 확인되지 않은 자격을 구분해 "
                "주거안정장학금이나 공공임대를 검토하되 지원 가능성을 단정해서는 안 됩니다."
            ),
            reference_contexts=housing_and_moving + lived_experience + student_policy,
            evaluation_focus="소득 변동 반영, 대안 비교, 학생 정책 자격의 정확성",
        ),
        _manual_case(
            case_id="scenario_incomplete_cost_inputs",
            situation_payload={
                **base_optional,
                "purpose": "직장 이동",
                "age": 31,
                "employment_status": "재직 중",
                "education_status": "대학교 졸업",
                "is_homeowner": None,
                "current_region": "인천광역시",
                "target_region": "서울특별시",
                "monthly_income_krw": 3_000_000,
                "available_cash_krw": 8_000_000,
                "move_timeline": "6개월 이내",
                "housing_preference": "월세",
                "priorities": ["계약 안전", "야간 안전", "통근시간"],
                "additional_context": "아직 매물을 보지 않아 보증금·월세·관리비를 모릅니다.",
            },
            reference=(
                "비용 입력이 비어 있으므로 감당 가능성을 확정하거나 임의의 금액을 채우지 말아야 "
                "합니다. 대신 후보 매물의 보증금·월세·관리비 포함 항목을 수집해 비교한 뒤 판단을 "
                "갱신하는 절차를 제시해야 합니다. 주택 보유 여부처럼 정책 자격에 영향을 주는 미확인 "
                "조건도 명시하고, 확인 전에는 정책 대상이라고 단정하지 않아야 합니다."
            ),
            reference_contexts=housing_and_moving + seoul_policy,
            evaluation_focus="결측 입력 처리, 숫자 환각 방지, 정책 자격 불확실성",
        ),
        _manual_case(
            case_id="scenario_non_seoul_policy_coverage",
            situation_payload={
                **base_optional,
                "purpose": "취업",
                "age": 26,
                "employment_status": "입사 예정",
                "education_status": "대학교 졸업",
                "is_homeowner": False,
                "current_region": "경상남도 창원시",
                "target_region": "부산광역시",
                "monthly_income_krw": 2_400_000,
                "available_cash_krw": 9_000_000,
                "move_timeline": "2개월 이내",
                "housing_preference": "월세 원룸",
                "priorities": ["직장 접근성", "안전", "고정비"],
                "additional_context": "부산에서 받을 수 있는 지원정책도 알고 싶습니다.",
            },
            reference=(
                "계약·이사와 실제 청년 이동 사례에 관한 일반 근거는 활용할 수 있지만, 현재 정책 "
                "코퍼스가 주로 서울 정책이므로 이를 부산 거주자에게 적용해서는 안 됩니다. 부산의 "
                "구체적인 최신 지원정책이 근거에 없다면 정보 범위를 솔직히 밝히고 별도 확인이 "
                "필요하다고 해야 합니다. 서울 정책명이나 자격을 부산 정책처럼 제시하면 안 됩니다."
            ),
            reference_contexts=housing_and_moving + lived_experience + seoul_policy,
            evaluation_focus="지역 불일치 탐지, 정책 환각·오적용 방지",
        ),
    ]


def _remove_custom_node_filter(transform_steps: list[Any]) -> list[Any]:
    # RAGAS 0.3.9에서 일부 OpenAI JSON 응답과 충돌했던 필터만 제외합니다.
    from ragas.testset.transforms.filters import CustomNodeFilter

    return [
        transform
        for transform in transform_steps
        if not isinstance(transform, CustomNodeFilter)
    ]


def _create_ragas_components(model: str, embedding_model: str) -> tuple[Any, Any]:
    """Import RAGAS lazily so --manual-only can run without the package/API."""
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    from langchain_openai import ChatOpenAI
    from openai import OpenAI
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms.base import LangchainLLMWrapper

    generator_chat_llm = ChatOpenAI(model=model, timeout=120, max_retries=2)
    generator_llm = LangchainLLMWrapper(generator_chat_llm)
    generator_embeddings = OpenAIEmbeddings(
        client=OpenAI(),
        model=embedding_model,
    )
    return generator_llm, generator_embeddings


async def _adapt_synthesizers_to_korean(
    distribution: list[tuple[Any, float]], generator_llm: Any
) -> None:
    for synthesizer, _ in distribution:
        prompts = await synthesizer.adapt_prompts("korean", llm=generator_llm)
        synthesizer.set_prompts(**prompts)


def generate_document_probes(
    documents: list[Document],
    *,
    testset_size: int,
    generator_model: str,
    embedding_model: str,
) -> list[dict[str, Any]]:
    """Generate grounded Korean probes with more multi-hop than vanilla RAGAS."""
    if testset_size < 1:
        raise ValueError("testset-size는 1 이상이어야 합니다.")

    from ragas.testset import TestsetGenerator
    from ragas.testset.synthesizers.multi_hop.abstract import (
        MultiHopAbstractQuerySynthesizer,
    )
    from ragas.testset.synthesizers.multi_hop.specific import (
        MultiHopSpecificQuerySynthesizer,
    )
    from ragas.testset.synthesizers.single_hop.specific import (
        SingleHopSpecificQuerySynthesizer,
    )
    from ragas.testset.transforms import default_transforms

    generator_llm, generator_embeddings = _create_ragas_components(
        generator_model, embedding_model
    )
    generator = TestsetGenerator(
        llm=generator_llm,
        embedding_model=generator_embeddings,
        persona_list=_project_personas(),
    )
    transforms = _remove_custom_node_filter(
        default_transforms(
            documents,
            llm=generator_llm,
            embedding_model=generator_embeddings,
        )
    )
    distribution = [
        (SingleHopSpecificQuerySynthesizer(llm=generator_llm), 0.35),
        (MultiHopSpecificQuerySynthesizer(llm=generator_llm), 0.40),
        (MultiHopAbstractQuerySynthesizer(llm=generator_llm), 0.25),
    ]
    asyncio.run(_adapt_synthesizers_to_korean(distribution, generator_llm))

    dataset = generator.generate_with_langchain_docs(
        documents,
        testset_size=testset_size,
        transforms=transforms,
        query_distribution=distribution,
        raise_exceptions=True,
    )
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(dataset.to_list(), start=1):
        item = dict(row)
        synthesizer_name = str(item.get("synthesizer_name", ""))
        item.update(
            {
                "sample_id": f"ragas_generated_{index:03d}",
                "dataset_role": "document_grounding_probe",
                "query_category": CATEGORY_BY_SYNTHESIZER.get(
                    synthesizer_name, "ragas_generated"
                ),
                "situation_json": None,
                "evaluation_focus": "검색 관련성, 문맥 정밀도, 답변 충실도",
                "reference_generation_model": generator_model,
            }
        )
        rows.append(item)
    return rows


def _project_personas() -> list[Any]:
    from ragas.testset.persona import Persona

    return [
        Persona(
            name="첫 자취를 준비하는 취업 청년",
            role_description=(
                "취업 또는 통근 때문에 본가를 떠나며, 계약 절차와 이사 순서를 처음 접하고 "
                "자신의 지역·일정·자금에 맞는 구체적인 행동을 알고 싶은 청년"
            ),
        ),
        Persona(
            name="소득이 불안정한 구직자·학생",
            role_description=(
                "제한된 현금과 변동 가능한 소득 때문에 독립 시기와 주거 조건을 비교하고, "
                "지원정책의 실제 자격과 대안을 신중하게 확인해야 하는 청년"
            ),
        ),
        Persona(
            name="청년 주거·정책 상담자",
            role_description=(
                "임대차계약, 이사, 1인 가구 생활 위험과 정부·지자체 공고를 함께 검토하여 "
                "확인된 근거와 미확인 조건을 구분하고 실행 순서를 설명하는 상담자"
            ),
        ),
    ]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    return str(value)


def validate_rows(rows: list[dict[str, Any]]) -> None:
    required = {"sample_id", "dataset_role", "user_input", "reference"}
    ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{index}번째 평가 행의 필수 필드 누락: {sorted(missing)}")
        sample_id = str(row["sample_id"])
        if sample_id in ids:
            raise ValueError(f"중복 sample_id입니다: {sample_id}")
        ids.add(sample_id)
        if not str(row["user_input"]).strip() or not str(row["reference"]).strip():
            raise ValueError(f"질문 또는 reference가 비어 있습니다: {sample_id}")


def write_dataset(
    rows: list[dict[str, Any]], jsonl_path: Path, csv_path: Path
) -> None:
    safe_rows = [_json_safe(row) for row in rows]
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in safe_rows) + "\n",
        encoding="utf-8",
    )

    csv_rows: list[dict[str, Any]] = []
    for row in safe_rows:
        csv_rows.append(
            {
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (list, dict))
                else value
                for key, value in row.items()
            }
        )
    pd.DataFrame(csv_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")


def print_summary(rows: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(rows)
    print(f"[shape] rows={frame.shape[0]} columns={frame.shape[1]}")
    first = rows[0]
    print(f"[sample] id={first.get('sample_id', 'unknown')}")
    print(f"[sample] Query: {_console_preview(first.get('user_input', ''))}")
    print(f"[sample] Reference: {_console_preview(first.get('reference', ''))}")
    contexts = first.get("reference_contexts")
    if isinstance(contexts, list):
        print(f"[sample] Reference contexts: {len(contexts)}개")
    for column in ("dataset_role", "query_category", "persona_name"):
        if column in frame.columns:
            distribution = frame[column].fillna("unknown").value_counts()
            rendered = ", ".join(
                f"{name}={count}" for name, count in distribution.items()
            )
            print(f"[distribution] {column}: {rendered}")
    print(f"[ok] 총 평가 문항: {len(frame)}")


def _console_preview(value: Any, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def main() -> None:
    _configure_utf8_console()
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    # RAGAS 0.3.9 imports o200k_base on first use. Keep the one-time download
    # inside this project instead of relying on a user-global temporary cache.
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(DEFAULT_TIKTOKEN_CACHE))
    generation_documents, reference_documents = load_active_documents(
        max_pages_per_pdf=args.max_pages_per_pdf,
        min_page_chars=args.min_page_chars,
    )
    rows = build_manual_cases(reference_documents)
    if not args.manual_only:
        rows = generate_document_probes(
            generation_documents,
            testset_size=args.testset_size,
            generator_model=args.generator_model,
            embedding_model=args.embedding_model,
        ) + rows

    validate_rows(rows)
    write_dataset(rows, args.output, args.csv_output)
    print_summary(rows)
    print(f"[ok] JSONL 저장: {args.output.resolve()}")
    print(f"[ok] CSV 저장: {args.csv_output.resolve()}")


if __name__ == "__main__":
    main()
