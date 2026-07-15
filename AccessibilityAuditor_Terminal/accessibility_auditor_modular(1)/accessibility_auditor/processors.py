from . import config as cfg
from .heading_detection import get_likely_heading_entries
from .ollama_client import ask_ollama
from .pdf_utils import (
    crop_image,
    get_image_entries,
    get_page_count,
    get_table_entries,
    render_page,
)
from .postprocess import make_fallback_remediation_script, validate_llm_remediation_script
from .prompts import build_alt_text_prompt, build_document_semantic_prompt, build_table_prompt
from .utils import estimate_tokens


def process_semantic_structure_document(doc, pdf_path, failure_report):
    print("Building document-level heading candidate list...", flush=True)

    heading_candidates = get_likely_heading_entries(doc)

    print(f"Heading candidates found: {len(heading_candidates)}", flush=True)

    warnings = []

    if not cfg.USE_LLM_FOR_SEMANTIC:
        script = make_fallback_remediation_script(heading_candidates)
        ai = {
            "remediation_script": script,
            "confidence": 0.65
        }
        warnings.append(
            "Used deterministic generic heading detection. LLM semantic refinement is disabled."
        )

    else:
        prompt = build_document_semantic_prompt(
            document_name=pdf_path.name,
            heading_candidates=heading_candidates,
            failure_report=failure_report
        )

        est_input_tokens = estimate_tokens(prompt)
        print(
            f"Estimated prompt tokens: ~{est_input_tokens} "
            f"(num_ctx={cfg.SEMANTIC_NUM_CTX}, num_predict={cfg.SEMANTIC_NUM_PREDICT})",
            flush=True
        )
        if est_input_tokens > cfg.SEMANTIC_NUM_CTX * 0.80:
            print(
                "WARNING: Prompt may be approaching the context limit. "
                "Consider reducing MAX_HEADING_CANDIDATES further.",
                flush=True
            )

        ai = ask_ollama(
            prompt,
            num_ctx=cfg.SEMANTIC_NUM_CTX,
            num_predict=cfg.SEMANTIC_NUM_PREDICT
        )

        if ai.get("_parse_error") or "remediation_script" not in ai:
            script = make_fallback_remediation_script(heading_candidates)
            ai = {
                "remediation_script": script,
                "confidence": 0.55
            }
            warnings.append(
                "Used generic layout/style fallback because Ollama did not return valid JSON."
            )

        else:
            script = validate_llm_remediation_script(ai, heading_candidates)

            if not script and heading_candidates:
                script = make_fallback_remediation_script(heading_candidates)
                warnings.append(
                    "Ollama returned JSON, but no valid heading entries matched the candidates. Used generic fallback."
                )

            ai["remediation_script"] = script

    return {
        "document_name": pdf_path.name,
        "page_number": None,
        "document_width": None,
        "document_height": None,
        "task": "semantic_structure",
        "remediations": [
            {
                "id": "remediation_001",
                "target_scope": "document",
                "target_entry_ids": [
                    item.get("source_entry_id")
                    for item in ai["remediation_script"]
                    if item.get("source_entry_id")
                ],
                "target_coordinates": None,
                "issue": "Document may need corrected heading hierarchy.",
                "recommended_action": "Review the document-level heading remediation script and apply tags with IronPDF.",
                "proposed_change": {
                    "action_type": "apply_semantic_structure",
                    "remediation_script": ai["remediation_script"]
                },
                "human_review_required": True,
                "confidence": ai.get("confidence", 0.0)
            }
        ],
        "warnings": warnings
    }


def process_alt_text_document(doc, pdf_path, failure_report):
    results = []
    page_count = get_page_count(doc)

    for page_index in range(page_count):
        page = doc[page_index]
        page_number = page_index + 1

        print(f"Processing page {page_number} for alt text...", flush=True)

        _, width, height = render_page(page, page_number, pdf_path)
        image_entries = get_image_entries(page)

        if cfg.MAX_IMAGES_PER_PAGE is not None:
            image_entries = image_entries[:cfg.MAX_IMAGES_PER_PAGE]

        page_result = {
            "document_name": pdf_path.name,
            "page_number": page_number,
            "document_width": width,
            "document_height": height,
            "task": "alt_text",
            "remediations": [],
            "warnings": []
        }

        if not image_entries:
            page_result["warnings"].append("No images were detected on this page.")
            results.append(page_result)
            continue

        for image_entry in image_entries:
            crop_path = crop_image(page, image_entry, page_number, pdf_path)

            prompt = build_alt_text_prompt(
                pdf_path.name,
                page_number,
                image_entry,
                failure_report
            )

            ai = ask_ollama(
                prompt,
                image_path=crop_path,
                num_ctx=cfg.ALT_TEXT_NUM_CTX,
                num_predict=cfg.ALT_TEXT_NUM_PREDICT
            )

            page_result["remediations"].append({
                "id": f"remediation_{len(page_result['remediations']) + 1:03d}",
                "target_scope": "element",
                "target_entry_ids": [image_entry["id"]],
                "target_coordinates": image_entry["coordinates"],
                "issue": "Image may need missing or improved alternative text.",
                "recommended_action": "Review and approve the suggested alt text before injection.",
                "proposed_change": {
                    "action_type": "add_or_update_alt_text",
                    "alt_text": ai.get("alt_text"),
                    "decorative": ai.get("decorative"),
                    "image_contains_text": ai.get("image_contains_text")
                },
                "human_review_required": True,
                "confidence": ai.get("confidence")
            })

        results.append(page_result)

    return results


def process_table_summary_document(doc, pdf_path, failure_report):
    results = []
    page_count = get_page_count(doc)

    for page_index in range(page_count):
        page = doc[page_index]
        page_number = page_index + 1

        print(f"Processing page {page_number} for tables...", flush=True)

        _, width, height = render_page(page, page_number, pdf_path)
        table_entries = get_table_entries(page)

        page_result = {
            "document_name": pdf_path.name,
            "page_number": page_number,
            "document_width": width,
            "document_height": height,
            "task": "table_summary",
            "remediations": [],
            "warnings": []
        }

        if not table_entries:
            page_result["warnings"].append("No tables were detected on this page.")
            results.append(page_result)
            continue

        for table_entry in table_entries:
            prompt = build_table_prompt(
                pdf_path.name,
                page_number,
                table_entry,
                failure_report
            )

            ai = ask_ollama(
                prompt,
                num_ctx=cfg.TABLE_NUM_CTX,
                num_predict=cfg.TABLE_NUM_PREDICT
            )

            page_result["remediations"].append({
                "id": f"remediation_{len(page_result['remediations']) + 1:03d}",
                "target_scope": "element",
                "target_entry_ids": [table_entry["id"]],
                "target_coordinates": table_entry["coordinates"],
                "issue": "Table may need a Markdown representation and screen-reader summary.",
                "recommended_action": "Review and inject the Summary attribute with IronPDF.",
                "proposed_change": {
                    "action_type": "add_table_summary",
                    "markdown_table": ai.get("markdown_table"),
                    "summary": ai.get("summary"),
                    "summary_attribute": ai.get("summary_attribute")
                },
                "human_review_required": True,
                "confidence": ai.get("confidence")
            })

        results.append(page_result)

    return results


def unsupported_result(pdf_path, failure_report, classification_reason):
    return {
        "document_name": pdf_path.name,
        "task": "unsupported",
        "classification_reason": classification_reason,
        "remediations": [],
        "warnings": [
            "No LLM remediation was generated because this failure is outside the three supported project tasks."
        ],
        "failure_report": failure_report
    }
