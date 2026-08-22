"""Typed input and JSON-wrapped narrative report schemas."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Disallow accidental fields in API and LLM outputs."""

    model_config = ConfigDict(extra="forbid")


class UserSituation(StrictModel):
    purpose: str = Field(description="독립 목적")
    age: int = Field(ge=0, le=120, description="사용자 만 나이")
    employment_status: str = Field(description="재직·구직 등 현재 고용 상태")
    education_status: str = Field(description="재학·졸업 등 현재 학업 상태")
    is_homeowner: bool | None = Field(
        description="본인 명의 주택 보유 여부, 모르는 경우 null"
    )
    current_region: str = Field(description="현재 거주 지역")
    target_region: str = Field(description="희망 독립 지역")
    monthly_income_krw: int = Field(ge=0, description="월 소득(원)")
    available_cash_krw: int = Field(ge=0, description="현재 사용 가능한 자금(원)")
    move_timeline: str = Field(description="희망 독립 시기")
    housing_preference: str = Field(description="선호 주거 형태")
    priorities: list[str] = Field(description="독립 시 우선순위")
    additional_context: str = Field(description="사용자가 자유롭게 입력한 추가 상황")
    target_deposit_krw: int | None = Field(
        default=None,
        ge=0,
        description="알아본 매물의 목표 보증금, 모르는 경우 null",
    )
    target_monthly_rent_krw: int | None = Field(
        default=None,
        ge=0,
        description="알아본 매물의 목표 월세, 모르는 경우 null",
    )
    expected_management_fee_krw: int | None = Field(
        default=None,
        ge=0,
        description="예상 월 관리비, 모르는 경우 null",
    )
    other_monthly_fixed_cost_krw: int | None = Field(
        default=None,
        ge=0,
        description="주거비 외 기존 월 고정지출, 모르는 경우 null",
    )
    monthly_debt_payment_krw: int | None = Field(
        default=None,
        ge=0,
        description="월 부채 상환액, 없거나 모르는 경우 null",
    )
    estimated_food_cost_krw: int | None = Field(
        default=None,
        ge=0,
        description="예상 월 식비, 모르는 경우 null",
    )
    estimated_transport_cost_krw: int | None = Field(
        default=None,
        ge=0,
        description="예상 월 교통비, 모르는 경우 null",
    )
    estimated_utilities_and_communications_krw: int | None = Field(
        default=None,
        ge=0,
        description="예상 월 공과금과 통신비, 모르는 경우 null",
    )
    estimated_moving_cost_krw: int | None = Field(
        default=None,
        ge=0,
        description="예상 일회성 이사비, 모르는 경우 null",
    )


class RetrievedEvidence(StrictModel):
    corpus: Literal["guides", "cases", "policies"]
    source_file: str
    page_number: int = Field(ge=1)
    content: str = Field(min_length=1)
    retrieval_methods: list[Literal["vector", "keyword"]] = Field(
        default_factory=list,
        description="해당 청크를 찾은 검색 채널",
    )
    hybrid_score: float | None = Field(
        default=None,
        ge=0,
        description="Weighted RRF로 계산한 결합 점수",
    )
    matched_queries: list[str] = Field(
        default_factory=list,
        description="해당 청크가 발견된 검색 하위 질의",
    )


class GenerationRequest(StrictModel):
    situation: UserSituation
    retrieved_context: list[RetrievedEvidence] = Field(min_length=1)


class RagRequest(StrictModel):
    """Public RAG input: the user supplies only their current situation."""

    situation: UserSituation


class NarrativeDraft(StrictModel):
    """Internal grounded draft; evidence IDs are removed from the user report."""

    report_title: str
    independence_assessment: Literal[
        "독립 진행이 적절함",
        "조건 확인 후 독립이 적절함",
        "현재는 독립 연기 또는 조건 조정이 적절함",
    ]
    assessment_paragraph: str = Field(
        description="사용자 상황을 연결한 판단 이유와 판단을 바꿀 조건을 담은 존댓말 문단",
    )
    assessment_evidence_ids: list[str] = Field(
        description="판단 문단에 실제 사용한 evidence_id 목록"
    )
    execution_plan_paragraph: str = Field(
        description="집 탐색부터 계약, 이사, 입주 후까지 사용자에게 맞춘 실행 순서 문단",
    )
    execution_evidence_ids: list[str] = Field(
        description="실행 문단에 실제 사용한 evidence_id 목록"
    )
    risk_paragraph: str = Field(
        description="사용자 상황에서 가능성이 큰 위험과 조건별 대응을 설명하는 문단",
    )
    risk_evidence_ids: list[str] = Field(
        description="위험 문단에 실제 사용한 evidence_id 목록"
    )
    policy_paragraph: str = Field(
        description="적합도가 높은 지원정책 2~3개와 확인할 자격을 설명하는 문단",
    )
    policy_evidence_ids: list[str] = Field(
        description="정책 문단에 실제 사용한 policies evidence_id 목록",
    )


class NarrativeReport(StrictModel):
    """One report body wrapped in JSON for the generation smoke test."""

    report_title: str
    report_body_markdown: str = Field(
        description="제목과 문단이 구분된 하나의 종합 자취 준비 보고서 본문"
    )

    @field_validator("report_body_markdown")
    @classmethod
    def validate_report_sections(cls, body: str) -> str:
        headings = [line for line in body.splitlines() if line.startswith("## ")]
        if len(headings) != 4:
            raise ValueError("보고서에는 정확히 4개의 ## 소제목이 필요합니다.")
        if not 800 <= len(body) <= 3700:
            raise ValueError("보고서 본문은 800자 이상 3,700자 이하여야 합니다.")

        sections = re.split(r"(?m)^## .+\n", body)[1:]
        if len(sections) != 4:
            raise ValueError("소제목별 보고서 본문을 확인할 수 없습니다.")
        for index, section in enumerate(sections, start=1):
            paragraphs = [part.strip() for part in section.split("\n\n") if part.strip()]
            if len(paragraphs) != 1:
                raise ValueError(f"{index}번째 소제목에는 서술 문단 하나만 있어야 합니다.")

        list_pattern = re.compile(r"(?m)^(?!## )\s*(?:[-*+] |\d+[.)] )")
        if list_pattern.search(body):
            raise ValueError("서술형 보고서 본문에는 목록 형식을 사용할 수 없습니다.")

        required_topics = {
            "계약": ("계약",),
            "이사": ("이사",),
            "위험·주의": ("위험", "주의", "안전"),
            "지원정책": ("지원", "정책"),
        }
        missing = [
            name
            for name, keywords in required_topics.items()
            if not any(keyword in body for keyword in keywords)
        ]
        if missing:
            raise ValueError(f"보고서 필수 주제가 누락되었습니다: {', '.join(missing)}")
        if "[출처:" in body or re.search(r"\b[CGP]\d+\b", body):
            raise ValueError("사용자용 보고서에는 출처나 내부 evidence_id를 표시할 수 없습니다.")
        if ".pdf" in body.lower():
            raise ValueError("사용자용 보고서에는 원본 PDF 파일명을 표시할 수 없습니다.")
        return body
