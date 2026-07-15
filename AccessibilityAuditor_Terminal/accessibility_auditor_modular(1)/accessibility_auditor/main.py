import json

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


def process_one_pdf(pdf_path):
    failure_report_path = get_failure_report_path(pdf_path)

    print("=" * 80, flush=True)
    print(f"Processing PDF: {pdf_path.name}", flush=True)

    if failure_report_path is None:
        print(f"Skipping {pdf_path.name}: no matching failure report found.", flush=True)

        skipped_result = [
            {
                "document_name": pdf_path.name,
                "task": "skipped",
                "remediations": [],
                "warnings": [
                    f"No matching failure report found for {pdf_path.name}."
                ]
            }
        ]

        output_json = cfg.OUTPUT_FOLDER / f"{pdf_path.stem}_results.json"

        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(skipped_result, f, indent=2, ensure_ascii=False)

        return {
            "document_name": pdf_path.name,
            "failure_report": None,
            "result_file": str(output_json),
            "results": skipped_result
        }

    print(f"Reading failure report: {failure_report_path.name}", flush=True)
    failure_report = failure_report_path.read_text(encoding="utf-8", errors="replace")

    print("Classifying failure report...", flush=True)
    classification = classify_task_with_llm(failure_report)

    task = classification["task"]

    if "confidence" in classification:
        print("Classification confidence:", classification["confidence"], flush=True)

    if "evidence" in classification:
        print("Classification evidence:", classification["evidence"], flush=True)

    if task == "unsupported":
        results = [
            unsupported_result(
                pdf_path=pdf_path,
                failure_report=failure_report,
                classification_reason=classification["reason"]
            )
        ]

    else:
        print("Opening PDF...", flush=True)
        doc = fitz.open(pdf_path)

        try:
            if task == "semantic_structure":
                results = [
                    process_semantic_structure_document(
                        doc=doc,
                        pdf_path=pdf_path,
                        failure_report=failure_report
                    )
                ]

            elif task == "alt_text":
                results = process_alt_text_document(
                    doc=doc,
                    pdf_path=pdf_path,
                    failure_report=failure_report
                )

            elif task == "table_summary":
                results = process_table_summary_document(
                    doc=doc,
                    pdf_path=pdf_path,
                    failure_report=failure_report
                )

            else:
                results = [
                    unsupported_result(
                        pdf_path=pdf_path,
                        failure_report=failure_report,
                        classification_reason=f"Unknown task: {task}"
                    )
                ]

        finally:
            doc.close()

    output_json = cfg.OUTPUT_FOLDER / f"{pdf_path.stem}_results.json"

    print(f"Saving results for {pdf_path.name}...", flush=True)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Saved: {output_json}", flush=True)

    return {
        "document_name": pdf_path.name,
        "failure_report": str(failure_report_path),
        "result_file": str(output_json),
        "results": results
    }


def main():
    pdf_files = sorted(cfg.INPUT_FOLDER.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in {cfg.INPUT_FOLDER}", flush=True)
        return

    print(f"PDF files found: {len(pdf_files)}", flush=True)

    all_results = []

    for pdf_path in pdf_files:
        try:
            result = process_one_pdf(pdf_path)
            all_results.append(result)

        except Exception as ex:
            print(f"ERROR processing {pdf_path.name}: {ex}", flush=True)

            all_results.append({
                "document_name": pdf_path.name,
                "task": "error",
                "remediations": [],
                "warnings": [
                    str(ex)
                ]
            })

    print("Saving combined results...", flush=True)

    with open(cfg.COMBINED_OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"Done. Combined results saved to {cfg.COMBINED_OUTPUT_JSON}", flush=True)


if __name__ == "__main__":
    main()
