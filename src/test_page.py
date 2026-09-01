"""Local service prototype with real report/policy calls. Not a production server."""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from pydantic import ValidationError

from src.common.selection_input import CHOICES, NUMBER_FIELDS, NumericInputs, ProfileChoices, parse_request

ASSETS = Path(__file__).resolve().parent / "web"
POLICY_DOCUMENTS = Path(__file__).resolve().parents[1] / "knowledge_base" / "pdfs" / "policies"


def build_handler(*, enable_external: bool = False, actions: dict | None = None):
    from src.services import calculate, create_plan, create_report, search_policies

    functions = actions or {"calculate": calculate, "plan": create_plan, "report": create_report, "policies": search_policies}
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    jobs_lock = threading.Lock()
    jobs: dict[str, dict] = {}

    def reserve_job(action):
        job_id = secrets.token_urlsafe(18)
        with jobs_lock:
            if any(value["status"] == "running" for value in jobs.values()):
                raise RuntimeError("다른 작업을 처리하고 있습니다.")
            finished = sorted((value for value in jobs.values() if value["status"] != "running"), key=lambda value: value["created_at"])
            while len(jobs) >= 100 and finished:
                jobs.pop(finished.pop(0)["job_id"], None)
            if len(jobs) >= 100:
                raise RuntimeError("처리 대기열이 가득 찼습니다.")
            jobs[job_id] = {"job_id": job_id, "action": action, "status": "running",
                            "created_at": time.time(), "stage": "queued", "result": None}
        return job_id

    def start_action_job(payload, action):
        parse_request(payload)
        if action not in {"report", "policies"}:
            raise ValueError("지원하지 않는 작업입니다.")
        job_id = reserve_job(action)

        def progress(stage):
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["stage"] = stage

        def work():
            try:
                result = functions[action](payload, progress_callback=progress)
                with jobs_lock:
                    jobs[job_id].update(status="completed", stage="completed", result=result)
            except Exception as error:
                print(f"[job:{job_id}] {action}: {type(error).__name__}", flush=True)
                with jobs_lock:
                    jobs[job_id].update(status="failed", stage="failed", error_type=type(error).__name__)
        threading.Thread(target=work, daemon=True, name=f"{action}-{job_id[:6]}").start()
        return job_id

    def start_plan_job(payload):
        parse_request(payload)
        job_id = secrets.token_urlsafe(18)
        with jobs_lock:
            if any(value["status"] == "running" for value in jobs.values()):
                raise RuntimeError("다른 독립 계획을 만들고 있습니다.")
            finished = sorted((value for value in jobs.values() if value["status"] != "running"), key=lambda value: value["created_at"])
            while len(jobs) >= 100 and finished:
                jobs.pop(finished.pop(0)["job_id"], None)
            if len(jobs) >= 100:
                raise RuntimeError("처리 대기열이 가득 찼습니다.")
            jobs[job_id] = {"job_id": job_id, "status": "running", "created_at": time.time(),
                            "report_stage": "queued", "policies_stage": "queued", "result": None}

        def progress(branch, stage):
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id][f"{branch}_stage"] = stage

        def work():
            try:
                result = functions["plan"](payload, progress_callback=progress)
                with jobs_lock:
                    jobs[job_id].update(status="completed", result=result)
            except Exception as error:
                print(f"[job:{job_id}] {type(error).__name__}", flush=True)
                with jobs_lock:
                    jobs[job_id].update(status="failed", error_type=type(error).__name__)
        threading.Thread(target=work, daemon=True, name=f"plan-{job_id[:6]}").start()
        return job_id

    class Handler(BaseHTTPRequestHandler):
        def allowed_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8") if not isinstance(body, bytes) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed_host():
                return self.reply(403, {"error": "로컬 주소로 접속하세요."})
            if self.path == "/api/options":
                choices = {key: value for key, value in CHOICES.items() if key in ProfileChoices.model_fields}
                choices["property_type"] = {"housing": "일반 주택", "officetel": "오피스텔", "other": "기타", "unknown": "미정"}
                return self.reply(200, {"api_version": 2, "choices": choices, "defaults": ProfileChoices().model_dump(),
                                        "number_fields": NUMBER_FIELDS, "number_defaults": NumericInputs().model_dump(), "csrf": token,
                                        "external_enabled": enable_external})
            if self.path.startswith("/api/plan-jobs/") or self.path.startswith("/api/jobs/"):
                if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), token):
                    return self.reply(403, {"error": "진행 상태 요청을 확인할 수 없습니다."})
                prefix = "/api/plan-jobs/" if self.path.startswith("/api/plan-jobs/") else "/api/jobs/"
                job_id = self.path.removeprefix(prefix)
                with jobs_lock:
                    job = deepcopy(jobs.get(job_id))
                if not job:
                    return self.reply(404, {"error": "진행 중인 요청을 찾을 수 없습니다."})
                job.pop("created_at", None)
                return self.reply(200, job)
            if self.path.startswith("/documents/"):
                filename = unquote(self.path[len("/documents/"):])
                root = POLICY_DOCUMENTS.resolve()
                document = (root / filename).resolve()
                if document.parent != root or document.suffix.lower() != ".pdf" or not document.is_file():
                    return self.reply(404, {"error": "공고 파일을 찾을 수 없습니다."})
                return self.reply(200, document.read_bytes(), "application/pdf")
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8"),
                     "/progress.css": ("progress.css", "text/css; charset=utf-8"),
                     "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8")}
            if self.path not in files:
                return self.reply(404, {"error": "경로를 찾을 수 없습니다."})
            filename, mime = files[self.path]
            return self.reply(200, (ASSETS / filename).read_bytes(), mime)

        def do_POST(self):
            host = self.headers.get("Host", "")
            if not self.allowed_host() or self.headers.get("Origin") != f"http://{host}" or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), token):
                return self.reply(403, {"error": "요청 출처를 확인할 수 없습니다. 페이지를 새로고침하세요."})
            name = self.path.removeprefix("/api/")
            job_actions = {"report-jobs": "report", "policy-jobs": "policies"}
            if self.path != f"/api/{name}" or (name not in functions and name != "plan-jobs" and name not in job_actions):
                return self.reply(404, {"error": "알 수 없는 기능입니다."})
            if name != "calculate" and not enable_external:
                return self.reply(403, {"error": "실제 검색·생성은 --enable-external로 실행한 서버에서만 가능합니다."})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json" or self.headers.get("Transfer-Encoding"):
                return self.reply(415, {"error": "JSON 요청만 지원합니다."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    return self.reply(413, {"error": "요청 크기를 확인하세요."})
                self.connection.settimeout(10)
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("JSON 객체가 필요합니다.")
            except (ValueError, OSError):
                return self.reply(400, {"error": "입력 JSON을 확인하세요."})
            if name == "plan-jobs":
                if not enable_external:
                    return self.reply(403, {"error": "오프라인 모드에서는 실제 계획을 생성할 수 없습니다."})
                try:
                    return self.reply(202, {"job_id": start_plan_job(payload)})
                except ValidationError:
                    return self.reply(400, {"error": "선택 항목과 숫자 입력을 확인하세요."})
                except RuntimeError:
                    return self.reply(409, {"error": "다른 독립 계획을 만들고 있습니다. 현재 요청이 끝난 뒤 다시 시도해 주세요."})
            if name in job_actions:
                if not enable_external:
                    return self.reply(403, {"error": "오프라인 모드에서는 실제 작업을 실행할 수 없습니다."})
                try:
                    return self.reply(202, {"job_id": start_action_job(payload, job_actions[name])})
                except ValidationError:
                    return self.reply(400, {"error": "선택 항목과 숫자 입력을 확인하세요."})
                except RuntimeError:
                    return self.reply(409, {"error": "다른 작업을 처리하고 있습니다. 완료된 뒤 다시 시도해 주세요."})
            if not lock.acquire(blocking=False):
                return self.reply(409, {"error": "다른 요청을 처리 중입니다. 완료 후 다시 실행하세요."})
            try:
                self.reply(200, functions[name](payload))
            except ValidationError:
                self.reply(400, {"error": "선택 코드·숫자 입력·수입 상태·입력 버전을 확인하세요. 금액은 0 이상의 정수 원 단위입니다."})
            except Exception as error:
                # Do not expose API request/credentials or private local paths to a page.
                print(f"[error] {name}: {type(error).__name__}", flush=True)
                self.reply(500, {"error": f"{name} 실행 실패 ({type(error).__name__}). DB·환경설정과 저장된 실행 기록을 확인하세요."})
            finally:
                lock.release()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--enable-external", action="store_true", help="호환 옵션: 기본 실행도 실제 검색·생성을 허용")
    mode.add_argument("--offline", action="store_true", help="입력 화면만 보기: 실제 검색·생성 금지")
    args = parser.parse_args()
    enabled = not args.offline
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(enable_external=enabled))
    print(f"[ready] http://127.0.0.1:{server.server_port} 실제 서비스 모드={enabled} (종료: Ctrl+C)", flush=True)
    print("[notice] 사용자가 계획 만들기를 누르면 실제 검색·LLM API 비용이 발생할 수 있습니다. 입력과 결과는 로컬에 저장됩니다.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
