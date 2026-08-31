"""Pure interval calculations before retrieval; missing costs are not zeros."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.finance.schema import FinancialResult, MoneyRange

if TYPE_CHECKING:
    from src.generation.report_schema import UserSituation

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = ROOT / "knowledge_base" / "metadata" / "cost_references.json"
COST_KEYS = {"deposit", "moving", "brokerage", "setup", "rent", "management", "living", "fixed", "reserve", "savings", "utilities"}


class CostReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str = Field(min_length=1)
    target_region: str = Field(min_length=1)
    housing_preference: str = Field(min_length=1)
    household_size: int = Field(default=1, ge=1)
    living_excludes_utilities: bool = False
    reviewed_on: date
    valid_until: date
    assumptions: list[str] = Field(min_length=1)
    sources: list[dict[str, str]] = Field(min_length=1)
    amounts: dict[str, MoneyRange]

    @model_validator(mode="after")
    def validate_reference(self):
        if self.valid_until < self.reviewed_on:
            raise ValueError("비용 기준 유효기간을 확인하세요.")
        if not self.amounts or set(self.amounts) - COST_KEYS:
            raise ValueError("비용 기준 항목이 비어 있거나 알 수 없는 항목이 있습니다.")
        for bounds in self.amounts.values():
            if bounds.lower is None or bounds.lower < 0:
                raise ValueError("비용 기준 하한은 0 이상이어야 합니다.")
        if any(not item.get("title") or not item.get("url") for item in self.sources):
            raise ValueError("비용 출처에는 title과 url이 필요합니다.")
        return self


class ReferenceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"]
    notice: str = ""
    references: list[CostReference]


def load_reference(situation: UserSituation, path: Path = REFERENCE_PATH) -> CostReference | None:
    catalog = ReferenceCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
    today = date.today()
    candidates = [r for r in catalog.references if r.target_region in {"*", situation.target_region}
                  and r.housing_preference in {"*", situation.housing_preference}
                  and r.household_size == situation.household_size
                  and r.reviewed_on <= today <= r.valid_until]
    if candidates:
        specificity = lambda r: int(r.target_region != "*") + int(r.housing_preference != "*")
        best = max(map(specificity, candidates))
        candidates = [r for r in candidates if specificity(r) == best]
    if len(candidates) > 1:
        raise ValueError("동일 지역·주거 형태에 활성 비용 기준이 중복되었습니다.")
    return candidates[0] if candidates else None


def add(*items: MoneyRange) -> MoneyRange:
    return MoneyRange(
        lower=sum(v.lower for v in items) if all(v.lower is not None for v in items) else None,
        upper=sum(v.upper for v in items) if all(v.upper is not None for v in items) else None,
    )


def subtract(left: MoneyRange, right: MoneyRange) -> MoneyRange | None:
    lower = left.lower - right.upper if left.lower is not None and right.upper is not None else None
    upper = left.upper - right.lower if left.upper is not None and right.lower is not None else None
    return None if lower is None and upper is None else MoneyRange(lower=lower, upper=upper)


def classify(balance: MoneyRange | None, complete: bool) -> str:
    if not complete or balance is None:
        return "정보 부족"
    if balance.upper is not None and balance.upper < 0:
        return "가정 범위 전체에서 부족"
    if balance.lower is not None and balance.lower >= 0:
        return "가정 범위 전체에서 비음수 잔액"
    return "구간에 따라 달라짐"


def calculate_finances(situation: UserSituation, reference: CostReference | None = None) -> FinancialResult:
    result = FinancialResult()
    costs = dict(reference.amounts) if reference else {}
    if reference:
        result.assumptions = [f"비용 기준: {reference.reference_id}", *reference.assumptions]
        result.sources = reference.sources
    else:
        result.assumptions.append("적용 가능한 검토 비용 기준이 없습니다. 입력된 항목만 계산합니다.")

    cash = situation.cash_range
    if situation.available_cash_krw is not None:
        cash = MoneyRange.exact(situation.available_cash_krw)
    income = situation.income_range
    if situation.monthly_income_krw is not None:
        income = MoneyRange.exact(situation.monthly_income_krw)
    if situation.income_status == "none":
        income = MoneyRange.exact(0)
    elif situation.income_status in {"unknown", "planned"}:
        income = None
        result.assumptions.append("미확인·예정 수입은 확정 수입에 포함하지 않았습니다.")

    for name, field in {"deposit": "target_deposit_krw", "moving": "estimated_moving_cost_krw",
                        "rent": "target_monthly_rent_krw", "management": "expected_management_fee_krw",
                        "utilities": "utilities_cost_krw", "brokerage": "brokerage_cost_krw",
                        "setup": "setup_cost_krw", "reserve": "reserve_cash_krw",
                        "savings": "monthly_savings_krw"}.items():
        value = getattr(situation, field)
        if value is not None:
            costs[name] = MoneyRange.exact(value)
    # Never combine known subtotal with a full reference estimate: no double counting.
    living_values = [situation.estimated_food_cost_krw, situation.estimated_transport_cost_krw,
                     situation.estimated_utilities_and_communications_krw]
    excludes_utilities = bool(reference and reference.living_excludes_utilities)
    if situation.nonhousing_living_cost_krw is not None:
        costs["living"] = MoneyRange.exact(situation.nonhousing_living_cost_krw)
        excludes_utilities = True
        result.assumptions.append("생활비 통계 대신 사용자가 적은 주거·수도·광열 외 생활비 합계를 사용합니다.")
    elif any(value is not None for value in living_values):
        costs["living"] = MoneyRange.exact(sum(value for value in living_values if value is not None))
        excludes_utilities = False
        costs.pop("utilities", None)
        result.assumptions.append("기존 세부 생활비 입력은 공과금 포함 소계이며 통계 생활비와 합산하지 않습니다.")
        if any(value is None for value in living_values):
            result.missing.append("생활비 일부 항목")
    fixed_values = [situation.other_monthly_fixed_cost_krw, situation.monthly_debt_payment_krw]
    if situation.existing_fixed_cost_krw is not None:
        costs["fixed"] = MoneyRange.exact(situation.existing_fixed_cost_krw)
    elif situation.fixed_cost_range is not None:
        costs["fixed"] = situation.fixed_cost_range
    elif any(value is not None for value in fixed_values):
        costs["fixed"] = MoneyRange.exact(sum(value for value in fixed_values if value is not None))
        if any(value is None for value in fixed_values):
            result.missing.append("기존 필수 지출 일부 항목")
    # Personal debts/obligations cannot be inferred from demographic cost statistics.
    else:
        costs.pop("fixed", None)

    initial_keys = ("deposit", "moving", "brokerage", "setup")
    monthly_keys = ("rent", "management", "living", "fixed") + (("utilities",) if excludes_utilities else ())
    initial_complete = all(k in costs for k in initial_keys) and cash is not None
    monthly_complete = all(k in costs for k in monthly_keys) and income is not None and not result.missing

    def remember(name, value):
        if value is not None:
            result.amounts[name] = value

    remember("available_cash_krw", cash)
    remember("regular_income_krw", income)
    if excludes_utilities and income is not None and all(k in costs for k in ("living", "fixed")):
        deductions = [costs["living"], costs["fixed"]]
        if "savings" in costs:
            deductions.append(costs["savings"])
        capacity = subtract(income, add(*deductions))
        remember("housing_utilities_capacity_krw", capacity)
        result.assumptions.append("주거·수도·광열 탐색 잔여액에는 월세·관리비·별도 공과금을 모두 넣어 비교해야 합니다. 실제 적정 월세나 매물 시세가 아닙니다.")
        if "savings" not in costs:
            result.assumptions.append("주거·수도·광열 탐색 잔여액은 목표 저축액 미입력으로 저축 전 금액입니다.")
        if capacity and capacity.upper is not None and capacity.upper < 0:
            result.query_hints.append("참고 생활비와 기존 지출만으로 수입 초과 생활비 조정 소득 공백 대응")
        else:
            result.query_hints.append("월세 관리비 공과금 총액 비교 주거비 탐색 예산")
    for name, value in costs.items():
        remember(f"component_{name}_krw", value)
    for name, keys, resource in (("initial", initial_keys, cash), ("monthly", monthly_keys, income)):
        known = [costs[k] for k in keys if k in costs]
        if known:
            total = add(*known)
            remember(f"known_{name}_cost_krw", total)
            if resource is not None:
                remember(f"after_known_{name}_cost_krw", subtract(resource, total))
        result.missing.extend(k for k in keys if k not in costs)
    if cash is None:
        result.missing.append("available_cash")
    if income is None:
        result.missing.append("regular_income")
    result.initial_status = classify(result.amounts.get("after_known_initial_cost_krw"), initial_complete)
    result.monthly_status = classify(result.amounts.get("after_known_monthly_cost_krw"), monthly_complete)
    if all(k in costs for k in ("moving", "brokerage", "setup", "reserve")) and cash:
        remember("deposit_capacity_krw", subtract(cash, add(*(costs[k] for k in ("moving", "brokerage", "setup", "reserve")))))
    if monthly_complete and "savings" in costs:
        deduction_keys = ("living", "fixed", "savings") + (("utilities",) if excludes_utilities else ())
        remember("housing_capacity_krw", subtract(income, add(*(costs[k] for k in deduction_keys))))
    if initial_complete and monthly_complete:
        result.scope = "complete"
    elif any(k.startswith("known_") for k in result.amounts):
        result.scope = "partial"
    result.missing = list(dict.fromkeys(result.missing))
    if result.initial_status == "가정 범위 전체에서 부족":
        result.query_hints.append("초기자금 부족 보증금 부담 낮추기 초기 구입비 이사비 절약")
    if result.monthly_status == "가정 범위 전체에서 부족":
        result.query_hints.append("월 적자 고정비 줄이기 주거 선택 소득 공백 생활비 사례")
    if "구간에 따라 달라짐" in (result.initial_status, result.monthly_status):
        result.query_hints.append("주거 조건별 예산 비교 실제 견적 확인")
    if result.scope != "complete":
        result.query_hints.append("첫 자취 실제 비용 확인 관리비 포함 항목 이사 견적 초기 비용")
    return result


def prepare_finances(situation: UserSituation) -> FinancialResult:
    from src.finance.brokerage import brokerage_ceiling

    result = calculate_finances(situation, load_reference(situation))
    fee = brokerage_ceiling(situation)
    if fee is not None:
        amount, source, note = fee
        result.amounts["brokerage_ceiling_excluding_vat_krw"] = MoneyRange.exact(amount)
        result.sources.append(source)
        result.assumptions.append(note)
    return result
