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


class NarrativeSectionDraft(StrictModel):
    """Two prose paragraphs used internally to assemble one report section."""

    analysis_paragraph: str = Field(
        description="사용자 상황과 검색 근거의 의미를 존댓말로 설명하는 상세한 서술 문단"
    )
    action_paragraph: str = Field(
        description="실제 확인 및 행동 방법과 그 이유를 존댓말로 설명하는 상세한 서술 문단"
    )


class AssessmentSectionDraft(StrictModel):
    """One concise assessment paragraph so budget calculations are not repeated."""

    assessment_paragraph: str = Field(
        description="독립 목적과 우선순위 중심의 판단 및 보조적인 예산 판단을 담은 존댓말 문단"
    )


class NarrativeDraft(StrictModel):
    """Internal generation schema; rendered into one NarrativeReport body."""

    report_title: str
    independence_assessment: Literal[
        "독립 진행이 적절함",
        "조건 확인 후 독립이 적절함",
        "현재는 독립 연기 또는 조건 조정이 적절함",
    ]
    situation_and_assessment: AssessmentSectionDraft
    housing_search_and_contract: NarrativeSectionDraft
    moving_and_settlement: NarrativeSectionDraft
    cautions_before_and_after: NarrativeSectionDraft
    support_policies: NarrativeSectionDraft


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
        if len(headings) < 5:
            raise ValueError("보고서에는 5개 이상의 ## 소제목이 필요합니다.")
        if len(body) < 2400:
            raise ValueError("상세 서술형 보고서 본문은 2,400자 이상이어야 합니다.")

        sections = re.split(r"(?m)^## .+\n", body)[1:]
        if len(sections) < 5:
            raise ValueError("소제목별 보고서 본문을 확인할 수 없습니다.")
        for index, section in enumerate(sections, start=1):
            paragraphs = [part.strip() for part in section.split("\n\n") if part.strip()]
            minimum_paragraphs = 1 if index == 1 else 2
            if len(paragraphs) < minimum_paragraphs:
                raise ValueError(
                    f"{index}번째 소제목에는 {minimum_paragraphs}개 이상의 서술 문단이 필요합니다."
                )

        list_pattern = re.compile(r"(?m)^(?!## )\s*(?:[-*+] |\d+[.)] )")
        if list_pattern.search(body):
            raise ValueError("서술형 보고서 본문에는 목록 형식을 사용할 수 없습니다.")

        required_topics = {
            "부동산·계약": ("부동산", "계약"),
            "이사": ("이사",),
            "주의점": ("주의", "안전"),
            "지원정책": ("지원", "정책"),
        }
        missing = [
            name
            for name, keywords in required_topics.items()
            if not any(keyword in body for keyword in keywords)
        ]
        if missing:
            raise ValueError(f"보고서 필수 주제가 누락되었습니다: {', '.join(missing)}")
        if "[출처:" not in body:
            raise ValueError("보고서 본문에 최소 하나 이상의 출처 표시가 필요합니다.")
        citation_markers = re.findall(r"\[출처:[^\]]+\]", body)
        citation_pattern = re.compile(r"\[출처:\s*[^,\]]+,\s*p\.\d+\]")
        malformed = [
            marker for marker in citation_markers if not citation_pattern.fullmatch(marker)
        ]
        if malformed:
            raise ValueError(f"잘못된 출처 표시 형식이 있습니다: {malformed}")
        return body
