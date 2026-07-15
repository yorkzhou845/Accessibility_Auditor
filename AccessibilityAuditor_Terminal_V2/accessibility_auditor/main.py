"""Batch orchestration for the local accessibility analysis pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz

from . import config as cfg
from .file_matching import get_failure_report_path
from .processors import (
    process_alt_text_document,
    process_semantic_structure_document,
    process_table_summary_document,
    unsupported_result,
)
from .router import classify_task_with_llm
from .vector_store import ensure_vector_store, format_reference_context

SUPPORTED_TASKS = ("auto", "semantic_structure", "alt_text", "table_summary")


def _load_failure_report(pdf_path: Path) -> tuple[Path | None, str]:
    report_path = get_failure_report_path(pdf_path)
    if report_path is None:
        return None, ""
    return report_path, report_path.read_text(encoding="utf-8", errors="replace")


def _reference_query(task: str, failure_report: str) -> str:
    labels = {
        "semantic_structure": "PDF heading hierarchy and semantic structure guidance",
        "alt_text": "PDF image alternative text and decorative image guidance",
        "table_summary": "PDF table structure, headers, and concise table description guidance",
    }
    return f"{labels.get(task, 'PDF accessibility guidance')}\n{failure_report[:500]}"


def process_one_pdf(pdf_path: Path, forced_task: str = "auto") -> dict:
    report_path, failure_report = _load_failure_report(pdf_path)

    print("=" * 80, flush=True)
    print(f"Processing PDF: {pdf_path.name}", flush=True)

    if forced_task == "auto":
        if report_path is None:
            skipped = [
                {
                    "document_name": pdf_path.name,
                    "task": "skipped",
                    "remediations": [],
                    "warnings": [
                        "No matching failure report was found. Add "
                        f"{pdf_path.stem}_Failure_Report.txt or select a task with --task."
                    ],
                }
            ]
            output_json = cfg.OUTPUT_FOLDER / f"{pdf_path.stem}_results.json"
            output_json.write_text(json.dumps(skipped, indent=2), encoding="utf-8")
            return {
                "document_name": pdf_path.name,
                "failure_report": None,
                "result_file": str(output_json),
                "results": skipped,
            }

        print(f"Reading failure report: {report_path.name}", flush=True)
        classification = classify_task_with_llm(failure_report)
        task = classification["task"]
        print(f"Selected task: {task}", flush=True)
    else:
        task = forced_task
        classification = {
            "task": task,
            "reason": "Task selected through the command line.",
        }
        if report_path is None:
            failure_report = "No failure report supplied; task selected manually."

    reference_context = ""
    if cfg.USE_RETRIEVAL and task in SUPPORTED_TASKS[1:]:
        reference_context = format_reference_context(
            _reference_query(task, failure_report)
        )

    if task == "unsupported":
        results = [unsupported_result(pdf_path, classification["reason"])]
    else:
        doc = fitz.open(pdf_path)
        try:
            if task == "semantic_structure":
                results = [
                    process_semantic_structure_document(
                        doc,
                        pdf_path,
                        failure_report,
                        reference_context,
                    )
                ]
            elif task == "alt_text":
                results = process_alt_text_document(
                    doc,
                    pdf_path,
                    failure_report,
                    reference_context,
                )
            elif task == "table_summary":
                results = process_table_summary_document(
                    doc,
                    pdf_path,
                    failure_report,
                    reference_context,
                )
            else:
                results = [
                    unsupported_result(pdf_path, f"Unknown task: {task}")
                ]
        finally:
            doc.close()

    output_json = cfg.OUTPUT_FOLDER / f"{pdf_path.stem}_results.json"
    output_json.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved: {output_json}", flush=True)

    return {
        "document_name": pdf_path.name,
        "failure_report": str(report_path) if report_path else None,
        "result_file": str(output_json),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze PDFs locally and generate JSON suggestions for headings, "
            "alternative text, or table descriptions."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=cfg.INPUT_FOLDER,
        help="Directory containing PDFs and optional matching failure reports.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=cfg.OUTPUT_FOLDER,
        help="Directory for JSON results and temporary rendered images.",
    )
    parser.add_argument(
        "--task",
        choices=SUPPORTED_TASKS,
        default="auto",
        help="Select a task directly or classify it from each failure report.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Process at most this many pages per PDF.",
    )
    parser.add_argument(
        "--rebuild-vector-store",
        action="store_true",
        help="Regenerate the local CSV embeddings before processing.",
    )
    parser.add_argument(
        "--skip-retrieval",
        action="store_true",
        help="Run without embedding or retrieving local reference context.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg.configure_runtime(
        input_folder=args.input,
        output_folder=args.output,
        max_pages=args.max_pages,
        rebuild_vector_store=args.rebuild_vector_store,
        use_retrieval=not args.skip_retrieval,
    )

    if cfg.USE_RETRIEVAL:
        ensure_vector_store()

    pdf_files = sorted(cfg.INPUT_FOLDER.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {cfg.INPUT_FOLDER}", flush=True)
        return 0

    print(f"PDF files found: {len(pdf_files)}", flush=True)
    all_results = []

    for pdf_path in pdf_files:
        try:
            all_results.append(process_one_pdf(pdf_path, args.task))
        except Exception as exc:
            print(f"ERROR processing {pdf_path.name}: {exc}", flush=True)
            all_results.append(
                {
                    "document_name": pdf_path.name,
                    "task": "error",
                    "remediations": [],
                    "warnings": [str(exc)],
                }
            )

    cfg.COMBINED_OUTPUT_JSON.write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Done. Combined results: {cfg.COMBINED_OUTPUT_JSON}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
