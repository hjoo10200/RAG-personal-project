"""Generate one grounded narrative report from input and retrieved evidence."""

from __future__ import annotations

import json
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from src.config import GenerationSettings
from src.generation.report_schema import GenerationRequest, NarrativeDraft, NarrativeReport


SYSTEM_PROMPT = """
당신은 처음 자취 독립을 준비하는 청년을 위한 준비 보고서 작성자다.
사용자 입력과 검색 근거만 사용하여 한국어로 자취 독립을 위한 준비 계획 보고서를 작성한다.

내부 출력은 일곱 개 주제별로 analysis_paragraph와 action_paragraph를 작성한다.
각 필드는 목록이 아닌 하나의 완전한 서술 문단이어야 한다. 프로그램이 이 문단들을
하나의 Markdown 보고서 본문으로 합치므로 문단 안에 소제목을 직접 작성하지 않는다.

보고서는 요약문이나 체크리스트가 아니라 사용자의 결정을 돕는 상세한 서술형 글이다.
전체 분량은 한국어 기준 약 3,000~4,200자가 되도록 각 문단을 충분히 자세하게 쓴다.
analysis_paragraph에서는 사용자 상황과 검색 근거가 무엇을
의미하는지 설명하고, 다음 문단에서는 실제로 무엇을 확인하고 어떤 순서로 행동해야
하는지 그 이유와 함께 자세히 설명한다. 근거가 부족하면 별도의 목록으로 넘기지 말고
해당 문단 안에서 확인이 필요한 정보와 확인 이유를 서술한다.

본문에는 다음 내용을 순서대로 종합하여 서술한다:
1. 현재 상황과 독립 방향
2. 집을 알아볼 때 필요한 부동산 정보와 계약 전 확인사항
3. 이사 전 준비, 이사 당일과 이사 직후 해야 할 일
4. 보증금·월세·관리비·공과금·식비·교통비·이사비·생활용품비 등 예상 예산
5. 자취 시작 전후의 안전, 계약, 생활비 및 행정상 주의점
6. 사용자 조건에서 검토할 수 있는 지원정책과 신청 전 확인사항
7. 실행 순서와 추가로 확인할 정보

필수 원칙:
1. 각 필드에는 줄글로 된 하나의 문단만 작성한다.
2. 불릿 목록, 번호 목록, 표, 체크박스, 단답형 항목 나열은 사용하지 않는다.
3. 문장 몇 개로 끝내지 말고 조건 사이의 관계, 판단 이유와 행동 방법을 풀어서 쓴다.
4. 검색 근거에 없는 정책 자격, 금액, 기한, 사실을 만들어내지 않는다.
5. 예산 금액은 사용자 입력이나 검색 근거에서 확인된 값만 사용한다. 초기비용,
   월 고정비, 변동비와 비상자금의 차이를 문장으로 설명한다.
6. 근거가 부족한 내용은 추정하지 말고 무엇을 어디에서 왜 추가 확인해야 하는지
   문단 안에서 구체적으로 서술한다.
7. 지원정책은 신청 가능성이 있는 후보와 자격이 확인된 정책을 명확히 구분한다.
8. 근거를 사용한 문장 끝에는 [출처: 파일명, p.페이지] 형식으로 표시한다.
9. 실제 제공된 source_file과 page_number만 출처로 사용한다.
10. 검색 근거에 등장하지 않은 지역명, 정책명, 보증금, 지원금, 신청 조건을
   예시로도 만들어내지 않는다.
11. 금액, 비율, 날짜, 기간, 연령, 신청기한, 제출서류와 행정절차 기한은 사용자
   입력 또는 검색 근거에 같은 정보가 직접 적혀 있을 때만 쓴다. 일반 상식이나
   기억으로 보충하거나 임의로 계산한 예시 값을 만들지 않는다.
12. 사용자의 연령, 무주택 여부, 실제 임대차 조건처럼 입력되지 않은 자격정보를
   추정하지 않는다. 조건이 부족하면 신청 가능성이 있다고 단정하지 말고
   후보 정책으로 소개한 뒤 확인하지 못한 조건을 명시한다.
13. 검색 근거에 없는 특정 동네, 기관, 웹사이트, 연락처를 추천하지 않는다.
14. 검색 근거가 해당 주제를 충분히 설명하지 못하면 분량을 채우기 위해 사실을
   보충하지 말고, 현재 근거로 확인되는 범위와 추가로 검색해야 할 내용을 설명한다.
""".strip()


SECTION_LAYOUT = (
    ("현재 상황과 독립 방향", "situation_and_direction"),
    ("집을 알아볼 때 필요한 부동산 정보와 계약 전 확인사항", "real_estate_and_contract"),
    ("이사 전 준비, 이사 당일과 이사 직후 해야 할 일", "moving_preparation"),
    ("자취에 필요한 예상 예산", "expected_budget"),
    ("자취 시작 전후의 주의점", "cautions_before_and_after"),
    ("도움이 되는 지원정책과 신청 전 확인사항", "support_policies"),
    ("실행 순서와 추가로 확인할 정보", "execution_and_follow_up"),
)


def create_report_model(settings: GenerationSettings) -> ChatGroq:
    """Create the LangChain ChatGroq model after validating settings."""
    settings.validate()
    return ChatGroq(
        api_key=settings.api_key,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        reasoning_effort=settings.reasoning_effort,
    )


def generate_narrative_report(
    request: GenerationRequest,
    settings: GenerationSettings | None = None,
) -> NarrativeReport:
    """Generate one paragraph-separated report wrapped in strict JSON."""
    active_settings = settings or GenerationSettings()
    llm = create_report_model(active_settings)
    structured_llm = llm.with_structured_output(
        NarrativeDraft,
        method="json_schema",
        strict=True,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                "다음 JSON을 바탕으로 하나의 종합 자취 준비 보고서를 작성하세요.\n"
                "{payload}",
            ),
        ]
    )
    result = (prompt | structured_llm).invoke(
        {"payload": json.dumps(request.model_dump(), ensure_ascii=False)}
    )
    draft = result if isinstance(result, NarrativeDraft) else NarrativeDraft.model_validate(result)
    source_references = list(
        dict.fromkeys(
            f"[출처: {evidence.source_file}, p.{evidence.page_number}]"
            for evidence in request.retrieved_context
        )
    )
    source_note = "이 보고서 작성에 사용한 검색 근거는 " + " ".join(source_references) + "입니다."
    sections: list[str] = []
    for index, (heading, field_name) in enumerate(SECTION_LAYOUT, start=1):
        section = getattr(draft, field_name)
        action_paragraph = section.action_paragraph.strip()
        if index == len(SECTION_LAYOUT):
            action_paragraph = f"{action_paragraph} {source_note}"
        sections.append(
            f"## {index}. {heading}\n\n"
            f"{section.analysis_paragraph.strip()}\n\n"
            f"{action_paragraph}"
        )
    report = NarrativeReport(
        report_title=draft.report_title,
        report_body_markdown="\n\n".join(sections),
    )
    allowed_sources = {
        (evidence.source_file, evidence.page_number)
        for evidence in request.retrieved_context
    }
    cited_sources = {
        (filename.strip(), int(page))
        for filename, page in re.findall(
            r"\[출처:\s*([^,\]]+),\s*p\.(\d+)\]",
            report.report_body_markdown,
        )
    }
    invalid_sources = cited_sources - allowed_sources
    if invalid_sources:
        raise ValueError(f"입력 검색 근거에 없는 출처가 포함되었습니다: {invalid_sources}")
    return report
