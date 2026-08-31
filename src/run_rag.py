"""Run the real hybrid retrieval-to-OpenAI generation pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openai import OpenAIError
from pydantic import ValidationError

from src.generation.report_schema import RagRequest
from src.common.selection_input import load_request as load_versioned_request
from src.finance.calculator import prepare_finances


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--calculate-only", action="store_true", help="DB/API 없이 혼합 입력의 계산·판단만 저장"
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        required=False,
        help="실제 Hybrid 검색 근거를 저장할 JSON 경로",
    )
    mode.add_argument(
        "--retrieve-only",
        action="store_true",
        help="Hybrid 검색과 증거 저장까지만 실행",
    )
    return parser.parse_args()


def load_request(path: Path) -> RagRequest:
    return load_versioned_request(path)


def write_evidence(path: Path, request: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(request.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    if not args.calculate_only and args.evidence_output is None:
        raise SystemExit("검색 실행에는 --evidence-output이 필요합니다.")
    try:
        rag_input = load_request(args.input)
        finance = prepare_finances(rag_input.situation)
        print(f"[calculate] scope={finance.scope} initial={finance.initial_status} monthly={finance.monthly_status}")
        if args.calculate_only:
            write_evidence(args.output, finance)
            print(f"[ok] 계산·판단 저장: {args.output.resolve()}")
            return
        from src.retrieval.hybrid_pipeline import retrieve_hybrid_evidence

        generation_request = retrieve_hybrid_evidence(rag_input.situation, finance)
        write_evidence(args.evidence_output, generation_request)
    except (OSError, ValidationError, ValueError, RuntimeError) as error:
        raise SystemExit(f"실제 Hybrid 검색 실패: {error}") from error

    print(
        f"[ok] 실제 Hybrid 근거 {len(generation_request.retrieved_context)}개 저장: "
        f"{args.evidence_output.resolve()}"
    )
    for evidence in generation_request.retrieved_context:
        print(
            f"[evidence] corpus={evidence.corpus} "
            f"source={evidence.source_file} page={evidence.page_number} "
            f"methods={'+'.join(evidence.retrieval_methods)} "
            f"rrf={evidence.hybrid_score}"
        )

    if args.retrieve_only:
        return

    try:
        from src.generation.report_generator import generate_narrative_report

        report = generate_narrative_report(generation_request)
    except (OpenAIError, ValidationError, ValueError) as error:
        raise SystemExit(f"실제 RAG 보고서 생성 실패: {error}") from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"[ok] 실제 RAG 보고서 저장: {args.output.resolve()}")


if __name__ == "__main__":
    main()
