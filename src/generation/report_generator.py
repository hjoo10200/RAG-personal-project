"""Generate one grounded narrative report from input and retrieved evidence."""

from __future__ import annotations

import json
import re
from datetime import date
from difflib import get_close_matches

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from src.config import GenerationSettings
from src.generation.report_schema import GenerationRequest, NarrativeDraft, NarrativeReport


SYSTEM_PROMPT = """
당신은 첫 자취를 준비하는 청년의 독립 실행 보고서 작성자입니다. 제공된 사용자 입력과
검색 근거만 사용해 한국어로 상세한 서술형 보고서를 작성합니다. 모든 문장은 독자에게
설명하는 `합니다`, `됩니다`, `필요합니다` 형식의 존댓말로 작성합니다.

내부 출력은 independence_assessment, 첫 주제의 assessment_paragraph, 나머지 네 주제의
analysis_paragraph와 action_paragraph입니다. 각 paragraph는 소제목·목록·표가 없는 하나의
완전한 줄글이어야 합니다. 분석 문단은 상황과 근거의 의미 및 판단 이유를, 실행 문단은
실제 확인·행동 순서와 그 이유를 설명합니다. 전체 분량은 약 2,400~3,300자로 작성합니다.

다섯 주제는 다음 순서를 따릅니다. 첫째, 독립 목적·지역 이동·소득·보유자금·일정과
우선순위를 요약하고 독립 적절성을 판단합니다. 예산 계산은 판단에 필요한 범위에서만
간결하게 설명합니다. 둘째, 매물 탐색, 현장 확인, 권리관계 확인과 계약서·특약 검토를
상세하게 설명합니다. 셋째, 이사업체 비교부터 이사 전·당일·입주 후 정착 절차까지
시간 순서로 설명합니다. 넷째, 계약·보증금·안전·생활비·소득 공백과 행정상 주의점을
상황별 대응과 함께 설명합니다. 다섯째, 검토할 정부·
지자체 정책마다 사용자와 맞는 조건, 아직 확인되지 않은 자격과 최신 공고 문제를 분리합니다.

원론적인 안내만 반복하지 않습니다. 각 분석 문단에서는 사용자의 실제 입력값을 서로
연결해 무엇이 유리하고 무엇이 아직 위험한지 설명합니다. 각 실행 문단에서는 `먼저`,
`그다음`, `계약 직전`, `이사 당일`, `입주 후` 같은 순서 표현을 사용해 행동을 구체화합니다.
단순히 `확인해야 합니다`로 끝내지 말고 확인할 항목, 비교 대상, 결과에 따른 다음 행동을
함께 씁니다. 다만 근거에 없는 횟수·기한·금액은 만들지 않습니다.

첫 번째 주제는 한 문단만 작성하며 독립 목적, 이동 시기, 지역, 주거 형태와 우선순위를
먼저 판단한 뒤 판단을 바꿀 수 있는 조건과 다음 의사결정을 설명합니다. 알려진 월 지출과
보증금·이사비 차감 후 현금은 이 문단에서 두세 문장만 사용하며,
동일한 금액이나 계산 결과를 반복하지 않습니다. 둘째와 셋째 주제는 보고서에서 가장
상세해야 합니다. 사용자가 실제로 따라 할 수 있도록 탐색 조건 정리, 매물 후보 비교,
방문 시 시설·안전 확인, 임대인과 소유자 대조, 등기 등 권리관계 확인, 계약금액·관리비·
수리 책임·특약 검토, 이사 견적의 작업 범위·추가비용·파손 대응 비교, 계약 후 일정 관리,
이사 당일 인계 상태 확인, 입주 후 행정·생활 정착 순서로 이어서 설명합니다. 각 단계마다
무엇을 확인하고 문제가 있으면 계약을 보류할지, 다른 매물을 찾을지, 문서에 반영할지를
분명히 씁니다. 넷째 주제에서는 실제 발생 가능한 상황을 `만약 ...라면 ...해야 합니다`
형태로 설명합니다. 다섯째 주제에서는 정책마다
사용자와 맞는 입력 조건, 아직 확인되지
않은 자격, 공고의 시점 문제를 각각 분리합니다.

independence_assessment는 '독립 진행이 적절함', '조건 확인 후 독립이 적절함',
'현재는 독립 연기 또는 조건 조정이 적절함' 중 하나만 선택한다. 목표 주거비나 기존
고정지출 등 핵심 정보가 없으면 원칙적으로 조건 확인 판단을 선택한다. 이 판단은 법적·
재무적 확정 판정이 아니라 입력과 근거에 기초한 현재 시점의 실행 권고임을 밝힌다.

검색 근거에 없는 정책명, 자격, 금액, 날짜, 기한, 제출서류, 지역, 기관, 연락처와
사실을 만들지 않는다. 금액은 입력이나 근거에서 확인된 값만 쓰고, 입력 수치를 합산·
차감하면 계산 항목을 모두 밝힌다. 정책은 검토 후보와 자격이 확인된 정책을 구분한다.
정보가 부족하면 추정하지 말고 무엇을 어디서 왜 추가 확인해야 하는지 설명한다.
근거를 사용한 문장 끝에는 실제 제공된 값만 이용해 [출처: 파일명, p.페이지]로 표시한다.
일반 상식이나 기억으로 분량을 채우지 않는다.

정책은 한 문장에 하나씩 설명하고 각 정책의 금액·자격·기한을 다른 정책과 합치지 않는다.
숫자는 인용한 해당 근거 본문에 같은 값이 있을 때만 쓴다. 검색 기준일보다 마감일이
앞선 공고는 현재 신청 가능한 정책으로 권하지 말고 과거 공고 스냅샷이라고 설명한다.
근거에 없는 홈페이지 다운로드·온라인 제출 방법을 만들지 않는다. 입력에 없는 일반적인
'소득의 30%' 같은 권장 비율은 절대 사용하지 않는다. 초기 가용 현금에서 매달 발생하는
고정비를 임의로 선차감하지 말고, payload의 calculated_financial_context만 계산 근거로 쓴다.
사용자 입력과 calculated_financial_context는 PDF 출처가 아니므로 출처 표시를 붙이지 않는다.
정책 공고는 모두 수집 시점의 스냅샷이므로 '즉시 신청한다'고 지시하지 말고 현재 모집 여부를
공식 최신 공고에서 다시 확인하도록 쓴다. 여러 정책에 공통 자격이 있다고 추정하지 않는다.
사용자가 입력한 월세·고정비 숫자를 식비 같은 다른 예산 항목으로 재사용하지 않으며, 근거 없는
'충분하다', '적정 범위다', '최소 몇 개월치가 필요하다' 같은 재무 기준을 만들지 않는다.
퍼센트는 payload의 allowed_percentage_values에 있는 값만 사용할 수 있습니다.
사용자 입력과 calculated_financial_context에서 나온 숫자는 PDF에서 나온 사실이 아니므로
PDF 출처를 붙이지 않습니다. 검색 근거에 없는 특정 동네, 역세권, 아파트 형태, 서울 평균,
은행 상품, 부업과 신청 홈페이지를 임의로 권하지 않습니다.
입력된 식비·교통비·공과금·통신비·이사비가 있으면 calculated_financial_context의 월 총지출,
월 잔여금액과 보증금·이사비 차감 후 현금을 사용해 판단하고 임의의 생활비를 만들지 않습니다.
사용자 입력 금액은 단위를 바꾸지 않고 `원` 단위로 그대로 표시하며, 원 값을 만원 값으로
잘못 변환하지 않습니다.
`allowed_percentage_values`라는 내부 필드명이나 `허용 퍼센트값`이라는 표현을 보고서에 쓰지 않습니다.
정책 선정이나 지원금 지급을 전제로 계약서에 반영하거나 비용을 지출하도록 지시하지 않습니다.
검색 근거가 신청자격 부분에서 잘렸다면 연령 제한이 없다고 추정하지 말고 자격을 확인하지
못했다고 씁니다. 법률 원문은 권리가 적용된다고 확대 해석하지 말고 제한 범위를 그대로 설명합니다.

보고서의 핵심 질문은 `얼마가 드는가`가 아니라 `사용자가 독립을 어떻게 실행해야 하는가`입니다.
예산·금액 설명은 전체 본문의 20% 이내로 제한하고, 실행 절차와 상황별 대응을 전체의 절반
이상으로 작성합니다. 같은 금액을 여러 문단에서 반복하지 않습니다. 입력 수치를 단순 나열해
분량을 채우지 않으며, 행동의 순서·확인 대상·판단 분기·다음 조치를 구체적으로 설명합니다.
근거에 없는 `몇 분 이내`, `몇 곳 이상`, `몇 개월치`, 특정 노선·동네, 보증보험 가입 지시,
전문가 의뢰, 온라인 플랫폼 기능을 만들지 않습니다. 횟수나 수량 근거가 없으면 `여러 후보를
같은 조건으로 비교합니다`처럼 숫자 없이 씁니다. 근거 사실을 쓴 문장은 반드시 문장 끝에
`[출처: source_file의 정확한 값, p.page_number의 정수]` 형식으로 표시하며, 파일명만 괄호에
넣거나 페이지를 생략하지 않습니다.

정책 주제에서는 retrieved_context 중 corpus가 policies인 근거를 우선 사용합니다. 정책명을
명시하고, 현재 입력으로 확인되는 조건, 아직 확인할 조건, 독립 과정에서 검토할 시점을 각각
설명합니다. 서로 다른 정책을 한 문장에 섞지 않습니다. 단순히 `정책을 확인해야 합니다`라는
문장을 반복하지 않습니다. 공고일과 모집기간은 다를 수 있으므로 공고일만 보고 종료 여부를
판단하지 않으며, 검색 기준일 현재의 최신 공고에서 모집 상태를 재확인하도록 설명합니다.
""".strip()


SECTION_LAYOUT = (
    ("현재 상황 요약과 독립 적절성 판단", "situation_and_assessment"),
    ("집 찾기와 임대차계약 진행 방법", "housing_search_and_contract"),
    ("이사 준비와 입주 후 정착 방법", "moving_and_settlement"),
    ("자취 시작 전후의 주의점", "cautions_before_and_after"),
    ("도움이 되는 정부·지자체 정책", "support_policies"),
)
GENERATION_EVIDENCE_CHARS = {
    "guides": 220,
    "cases": 220,
    "policies": 450,
}


def _normalize_numeric_text(value: str | float | int) -> str:
    text = str(value)
    if "." in text:
        return text.rstrip("0").rstrip(".")
    return text


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


def _build_financial_context(request: GenerationRequest) -> dict[str, object]:
    """Calculate transparent input-only amounts without applying decision rules."""
    situation = request.situation
    components = {
        "target_monthly_rent_krw": situation.target_monthly_rent_krw,
        "expected_management_fee_krw": situation.expected_management_fee_krw,
        "other_monthly_fixed_cost_krw": situation.other_monthly_fixed_cost_krw,
        "monthly_debt_payment_krw": situation.monthly_debt_payment_krw,
    }
    known_components = {
        name: value for name, value in components.items() if value is not None
    }
    result: dict[str, object] = {
        "known_monthly_cost_components": known_components,
        "notice": (
            "입력된 항목만 계산했으며 미입력 비용은 포함하지 않았습니다. "
            "이 값은 독립 실행 방법을 결정하는 보조 정보이며 단독 판정 기준이 아닙니다."
        ),
    }
    if known_components:
        monthly_total = sum(known_components.values())
        result["known_monthly_fixed_cost_total_krw"] = monthly_total
        result["income_after_known_monthly_fixed_cost_krw"] = (
            situation.monthly_income_krw - monthly_total
        )
        if situation.monthly_income_krw > 0:
            result["known_fixed_cost_share_of_income_percent"] = round(
                monthly_total / situation.monthly_income_krw * 100,
                1,
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

    living_components = {
        "estimated_food_cost_krw": situation.estimated_food_cost_krw,
        "estimated_transport_cost_krw": situation.estimated_transport_cost_krw,
        "estimated_utilities_and_communications_krw": (
            situation.estimated_utilities_and_communications_krw
        ),
    }
    known_living_components = {
        name: value for name, value in living_components.items() if value is not None
    }
    result["known_monthly_living_cost_components"] = known_living_components
    if known_components or known_living_components:
        monthly_expense_total = sum(known_components.values()) + sum(
            known_living_components.values()
        )
        result["known_monthly_expense_total_krw"] = monthly_expense_total
        result["income_after_known_monthly_expenses_krw"] = (
            situation.monthly_income_krw - monthly_expense_total
        )
    if situation.estimated_moving_cost_krw is not None:
        result["estimated_moving_cost_krw"] = situation.estimated_moving_cost_krw
    return result


def _normalize_narrative_paragraph(value: str) -> str:
    """Flatten accidental list formatting while preserving the prose content."""
    value = re.sub(
        r"\[출처:\s*(?:calculated_financial_context[^\]]*|계산된 재무 컨텍스트[^\]]*|사용자 입력[^\]]*|payload|없음)\]",
        "",
        value,
    )
    cleaned_lines = []
    for line in value.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    paragraph = " ".join(cleaned_lines)
    replacements = (
        (r"해야 한다\.", "해야 합니다."),
        (r"필요하다\.", "필요합니다."),
        (r"권장한다\.", "권장합니다."),
        (r"확인한다\.", "확인합니다."),
        (r"진행한다\.", "진행합니다."),
        (r"설명한다\.", "설명합니다."),
        (r"판단한다\.", "판단합니다."),
        (r"사용한다\.", "사용합니다."),
        (r"관리한다\.", "관리합니다."),
        (r"대응한다\.", "대응합니다."),
        (r"된다\.", "됩니다."),
        (r"있다\.", "있습니다."),
        (r"없다\.", "없습니다."),
        (r"이다\.", "입니다."),
    )
    for pattern, replacement in replacements:
        paragraph = re.sub(pattern, replacement, paragraph)
    paragraph = re.sub(r"\s*\(?허용 퍼센트값[^)]。.!?]*\)?", "", paragraph)
    return paragraph


def _normalize_citation_filenames(
    body: str,
    allowed_sources: set[tuple[str, int]],
) -> str:
    """Repair only a uniquely close filename on an actually retrieved page."""
    def expand_combined(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split(";")]
        expanded: list[str] = []
        for part in parts:
            parsed = re.fullmatch(r"([^,\]]+),\s*p\.(\d+)", part)
            if not parsed:
                return match.group(0)
            expanded.append(
                f"[출처: {parsed.group(1).strip()}, p.{int(parsed.group(2))}]"
            )
        return " ".join(expanded)

    body = re.sub(
        r"\(([^()]+\.pdf),\s*p\.(\d+)\)",
        lambda match: (
            f"[출처: {match.group(1).strip()}, p.{int(match.group(2))}]"
        ),
        body,
    )
    body = re.sub(
        r"\[출처:\s*([^\]]*;[^\]]*)\]",
        expand_combined,
        body,
    )
    filenames_by_page: dict[int, list[str]] = {}
    for filename, page in allowed_sources:
        filenames_by_page.setdefault(page, []).append(filename)

    def replace(match: re.Match[str]) -> str:
        filename = match.group(1).strip()
        page = int(match.group(2))
        if (filename, page) in allowed_sources:
            return match.group(0)
        close = get_close_matches(
            filename,
            filenames_by_page.get(page, []),
            n=2,
            cutoff=0.88,
        )
        if len(close) == 1:
            return f"[출처: {close[0]}, p.{page}]"
        return match.group(0)

    return re.sub(
        r"\[출처:\s*([^,\]]+),\s*p\.(\d+)\]",
        replace,
        body,
    )


def _sanitize_unsupported_claims(
    body: str,
    request: GenerationRequest,
    generation_payload: dict[str, object],
) -> str:
    """Replace a small set of mechanically detectable ungrounded claims."""
    allowed_percentages = {
        _normalize_numeric_text(value)
        for value in generation_payload.get("allowed_percentage_values", [])
    }
    calculated_percentage = generation_payload["calculated_financial_context"].get(
        "known_fixed_cost_share_of_income_percent"
    )
    calculated_allowed = (
        {_normalize_numeric_text(calculated_percentage)}
        if calculated_percentage is not None
        else set()
    )
    evidence_by_source = {
        (evidence.source_file, evidence.page_number): evidence.content
        for evidence in request.retrieved_context
    }
    reference_date = date.fromisoformat(
        str(generation_payload["retrieval_reference_date"])
    )
    remaining_income = generation_payload["calculated_financial_context"].get(
        "income_after_known_monthly_expenses_krw",
        generation_payload["calculated_financial_context"].get(
            "income_after_known_monthly_fixed_cost_krw"
        ),
    )
    remaining_income_text = (
        f"{int(remaining_income):,}원"
        if isinstance(remaining_income, int | float)
        else "고정비 차감 후 금액"
    )
    financial_fallback = (
        f"현재 계산에는 입력된 월 지출 항목만 포함되어 있으므로 누락된 비용이 있는지 "
        f"확인한 뒤 {remaining_income_text} 안에서 감당되는지 비교하고, 부족하면 계약 전에 "
        "월세나 기타 고정비를 낮춰야 합니다."
    )
    situation = request.situation
    policy_fallback = (
        f"사용자는 만 {situation.age}세이고 {situation.target_region}로 "
        f"{situation.housing_preference} 입주를 계획하고 있어 청년 주거정책을 검토할 수 "
        "있지만, 소득·거주·임대차 조건과 모집기간은 정책마다 다르므로 최신 공식 공고를 "
        "정책별로 대조한 뒤 신청 가능 여부를 판단해야 합니다."
    )
    date_fallback = (
        "검색된 문서는 수집 당시 공고이므로 문서의 작성일을 모집 종료일로 해석하지 말고, "
        "현재 모집 여부와 실제 신청기간을 최신 공식 공고에서 다시 확인해야 합니다."
    )
    procedure_fallback = (
        "이사 견적에서는 운송 범위·작업 인원·차량·추가비용·파손 대응을 같은 기준으로 "
        "비교하고, 정확한 처리기한은 계약 및 전입 관련 최신 공식 안내에서 확인해야 합니다."
    )

    blocks: list[str] = []
    in_policy_section = False
    current_section = ""
    fallback_seen_by_section: dict[str, set[str]] = {}
    for block in body.split("\n\n"):
        if block.startswith("## "):
            current_section = block
            in_policy_section = block.startswith("## 5.")
            fallback_seen_by_section.setdefault(current_section, set())
            blocks.append(block)
            continue
        if block.startswith("이 보고서 작성에 사용한 검색 근거는"):
            blocks.append(block)
            continue

        sanitized_sentences: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", block):
            if sentence.startswith("이 보고서 작성에 사용한 검색 근거는"):
                sanitized_sentences.append(sentence.strip())
                continue
            replacement: str | None = None
            percentages = {
                _normalize_numeric_text(value)
                for value in re.findall(
                    r"(?<!\d)(\d+(?:\.\d+)?)\s*%",
                    sentence,
                )
            }
            if percentages - allowed_percentages:
                replacement = financial_fallback

            citations = [
                (filename.strip(), int(page))
                for filename, page in re.findall(
                    r"\[출처:\s*([^,\]]+),\s*p\.(\d+)\]",
                    sentence,
                )
            ]
            numeric_values = re.findall(r"(?<!\w)\d[\d,.]*", sentence)
            risky_numeric_topics = (
                "가구 구입",
                "초기 가구",
                "이사업체",
                "이사 업체",
                "전입 신고",
                "전입신고",
                "제출",
            )
            if (
                numeric_values
                and not citations
                and any(term in sentence for term in risky_numeric_topics)
            ):
                replacement = procedure_fallback
            if (
                not citations
                and re.search(r"\d[\d,.]*\s*(?:분|곳|개월|개|호선)", sentence)
            ):
                replacement = procedure_fallback
            if (
                numeric_values
                and any(
                    term in sentence
                    for term in (
                        "안정적인 수준",
                        "적정 범위",
                        "충분하다",
                        "충분",
                        "재무 건전",
                    )
                )
            ):
                replacement = financial_fallback
            if percentages and citations:
                cited_text = " ".join(
                    evidence_by_source.get(key, "") for key in citations
                )
                cited_percentages = {
                    _normalize_numeric_text(value)
                    for value in re.findall(
                        r"(?<!\d)(\d+(?:\.\d+)?)\s*%",
                        cited_text,
                    )
                }
                if percentages - cited_percentages - calculated_allowed:
                    replacement = financial_fallback
                elif percentages <= calculated_allowed and not cited_percentages:
                    sentence = re.sub(r"\s*\[출처:[^\]]+\]", "", sentence)
                    citations = []

            if (
                any(term in sentence for term in ("모집이 종료", "모집 종료", "마감되"))
                and citations
                and not any(
                    term in cited_text for term in ("모집이 종료", "모집 종료", "마감")
                )
            ):
                replacement = date_fallback

            policy_source_files = {
                filename
                for filename, _page in citations
                if any(
                    evidence.source_file == filename and evidence.corpus == "policies"
                    for evidence in request.retrieved_context
                )
            }
            if len(policy_source_files) > 1:
                replacement = policy_fallback
            if (
                not citations
                and any(
                    term in sentence
                    for term in (
                        "지원 대상",
                        "소득 기준",
                        "지원금",
                        "신청 요건",
                        "신청 절차",
                        "동일 문서",
                        "중위소득",
                        "지원사업",
                        "지원 사업",
                        "지원금",
                        "신청 가능",
                        "신청서를 작성",
                    )
                )
            ):
                replacement = policy_fallback
            if in_policy_section and any(
                term in sentence
                for term in (
                    "연령 제한은 없",
                    "온라인 신청",
                    "온라인 신청 페이지",
                    "지원금 지급 예정액을 계약서",
                    "지원받은 이사비",
                    "지원금이 실제로 지급",
                    "지원금을 실제로 지급",
                    "신청서를 미리",
                    "소득증명서를 준비",
                    "담당 부서에 연락",
                    "추가 청구",
                )
            ):
                replacement = policy_fallback

            if re.search(r"보증금.*2분의 1.*초과.*우선변제권.*적용", sentence):
                replacement = (
                    "검색 근거에서는 보증금 중 일정액이 주택가액의 2분의 1을 초과하면 "
                    "우선변제받을 수 있는 금액이 주택가액의 2분의 1 범위로 제한된다고 "
                    "설명하므로, 실제 보호 범위는 계약 전 해당 기준과 권리관계를 함께 "
                    "확인해야 합니다[출처: housing_lease_protection_guide_2020.pdf, p.69]."
                )

            for year, month, day in re.findall(
                r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
                sentence,
            ):
                mentioned_date = date(int(year), int(month), int(day))
                if (
                    mentioned_date < reference_date
                    and "신청" in sentence
                    and not any(
                        term in sentence
                        for term in ("마감되", "종료", "과거", "현재 신청 불가")
                    )
                ):
                    replacement = date_fallback

            if replacement:
                seen_fallbacks = fallback_seen_by_section.setdefault(
                    current_section, set()
                )
                if replacement in seen_fallbacks:
                    continue
                seen_fallbacks.add(replacement)
            final_sentence = replacement or sentence.strip()
            if final_sentence and final_sentence not in sanitized_sentences:
                sanitized_sentences.append(final_sentence)
        blocks.append(" ".join(sanitized_sentences))
    return "\n\n".join(blocks)


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
    generation_payload = {
        "retrieval_reference_date": date.today().isoformat(),
        "situation": request.situation.model_dump(),
        "calculated_financial_context": _build_financial_context(request),
        "retrieved_context": [
            {
                "corpus": evidence.corpus,
                "source_file": evidence.source_file,
                "page_number": evidence.page_number,
                "content": evidence.content[
                    :GENERATION_EVIDENCE_CHARS[evidence.corpus]
                ],
            }
            for evidence in request.retrieved_context
        ],
    }
    evidence_percentages = {
        _normalize_numeric_text(value)
        for evidence in request.retrieved_context
        for value in re.findall(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*%",
            evidence.content,
        )
    }
    calculated_percentage_for_prompt = generation_payload[
        "calculated_financial_context"
    ].get("known_fixed_cost_share_of_income_percent")
    if calculated_percentage_for_prompt is not None:
        evidence_percentages.add(
            _normalize_numeric_text(calculated_percentage_for_prompt)
        )
    generation_payload["allowed_percentage_values"] = sorted(evidence_percentages)
    result = (prompt | structured_llm).invoke(
        {"payload": json.dumps(generation_payload, ensure_ascii=False)}
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
        if index == 1:
            assessment_paragraph = _normalize_narrative_paragraph(
                section.assessment_paragraph
            )
            sections.append(
                f"## {index}. {heading}\n\n"
                f"현재 판단은 **{draft.independence_assessment}**입니다. "
                f"{assessment_paragraph}"
            )
            continue
        analysis_paragraph = _normalize_narrative_paragraph(
            section.analysis_paragraph
        )
        action_paragraph = _normalize_narrative_paragraph(section.action_paragraph)
        if index == len(SECTION_LAYOUT):
            action_paragraph = f"{action_paragraph} {source_note}"
        sections.append(
            f"## {index}. {heading}\n\n"
            f"{analysis_paragraph}\n\n"
            f"{action_paragraph}"
        )
    allowed_sources = {
        (evidence.source_file, evidence.page_number)
        for evidence in request.retrieved_context
    }
    report_body = _normalize_citation_filenames(
        "\n\n".join(sections),
        allowed_sources,
    )
    report_body = _sanitize_unsupported_claims(
        report_body,
        request,
        generation_payload,
    )
    report = NarrativeReport(
        report_title=draft.report_title,
        report_body_markdown=report_body,
    )
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
    allowed_percent_text = json.dumps(generation_payload, ensure_ascii=False)
    allowed_percentages = {
        _normalize_numeric_text(value)
        for value in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", allowed_percent_text)
    }
    calculated_percentage = generation_payload["calculated_financial_context"].get(
        "known_fixed_cost_share_of_income_percent"
    )
    if calculated_percentage is not None:
        allowed_percentages.add(
            _normalize_numeric_text(calculated_percentage)
        )
    reported_percentages = {
        _normalize_numeric_text(value)
        for value in re.findall(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*%",
            report.report_body_markdown,
        )
    }
    unsupported_percentages = reported_percentages - allowed_percentages
    if unsupported_percentages:
        raise ValueError(
            "입력·검색 근거·명시적 계산에 없는 비율이 포함되었습니다: "
            f"{sorted(unsupported_percentages)}"
        )

    policy_section_match = re.search(
        r"(?ms)^## 6\.[^\n]*\n(.*)$",
        report.report_body_markdown,
    )
    if policy_section_match:
        policy_text = policy_section_match.group(1)
        for sentence in re.split(r"(?<=[.!?])\s+", policy_text):
            if sentence.startswith("이 보고서 작성에 사용한 검색 근거는"):
                continue
            markers = re.findall(r"\[출처:[^\]]+\]", sentence)
            if len(markers) > 1:
                raise ValueError(
                    "정책별 조건 혼합을 막기 위해 정책 문장 하나에는 출처 하나만 "
                    f"사용해야 합니다: {sentence[:160]}"
                )

    evidence_by_source = {
        (evidence.source_file, evidence.page_number): evidence.content
        for evidence in request.retrieved_context
    }
    calculated_allowed = set()
    if calculated_percentage is not None:
        calculated_allowed.add(
            _normalize_numeric_text(calculated_percentage)
        )
    for sentence in re.split(r"(?<=[.!?])\s+", report.report_body_markdown):
        percentages = {
            _normalize_numeric_text(value)
            for value in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", sentence)
        }
        if not percentages:
            continue
        citations = [
            (filename.strip(), int(page))
            for filename, page in re.findall(
                r"\[출처:\s*([^,\]]+),\s*p\.(\d+)\]",
                sentence,
            )
        ]
        cited_text = " ".join(evidence_by_source.get(key, "") for key in citations)
        cited_percentages = {
            _normalize_numeric_text(value)
            for value in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", cited_text)
        }
        unsupported_in_sentence = percentages - cited_percentages - calculated_allowed
        if unsupported_in_sentence:
            raise ValueError(
                "인용한 해당 페이지에서 확인되지 않은 비율이 있습니다: "
                f"{sorted(unsupported_in_sentence)}"
            )

    reference_date = date.fromisoformat(
        str(generation_payload["retrieval_reference_date"])
    )
    for sentence in re.split(r"(?<=[.!?])\s+", report.report_body_markdown):
        for year, month, day in re.findall(
            r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
            sentence,
        ):
            mentioned_date = date(int(year), int(month), int(day))
            if (
                mentioned_date < reference_date
                and "신청" in sentence
                and not any(
                    term in sentence
                    for term in ("마감되", "종료", "과거", "현재 신청 불가")
                )
            ):
                raise ValueError(
                    "이미 지난 날짜가 현재 신청 행동으로 표현되었습니다: "
                    f"{sentence[:160]}"
                )
    return report
