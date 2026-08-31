"""Mixed categorical/numeric input, with legacy v2 band input compatibility."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.finance.schema import MoneyRange


REGIONS = {
    "seoul": "서울특별시", "busan": "부산광역시", "daegu": "대구광역시",
    "incheon": "인천광역시", "gwangju": "광주광역시", "daejeon": "대전광역시",
    "ulsan": "울산광역시", "sejong": "세종특별자치시", "gyeonggi": "경기도",
    "gangwon": "강원특별자치도", "chungbuk": "충청북도", "chungnam": "충청남도",
    "jeonbuk": "전북특별자치도", "jeonnam": "전라남도", "gyeongbuk": "경상북도",
    "gyeongnam": "경상남도", "jeju": "제주특별자치도", "unknown": "미정",
}
CHOICES = {
    "purpose": {"work": "취업", "job_search": "취업 준비", "study": "학업", "marriage": "결혼", "other": "기타"},
    "employment": {"employed": "재직 중", "seeking": "구직 중", "unemployed": "미취업", "unknown": "미정"},
    "education": {"student": "재학 중", "graduate_student": "대학원 재학", "graduated": "졸업", "other": "기타"},
    "current_region": REGIONS, "target_region": REGIONS,
    "timeline": {"month": "1개월 이내", "quarter": "1개월 초과 3개월 이내", "half_year": "3개월 초과 6개월 이내", "later": "6개월 초과", "unknown": "미정"},
    "housing": {"monthly": "월세", "deposit": "전세", "public": "공공임대", "unknown": "미정"},
    "income_status": {"current": "현재 정기 수입 있음", "none": "정기 수입 없음", "planned": "수입 발생 예정", "unknown": "수입 미확인"},
    "cash_band": {"under_500": "500만 원 미만", "500_1000": "500만~1,000만 원 미만", "1000_1500": "1,000만~1,500만 원 미만", "1500_3000": "1,500만~3,000만 원 미만", "over_3000": "3,000만 원 이상", "unknown": "모름"},
    "income_band": {"under_100": "월 100만 원 미만", "100_200": "월 100만~200만 원 미만", "200_250": "월 200만~250만 원 미만", "250_350": "월 250만~350만 원 미만", "over_350": "월 350만 원 이상", "unknown": "모름"},
    "fixed_band": {"none": "기존 필수 지출 없음", "under_30": "월 30만 원 미만", "30_60": "월 30만~60만 원 미만", "over_60": "월 60만 원 이상", "unknown": "모름"},
    "homeowner": {"no": "본인 주택 없음", "yes": "본인 주택 있음", "unknown": "모름"},
    "experience": {"first": "첫 자취", "experienced": "자취 경험 있음"},
    "priorities": {"commute": "통근시간", "safety": "안전", "cost": "월 고정비", "convenience": "생활 편의", "contract": "계약", "moving": "이사 준비"},
}
BOUNDS = {
    "cash_band": {"under_500": (0, 4999999), "500_1000": (5000000, 9999999), "1000_1500": (10000000, 14999999), "1500_3000": (15000000, 29999999), "over_3000": (30000000, None)},
    "income_band": {"under_100": (0, 999999), "100_200": (1000000, 1999999), "200_250": (2000000, 2499999), "250_350": (2500000, 3499999), "over_350": (3500000, None)},
    "fixed_band": {"none": (0, 0), "under_30": (0, 299999), "30_60": (300000, 599999), "over_60": (600000, None)},
}


class Selections(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    purpose: str = "work"
    age: int = Field(default=27, ge=18, le=45)
    employment: str = "unknown"
    education: str = "other"
    current_region: str = "unknown"
    target_region: str = "unknown"
    timeline: str = "unknown"
    housing: str = "unknown"
    income_status: str = "unknown"
    cash_band: str = "unknown"
    income_band: str = "unknown"
    fixed_band: str = "unknown"
    homeowner: str = "unknown"
    experience: str = "first"
    priorities: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_codes(self):
        for name, options in CHOICES.items():
            values = self.priorities if name == "priorities" else [getattr(self, name)]
            if any(value not in options for value in values):
                raise ValueError(f"{name}: 유효하지 않은 선택 코드입니다.")
        if len(set(self.priorities)) != len(self.priorities):
            raise ValueError("우선순위 선택이 중복되었습니다.")
        if self.income_status in {"none", "unknown"} and self.income_band != "unknown":
            raise ValueError("수입 없음·미확인 상태에는 수입 구간을 지정하지 마세요.")
        return self

    def to_situation(self):
        from src.generation.report_schema import UserSituation

        def band(name):
            bounds = BOUNDS[name].get(getattr(self, name))
            return MoneyRange(lower=bounds[0], upper=bounds[1]) if bounds else None

        return UserSituation(
            purpose=CHOICES["purpose"][self.purpose], age=self.age,
            employment_status=CHOICES["employment"][self.employment],
            education_status=CHOICES["education"][self.education],
            is_homeowner={"yes": True, "no": False, "unknown": None}[self.homeowner],
            current_region=REGIONS[self.current_region], target_region=REGIONS[self.target_region],
            move_timeline=CHOICES["timeline"][self.timeline], housing_preference=CHOICES["housing"][self.housing],
            priorities=[CHOICES["priorities"][code] for code in self.priorities],
            additional_context=CHOICES["experience"][self.experience],
            monthly_income_krw=0 if self.income_status == "none" else None,
            available_cash_krw=None, cash_range=band("cash_band"),
            income_range=band("income_band"), fixed_cost_range=band("fixed_band"),
            income_status=self.income_status,
        )


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2"]
    selections: Selections


class ProfileChoices(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    purpose: str = "work"
    employment: str = "unknown"
    education: str = "other"
    current_region: str = "unknown"
    target_region: str = "unknown"
    timeline: str = "unknown"
    housing: str = "unknown"
    income_status: str = "unknown"
    homeowner: str = "unknown"
    experience: str = "first"
    property_type: Literal["housing", "officetel", "other", "unknown"] = "unknown"
    priorities: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def valid_choices(self):
        data = self.model_dump(exclude={"property_type"})
        Selections.model_validate(data)
        return self


NUMBER_FIELDS = {
    "age": "만 나이",
    "household_size": "독립 후 함께 사는 인원 (본인 포함)",
    "available_cash_krw": "현재 사용 가능한 자금 (원)",
    "monthly_income_krw": "월 정기 실수령 수입 (원)",
    "existing_fixed_cost_krw": "기존 필수지출 합계 (원/월, 부채상환·가족지원 등; 생활비 중복 제외)",
    "target_deposit_krw": "알아본 보증금 (원, 선택 입력)",
    "target_monthly_rent_krw": "알아본 월세 (원, 전세는 0; 선택 입력)",
    "expected_management_fee_krw": "알아본 관리비 (원/월, 선택 입력)",
    "utilities_cost_krw": "관리비 외 수도·전기·가스 (원/월, 전액 포함이면 0; 선택 입력)",
    "nonhousing_living_cost_krw": "주거·수도·광열 외 생활비 합계 (원/월, 미입력 시 통계 참고)",
    "estimated_moving_cost_krw": "이사 견적 (원, 선택 입력)",
    "brokerage_cost_krw": "협의한 중개보수 총액 (세금 포함 원, 선택 입력)",
    "setup_cost_krw": "초기 구입·설치비 (원, 선택 입력)",
    "reserve_cash_krw": "별도로 남겨둘 예비금 (원, 선택 입력)",
    "monthly_savings_krw": "월 목표 적립액 (원, 선택 입력)",
}


class NumericInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    age: int = Field(default=27, ge=0, le=120)
    household_size: int = Field(default=1, ge=1, le=20)
    available_cash_krw: int | None = Field(default=None, ge=0, le=10**13)
    monthly_income_krw: int | None = Field(default=None, ge=0, le=10**13)
    existing_fixed_cost_krw: int | None = Field(default=None, ge=0, le=10**13)
    target_deposit_krw: int | None = Field(default=None, ge=0, le=10**13)
    target_monthly_rent_krw: int | None = Field(default=None, ge=0, le=10**13)
    expected_management_fee_krw: int | None = Field(default=None, ge=0, le=10**13)
    utilities_cost_krw: int | None = Field(default=None, ge=0, le=10**13)
    nonhousing_living_cost_krw: int | None = Field(default=None, ge=0, le=10**13)
    estimated_moving_cost_krw: int | None = Field(default=None, ge=0, le=10**13)
    brokerage_cost_krw: int | None = Field(default=None, ge=0, le=10**13)
    setup_cost_krw: int | None = Field(default=None, ge=0, le=10**13)
    reserve_cash_krw: int | None = Field(default=None, ge=0, le=10**13)
    monthly_savings_krw: int | None = Field(default=None, ge=0, le=10**13)


class NumericRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["3"]
    selections: ProfileChoices
    numbers: NumericInputs

    def to_situation(self):
        from src.generation.report_schema import UserSituation

        # Reuse categorical label mapping; v3 amounts never pass through bands.
        profile = Selections(**self.selections.model_dump(exclude={"property_type"})).to_situation()
        data = profile.model_dump()
        data.update(self.numbers.model_dump())
        data["property_type"] = self.selections.property_type
        if self.selections.income_status == "none" and data["monthly_income_krw"] is None:
            data["monthly_income_krw"] = 0
        return UserSituation.model_validate(data)


def parse_request(payload: dict):
    """Explicit v2 adapter, with legacy exact-number input kept intact."""
    from src.generation.report_schema import RagRequest

    if payload.get("schema_version") == "3":
        return RagRequest(situation=NumericRequest.model_validate(payload).to_situation())
    if "schema_version" in payload or "selections" in payload:
        return RagRequest(situation=SelectionRequest.model_validate(payload).selections.to_situation())
    return RagRequest.model_validate(payload)


def load_request(path: Path):
    return parse_request(json.loads(path.read_text(encoding="utf-8")))
