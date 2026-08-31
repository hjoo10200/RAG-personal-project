"""Reviewed Seoul housing lease ceiling, not a quote or universal regional rule."""

import json
from datetime import date
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[2] / "knowledge_base/metadata/brokerage_reference.json"


def brokerage_ceiling(situation):
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if not date.fromisoformat(data["reviewed_on"]) <= date.today() <= date.fromisoformat(data["review_due"]):
        return None
    if situation.target_region != data["region"] or situation.property_type != data["property_type"]:
        return None
    deposit = situation.target_deposit_krw
    if deposit is None or situation.housing_preference not in {"월세", "전세"}:
        return None
    rent = situation.target_monthly_rent_krw
    if situation.housing_preference == "전세":
        if rent not in (None, 0):
            return None
        rent = 0
    if rent is None:
        return None
    transaction = deposit + rent * data["monthly_multiplier"]
    if transaction < data["small_transaction_threshold"]:
        transaction = deposit + rent * data["small_monthly_multiplier"]
    for tier in data["lease_tiers"]:
        if tier["under_krw"] is None or transaction < tier["under_krw"]:
            ceiling = transaction * tier["rate_per_thousand"] // 1000
            if tier["cap_krw"] is not None:
                ceiling = min(ceiling, tier["cap_krw"])
            return ceiling, data["source"], data["note"]
    return None
