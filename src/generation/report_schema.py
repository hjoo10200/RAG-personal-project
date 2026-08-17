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
    current_region: str = Field(description="현재 거주 지역")
    target_region: str = Field(description="희망 독립 지역")
    monthly_income_krw: int = Field(ge=0, description="월 소득(원)")
    available_cash_krw: int = Field(ge=0, description="현재 사용 가능한 자금(원)")
    move_timeline: str = Field(description="희망 독립 시기")
    housing_preference: str = Field(description="선호 주거 형태")
    priorities: list[str] = Field(description="독립 시 우선순위")
    additional_context: str = Field(description="사용자가 자유롭게 입력한 추가 상황")


class RetrievedEvidence(StrictModel):
    corpus: Literal["guides", "cases", "policies"]
    source_file: str
    page_number: int = Field(ge=1)
    content: str = Field(min_length=1)


class GenerationRequest(StrictModel):
    situation: UserSituation
    retrieved_context: list[RetrievedEvidence] = Field(min_length=1)


class RagRequest(StrictModel):
    """Public RAG input: the user supplies only their current situation."""

    situation: UserSituation


class NarrativeSectionDraft(StrictModel):
    """Two prose paragraphs used internally to assemble one report section."""

    analysis_paragraph: str = Field(
        description="사용자 상황과 검색 근거의 의미를 설명하는 상세한 서술 문단"
    )
    action_paragraph: str = Field(
        description="실제 확인 및 행동 방법과 그 이유를 설명하는 상세한 서술 문단"
    )


class NarrativeDraft(StrictModel):
    """Internal generation schema; rendered into one NarrativeReport body."""

    report_title: str
    situation_and_direction: NarrativeSectionDraft
    real_estate_and_contract: NarrativeSectionDraft
    moving_preparation: NarrativeSectionDraft
    expected_budget: NarrativeSectionDraft
    cautions_before_and_after: NarrativeSectionDraft
    support_policies: NarrativeSectionDraft
    execution_and_follow_up: NarrativeSectionDraft


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
        if len(headings) < 7:
            raise ValueError("보고서에는 7개 이상의 ## 소제목이 필요합니다.")
        if len(body) < 3000:
            raise ValueError("상세 서술형 보고서 본문은 3,000자 이상이어야 합니다.")

        sections = re.split(r"(?m)^## .+\n", body)[1:]
        if len(sections) < 7:
            raise ValueError("소제목별 보고서 본문을 확인할 수 없습니다.")
        for index, section in enumerate(sections, start=1):
            paragraphs = [part.strip() for part in section.split("\n\n") if part.strip()]
            if len(paragraphs) < 2:
                raise ValueError(
                    f"{index}번째 소제목에는 두 개 이상의 서술 문단이 필요합니다."
                )

        list_pattern = re.compile(r"(?m)^(?!## )\s*(?:[-*+] |\d+[.)] )")
        if list_pattern.search(body):
            raise ValueError("서술형 보고서 본문에는 목록 형식을 사용할 수 없습니다.")

        required_topics = {
            "부동산·계약": ("부동산", "계약"),
            "이사": ("이사",),
            "예산": ("예산", "생활비"),
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
        return body
