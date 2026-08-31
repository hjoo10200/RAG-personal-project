"""Build corpus-specific keyword queries from structured user input."""

from __future__ import annotations

from src.generation.report_schema import UserSituation
from src.finance.schema import FinancialResult


def _age_band(age: int) -> str:
    if age < 20:
        return "10대"
    return f"{age // 10 * 10}대"


def _region_terms(region: str) -> str:
    normalized = " ".join(region.split())
    aliases = {
        "서울특별시": "서울 서울특별시",
        "부산광역시": "부산 부산광역시",
        "대구광역시": "대구 대구광역시",
        "인천광역시": "인천 인천광역시",
        "광주광역시": "광주 광주광역시",
        "대전광역시": "대전 대전광역시",
        "울산광역시": "울산 울산광역시",
        "세종특별자치시": "세종 세종특별자치시",
    }
    return aliases.get(normalized, normalized)


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    normalized = value.replace(" ", "").lower()
    return any(term.replace(" ", "").lower() in normalized for term in terms)


def build_structured_keyword_queries(
    situation: UserSituation,
    *,
    corpora: tuple[str, ...] = ("guides", "cases", "policies"),
    financial_result: FinancialResult | None = None,
) -> dict[str, tuple[str, ...]]:
    """Use only fields that help each corpus rather than one concatenated sentence."""
    target_region = _region_terms(situation.target_region)
    current_region = _region_terms(situation.current_region)
    age_terms = f"만 {situation.age}세 {_age_band(situation.age)} 청년 연령 신청자격"
    housing = situation.housing_preference.strip()
    priorities = " ".join(situation.priorities)
    homeowner = (
        "무주택"
        if situation.is_homeowner is False
        else "주택 보유"
        if situation.is_homeowner is True
        else "주택 보유 여부"
    )

    guide_queries = [
        f"{housing} 임대차계약 등기사항증명서 보증금 관리비 특약 전입신고 확정일자",
        "이사업체 방문견적 운송계약 허가 피해배상보험 파손 분실",
        f"{housing} 자취 초기비용 월 생활비 고정지출 변동지출 비정기지출 비상자금",
    ]

    case_queries = [
        f"{_age_band(situation.age)} 청년 {housing} 1인 가구 실제 생활비 주거비 소득 공백 사례",
        f"{current_region} {target_region} {situation.purpose} 지역이동 통근 주거 선택 본가 복귀 사례",
    ]
    if priorities:
        case_queries.append(
            f"청년 독립 {housing} {priorities} 주거 선택 실제 경험 심층면접"
        )

    policy_queries: list[str] = []
    # Do not assume that the newest notice has the current year in its title.
    policy_base = f"{target_region} {age_terms} {homeowner}"
    if _contains_any(housing, ("월세", "원룸", "오피스텔")):
        policy_queries.extend(
            [
                f"{policy_base} 청년월세지원 월세 지원 소득 임차 조건 제출서류",
                f"{policy_base} 청년 부동산 중개보수 이사비 지원",
            ]
        )
    if _contains_any(housing, ("공공임대", "매입임대", "임대주택")):
        policy_queries.append(
            f"{policy_base} LH 청년 매입임대 공공 임대주택 신청자격 임대조건"
        )
    if _contains_any(housing, ("전세",)):
        policy_queries.append(
            f"{policy_base} 청년 전세 보증금 대출 이자 지원 반환보증"
        )

    if _contains_any(
        situation.employment_status,
        ("미취업", "구직", "취업 준비", "취업준비", "실업"),
    ):
        policy_queries.append(
            f"{policy_base} 미취업 구직 취업준비 생활비 지원"
        )
    elif _contains_any(
        situation.employment_status,
        ("재직", "근로", "취업", "직장"),
    ):
        policy_queries.append(
            f"{policy_base} 근로 청년 저축 자산형성 지원"
        )
    is_current_student = _contains_any(
        situation.education_status,
        ("재학", "재학생", "대학원생", "학생"),
    ) and not _contains_any(
        situation.education_status,
        ("졸업", "중퇴"),
    )
    if is_current_student or _contains_any(
        situation.purpose, ("학업", "진학", "대학원"),
    ):
        policy_queries.append(
            f"{policy_base} 대학생 주거안정장학금 원거리 자취 주거비"
        )

    if not policy_queries:
        policy_queries.append(
            f"{policy_base} 청년 주거 지원 {housing} 신청자격"
        )

    if financial_result:
        for hint in financial_result.query_hints:
            guide_queries.append(f"{housing} {priorities} {hint}")
            case_queries.append(f"{target_region} {situation.purpose} 청년 실제 사례 {hint}")
    queries = {
        "guides": tuple(dict.fromkeys(guide_queries)),
        "cases": tuple(dict.fromkeys(case_queries)),
        "policies": tuple(dict.fromkeys(policy_queries)),
    }
    return {name: values for name, values in queries.items() if name in corpora}
