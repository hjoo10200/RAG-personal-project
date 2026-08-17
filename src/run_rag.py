"""Run the real PGVector retrieval-to-Groq generation pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from groq import GroqError
from pydantic import ValidationError

from src.report_generator import generate_narrative_report
from src.report_schema import RagRequest
from src.rag_pipeline import retrieve_real_evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--evidence-output",
        type=Path,
        required=True,
        help="실제 PGVector 검색 근거를 저장할 JSON 경로",
    )
    parser.add_argument(
        "--retrieve-only",
        action="store_true",
        help="PGVector 검색과 증거 저장까지만 실행",
    )
    return parser.parse_args()


def load_request(path: Path) -> RagRequest:
    return RagRequest.model_validate_json(path.read_text(encoding="utf-8"))


def write_evidence(path: Path, request: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(request.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    try:
        rag_input = load_request(args.input)
        generation_request = retrieve_real_evidence(rag_input.situation)
        write_evidence(args.evidence_output, generation_request)
    except (OSError, ValidationError, ValueError, RuntimeError) as error:
        raise SystemExit(f"실제 PGVector 검색 실패: {error}") from error

    print(
        f"[ok] 실제 PGVector 근거 {len(generation_request.retrieved_context)}개 저장: "
        f"{args.evidence_output.resolve()}"
    )
    for evidence in generation_request.retrieved_context:
        print(
            f"[evidence] corpus={evidence.corpus} "
            f"source={evidence.source_file} page={evidence.page_number}"
        )

    if args.retrieve_only:
        return

    try:
        report = generate_narrative_report(generation_request)
    except (GroqError, ValidationError, ValueError) as error:
        raise SystemExit(f"실제 RAG 보고서 생성 실패: {error}") from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"[ok] 실제 RAG 보고서 저장: {args.output.resolve()}")


if __name__ == "__main__":
    main()
