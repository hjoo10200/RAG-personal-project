"""Evaluate a completed response dataset with RAGAS 0.3.9 metrics.

This is the scoring-side companion of ``test_dataset.py`` and
``response_dataset.py``. It reads only completed end-to-end RAG rows and
computes response relevancy, faithfulness, context recall, and context
precision in one RAGAS evaluation run.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from src.config import PROJECT_ROOT
from src.ragas.response_dataset import read_dataset


DEFAULT_INPUT = (
    PROJECT_ROOT / "evaluation" / "ragas" / "ragas_response_dataset.jsonl"
)
DEFAULT_RESULTS_ROOT = PROJECT_ROOT / "evaluation" / "ragas" / "results"
DEFAULT_TIKTOKEN_CACHE = PROJECT_ROOT / "storage" / "cache" / "tiktoken"
METRIC_NAMES = (
    "answer_relevancy",
    "faithfulness",
    "context_recall",
    "context_precision",
)
COMPACT_RESULT_COLUMNS = (
    "sample_id",
    "evaluation_focus",
    *METRIC_NAMES,
    "metric_failure_count",
    "min_score",
    "diagnosis",
    "is_low_score",
    "generation_model",
    "judge_model",
    "retrieved_context_count",
    "reference_context_count",
)


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="response_dataset.py가 만든 완료 응답 JSONL 또는 CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="결과 디렉터리. 생략하면 실행 시각별 새 디렉터리 생성",
    )
    parser.add_argument(
        "--judge-model",
        default=os.getenv("RAGAS_JUDGE_MODEL", "gpt-5.4"),
        help="RAGAS LLM 판정 모델(기본 gpt-5.4)",
    )
    parser.add_argument(
        "--embedding-model",
        default=os.getenv(
            "RAGAS_EVALUATOR_EMBEDDING_MODEL", "text-embedding-3-small"
        ),
        help="answer relevancy 계산용 임베딩 모델",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh"),
        default=os.getenv("RAGAS_JUDGE_REASONING_EFFORT", "low"),
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--low-score-threshold",
        type=float,
        default=0.7,
        help="낮은 점수 사례로 분류할 기준(0~1)",
    )
    parser.add_argument(
        "--normalize-whitespace",
        action="store_true",
        help="평가 전 줄바꿈·연속 공백만 정규화. 기호와 금액은 보존",
    )
    exception_group = parser.add_mutually_exclusive_group()
    exception_group.add_argument(
        "--raise-exceptions",
        dest="raise_exceptions",
        action="store_true",
        help="한 지표 호출 실패 시 즉시 중단(기본 동작)",
    )
    exception_group.add_argument(
        "--continue-on-error",
        dest="raise_exceptions",
        action="store_false",
        help="일부 지표 실패를 NaN으로 기록하고 계속 평가",
    )
    parser.set_defaults(raise_exceptions=True)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="OpenAI·RAGAS 호출 없이 입력 필드와 설정만 검증",
    )
    return parser.parse_args()


def _validate_runtime_args(args: argparse.Namespace) -> None:
    if args.timeout <= 0:
        raise ValueError("timeout은 1 이상이어야 합니다.")
    if args.max_retries < 0:
        raise ValueError("max-retries는 0 이상이어야 합니다.")
    if args.max_workers < 1:
        raise ValueError("max-workers는 1 이상이어야 합니다.")
    if args.batch_size is not None and args.batch_size < 1:
        raise ValueError("batch-size는 1 이상이어야 합니다.")
    if args.limit is not None and args.limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")
    if not 0 <= args.low_score_threshold <= 1:
        raise ValueError("low-score-threshold는 0 이상 1 이하여야 합니다.")
    if not str(args.judge_model).strip():
        raise ValueError("judge-model은 비어 있을 수 없습니다.")
    if not str(args.embedding_model).strip():
        raise ValueError("embedding-model은 비어 있을 수 없습니다.")


def _normalize_text(value: str, normalize_whitespace: bool) -> str:
    """Remove unsafe control bytes without destroying policy or money symbols."""
    text = value.replace("\x00", " ")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    if normalize_whitespace:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def _as_text_list(value: Any, field_name: str, sample_id: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{sample_id}의 {field_name}는 비어 있지 않은 목록이어야 합니다.")
    contexts: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"{sample_id}의 {field_name}[{index}]가 문자열이 아니거나 비어 있습니다."
            )
        contexts.append(item)
    return contexts


def prepare_completed_rows(
    rows: list[dict[str, Any]],
    *,
    normalize_whitespace: bool,
    limit: int | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Validate RAGAS columns and keep stable metadata by sample_id."""
    completed: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    skipped_failed = 0
    skipped_other_role = 0

    for index, row in enumerate(rows, start=1):
        if row.get("dataset_role") != "end_to_end_scenario":
            skipped_other_role += 1
            continue
        if row.get("execution_status") != "completed":
            skipped_failed += 1
            continue

        sample_id = str(row.get("sample_id", "")).strip()
        if not sample_id:
            raise ValueError(f"{index}번째 완료 행에 sample_id가 없습니다.")
        if sample_id in seen_ids:
            raise ValueError(f"중복 sample_id입니다: {sample_id}")
        seen_ids.add(sample_id)

        required_text = {}
        for field in ("user_input", "response", "reference"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{sample_id}의 {field}가 비어 있습니다.")
            required_text[field] = _normalize_text(value, normalize_whitespace)

        retrieved = _as_text_list(
            row.get("retrieved_contexts"), "retrieved_contexts", sample_id
        )
        references = _as_text_list(
            row.get("reference_contexts"), "reference_contexts", sample_id
        )
        normalized_row = dict(row)
        normalized_row.update(required_text)
        normalized_row["retrieved_contexts"] = [
            _normalize_text(text, normalize_whitespace) for text in retrieved
        ]
        normalized_row["reference_contexts"] = [
            _normalize_text(text, normalize_whitespace) for text in references
        ]
        normalized_row["retrieved_context_count"] = len(retrieved)
        normalized_row["reference_context_count"] = len(references)
        completed.append(normalized_row)

    if limit is not None:
        completed = completed[:limit]
    if not completed:
        raise ValueError("RAGAS로 평가할 execution_status=completed 행이 없습니다.")

    audit = {
        "input_rows": len(rows),
        "evaluated_rows": len(completed),
        "skipped_failed_rows": skipped_failed,
        "skipped_other_role_rows": skipped_other_role,
    }
    return completed, audit


def _evaluation_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "user_input": row["user_input"],
            "retrieved_contexts": row["retrieved_contexts"],
            "response": row["response"],
            "reference": row["reference"],
            "reference_contexts": row["reference_contexts"],
        }
        for row in rows
    ]


def _create_evaluator(args: argparse.Namespace) -> tuple[Any, Any, list[Any], Any]:
    """Import RAGAS lazily so --validate-only works without API/cache access."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.lower().startswith("your_"):
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset
    from ragas.embeddings.base import LangchainEmbeddingsWrapper
    from ragas.llms.base import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    judge_llm = LangchainLLMWrapper(
        ChatOpenAI(
            model=args.judge_model,
            timeout=args.timeout,
            max_retries=args.max_retries,
            reasoning_effort=args.reasoning_effort,
        ),
        # RAGAS 0.3.9 changes temperature per prompt. GPT-5.4 accepts only
        # its default temperature, so forwarding RAGAS's 0.3 value causes a
        # 400 response and turns every metric into NaN when errors are hidden.
        bypass_temperature=True,
        bypass_n=True,
    )
    judge_embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(
            api_key=api_key,
            model=args.embedding_model,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )
    )
    metrics = [
        ResponseRelevancy(
            llm=judge_llm,
            embeddings=judge_embeddings,
            strictness=3,
        ),
        Faithfulness(llm=judge_llm),
        LLMContextRecall(llm=judge_llm),
        LLMContextPrecisionWithReference(
            name="context_precision",
            llm=judge_llm,
        ),
    ]
    return judge_llm, judge_embeddings, metrics, EvaluationDataset


def run_evaluation(
    rows: list[dict[str, Any]], args: argparse.Namespace
) -> pd.DataFrame:
    from ragas import evaluate
    from ragas.run_config import RunConfig

    judge_llm, judge_embeddings, metrics, evaluation_dataset_class = (
        _create_evaluator(args)
    )
    dataset = evaluation_dataset_class.from_list(_evaluation_payload(rows))
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=judge_llm,
        embeddings=judge_embeddings,
        experiment_name="youth_independence_report_ragas",
        run_config=RunConfig(
            timeout=args.timeout,
            max_retries=args.max_retries,
            max_workers=args.max_workers,
            seed=42,
        ),
        raise_exceptions=args.raise_exceptions,
        show_progress=True,
        batch_size=args.batch_size,
    )
    evaluated = result.to_pandas()
    if len(evaluated) != len(rows):
        raise RuntimeError(
            f"평가 행 수가 달라졌습니다: 입력={len(rows)}, 결과={len(evaluated)}"
        )

    # EvaluationDataset intentionally excludes project metadata. Restore it by
    # stable row position instead of merging on possibly duplicated user_input.
    evaluated.insert(0, "sample_id", [row["sample_id"] for row in rows])
    evaluated.insert(
        1,
        "evaluation_focus",
        [row.get("evaluation_focus", "") for row in rows],
    )
    evaluated["generation_model"] = [
        row.get("generation_model", "") for row in rows
    ]
    evaluated["judge_model"] = args.judge_model
    evaluated["retrieved_context_count"] = [
        row["retrieved_context_count"] for row in rows
    ]
    evaluated["reference_context_count"] = [
        row["reference_context_count"] for row in rows
    ]
    return evaluated


def diagnose_rag_failure(row: pd.Series, threshold: float) -> str:
    scores = [row.get(metric) for metric in METRIC_NAMES]
    if any(pd.isna(value) for value in scores):
        return "평가 호출 오류 또는 결측 점수 확인"

    retrieval_low = min(row["context_recall"], row["context_precision"]) < threshold
    generation_low = min(row["answer_relevancy"], row["faithfulness"]) < threshold
    if retrieval_low and generation_low:
        return "검색과 생성 모두 점검"
    if retrieval_low:
        return "검색 단계 우선 점검"
    if generation_low:
        return "생성 단계 우선 점검"
    return "기준 이상"


def analyze_scores(
    evaluated: pd.DataFrame, threshold: float
) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing = [metric for metric in METRIC_NAMES if metric not in evaluated.columns]
    if missing:
        raise ValueError(f"RAGAS 결과에 지표 컬럼이 없습니다: {missing}")

    scored = evaluated.copy()
    scored[list(METRIC_NAMES)] = scored[list(METRIC_NAMES)].apply(
        pd.to_numeric, errors="coerce"
    )
    scored["metric_failure_count"] = scored[list(METRIC_NAMES)].isna().sum(axis=1)
    scored["min_score"] = scored[list(METRIC_NAMES)].min(axis=1, skipna=True)
    scored.loc[scored["metric_failure_count"] == len(METRIC_NAMES), "min_score"] = math.nan
    scored["diagnosis"] = scored.apply(
        diagnose_rag_failure, axis=1, threshold=threshold
    )
    scored["is_low_score"] = (
        scored["min_score"].lt(threshold) | scored["metric_failure_count"].gt(0)
    )

    metric_summary: dict[str, Any] = {}
    for metric in METRIC_NAMES:
        series = scored[metric]
        valid_series = series.dropna()
        metric_summary[metric] = {
            "mean": _safe_float(valid_series.mean()) if not valid_series.empty else None,
            "median": (
                _safe_float(valid_series.median()) if not valid_series.empty else None
            ),
            "min": _safe_float(valid_series.min()) if not valid_series.empty else None,
            "max": _safe_float(valid_series.max()) if not valid_series.empty else None,
            "valid_count": int(valid_series.count()),
            "failure_count": int(series.isna().sum()),
        }
    has_metric_failure = scored[list(METRIC_NAMES)].isna().any().any()
    summary = {
        "evaluation_status": "partial" if has_metric_failure else "completed",
        "evaluated_rows": len(scored),
        "low_score_threshold": threshold,
        "low_score_rows": int(scored["is_low_score"].sum()),
        "metrics": metric_summary,
        "low_score_sample_ids": scored.loc[
            scored["is_low_score"], "sample_id"
        ].tolist(),
    }
    return scored, summary


def validate_evaluation_completeness(summary: dict[str, Any]) -> None:
    """Reject runs that produced no usable score for one or more metrics."""
    failed_metrics = [
        metric
        for metric in METRIC_NAMES
        if summary["metrics"][metric]["valid_count"] == 0
    ]
    if failed_metrics:
        joined = ", ".join(failed_metrics)
        raise RuntimeError(
            "정상 평가 결과를 만들 수 없습니다. 유효 점수가 하나도 없는 지표: "
            f"{joined}. 평가 보고서와 점수 파일을 저장하지 않습니다. "
            "기본 예외 표시 모드에서 앞선 API 또는 파싱 오류를 확인하세요."
        )


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 6)


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _resolve_output_dir(path: Path | None) -> Path:
    if path is not None:
        return path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_RESULTS_ROOT / timestamp


def _write_jsonl(frame: pd.DataFrame, path: Path) -> None:
    records = [_json_safe(record) for record in frame.to_dict(orient="records")]
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _compact_score_frame(scored: pd.DataFrame) -> pd.DataFrame:
    """Keep result artifacts small; source text remains in the input dataset."""
    available = [column for column in COMPACT_RESULT_COLUMNS if column in scored]
    return scored.loc[:, available].copy()


def _write_markdown_report(
    summary: dict[str, Any], scored: pd.DataFrame, config: dict[str, Any], path: Path
) -> None:
    lines = [
        "# RAGAS 평가 결과",
        "",
        "## 실행 설정",
        "",
        f"- 평가 시각(UTC): {config['evaluated_at']}",
        f"- 입력 파일: `{config['input_file']}`",
        f"- 보고서 생성 모델: `{config['generation_models']}`",
        f"- 판정 모델: `{config['judge_model']}`",
        f"- 임베딩 모델: `{config['embedding_model']}`",
        f"- 평가 문항: {summary['evaluated_rows']}개",
        f"- 평가 상태: `{summary['evaluation_status']}`",
        f"- 낮은 점수 기준: {summary['low_score_threshold']}",
        "",
        "## 지표 요약",
        "",
        "| 지표 | 평균 | 중앙값 | 최솟값 | 최댓값 | 성공 | 실패 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in METRIC_NAMES:
        stats = summary["metrics"][metric]
        lines.append(
            f"| {metric} | {_format_score(stats['mean'])} | "
            f"{_format_score(stats['median'])} | {_format_score(stats['min'])} | "
            f"{_format_score(stats['max'])} | {stats['valid_count']} | "
            f"{stats['failure_count']} |"
        )

    lines.extend(["", "## 낮은 점수 및 오류 사례", ""])
    low_rows = scored[scored["is_low_score"]].sort_values(
        "min_score", na_position="first"
    )
    if low_rows.empty:
        lines.append("낮은 점수 기준 미만이거나 평가에 실패한 사례가 없습니다.")
    else:
        lines.extend(
            [
                "| sample_id | 최저 점수 | 진단 | 평가 초점 |",
                "|---|---:|---|---|",
            ]
        )
        for _, row in low_rows.iterrows():
            focus = str(row.get("evaluation_focus", "")).replace("|", "/")
            diagnosis = str(row["diagnosis"]).replace("|", "/")
            lines.append(
                f"| {row['sample_id']} | {_format_score(_safe_float(row['min_score']))} "
                f"| {diagnosis} | {focus} |"
            )

    lines.extend(
        [
            "",
            "## 해석 기준",
            "",
            "- `context_recall`과 `context_precision`이 낮으면 검색 질의, 청킹, "
            "코퍼스 구성과 RRF 결합 결과를 먼저 확인합니다.",
            "- `answer_relevancy`와 `faithfulness`가 낮으면 생성 프롬프트, 검색 근거 "
            "사용 방식과 근거 없는 단정을 먼저 확인합니다.",
            "- 점수가 `NaN`이면 품질 점수가 낮다는 뜻이 아니라 해당 평가 호출이 "
            "실패했다는 뜻이므로 오류와 재실행 여부를 먼저 확인합니다.",
            "- 자동 점수는 보고서 실용성에 대한 사람 평가를 대체하지 않습니다.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_score(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def save_results(
    scored: pd.DataFrame,
    summary: dict[str, Any],
    audit: dict[str, int],
    args: argparse.Namespace,
    rows: list[dict[str, Any]],
) -> Path:
    output_dir = _resolve_output_dir(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"비어 있지 않은 결과 디렉터리입니다: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(args.input.resolve()),
        "judge_model": args.judge_model,
        "judge_reasoning_effort": args.reasoning_effort,
        "embedding_model": args.embedding_model,
        "generation_models": sorted(
            {str(row.get("generation_model", "unknown")) for row in rows}
        ),
        "normalization": "whitespace" if args.normalize_whitespace else "control_only",
        "run_config": {
            "timeout": args.timeout,
            "max_retries": args.max_retries,
            "max_workers": args.max_workers,
            "batch_size": args.batch_size,
            "raise_exceptions": args.raise_exceptions,
        },
        "input_audit": audit,
    }
    summary_payload = {**summary, "config": config}

    # The response dataset is the source of truth for long texts and contexts.
    # Score artifacts intentionally contain only metrics and trace metadata.
    compact_scores = _compact_score_frame(scored)
    compact_scores.to_csv(
        output_dir / "ragas_scores.csv", index=False, encoding="utf-8-sig"
    )
    _write_jsonl(compact_scores, output_dir / "ragas_scores.jsonl")
    (output_dir / "ragas_summary.json").write_text(
        json.dumps(_json_safe(summary_payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown_report(
        summary_payload,
        scored,
        config,
        output_dir / "ragas_evaluation_report.md",
    )
    return output_dir


def main() -> None:
    _configure_utf8_console()
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(DEFAULT_TIKTOKEN_CACHE))
    _validate_runtime_args(args)

    source_rows = read_dataset(args.input)
    rows, audit = prepare_completed_rows(
        source_rows,
        normalize_whitespace=args.normalize_whitespace,
        limit=args.limit,
    )
    generation_models = sorted(
        {str(row.get("generation_model", "unknown")) for row in rows}
    )
    print(
        f"[input] 전체={audit['input_rows']} 평가={audit['evaluated_rows']} "
        f"실패_제외={audit['skipped_failed_rows']} "
        f"다른_역할_제외={audit['skipped_other_role_rows']}"
    )
    input_columns = len({key for row in source_rows for key in row})
    print(f"[shape] rows={audit['evaluated_rows']} input_columns={input_columns}")
    print(f"[sample] id={rows[0]['sample_id']}")
    print(f"[sample] user_input={_console_preview(rows[0]['user_input'])}")
    print(f"[sample] reference={_console_preview(rows[0]['reference'])}")
    print(
        f"[model] generation={generation_models} judge={args.judge_model} "
        f"embedding={args.embedding_model}"
    )

    if args.validate_only:
        print("[ok] RAGAS 입력 필드와 평가 설정 검증 완료")
        return

    evaluated = run_evaluation(rows, args)
    scored, summary = analyze_scores(evaluated, args.low_score_threshold)
    validate_evaluation_completeness(summary)
    output_dir = save_results(scored, summary, audit, args, rows)
    print(
        f"[done] 평가={summary['evaluated_rows']} "
        f"낮은점수_또는오류={summary['low_score_rows']}"
    )
    for metric in METRIC_NAMES:
        stats = summary["metrics"][metric]
        print(
            f"[metric] {metric}: mean={stats['mean']} median={stats['median']} "
            f"min={stats['min']} max={stats['max']} "
            f"valid={stats['valid_count']} failed={stats['failure_count']}"
        )
    low_rows = scored[scored["is_low_score"]].sort_values(
        "min_score", na_position="first"
    )
    if low_rows.empty:
        print("[low-score] 기준 미만 또는 평가 오류 사례 없음")
    else:
        for _, row in low_rows.iterrows():
            print(
                f"[low-score] id={row['sample_id']} min={_safe_float(row['min_score'])} "
                f"diagnosis={row['diagnosis']}"
            )
    print(f"[output] {output_dir.resolve()}")


def _console_preview(value: Any, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"RAGAS 평가 실패: {error}") from error
