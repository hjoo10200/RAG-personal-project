"""Framework-independent entrypoints for CLI, local test page and Django views."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote

from src.common.selection_input import parse_request
from src.finance.calculator import prepare_finances

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "storage" / "generated_reports" / "v2"


def calculate(payload: dict) -> dict:
    request = parse_request(payload)
    return prepare_finances(request.situation).model_dump(mode="json")


def _new_run(output_root: Path) -> tuple[str, Path]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:10]
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    return run_id, directory


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def create_report(payload: dict, *, output_root: Path = OUTPUT_ROOT, progress_callback=None) -> dict:
    # No web framework types cross this boundary.
    from src.generation.report_generator import generate_narrative_report
    from src.retrieval.hybrid_pipeline import retrieve_hybrid_evidence

    request = parse_request(payload)
    finance = prepare_finances(request.situation)
    run_id, directory = _new_run(output_root)
    _save(directory / "input.json", payload)
    _save(directory / "finance.json", finance.model_dump(mode="json"))
    trace: dict = {"pipeline_version": "report-v2", "status": "running", "stage": "retrieval"}
    try:
        if progress_callback:
            progress_callback("retrieving")
        generation_request = retrieve_hybrid_evidence(request.situation, finance)
        _save(directory / "evidence.json", generation_request.model_dump(mode="json"))
        trace["stage"] = "generation"
        if progress_callback:
            progress_callback("generating")
        report = generate_narrative_report(generation_request, trace=trace)
        result = {"pipeline_version": "report-v2", "run_id": run_id,
                  "report": report.model_dump(), "finance": finance.model_dump(mode="json")}
        _save(directory / "report.json", report.model_dump())
        trace.update(status="completed", stage="completed")
        return result
    except Exception as error:
        # Exception text can include provider request details; retain only its type.
        trace.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        # Never store API credentials. Trace contains only prompt data and generated draft.
        _save(directory / "trace.json", trace)


def search_policies(payload: dict, *, output_root: Path = OUTPUT_ROOT, progress_callback=None) -> dict:
    """Policy retrieval does not invoke the calculator or report LLM."""
    from src.retrieval.hybrid_pipeline import retrieve_evidence

    request = parse_request(payload)
    if progress_callback:
        progress_callback("retrieving")
    evidence = retrieve_evidence(request.situation, corpora=("policies",), allow_empty=True)
    metadata_path = ROOT / "knowledge_base" / "metadata" / "search_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")).get("documents", {}) if metadata_path.exists() else {}
    grouped: dict[str, dict] = {}
    for item in evidence:
        entry = metadata.get(item.source_file, {})
        card = grouped.setdefault(item.source_file, {
            "title": entry.get("policy_name") or entry.get("document_title") or item.source_file,
            "source_file": item.source_file,
            "document_title": entry.get("document_title") or item.source_file,
            "document_url": "/documents/" + quote(item.source_file, safe=""),
            "topics": entry.get("search_keywords", [])[:4],
            "source_url": entry.get("source_url") or entry.get("url") or None,
            "application_period": entry.get("application_period") or "접수 정보 미확인",
            "notice": "관련 공고 검색 결과이며 자격·현재 모집 여부는 확인되지 않았습니다.",
            "excerpts": [],
        })
        card["excerpts"].append({"page_number": item.page_number, "content": item.content})
    run_id, directory = _new_run(output_root)
    result = {"pipeline_version": "policy-search-v2", "run_id": run_id,
              "retrieved_at": datetime.now(timezone.utc).isoformat(), "policies": list(grouped.values()),
              "notice": "검색 근거 발췌입니다. 전체 자격 판정이나 최신 공고 확인을 대신하지 않습니다."}
    _save(directory / "input.json", payload)
    _save(directory / "policies.json", result)
    _save(directory / "evidence.json", {"retrieved_context": [e.model_dump(mode="json") for e in evidence]})
    return result


def create_plan(payload: dict, *, output_root: Path = OUTPUT_ROOT, progress_callback=None) -> dict:
    """One user submission; independent real report and policy services.

    No sample/fallback content is substituted on failure. Successful branches
    remain available and can be reused when the client retries only a failure.
    """
    request = parse_request(payload)  # Invalid input must fail before either paid branch.
    # Finance is a local deterministic step. Keep it outside the report branch so
    # the dashboard remains available even when retrieval or generation fails.
    finance = prepare_finances(request.situation).model_dump(mode="json")
    run_id, directory = _new_run(output_root)
    _save(directory / "input.json", payload)
    _save(directory / "finance.json", finance)
    result = {"pipeline_version": "service-prototype-v2", "run_id": run_id, "finance": finance}
    def notify(branch, stage):
        if progress_callback:
            progress_callback(branch, stage)

    def run_branch(branch, function):
        try:
            value = function(deepcopy(payload), output_root=output_root,
                             progress_callback=lambda stage: notify(branch, stage))
            notify(branch, "completed")
            return value
        except Exception:
            notify(branch, "failed")
            raise

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            "report": executor.submit(run_branch, "report", create_report),
            "policies": executor.submit(run_branch, "policies", search_policies),
        }
        for name, future in futures.items():
            try:
                result[name] = {"status": "completed", "data": future.result()}
            except Exception as error:
                # Provider exceptions may contain private request details.
                print(f"[plan:{run_id}] {name}: {type(error).__name__}", flush=True)
                result[name] = {"status": "failed", "error_type": type(error).__name__,
                                "message": "결과를 가져오지 못했습니다. 잠시 후 이 항목만 다시 시도해 주세요."}
    statuses = [result[name]["status"] for name in ("report", "policies")]
    result["status"] = "completed" if all(s == "completed" for s in statuses) else "failed" if all(s == "failed" for s in statuses) else "partial"
    _save(directory / "plan.json", result)
    return result
