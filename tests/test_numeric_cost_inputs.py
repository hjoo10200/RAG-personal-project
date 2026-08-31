"""Numeric-entry and researched-reference regression tests; no live API calls."""

import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from src.common.selection_input import parse_request
from src.finance.calculator import calculate_finances, load_reference
from src.finance.brokerage import brokerage_ceiling

ROOT = Path(__file__).resolve().parents[1]


def payload():
    return json.loads((ROOT / "examples/inputs/mixed_rag_input.json").read_text(encoding="utf-8"))


class NumericCostTests(unittest.TestCase):
    def test_exact_numbers_are_not_bands(self):
        situation = parse_request(payload()).situation
        self.assertEqual(situation.available_cash_krw, 10000000)
        self.assertEqual(situation.monthly_income_krw, 2200000)
        self.assertIsNone(situation.cash_range)
        self.assertIsNone(situation.income_range)

    def test_invalid_numeric_values_and_band_fields(self):
        for value in (-1, True, "2200000", 1.5):
            data = payload()
            data["numbers"]["monthly_income_krw"] = value
            with self.assertRaises(ValidationError):
                parse_request(data)
        data = payload()
        data["selections"]["cash_band"] = "1000_1500"
        with self.assertRaises(ValidationError):
            parse_request(data)

    def test_benchmark_is_applied_without_inventing_rent(self):
        situation = parse_request(payload()).situation
        reference = load_reference(situation)
        self.assertIsNotNone(reference)
        result = calculate_finances(situation, reference)
        self.assertEqual(result.amounts["component_living_krw"].lower, 1378000)
        self.assertEqual(result.amounts["housing_utilities_capacity_krw"].lower, 722000)
        self.assertNotIn("component_rent_krw", result.amounts)
        self.assertEqual(result.monthly_status, "정보 부족")

    def test_single_household_statistics_not_multiplied(self):
        data = payload()
        data["numbers"]["household_size"] = 2
        self.assertIsNone(load_reference(parse_request(data).situation))

    def test_unknown_fixed_cost_does_not_become_zero(self):
        data = payload()
        data["numbers"]["existing_fixed_cost_krw"] = None
        situation = parse_request(data).situation
        result = calculate_finances(situation, load_reference(situation))
        self.assertNotIn("housing_utilities_capacity_krw", result.amounts)

    def test_user_living_cost_replaces_benchmark_and_utilities_added_once(self):
        data = payload()
        data["numbers"].update(nonhousing_living_cost_krw=900000, utilities_cost_krw=50000,
                               target_monthly_rent_krw=500000, expected_management_fee_krw=100000)
        situation = parse_request(data).situation
        result = calculate_finances(situation, load_reference(situation))
        self.assertEqual(result.amounts["known_monthly_cost_krw"].lower, 1650000)
        self.assertEqual(result.amounts["after_known_monthly_cost_krw"].lower, 550000)

    def test_fee_ceiling_scope_and_vat_exclusion(self):
        data = payload()
        data["selections"]["property_type"] = "housing"
        data["numbers"].update(target_deposit_krw=5000000, target_monthly_rent_krw=350000)
        fee = brokerage_ceiling(parse_request(data).situation)
        self.assertEqual(fee[0], 147500)  # (5m + 350k*70)*0.005, before VAT
        for field, value in (("target_region", "busan"), ("property_type", "officetel")):
            other = copy.deepcopy(data)
            other["selections"][field] = value
            self.assertIsNone(brokerage_ceiling(parse_request(other).situation))


if __name__ == "__main__":
    unittest.main()
