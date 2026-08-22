"""Generate a concise, personalized report from retrieved RAG evidence."""

from __future__ import annotations

import json
import re
from datetime import date

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.config import GenerationSettings
from src.generation.report_schema import GenerationRequest, NarrativeDraft, NarrativeReport


SYSTEM_PROMPT = """
당신은 첫 자취를 준비하는 청년에게 개인별 실행 결정을 설명하는 보고서 작성자입니다.
사용자 입력과 계산 결과, 검색 근거만 사용하고 한국어 존댓말로 작성합니다.

목표
- 일반적인 자취 안내서를 쓰지 말고, 이 사용자의 지역 이동·목적·일정·주거 형태·우선순위·자금을 연결합니다.
- 핵심 질문은 얼마가 드는지가 아니라 지금 독립이 적절한지와 실제로 어떤 순서로 행동할지입니다.
- 서로 다른 필드에 같은 조언이나 입력값을 반복하지 않습니다.

네 문단
1. assessment_paragraph는 대략 200~500자로 씁니다. 현재 지역과 목표 지역, 독립 목적, 이동 시기,
주거 형태, 우선순위를 연결해 판단하고, 현재 진행에 유리한 조건과 계약 전에 확인해야 판단이
바뀌는 조건을 구분합니다. 예산은 판단에 필요한 경우에만 한두 문장으로 설명합니다.
2. execution_plan_paragraph는 대략 450~1,000자로 씁니다. 먼저 후보 지역을 좁히는 기준, 매물 간
비교 항목, 현장 방문에서 확인할 상태, 계약 직전 확인할 계약 상대방·권리관계·금액·관리비·
수리 책임·특약, 이사업체 견적 비교, 이사 당일 인계 확인, 입주 후 생활 점검을 시간 순서로
설명합니다. 각 단계에서 문제가 발견되면 계약 보류, 다른 후보 탐색, 계약서 반영 중 어떤
다음 행동을 해야 하는지 함께 씁니다.
3. risk_paragraph는 대략 250~650자로 씁니다. 이 사용자의 입력과 검색 근거에서 가능성이 큰 위험
세 가지 안팎만 선별하고, 위험이 현실화되는 신호와 그때 조정할 계약 조건·이동 일정·지출·
주거 선택을 연결합니다. 앞 문단의 체크 항목을 그대로 반복하지 않습니다.
4. policy_paragraph는 대략 300~700자로 씁니다. 현재 입력과 가장 잘 맞는 정책 2~3개만 골라 정책별로
맞는 사용자 조건, 아직 확인되지 않은 자격, 독립 과정 중 확인할 시점, 자격이 맞지 않을 때의
대안을 설명합니다. 정책명을 나열한 뒤 모두 최신 공고를 확인하라는 문장으로 끝내지 않습니다.

개인화 기준
- target_region, housing_preference, move_timeline과 priorities 중 하나 이상을 실제 판단과 행동에 사용합니다.
- 소득과 보유자금은 나열하지 말고 계약 가능성 또는 조정 조건을 설명할 때만 사용합니다.
- cases 근거에서 얻은 실제 청년의 경험이나 생활비·주거 선택 시사점을 적어도 하나의 문단에 자연스럽게 반영합니다.
- 사용자의 상황과 무관한 정책, 지역, 대출, 동네를 추가하지 않습니다.
- `확인해야 합니다`라고만 쓰지 말고 확인 대상, 비교 기준, 확인 결과에 따른 다음 행동을 한 문장 안에서 연결합니다.
- 사용자의 입력값을 서두에 나열하지 말고 해당 값 때문에 일반적인 자취 계획과 달라지는 행동을 설명합니다.

근거와 출력
- 각 문단의 evidence_ids에는 실제로 사용한 evidence_id만 넣습니다.
- 정책 문단은 P로 시작하는 근거만 사용하고 최대 3개 정책만 다룹니다.
- 보고서 문단에는 evidence_id, 파일명, 페이지, '[출처: ...]'를 절대 쓰지 않습니다.
- 근거에 없는 정책 자격·금액·날짜·기한·절차와 일반적인 적정 비율을 만들지 않습니다.
- 입력이나 근거에 없는 사실은 단정하지 말고 확인이 필요한 조건으로 표현합니다.
- 모든 문단은 목록이나 소제목 없이 하나의 이어진 줄글로 작성합니다.
""".strip()


SECTION_LAYOUT = (
    ("지금 독립해도 되는지", "assessment_paragraph"),
    ("나에게 맞는 집 찾기·계약·이사 순서", "execution_plan_paragraph"),
    ("내 상황에서 조심할 점", "risk_paragraph"),
    ("우선 확인할 지원정책", "policy_paragraph"),
)


def _normalize_numeric_text(value: str | float | int) -> str:
    text = str(value)
    if "." in text:
        return text.rstrip("0").rstrip(".")
    return text


def create_report_model(settings: GenerationSettings) -> ChatOpenAI:
    """Create the LangChain ChatOpenAI model after validating settings."""
    settings.validate()
    return ChatOpenAI(
        api_key=settings.api_key,
        model=settings.model,
        max_completion_tokens=settings.max_tokens,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        reasoning_effort=settings.reasoning_effort,
    )


def _build_financial_context(request: GenerationRequest) -> dict[str, object]:
    """Calculate transparent input-only amounts without decision thresholds."""
    situation = request.situation
    fixed_components = {
        "target_monthly_rent_krw": situation.target_monthly_rent_krw,
        "expected_management_fee_krw": situation.expected_management_fee_krw,
        "other_monthly_fixed_cost_krw": situation.other_monthly_fixed_cost_krw,
        "monthly_debt_payment_krw": situation.monthly_debt_payment_krw,
    }
    living_components = {
        "estimated_food_cost_krw": situation.estimated_food_cost_krw,
        "estimated_transport_cost_krw": situation.estimated_transport_cost_krw,
        "estimated_utilities_and_communications_krw": (
            situation.estimated_utilities_and_communications_krw
        ),
    }
    known_fixed = {
        name: value for name, value in fixed_components.items() if value is not None
    }
    known_living = {
        name: value for name, value in living_components.items() if value is not None
    }
    result: dict[str, object] = {
        "known_monthly_fixed_components": known_fixed,
        "known_monthly_living_components": known_living,
        "notice": "입력된 항목만 계산했으며 미입력 초기비용과 생활비는 포함하지 않았습니다.",
    }
    if known_fixed:
        fixed_total = sum(known_fixed.values())
        result["known_monthly_fixed_cost_total_krw"] = fixed_total
        result["income_after_known_monthly_fixed_cost_krw"] = (
            situation.monthly_income_krw - fixed_total
        )
    if known_fixed or known_living:
        expense_total = sum(known_fixed.values()) + sum(known_living.values())
        result["known_monthly_expense_total_krw"] = expense_total
        result["income_after_known_monthly_expenses_krw"] = (
            situation.monthly_income_krw - expense_total
        )
    if situation.target_deposit_krw is not None:
        result["cash_after_target_deposit_krw"] = (
            situation.available_cash_krw - situation.target_deposit_krw
        )
        if situation.estimated_moving_cost_krw is not None:
            result["cash_after_target_deposit_and_moving_cost_krw"] = (
                situation.available_cash_krw
                - situation.target_deposit_krw
                - situation.estimated_moving_cost_krw
            )
    if situation.estimated_moving_cost_krw is not None:
        result["estimated_moving_cost_krw"] = situation.estimated_moving_cost_krw
    return result


def _build_evidence_payload(
    request: GenerationRequest,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    prefixes = {"guides": "G", "cases": "C", "policies": "P"}
    counters = {corpus: 0 for corpus in prefixes}
    payload: list[dict[str, object]] = []
    corpus_by_id: dict[str, str] = {}
    for evidence in request.retrieved_context:
        counters[evidence.corpus] += 1
        evidence_id = f"{prefixes[evidence.corpus]}{counters[evidence.corpus]}"
        corpus_by_id[evidence_id] = evidence.corpus
        payload.append(
            {
                "evidence_id": evidence_id,
                "corpus": evidence.corpus,
                "content": evidence.content,
            }
        )
    return payload, corpus_by_id


def _normalize_paragraph(value: str) -> str:
    """Flatten accidental formatting and remove non-user-facing trace markers."""
    value = re.sub(r"\[출처:[^\]]+\]", "", value)
    value = re.sub(r"\[(?:G|C|P)\d+\]", "", value)
    lines: list[str] = []
    for line in value.splitlines():
        cleaned = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", line)
        if cleaned.strip():
            lines.append(cleaned.strip())
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _validate_evidence_usage(
    draft: NarrativeDraft,
    corpus_by_id: dict[str, str],
) -> None:
    usage = {
        "assessment": draft.assessment_evidence_ids,
        "execution": draft.execution_evidence_ids,
        "risk": draft.risk_evidence_ids,
        "policy": draft.policy_evidence_ids,
    }
    supplied_ids = set(corpus_by_id)
    used_ids = {item for values in usage.values() for item in values}
    unknown = used_ids - supplied_ids
    if unknown:
        raise ValueError(f"검색 근거에 없는 evidence_id가 사용되었습니다: {sorted(unknown)}")

    available_corpora = set(corpus_by_id.values())
    used_corpora = {corpus_by_id[item] for item in used_ids}
    if "guides" in available_corpora and "guides" not in used_corpora:
        raise ValueError("실행 보고서에 guides 근거가 사용되지 않았습니다.")
    if "cases" in available_corpora and "cases" not in used_corpora:
        raise ValueError("개인화 보고서에 실제 청년 cases 근거가 사용되지 않았습니다.")
    if "policies" in available_corpora and "policies" not in used_corpora:
        raise ValueError("지원정책 문단에 policies 근거가 사용되지 않았습니다.")

    if any(corpus_by_id[item] != "policies" for item in usage["policy"]):
        raise ValueError("정책 문단의 evidence_id는 policies 근거만 사용할 수 있습니다.")
    if not usage["policy"]:
        raise ValueError("정책 문단에 사용된 policies evidence_id가 없습니다.")
    if len(set(usage["policy"])) > 3:
        raise ValueError("정책 문단에는 최대 3개의 정책 근거만 사용할 수 있습니다.")


def _validate_draft_lengths(draft: NarrativeDraft) -> None:
    # 프롬프트의 권장 분량보다 하한을 넉넉히 낮춘 안전장치입니다. 모델이 핵심을
    # 충분히 설명했다면 문단별 글자 수가 조금 짧다는 이유만으로 생성을 폐기하지 않습니다.
    limits = {
        "assessment_paragraph": (120, 600),
        "execution_plan_paragraph": (250, 1200),
        "risk_paragraph": (150, 750),
        "policy_paragraph": (180, 800),
    }
    for field_name, (minimum, maximum) in limits.items():
        length = len(_normalize_paragraph(getattr(draft, field_name)))
        if not minimum <= length <= maximum:
            raise ValueError(
                f"{field_name} 길이는 {minimum}~{maximum}자여야 합니다: {length}자"
            )


def _validate_personalization(body: str, request: GenerationRequest) -> None:
    situation = request.situation

    def reflected(value: str) -> bool:
        aliases = {value}
        for suffix in ("특별시", "광역시", "특별자치시", "특별자치도"):
            if value.endswith(suffix):
                aliases.add(value[: -len(suffix)])
        if " " in value:
            aliases.add(value.split()[-1].removesuffix("시").removesuffix("군"))
        return any(alias and alias in body for alias in aliases)

    mandatory = [situation.target_region, situation.housing_preference]
    missing = [value for value in mandatory if not reflected(value)]
    if missing:
        raise ValueError(f"개인화 필수 입력이 보고서에 반영되지 않았습니다: {missing}")
    if not any(priority in body for priority in situation.priorities):
        raise ValueError("사용자 우선순위가 보고서의 판단이나 실행 계획에 반영되지 않았습니다.")

    context_values = {
        situation.purpose,
        situation.employment_status,
        situation.education_status,
        situation.current_region,
        situation.target_region,
        situation.move_timeline,
        situation.housing_preference,
        *situation.priorities,
    }
    reflected_values = {value for value in context_values if value and reflected(value)}
    if len(reflected_values) < 5:
        raise ValueError(
            "사용자 상황이 충분히 개인화되지 않았습니다. "
            f"반영된 입력={sorted(reflected_values)}"
        )

def _validate_no_duplicate_sentences(body: str) -> None:
    seen: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        normalized = re.sub(r"[^0-9A-Za-z가-힣]", "", sentence)
        if len(normalized) < 35:
            continue
        if normalized in seen:
            raise ValueError(f"보고서에 같은 문장이 반복되었습니다: {sentence[:100]}")
        seen.add(normalized)


def _validate_percentages(body: str, payload: dict[str, object]) -> None:
    allowed = {
        _normalize_numeric_text(value)
        for value in re.findall(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*%",
            json.dumps(payload, ensure_ascii=False),
        )
    }
    reported = {
        _normalize_numeric_text(value)
        for value in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", body)
    }
    unsupported = reported - allowed
    if unsupported:
        raise ValueError(f"입력·검색 근거에 없는 비율이 포함되었습니다: {sorted(unsupported)}")


def generate_narrative_report(
    request: GenerationRequest,
    settings: GenerationSettings | None = None,
) -> NarrativeReport:
    """Generate and validate one concise personalized report."""
    generation_settings = settings or GenerationSettings()
    model = create_report_model(generation_settings)
    structured_llm = model.with_structured_output(
        NarrativeDraft,
        method="json_schema",
        strict=True,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "다음 JSON만 근거로 개인 맞춤형 보고서 초안을 작성하세요.\n{payload}"),
        ]
    )

    evidence_payload, corpus_by_id = _build_evidence_payload(request)
    payload: dict[str, object] = {
        "retrieval_reference_date": date.today().isoformat(),
        "situation": request.situation.model_dump(),
        "calculated_financial_context": _build_financial_context(request),
        "evidence": evidence_payload,
    }
    result = (prompt | structured_llm).invoke(
        {"payload": json.dumps(payload, ensure_ascii=False)}
    )
    draft = (
        result
        if isinstance(result, NarrativeDraft)
        else NarrativeDraft.model_validate(result)
    )
    _validate_evidence_usage(draft, corpus_by_id)
    _validate_draft_lengths(draft)

    sections: list[str] = []
    for index, (heading, field_name) in enumerate(SECTION_LAYOUT, start=1):
        paragraph = _normalize_paragraph(getattr(draft, field_name))
        if index == 1:
            paragraph = f"현재 판단은 **{draft.independence_assessment}**입니다. {paragraph}"
        sections.append(f"## {index}. {heading}\n\n{paragraph}")

    report = NarrativeReport(
        report_title=draft.report_title,
        report_body_markdown="\n\n".join(sections),
    )
    _validate_personalization(report.report_body_markdown, request)
    _validate_no_duplicate_sentences(report.report_body_markdown)
    _validate_percentages(report.report_body_markdown, payload)
    return report
