from __future__ import annotations

import unittest

import pandas as pd

from src.ragas.ragas import (
    _compact_score_frame,
    analyze_scores,
    prepare_completed_rows,
    validate_evaluation_completeness,
)


class RagasEvaluationTest(unittest.TestCase):
    def _completed_row(self) -> dict[str, object]:
        return {
            "sample_id": "scenario_1",
            "dataset_role": "end_to_end_scenario",
            "execution_status": "completed",
            "user_input": "월세 60만 원과 관리비 10만 원을 고려한 서울 자취 계획",
            "retrieved_contexts": ["보증금은 5,000,000원이며 전용면적은 20㎡입니다."],
            "response": "월세·관리비와 계약 조건을 함께 확인해야 합니다.",
            "reference": "금액과 계약 조건을 함께 비교해야 합니다.",
            "reference_contexts": ["계약 전 보증금과 관리비 항목을 확인합니다."],
            "generation_model": "gpt-5.4-mini",
        }

    def test_prepare_keeps_meaningful_symbols_and_skips_failed_rows(self) -> None:
        failed = self._completed_row()
        failed["sample_id"] = "scenario_failed"
        failed["execution_status"] = "failed"

        rows, audit = prepare_completed_rows(
            [self._completed_row(), failed],
            normalize_whitespace=True,
            limit=None,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(audit["skipped_failed_rows"], 1)
        self.assertIn("5,000,000원", rows[0]["retrieved_contexts"][0])
        self.assertIn("20㎡", rows[0]["retrieved_contexts"][0])

    def test_analyze_scores_distinguishes_retrieval_and_generation(self) -> None:
        evaluated = pd.DataFrame(
            [
                {
                    "sample_id": "retrieval_low",
                    "answer_relevancy": 0.9,
                    "faithfulness": 0.9,
                    "context_recall": 0.4,
                    "context_precision": 0.6,
                },
                {
                    "sample_id": "generation_low",
                    "answer_relevancy": 0.5,
                    "faithfulness": 0.6,
                    "context_recall": 0.9,
                    "context_precision": 0.9,
                },
            ]
        )

        scored, summary = analyze_scores(evaluated, threshold=0.7)

        diagnoses = dict(zip(scored["sample_id"], scored["diagnosis"]))
        self.assertEqual(diagnoses["retrieval_low"], "검색 단계 우선 점검")
        self.assertEqual(diagnoses["generation_low"], "생성 단계 우선 점검")
        self.assertEqual(summary["low_score_rows"], 2)

    def test_all_nan_metrics_are_rejected_before_saving(self) -> None:
        evaluated = pd.DataFrame(
            [
                {
                    "sample_id": "all_failed",
                    "answer_relevancy": None,
                    "faithfulness": None,
                    "context_recall": None,
                    "context_precision": None,
                }
            ]
        )

        _, summary = analyze_scores(evaluated, threshold=0.7)

        with self.assertRaisesRegex(RuntimeError, "유효 점수가 하나도 없는 지표"):
            validate_evaluation_completeness(summary)

    def test_score_artifact_excludes_long_source_text(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "sample_id": "scenario_1",
                    "evaluation_focus": "근거성",
                    "user_input": "긴 사용자 입력",
                    "response": "긴 생성 보고서",
                    "retrieved_contexts": ["긴 검색 문맥"],
                    "reference_contexts": ["긴 기준 문맥"],
                    "answer_relevancy": 0.8,
                    "faithfulness": 0.9,
                    "context_recall": 0.7,
                    "context_precision": 0.6,
                    "metric_failure_count": 0,
                    "min_score": 0.6,
                    "diagnosis": "검색 단계 우선 점검",
                    "is_low_score": True,
                }
            ]
        )

        compact = _compact_score_frame(scored)

        self.assertIn("sample_id", compact.columns)
        self.assertIn("faithfulness", compact.columns)
        self.assertNotIn("response", compact.columns)
        self.assertNotIn("retrieved_contexts", compact.columns)
        self.assertNotIn("reference_contexts", compact.columns)


if __name__ == "__main__":
    unittest.main()
