"""Money intervals are inclusive integer KRW bounds; None means unbounded."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MoneyRange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lower: int | None = None
    upper: int | None = None

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.lower is None and self.upper is None:
            raise ValueError("범위에는 적어도 한 경계가 필요합니다. 미확인은 null로 표현하세요.")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("금액 범위의 하한이 상한보다 큽니다.")
        return self

    @classmethod
    def exact(cls, amount: int):
        return cls(lower=amount, upper=amount)


class FinancialResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["finance-v2"] = "finance-v2"
    scope: Literal["complete", "partial", "unavailable"] = "unavailable"
    initial_status: str = "정보 부족"
    monthly_status: str = "정보 부족"
    amounts: dict[str, MoneyRange] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sources: list[dict[str, str]] = Field(default_factory=list)
    query_hints: list[str] = Field(default_factory=list)

