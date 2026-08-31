"""Run the real Hybrid RAG for test_dataset.py scenarios and save RAGAS rows.

This module is the execution-side pair of ``src.ragas.test_dataset``. It does
not create another vector store, retriever, prompt, or LLM. Every structured
scenario is passed through the same PGVector + Elasticsearch + Weighted RRF +
LangChain report-generation pipeline used by ``src.run_rag``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.config import GenerationSettings, IngestSettings, PROJECT_ROOT
from src.generation.report_schema import RagRequest


DEFAULT_INPUT = (
    PROJECT_ROOT / "evaluation" / "ragas" / "ragas_test_dataset.jsonl"
)
DEFAULT_JSONL_OUTPUT = (
    PROJECT_ROOT / "evaluation" / "ragas" / "ragas_response_dataset.jsonl"
)
DEFAULT_CSV_OUTPUT = (
    PROJECT_ROOT / "evaluation" / "ragas" / "ragas_response_dataset.csv"
)
SUPPORTED_DATASET_ROLE = "end_to_end_scenario"


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
        help="test_dataset.py가 만든 JSONL 또는 CSV",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_JSONL_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="비용 확인용 최대 실행 사례 수",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="DB·Elasticsearch·OpenAI 호출 없이 입력 쌍과 모델 설정만 검증",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="한 사례가 실패해도 실패 정보를 저장하고 다음 사례 계속 실행",
    )
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 응답 데이터셋이 있으면 새 결과로 교체",
    )
    output_mode.add_argument(
        "--resume",
        action="store_true",
        help="기존 성공 행은 건너뛰고 미완료·실패 행부터 다시 실행",
    )
    return parser.parse_args()


def _decode_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return None
    if stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"JSONL {line_number}번째 줄을 해석할 수 없습니다: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL {line_number}번째 줄은 JSON 객체여야 합니다.")
        rows.append(payload)
    return rows


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for field in (
            "reference_contexts",
            "situation_json",
            "retrieved_contexts",
            "retrieved_evidence",
        ):
            if field in row:
                row[field] = _decode_json_value(row[field])
    return rows


def read_dataset(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"테스트 데이터셋을 찾을 수 없습니다: {path}")
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = _read_jsonl(path)
    elif suffix == ".csv":
        rows = _read_csv(path)
    else:
        raise ValueError("입력 데이터셋은 .jsonl 또는 .csv 파일이어야 합니다.")
    if not rows:
        raise ValueError(f"입력 데이터셋이 비어 있습니다: {path}")
    return rows


def select_scenario_rows(
    rows: list[dict[str, Any]], limit: int | None
) -> tuple[list[dict[str, Any]], int]:
    if limit is not None and limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    selected: list[dict[str, Any]] = []
    skipped = 0
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if row.get("dataset_role") != SUPPORTED_DATASET_ROLE:
            skipped += 1
            continue
        sample_id = str(row.get("sample_id", "")).strip()
        if not sample_id:
            raise ValueError(f"{index}번째 구조화 사례에 sample_id가 없습니다.")
        if sample_id in seen_ids:
            raise ValueError(f"중복 sample_id입니다: {sample_id}")
        seen_ids.add(sample_id)
        situation_payload = _decode_json_value(row.get("situation_json"))
        if not isinstance(situation_payload, dict):
            raise ValueError(f"{sample_id}의 situation_json이 JSON 객체가 아닙니다.")
        RagRequest.model_validate({"situation": situation_payload})
        if not str(row.get("user_input", "")).strip():
            raise ValueError(f"{sample_id}의 user_input이 비어 있습니다.")
        if not str(row.get("reference", "")).strip():
            raise ValueError(f"{sample_id}의 reference가 비어 있습니다.")
        reference_contexts = _decode_json_value(row.get("reference_contexts"))
        if not isinstance(reference_contexts, list) or not reference_contexts:
            raise ValueError(f"{sample_id}의 reference_contexts가 비어 있습니다.")

        normalized = dict(row)
        normalized["situation_json"] = situation_payload
        normalized["reference_contexts"] = reference_contexts
        selected.append(normalized)

    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError(
            f"dataset_role={SUPPORTED_DATASET_ROLE}인 평가 사례가 없습니다."
        )
    return selected, skipped


def _format_report_response(title: str, body: str) -> str:
    return f"# {title.strip()}\n\n{body.strip()}"


def _evidence_payload(generation_request: Any) -> list[dict[str, Any]]:
    return [
        {
            "corpus": evidence.corpus,
            "source_file": evidence.source_file,
            "page_number": evidence.page_number,
            "retrieval_methods": evidence.retrieval_methods,
            "hybrid_score": evidence.hybrid_score,
            "matched_queries": evidence.matched_queries,
            "content": evidence.content,
        }
        for evidence in generation_request.retrieved_context
    ]


def run_real_rag(
    row: dict[str, Any], generation_settings: GenerationSettings
) -> dict[str, Any]:
    """Populate one RAGAS row using the production-equivalent local pipeline."""
    # Keep validation and dataset inspection fast; these imports initialize the
    # database, embedding, Elasticsearch, and LangChain integration modules.
    from src.generation.report_generator import generate_narrative_report
    from src.retrieval.hybrid_pipeline import retrieve_hybrid_evidence

    request = RagRequest.model_validate({"situation": row["situation_json"]})
    generation_request = retrieve_hybrid_evidence(request.situation)
    report = generate_narrative_report(generation_request, generation_settings)
    evidence = _evidence_payload(generation_request)

    result = dict(row)
    result.update(
        {
            "retrieved_contexts": [item["content"] for item in evidence],
            "response": _format_report_response(
                report.report_title, report.report_body_markdown
            ),
            "response_title": report.report_title,
            "retrieved_evidence": evidence,
            "pipeline_type": "finance_guides_cases_weighted_rrf_report_v2",
            "financial_result": generation_request.financial_result.model_dump(mode="json") if generation_request.financial_result else None,
            "generation_model": generation_settings.model,
            "embedding_model": IngestSettings().embedding_model,
            "execution_status": "completed",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error_type": None,
            "error_message": None,
        }
    )
    return result


def _failed_row(
    row: dict[str, Any], error: Exception, generation_settings: GenerationSettings
) -> dict[str, Any]:
    result = dict(row)
    result.update(
        {
            "retrieved_contexts": [],
            "response": "",
            "response_title": "",
            "retrieved_evidence": [],
            "pipeline_type": "finance_guides_cases_weighted_rrf_report_v2",
            "generation_model": generation_settings.model,
            "embedding_model": IngestSettings().embedding_model,
            "execution_status": "failed",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
    )
    return result


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    return str(value)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    safe_rows = [_json_safe(row) for row in rows]
    content = "\n".join(
        json.dumps(row, ensure_ascii=False) for row in safe_rows
    )
    _atomic_write_text(path, f"{content}\n" if content else "")


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    safe_rows = [_json_safe(row) for row in rows]
    if not safe_rows:
        _atomic_write_text(path, "")
        return

    fieldnames: list[str] = []
    for row in safe_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in safe_rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )
    temporary.replace(path)


def _load_resume_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    rows = _read_jsonl(path)
    return {
        str(row["sample_id"]): row
        for row in rows
        if str(row.get("sample_id", "")).strip()
    }


def _ensure_output_mode(args: argparse.Namespace) -> None:
    existing = [path for path in (args.output, args.csv_output) if path.exists()]
    if existing and not (args.overwrite or args.resume or args.validate_only):
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"기존 출력 파일이 있습니다: {joined}. "
            "--overwrite 또는 --resume을 선택하세요."
        )


def _console_preview(value: Any, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _print_completed_preview(result: dict[str, Any]) -> None:
    evidence = result.get("retrieved_evidence", [])
    corpus_counts = Counter(
        str(item.get("corpus", "unknown"))
        for item in evidence
        if isinstance(item, dict)
    )
    method_counts = Counter(
        "+".join(item.get("retrieval_methods", [])) or "unknown"
        for item in evidence
        if isinstance(item, dict)
    )
    sources = list(
        dict.fromkeys(
            str(item.get("source_file", ""))
            for item in evidence
            if isinstance(item, dict) and item.get("source_file")
        )
    )
    print(
        "[retrieval] corpus="
        + ", ".join(f"{name}:{count}" for name, count in corpus_counts.items())
    )
    print(
        "[retrieval] methods="
        + ", ".join(f"{name}:{count}" for name, count in method_counts.items())
    )
    print(f"[retrieval] sources={', '.join(sources)}")
    print(f"[response] title={result.get('response_title', '')}")
    print(f"[response] preview={_console_preview(result.get('response', ''))}")


def main() -> None:
    _configure_utf8_console()
    args = parse_args()
    _ensure_output_mode(args)

    generation_settings = GenerationSettings()
    generation_settings.validate()
    rows = read_dataset(args.input)
    scenarios, skipped = select_scenario_rows(rows, args.limit)
    print(
        f"[input] 전체={len(rows)} 구조화_상황={len(scenarios)} "
        f"문서_프로브_제외={skipped}"
    )
    input_columns = len({key for row in rows for key in row})
    print(f"[shape] rows={len(rows)} columns={input_columns}")
    print(f"[sample] id={scenarios[0]['sample_id']}")
    print(f"[sample] question={_console_preview(scenarios[0]['user_input'])}")
    print(f"[sample] reference={_console_preview(scenarios[0]['reference'])}")
    print(
        f"[model] generation={generation_settings.model} "
        f"embedding={IngestSettings().embedding_model}"
    )

    if args.validate_only:
        print("[ok] 입력 데이터셋과 실제 RAG 모델 설정 검증 완료")
        return

    results_by_id = _load_resume_rows(args.output) if args.resume else {}
    ordered_ids = [str(row["sample_id"]) for row in scenarios]
    for position, row in enumerate(scenarios, start=1):
        sample_id = str(row["sample_id"])
        previous = results_by_id.get(sample_id)
        if args.resume and previous and previous.get("execution_status") == "completed":
            print(f"[skip] {position}/{len(scenarios)} {sample_id}: 이미 완료")
            continue

        print(f"[run] {position}/{len(scenarios)} {sample_id}")
        print(f"[question] {_console_preview(row.get('user_input', ''))}")
        try:
            result = run_real_rag(row, generation_settings)
        except Exception as error:  # CLI boundary: preserve per-sample failure details.
            if not args.continue_on_error:
                raise RuntimeError(
                    f"{sample_id} 실제 RAG 실행 실패: {error}"
                ) from error
            result = _failed_row(row, error, generation_settings)
            print(f"[failed] {sample_id}: {type(error).__name__}: {error}")
        else:
            print(
                f"[ok] {sample_id}: "
                f"contexts={len(result['retrieved_contexts'])} "
                f"response_chars={len(result['response'])}"
            )
            _print_completed_preview(result)

        results_by_id[sample_id] = result
        checkpoint = [
            results_by_id[item]
            for item in ordered_ids
            if item in results_by_id
        ]
        write_jsonl(checkpoint, args.output)
        write_csv(checkpoint, args.csv_output)

    final_rows = [
        results_by_id[item] for item in ordered_ids if item in results_by_id
    ]
    completed = sum(
        row.get("execution_status") == "completed" for row in final_rows
    )
    failed = sum(row.get("execution_status") == "failed" for row in final_rows)
    print(f"[done] completed={completed} failed={failed}")
    print(f"[shape] response_rows={len(final_rows)}")
    print(f"[output] JSONL={args.output.resolve()}")
    print(f"[output] CSV={args.csv_output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, ValidationError, RuntimeError) as error:
        raise SystemExit(f"RAGAS 응답 데이터셋 생성 실패: {error}") from error
