"""Local FastAPI service for PDF accessibility remediation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from config import ENGINE_TIMEOUT_SECONDS, MAX_UPLOAD_MB, OLLAMA_BASE_URL

APP_NAME = "Local PDF Accessibility Remediation Backend"
JOBS_ROOT = Path(tempfile.gettempdir()) / "pdf-accessibility-auditor" / "backend-jobs"
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

app = FastAPI(title=APP_NAME)


def delete_stale_job_directories(maximum_age_seconds: int = 7200) -> None:
    if not JOBS_ROOT.exists():
        return

    cutoff = time.time() - maximum_age_seconds
    for directory in JOBS_ROOT.iterdir():
        if directory.is_dir() and directory.stat().st_mtime < cutoff:
            shutil.rmtree(directory, ignore_errors=True)


delete_stale_job_directories()


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "ollama_base_url": OLLAMA_BASE_URL,
    }


def parse_tasks(task_value: str | None, tasks_value: str | None) -> list[str]:
    raw = tasks_value if tasks_value and tasks_value.strip() else task_value
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

    parsed: list[str] = []
    for item in raw.replace(";", ",").split(","):
        normalized = aliases.get(item.strip())
        if normalized is None:
            raise HTTPException(
                status_code=400,
                detail="Tasks must be image captioning, table summarization, or both.",
            )
        if normalized not in parsed:
            parsed.append(normalized)
    return parsed


async def save_upload(upload: UploadFile, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    await upload.seek(0)
    bytes_written = 0

    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"The uploaded PDF exceeds the {MAX_UPLOAD_MB} MB limit.",
                )
            output.write(chunk)
    return bytes_written


def read_result_objects(result_json: str) -> list[dict]:
    payload = json.loads(result_json)
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    if isinstance(payload, list):
        output: list[dict] = []
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("results"), list):
                output.extend(item["results"])
            elif isinstance(item, dict):
                output.append(item)
        return output
    return []


def run_engine_for_task(engine_script: Path, pdf_path: Path, output_dir: Path, task: str):
    task_output_dir = output_dir / task
    task_output_dir.mkdir(parents=True, exist_ok=True)
    results_json_path = task_output_dir / "all_results.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(engine_script),
            "--pdf",
            str(pdf_path),
            "--output",
            str(task_output_dir),
            "--task",
            task,
        ],
        cwd=str(engine_script.parent),
        capture_output=True,
        text=True,
        timeout=ENGINE_TIMEOUT_SECONDS,
        env=os.environ.copy(),
    )

    result_json = results_json_path.read_text(encoding="utf-8") if results_json_path.exists() else ""
    return completed, result_json


@app.post("/remediate")
async def remediate(
    pdf: UploadFile = File(...),
    task: str | None = Form(default=None),
    tasks: str | None = Form(default=None),
):
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="The uploaded file must have a .pdf filename.")

    selected_tasks = parse_tasks(task, tasks)
    job_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}"
    job_dir = JOBS_ROOT / job_id
    output_dir = job_dir / "engine_output"
    pdf_path = job_dir / "input.pdf"

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    exit_codes: list[int] = []
    combined_results: list[dict] = []

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        uploaded_bytes = await save_upload(pdf, pdf_path)
        if uploaded_bytes <= 0:
            raise HTTPException(status_code=400, detail="The uploaded PDF contained zero bytes.")

        engine_script = Path(__file__).resolve().parent / "remediation_engine.py"
        for selected_task in selected_tasks:
            stdout_parts.append(f"===== Task: {selected_task} =====\n")
            completed, result_json = run_engine_for_task(
                engine_script=engine_script,
                pdf_path=pdf_path,
                output_dir=output_dir,
                task=selected_task,
            )
            exit_codes.append(completed.returncode)
            stdout_parts.append(completed.stdout or "")
            stderr_parts.append(completed.stderr or "")
            if result_json:
                combined_results.extend(read_result_objects(result_json))

        success = bool(combined_results) and all(code == 0 for code in exit_codes)
        final_payload = {
            "document_name": pdf.filename,
            "failure_report": None,
            "tasks": selected_tasks,
            "results": combined_results,
        }

        return {
            "success": success,
            "status": "Engine complete" if success else "Engine failed",
            "job_id": job_id,
            "exit_code": max(exit_codes) if exit_codes else None,
            "stdout": "\n".join(stdout_parts),
            "stderr": "\n".join(stderr_parts),
            "result_json": json.dumps(final_payload, indent=2, ensure_ascii=False) if success else "",
            "error": "" if success else "The engine failed or produced no remediation results.",
        }
    except HTTPException:
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
                "error": f"Engine timed out after {ENGINE_TIMEOUT_SECONDS} seconds.",
            },
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
                "error": str(ex),
            },
        )
    finally:
        try:
            await pdf.close()
        except Exception:
            pass
        shutil.rmtree(job_dir, ignore_errors=True)
