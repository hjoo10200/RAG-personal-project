"""CLI for the isolated narrative-report generation smoke test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openai import OpenAIError
from pydantic import ValidationError

from src.config import GenerationSettings
from src.generation.report_generator import create_report_model, generate_narrative_report
from src.generation.report_schema import GenerationRequest, NarrativeDraft, NarrativeReport


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenAI 종합 자취 보고서 생성 단계를 독립적으로 시험합니다."
    )
    parser.add_argument("--input", type=Path, help="GenerationRequest JSON 파일")
    parser.add_argument("--output", type=Path, help="생성 보고서 JSON 저장 경로")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="API 호출 없이 환경설정과 모델 초기화만 확인",
    )
    parser.add_argument(
        "--validate-input",
        action="store_true",
        help="API 호출 없이 입력 JSON과 출력 스키마만 확인",
    )
    return parser.parse_args()


def load_request(path: Path) -> GenerationRequest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return GenerationRequest.model_validate(payload)


def validate_output_schema() -> None:
    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                properties = set(node.get("properties", {}))
                required = set(node.get("required", []))
                if required != properties:
                    raise ValueError(
                        "strict 스키마의 모든 object 필드는 required여야 합니다."
                    )
                if node.get("additionalProperties") is not False:
                    raise ValueError(
                        "strict 스키마의 모든 object는 "
                        "additionalProperties=false여야 합니다."
                    )
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(NarrativeDraft.model_json_schema())
    visit(NarrativeReport.model_json_schema())


def main() -> None:
    args = parse_args()

    if args.check_config:
        settings = GenerationSettings()
        try:
            create_report_model(settings)
        except ValueError as error:
            raise SystemExit(f"OpenAI 설정 검증 실패: {error}") from error
        print(f"[ok] OpenAI 설정 및 모델 초기화: {settings.model}")
        return

    if args.input is None:
        raise SystemExit("--input을 지정하세요.")

    try:
        request = load_request(args.input)
        validate_output_schema()
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
        raise SystemExit(f"입력 또는 스키마 검증 실패: {error}") from error

    if args.validate_input:
        print(
            f"[ok] 입력 검증: 검색 근거 {len(request.retrieved_context)}개, "
            f"목적={request.situation.purpose}"
        )
        print("[ok] NarrativeReport JSON Schema 검증")
        return

    if args.output is None:
        raise SystemExit("실제 생성 시 --output을 지정하세요.")

    try:
        report = generate_narrative_report(request)
    except (OpenAIError, ValidationError, ValueError) as error:
        raise SystemExit(f"OpenAI 설정 또는 보고서 검증 실패: {error}") from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"[ok] 종합 보고서 JSON 저장: {args.output.resolve()}")


if __name__ == "__main__":
    main()
