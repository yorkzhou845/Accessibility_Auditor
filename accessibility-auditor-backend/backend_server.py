import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse


APP_NAME = "Accessibility Auditor GB10 Backend"
JOBS_ROOT = Path(os.getenv("ACCESSIBILITY_AUDITOR_JOBS_ROOT", "/tmp/accessibility-auditor-jobs"))
BACKEND_API_KEY = os.getenv("ACCESSIBILITY_AUDITOR_BACKEND_API_KEY", "")
ENGINE_TIMEOUT_SECONDS = int(os.getenv("ACCESSIBILITY_AUDITOR_ENGINE_TIMEOUT_SECONDS", "3600"))

# Default to local Ollama on GB10 if no explicit endpoint is provided.
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

app = FastAPI(title=APP_NAME)


def delete_stale_job_directories(maximum_age_seconds: int = 7200):
    """Remove orphaned GB10 jobs left by an abrupt process termination."""
    if not JOBS_ROOT.exists():
        return

    cutoff = time.time() - maximum_age_seconds

    for directory in JOBS_ROOT.iterdir():
        if not directory.is_dir():
            continue

        try:
            if directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            # A concurrent request may still be using or removing the folder.
            pass


delete_stale_job_directories()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": APP_NAME,
        "auth_configured": bool(BACKEND_API_KEY),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "")
    }


def require_api_key(request: Request):
    if not BACKEND_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ACCESSIBILITY_AUDITOR_BACKEND_API_KEY is not configured on the server."
        )

    supplied_key = request.headers.get("X-API-KEY", "")

    if supplied_key != BACKEND_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid backend API key.")


async def save_upload(upload: UploadFile, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Ensure the multipart upload is read from the beginning even if another
    # component inspected the UploadFile before this function was called.
    await upload.seek(0)

    bytes_written = 0

    with destination.open("wb") as output:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break

            output.write(chunk)
            bytes_written += len(chunk)

        output.flush()
        os.fsync(output.fileno())

    return bytes_written


def parse_tasks(task_value: str | None, tasks_value: str | None):
    raw = tasks_value if tasks_value is not None and tasks_value.strip() else task_value
    raw = (raw or "").strip().lower()

    if not raw:
        raise HTTPException(status_code=400, detail="At least one task must be selected.")

    aliases = {
        "table": "table_summary",
        "table_summary": "table_summary",
        "table-summary": "table_summary",
        "tables": "table_summary",
        "image": "alt_text",
        "image_captioning": "alt_text",
        "image-captioning": "alt_text",
        "alt": "alt_text",
        "alt_text": "alt_text",
        "alt-text": "alt_text",
        "captioning": "alt_text",
    }

    parsed = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue

        normalized = aliases.get(item)
        if normalized is None:
            raise HTTPException(
                status_code=400,
                detail="Tasks must be image captioning, table summarization, or both."
            )

        if normalized not in parsed:
            parsed.append(normalized)

    if not parsed:
        raise HTTPException(status_code=400, detail="At least one task must be selected.")

    return parsed


def read_result_objects(result_json: str):
    if not result_json:
        return []

    payload = json.loads(result_json)

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]

    if isinstance(payload, list):
        output = []
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("results"), list):
                output.extend(item["results"])
            else:
                output.append(item)
        return output

    return []


def run_engine_for_task(engine_script: Path, pdf_path: Path, output_dir: Path, task: str):
    task_output_dir = output_dir / task
    task_output_dir.mkdir(parents=True, exist_ok=True)
    results_json_path = task_output_dir / "all_results.json"

    command = [
        sys.executable,
        str(engine_script),
        "--pdf",
        str(pdf_path),
        "--output",
        str(task_output_dir),
        "--task",
        task
    ]

    completed = subprocess.run(
        command,
        cwd=str(engine_script.parent),
        capture_output=True,
        text=True,
        timeout=ENGINE_TIMEOUT_SECONDS,
        env=os.environ.copy()
    )

    result_json = ""
    if results_json_path.exists():
        result_json = results_json_path.read_text(encoding="utf-8")

    return completed, result_json


@app.post("/remediate")
async def remediate(
    request: Request,
    pdf: UploadFile = File(...),
    task: str | None = Form(default=None),
    tasks: str | None = Form(default=None)
):
    require_api_key(request)

    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="The uploaded file must have a .pdf filename.")

    selected_tasks = parse_tasks(task, tasks)

    job_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}"
    job_dir = JOBS_ROOT / job_id
    output_dir = job_dir / "engine_output"
    pdf_path = job_dir / "input.pdf"

    stdout_parts = []
    stderr_parts = []
    exit_codes = []
    combined_results = []

    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        uploaded_bytes = await save_upload(pdf, pdf_path)

        if uploaded_bytes <= 0:
            raise HTTPException(
                status_code=400,
                detail="The uploaded PDF contained zero bytes. Please select the PDF again and retry."
            )

        engine_script = Path(__file__).resolve().parent / "remediation_engine.py"

        for selected_task in selected_tasks:
            stdout_parts.append(f"===== Task: {selected_task} =====\n")
            completed, result_json = run_engine_for_task(
                engine_script=engine_script,
                pdf_path=pdf_path,
                output_dir=output_dir,
                task=selected_task
            )

            exit_codes.append(completed.returncode)
            stdout_parts.append(completed.stdout or "")
            stderr_parts.append(completed.stderr or "")

            if result_json:
                combined_results.extend(read_result_objects(result_json))

        final_payload = {
            "document_name": pdf.filename,
            "failure_report": None,
            "tasks": selected_tasks,
            "results": combined_results
        }

        # Keep the final JSON only in memory. The Blazor app receives it in
        # this response and the GB10 temporary job directory is then deleted.
        final_result_json = json.dumps(final_payload, indent=2, ensure_ascii=False)
        success = bool(combined_results) and all(code == 0 for code in exit_codes)

        return {
            "success": success,
            "status": "Engine complete" if success else "Engine failed",
            "job_id": job_id,
            "exit_code": max(exit_codes) if exit_codes else None,
            "stdout": "\n".join(stdout_parts),
            "stderr": "\n".join(stderr_parts),
            "result_json": final_result_json if success else "",
            "error": "" if success else "Engine failed or no remediation results were created."
        }

    except HTTPException:
        # Preserve intended 4xx responses while still running the finally cleanup.
        raise

    except subprocess.TimeoutExpired as ex:
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "status": "Engine failed",
                "job_id": job_id,
                "exit_code": None,
                "stdout": ex.stdout or "",
                "stderr": ex.stderr or "",
                "result_json": "",
                "error": f"Engine timed out after {ENGINE_TIMEOUT_SECONDS} seconds."
            }
        )

    except Exception as ex:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "Engine failed",
                "job_id": job_id,
                "exit_code": None,
                "stdout": "\n".join(stdout_parts),
                "stderr": "\n".join(stderr_parts) + "\n" + str(ex),
                "result_json": "",
                "error": str(ex)
            }
        )

    finally:
        # Uploads, page renders, crops, and task result files exist only while
        # this request is running. They are removed after success or failure.
        try:
            await pdf.close()
        except Exception:
            pass

        shutil.rmtree(job_dir, ignore_errors=True)
