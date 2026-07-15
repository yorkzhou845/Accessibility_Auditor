import argparse
import json
import re
import time
from functools import lru_cache
from pathlib import Path

import fitz  # PyMuPDF

from config import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL
from ollama_client import chat_json
from vector_store import retrieve_guidance


# ============================================================
# CONFIG
# ============================================================

MODEL = OLLAMA_CHAT_MODEL


INPUT_FOLDER = None

OUTPUT_FOLDER = None
RENDERED_FOLDER = None
CROPPED_FOLDER = None
COMBINED_OUTPUT_JSON = None


def configure_output_paths(output_folder):
    global OUTPUT_FOLDER
    global RENDERED_FOLDER
    global CROPPED_FOLDER
    global COMBINED_OUTPUT_JSON

    OUTPUT_FOLDER = Path(output_folder)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    RENDERED_FOLDER = OUTPUT_FOLDER / "rendered_pages"
    RENDERED_FOLDER.mkdir(parents=True, exist_ok=True)

    CROPPED_FOLDER = OUTPUT_FOLDER / "cropped_images"
    CROPPED_FOLDER.mkdir(parents=True, exist_ok=True)

    COMBINED_OUTPUT_JSON = OUTPUT_FOLDER / "all_results.json"

# These are updated each time a PDF is processed.
PDF_PATH = None
FAILURE_REPORT_PATH = None
TASK_OVERRIDE = None

RENDER_SCALE = 1.0

# Use 1 while testing. Change to None for the whole PDF.
MAX_PAGES = None

# For alt_text only. Use 2 while testing. Change to None for all images per page.
MAX_IMAGES_PER_PAGE = None

# Maximum characters of the failure report included in each prompt.
# The failure report is typically short, but cap it to avoid surprises.
FAILURE_REPORT_CHAR_LIMIT = 1200

# Alt-text: one cropped image + a short prompt → small context is fine.
ALT_TEXT_NUM_CTX     = 4096
ALT_TEXT_NUM_PREDICT = 250

# Table: Markdown output can be verbose; give a generous output budget.
TABLE_NUM_CTX        = 4096
TABLE_NUM_PREDICT    = 600


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYS_PROMPT = """
You are a PDF accessibility remediation assistant.

You only support these two tasks:
1. Automated alt-text generation.
2. Table summarization.

Do not produce heading, bookmark, outline, reading-order, or PDF restructuring instructions.

Do not repair unsupported PDF internals such as fonts, CIDSet streams, ToUnicode maps, metadata, signatures, xref tables, annotations, form fields, optional-content groups, heading hierarchy, bookmarks, outlines, or document reading order.

Return only valid JSON.
"""


# ============================================================
# HELPERS
# ============================================================

def estimate_tokens(text):
    """Rough token count estimate: ~4 characters per token.
    Used only for diagnostic printing; not passed to the model."""
    return len(text) // 4


# ============================================================
# OLLAMA
# ============================================================

def ask_ollama(prompt, image_path=None, num_ctx=4096, num_predict=500):
    print(f"Using local Ollama endpoint: {OLLAMA_BASE_URL}", flush=True)
    print(f"Using model: {MODEL}", flush=True)
    print("Calling Ollama...", flush=True)
    start = time.time()

    result = chat_json(
        system_prompt=SYS_PROMPT,
        user_prompt=prompt,
        image_path=image_path,
        num_ctx=num_ctx,
        num_predict=num_predict,
    )

    print("Ollama finished in", round(time.time() - start, 2), "seconds", flush=True)
    return result


@lru_cache(maxsize=16)
def get_retrieved_guidance(task, failure_report):
    query = f"PDF accessibility {task} guidance. {failure_report[:500]}"
    try:
        return retrieve_guidance(query)
    except Exception as ex:
        print(f"Local guidance retrieval was unavailable: {ex}", flush=True)
        return "No retrieved guidance was available. Follow the task rules and require human review."


# ============================================================
# ROUTER
# ============================================================

def classify_task_rules(failure_report):
    text = failure_report.lower()
    text = re.sub(r"\s+", " ", text)

    unsupported_patterns = [
        r"\bheading tags?\b",
        r"\bheading sequence\b",
        r"\bheading hierarchy\b",
        r"\bheader hierarchy\b",
        r"\bheader sequence\b",
        r"\bh[1-6]\b",
        r"\bbookmarks?\b",
        r"\boutlines?\b",
        r"\breading order\b",
        r"\bclause\s+7\.4\.2\b",
        r"\bcidset\b",
        r"\btounicode\b",
        r"\bnotdef\b",
        r"\b\.notdef\b",
        r"\bglyph\b",
        r"\bfont\b",
        r"\bwidths?\b",
        r"\boptional content\b",
        r"\bocg\b",
        r"\bocproperties\b",
        r"\bname key\b",
        r"\bannotation\b",
        r"\bwidget\b",
        r"\bform field\b",
        r"\btab order\b",
        r"\bpage tab\b",
        r"\bmetadata\b",
        r"\bxref\b",
        r"\bsignature\b",
        r"\bcid\b",
    ]


    alt_text_patterns = [
        r"\balternative text\b",
        r"\balt text\b",
        r"\b/alt\b",
        r"\balt entry\b",
        r"\bmissing alt\b",
        r"\bmissing alternative text\b",
        r"\bfigure\b.*\balt\b",
        r"\bimage\b.*\balt\b",
        r"\bfigure\b.*\balternative text\b",
        r"\bimage\b.*\balternative text\b",
        r"\bnon-text content\b",
        r"\bdecorative image\b",
    ]

    table_patterns = [
        r"\btable\b.*\bscope\b",
        r"\bscope attribute\b",
        r"\btable\b.*\bsummary\b",
        r"\bsummary attribute\b",
        r"\btable\b.*\bheader\b",
        r"\btable\b.*\bheaders\b",
        r"\btable\b.*\brow\b",
        r"\btable\b.*\bcolumn\b",
        r"\brow header\b",
        r"\bcolumn header\b",
        r"\btable structure\b",
        r"\bregularity of tables\b",
        r"\btable rows?\b",
        r"\btable columns?\b",
        r"\bclause\s+7\.2\b",
    ]


    if any(re.search(pattern, text) for pattern in alt_text_patterns):
        return {
            "task": "alt_text",
            "reason": "Rule match: missing or inadequate alternative text."
        }

    if any(re.search(pattern, text) for pattern in table_patterns):
        return {
            "task": "table_summary",
            "reason": "Rule match: table structure, headers, scope, row/column relationships, or summary issue."
        }

    if any(re.search(pattern, text) for pattern in unsupported_patterns):
        return {
            "task": "unsupported",
            "reason": "Rule match: unsupported PDF issue such as heading/bookmark/reading-order restructuring, font, CIDSet, ToUnicode, annotation, metadata, form, tab-order, or optional-content problem."
        }

    return {
        "task": "unknown",
        "reason": "No strong rule match."
    }


def build_task_classification_prompt(failure_report):
    return f"""
You are classifying a PDF accessibility failure report.

The remediation system supports ONLY these tasks:

1. alt_text
Use this only for missing, incorrect, or inadequate alternative text for images, figures, non-text content, or decorative images.

2. table_summary
Use this only for table structure, table headers, row headers, column headers, scope attributes, summary attributes, or row/column regularity.

Everything else must be unsupported.

Unsupported examples:
- heading hierarchy, heading sequence, H1/H2/H3/H4/H5/H6 issues
- document outlines or bookmarks
- paragraph/span restructuring
- reading-order fixes
- top-level Document/Span cleanup
- font problems
- CIDSet
- ToUnicode
- glyph widths
- .notdef glyphs
- metadata
- signatures
- xref
- annotations
- widgets
- form fields
- page tab order
- optional content
- OCG
- low-level PDF object issues

Failure report:
{failure_report[:2000]}

Return only valid JSON:

{{
  "task": "alt_text | table_summary | unsupported",
  "confidence": 0.0,
  "reason": "brief explanation",
  "evidence": ["short phrase from the report"]
}}
"""

def classify_task_with_ai(failure_report):
    prompt = build_task_classification_prompt(failure_report)

    ai = ask_ollama(
        prompt,
        num_ctx=4096,
        num_predict=300
    )

    if ai.get("_parse_error"):
        return {
            "task": "unsupported",
            "confidence": 0.0,
            "reason": "AI classifier did not return valid JSON.",
            "evidence": []
        }

    return ai


def validate_ai_classification(ai_result):
    allowed_tasks = {
        "alt_text",
        "table_summary",
        "unsupported"
    }

    task = str(ai_result.get("task", "")).strip().lower()
    confidence = ai_result.get("confidence", 0.0)

    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    if task not in allowed_tasks:
        return {
            "task": "unsupported",
            "reason": "AI returned an invalid task label.",
            "confidence": confidence
        }

    if confidence < 0.75:
        return {
            "task": "unsupported",
            "reason": f"AI confidence was too low ({confidence}). Defaulted to unsupported.",
            "confidence": confidence
        }

    return {
        "task": task,
        "reason": ai_result.get("reason", "AI classified the failure report."),
        "confidence": confidence,
        "evidence": ai_result.get("evidence", [])
    }


def classify_task_with_llm(failure_report):
    """
    Hybrid classifier:
    1. Use rules first.
    2. If rules are uncertain, ask Ollama.
    3. Validate Ollama output.
    4. Default to unsupported if uncertain.
    """

    rule_result = classify_task_rules(failure_report)

    if rule_result["task"] != "unknown":
        return rule_result

    ai_result = classify_task_with_ai(failure_report)

    return validate_ai_classification(ai_result)

# ============================================================
# PDF HELPERS
# ============================================================

def normalize_task_override(task):
    if task is None:
        return None

    normalized = str(task).strip().lower()

    if normalized in {"table", "table_summary", "table-summary"}:
        return "table_summary"

    if normalized in {"image", "image_captioning", "image-captioning", "alt", "alt_text", "alt-text"}:
        return "alt_text"

    if normalized == "":
        return None

    raise ValueError("Task must be either table_summary or alt_text.")


def get_page_count(doc):
    if MAX_PAGES is None:
        return len(doc)

    return min(len(doc), MAX_PAGES)


def bbox_to_pixels(bbox):
    x0, y0, x1, y1 = bbox

    return {
        "x": round(x0 * RENDER_SCALE),
        "y": round(y0 * RENDER_SCALE),
        "width": round((x1 - x0) * RENDER_SCALE),
        "height": round((y1 - y0) * RENDER_SCALE)
    }


def clean_text(text):
    return " ".join(text.split())


def render_page(page, page_number):
    pix = page.get_pixmap(
        matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE),
        alpha=False
    )

    image_path = RENDERED_FOLDER / f"{PDF_PATH.stem}_page_{page_number}.png"
    pix.save(image_path)

    return image_path, pix.width, pix.height


def is_probably_page_number_or_footer(text):
    lower = text.lower().strip()

    if re.fullmatch(r"page\s+\d+\s*(of|/|\|)\s*\d+", lower):
        return True

    if re.fullmatch(r"\d+\s*(/|\|)\s*\d+", lower):
        return True

    if re.fullmatch(r"-?\s*\d+\s*-?", lower):
        return True

    return False


def get_image_entries(page):
    entries = []
    entry_num = 1

    for image_info in page.get_images(full=True):
        xref = image_info[0]
        rects = page.get_image_rects(xref)

        for rect in rects:
            entries.append({
                "id": f"entry_{entry_num:03d}",
                "type": "image",
                "xref": xref,
                "coordinates": bbox_to_pixels(rect),
                "pdf_rect": {
                    "x0": rect.x0,
                    "y0": rect.y0,
                    "x1": rect.x1,
                    "y1": rect.y1
                }
            })

            entry_num += 1

    entries.sort(key=lambda e: (
        e["coordinates"]["y"],
        e["coordinates"]["x"],
        e["coordinates"]["width"] * e["coordinates"]["height"]
    ))

    return entries


def crop_image(page, image_entry, page_number):
    rect = fitz.Rect(
        image_entry["pdf_rect"]["x0"],
        image_entry["pdf_rect"]["y0"],
        image_entry["pdf_rect"]["x1"],
        image_entry["pdf_rect"]["y1"]
    )

    pix = page.get_pixmap(
        matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE),
        clip=rect,
        alpha=False
    )

    crop_path = CROPPED_FOLDER / f"{PDF_PATH.stem}_page_{page_number}_{image_entry['id']}.png"
    pix.save(crop_path)

    return crop_path

def get_table_entries(page):
    entries = []
    entry_num = 1

    tables = page.find_tables().tables

    for table in tables:
        entries.append({
            "id": f"entry_{entry_num:03d}",
            "type": "table",
            "value": table.extract(),
            "coordinates": bbox_to_pixels(table.bbox)
        })

        entry_num += 1

    entries.sort(key=lambda e: (
        e["coordinates"]["y"],
        e["coordinates"]["x"],
        e["coordinates"]["width"] * e["coordinates"]["height"]
    ))

    return entries


# ============================================================
# TASK PROMPTS
# ============================================================

def build_alt_text_prompt(document_name, page_number, image_entry, failure_report):
    guidance = get_retrieved_guidance("alt text", failure_report)
    return f"""
Task: Automated Alt-Text Generation

Document:
{document_name}

Page:
{page_number}

Failure Context:
{failure_report[:FAILURE_REPORT_CHAR_LIMIT]}

Retrieved Local Guidance:
{guidance}

Image Entry:
{json.dumps(image_entry, indent=2)}

Generate suggested alt text for this image.

Rules:
- Return only valid JSON.
- Never return null for alt_text, decorative, image_contains_text, or confidence.
- If the image is decorative, return alt_text="" and decorative=true.
- If the image is meaningful, decorative=false and alt_text must be a non-empty string.
- If the image contains readable text, alt_text should contain the visible text.
- Otherwise, describe the meaningful content of the image in under 25 words.
- If uncertain, describe the main visible subject, setting, and action.
- Do not start with "image of" or "picture of" unless necessary.
- Human review is required before injection.

Return only valid JSON:

{{
  "alt_text": "",
  "decorative": false,
  "image_contains_text": false,
  "confidence": 0.0
}}
"""


def is_valid_alt_text_result(ai):
    if not isinstance(ai, dict):
        return False

    if ai.get("_parse_error"):
        return False

    decorative = ai.get("decorative")
    alt_text = str(ai.get("alt_text") or "").strip()

    # Decorative images may correctly have empty alt text.
    if decorative is True:
        return True

    # Meaningful images must have non-empty alt text.
    return bool(alt_text)


def build_alt_text_retry_prompt(original_prompt):
    return original_prompt + """

The previous response was empty, null, or invalid.

Retry with these stricter rules:
- Do not return null values.
- If the image is meaningful, alt_text must be a non-empty string.
- If uncertain, describe the main visible subject, setting, and action.
- Use fewer than 25 words.
- Return only valid JSON.

Return only this JSON shape:

{
  "alt_text": "Brief useful description of the image.",
  "decorative": false,
  "image_contains_text": false,
  "confidence": 0.5
}
"""


def build_table_prompt(document_name, page_number, table_entry, failure_report):
    guidance = get_retrieved_guidance("table summary", failure_report)
    return f"""
Task: Table Summarization

Document:
{document_name}

Page:
{page_number}

Failure Context:
{failure_report[:FAILURE_REPORT_CHAR_LIMIT]}

Retrieved Local Guidance:
{guidance}

Table Entry:
{json.dumps(table_entry, indent=2)}

Convert this table to Markdown and create a one-sentence screen-reader summary.

Rules:
- Preserve the table data as accurately as possible.
- The summary must be one sentence.
- The summary should describe what the table communicates.
- Human review is required before injection.

Return only valid JSON:

{{
  "markdown_table": "",
  "summary": "",
  "summary_attribute": "",
  "confidence": 0.0
}}
"""

def normalize_table_rows(table_value):
    if not isinstance(table_value, list):
        return []

    rows = []
    for row in table_value:
        if not isinstance(row, list):
            continue

        cleaned_row = []
        for cell in row:
            cleaned = clean_text(str(cell or ""))
            cleaned_row.append(cleaned)

        if any(cleaned_row):
            rows.append(cleaned_row)

    if not rows:
        return []

    max_cols = max(len(row) for row in rows)
    normalized = []

    for row in rows:
        padded = row + [""] * (max_cols - len(row))
        normalized.append(padded)

    return normalized


def escape_markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def table_value_to_markdown(table_value):
    rows = normalize_table_rows(table_value)

    if not rows:
        return ""

    column_count = max(len(row) for row in rows)

    if len(rows) == 1:
        header = [f"Column {i + 1}" for i in range(column_count)]
        body_rows = rows
    else:
        header = rows[0]
        body_rows = rows[1:]

    lines = []
    lines.append("| " + " | ".join(escape_markdown_cell(cell) for cell in header) + " |")
    lines.append("| " + " | ".join("---" for _ in range(column_count)) + " |")

    for row in body_rows:
        lines.append("| " + " | ".join(escape_markdown_cell(cell) for cell in row) + " |")

    return "\n".join(lines)


def deterministic_table_summary(table_value):
    rows = normalize_table_rows(table_value)

    if not rows:
        return ""

    row_count = len(rows)
    column_count = max(len(row) for row in rows)
    first_non_empty_cells = []

    for row in rows[:3]:
        for cell in row:
            if cell and cell not in first_non_empty_cells:
                first_non_empty_cells.append(cell)
            if len(first_non_empty_cells) >= 3:
                break
        if len(first_non_empty_cells) >= 3:
            break

    preview = ", ".join(first_non_empty_cells)

    if preview:
        return f"This table contains {row_count} row(s) and {column_count} column(s), beginning with {preview}."

    return f"This table contains {row_count} row(s) and {column_count} column(s)."


def is_valid_table_result(ai):
    if not isinstance(ai, dict):
        return False

    if ai.get("_parse_error"):
        return False

    markdown_table = str(ai.get("markdown_table") or "").strip()
    summary = str(ai.get("summary") or "").strip()
    summary_attribute = str(ai.get("summary_attribute") or "").strip()

    return bool(markdown_table or summary or summary_attribute)


def build_table_retry_prompt(original_prompt):
    return original_prompt + """

The previous response was empty, null, or invalid.

Retry with these stricter rules:
- Do not return null values.
- markdown_table must be a Markdown table string if table data is present.
- summary must be one useful sentence.
- summary_attribute should repeat the summary unless a shorter screen-reader summary is better.
- Return only valid JSON.

Return only this JSON shape:

{
  "markdown_table": "| Header | Header |\n|---|---|\n| Cell | Cell |",
  "summary": "One-sentence summary of the table.",
  "summary_attribute": "One-sentence summary of the table.",
  "confidence": 0.5
}
"""


def table_fallback_result(table_entry):
    table_value = table_entry.get("value")
    markdown_table = table_value_to_markdown(table_value)
    summary = deterministic_table_summary(table_value)

    if not summary and markdown_table:
        summary = "This table contains structured information extracted from the PDF."

    return {
        "markdown_table": markdown_table,
        "summary": summary,
        "summary_attribute": summary,
        "confidence": 0.4
    }


# ============================================================
# SEMANTIC STRUCTURE POST-PROCESSING
# ============================================================


def process_alt_text_document(doc, failure_report):
    results = []
    page_count = get_page_count(doc)

    for page_index in range(page_count):
        page = doc[page_index]
        page_number = page_index + 1

        print(f"Processing page {page_number} for alt text...", flush=True)

        _, width, height = render_page(page, page_number)
        image_entries = get_image_entries(page)

        if MAX_IMAGES_PER_PAGE is not None:
            image_entries = image_entries[:MAX_IMAGES_PER_PAGE]

        page_result = {
            "document_name": PDF_PATH.name,
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
            crop_path = crop_image(page, image_entry, page_number)

            prompt = build_alt_text_prompt(
                PDF_PATH.name,
                page_number,
                image_entry,
                failure_report
            )

            ai = ask_ollama(
                prompt,
                image_path=crop_path,
                num_ctx=ALT_TEXT_NUM_CTX,
                num_predict=ALT_TEXT_NUM_PREDICT
            )

            if not is_valid_alt_text_result(ai):
                print(
                    f"Alt-text result was empty or invalid for page {page_number}, "
                    f"{image_entry['id']}. Retrying once...",
                    flush=True
                )

                retry_prompt = build_alt_text_retry_prompt(prompt)

                ai = ask_ollama(
                    retry_prompt,
                    image_path=crop_path,
                    num_ctx=ALT_TEXT_NUM_CTX,
                    num_predict=ALT_TEXT_NUM_PREDICT
                )

            if not is_valid_alt_text_result(ai):
                page_result["warnings"].append(
                    f"Alt-text generation failed for {image_entry['id']} on page {page_number}. "
                    "The image was detected, but the model returned empty or invalid alt text after retry."
                )

                ai = {
                    "alt_text": "",
                    "decorative": False,
                    "image_contains_text": False,
                    "confidence": 0.0
                }

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


def process_table_summary_document(doc, failure_report):
    results = []
    page_count = get_page_count(doc)

    for page_index in range(page_count):
        page = doc[page_index]
        page_number = page_index + 1

        print(f"Processing page {page_number} for tables...", flush=True)

        _, width, height = render_page(page, page_number)
        table_entries = get_table_entries(page)

        page_result = {
            "document_name": PDF_PATH.name,
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
                PDF_PATH.name,
                page_number,
                table_entry,
                failure_report
            )

            ai = ask_ollama(
                prompt,
                num_ctx=TABLE_NUM_CTX,
                num_predict=TABLE_NUM_PREDICT
            )

            if not is_valid_table_result(ai):
                print(
                    f"Table-summary result was empty or invalid for page {page_number}, "
                    f"{table_entry['id']}. Retrying once...",
                    flush=True
                )

                retry_prompt = build_table_retry_prompt(prompt)

                ai = ask_ollama(
                    retry_prompt,
                    num_ctx=TABLE_NUM_CTX,
                    num_predict=TABLE_NUM_PREDICT
                )

            if not is_valid_table_result(ai):
                page_result["warnings"].append(
                    f"Table-summary generation failed for {table_entry['id']} on page {page_number}. "
                    "Used deterministic fallback from PyMuPDF table extraction."
                )
                ai = table_fallback_result(table_entry)

            page_result["remediations"].append({
                "id": f"remediation_{len(page_result['remediations']) + 1:03d}",
                "target_scope": "element",
                "target_entry_ids": [table_entry["id"]],
                "target_coordinates": table_entry["coordinates"],
                "issue": "Table may need a Markdown representation and screen-reader summary.",
                "recommended_action": "Review the summary before applying it to the PDF structure.",
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


def unsupported_result(failure_report, classification_reason):
    return {
        "document_name": PDF_PATH.name,
        "task": "unsupported",
        "classification_reason": classification_reason,
        "remediations": [],
        "warnings": [
            "No LLM remediation was generated because this failure is outside the two supported project tasks."
        ],
        "failure_report": failure_report
    }

# Batch-file helper
def get_failure_report_path(pdf_path):
    """
    Finds the failure report that matches a PDF.

    Preferred naming:
        Example.pdf
        Example_Failure_Report.txt
    """

    exact_path = pdf_path.with_name(f"{pdf_path.stem}_Failure_Report.txt")

    if exact_path.exists():
        return exact_path

    # Fallback: allow names like Example_Failure_Report(1).txt
    possible_reports = sorted(
        pdf_path.parent.glob(f"{pdf_path.stem}*Failure*Report*.txt")
    )

    if possible_reports:
        return possible_reports[0]

    return None

# ============================================================
# MAIN
# ============================================================

def build_synthetic_failure_context(task):
    if task == "alt_text":
        return (
            "No external failure report was provided. The user selected Image Captioning in the web UI. "
            "Analyze detected PDF images and figures, then generate concise accessibility alt text for meaningful images. "
            "Mark decorative images as decorative when appropriate."
        )

    if task == "table_summary":
        return (
            "No external failure report was provided. The user selected Table Summarization in the web UI. "
            "Analyze detected PDF tables, then generate Markdown representations and concise screen-reader summaries."
        )

    return (
        "No external failure report was provided. The user selected a remediation task in the web UI. "
        "Analyze the PDF directly and generate remediation data for the selected task."
    )


# ============================================================
# MAIN
# ============================================================

def process_one_pdf(pdf_path, failure_report_path=None):
    global PDF_PATH
    global FAILURE_REPORT_PATH

    PDF_PATH = pdf_path
    FAILURE_REPORT_PATH = Path(failure_report_path) if failure_report_path is not None else None

    print("=" * 80, flush=True)
    print(f"Processing PDF: {pdf_path.name}", flush=True)

    if FAILURE_REPORT_PATH is not None and FAILURE_REPORT_PATH.exists():
        print(f"Reading failure report: {FAILURE_REPORT_PATH.name}", flush=True)
        failure_report = FAILURE_REPORT_PATH.read_text(encoding="utf-8", errors="replace")
    elif TASK_OVERRIDE:
        print("No failure report provided. Using selected task from web UI and scanning the PDF directly.", flush=True)
        failure_report = build_synthetic_failure_context(TASK_OVERRIDE)
        FAILURE_REPORT_PATH = None
    else:
        print(f"Skipping {pdf_path.name}: no failure report and no selected task were provided.", flush=True)

        skipped_result = [
            {
                "document_name": pdf_path.name,
                "task": "skipped",
                "remediations": [],
                "warnings": [
                    f"No failure report or selected remediation task was provided for {pdf_path.name}."
                ]
            }
        ]

        output_json = OUTPUT_FOLDER / f"{pdf_path.stem}_results.json"

        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(skipped_result, f, indent=2, ensure_ascii=False)

        return {
            "document_name": pdf_path.name,
            "failure_report": None,
            "result_file": str(output_json),
            "results": skipped_result
        }

    if TASK_OVERRIDE:
        classification = {
            "task": TASK_OVERRIDE,
            "reason": "Task selected by the web UI.",
            "confidence": 1.0,
            "evidence": []
        }
        print(f"Using selected task from web UI: {TASK_OVERRIDE}", flush=True)
    else:
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
                failure_report=failure_report,
                classification_reason=classification["reason"]
            )
        ]

    else:
        print("Opening PDF...", flush=True)
        doc = fitz.open(pdf_path)

        try:
            if task == "alt_text":
                results = process_alt_text_document(
                    doc=doc,
                    failure_report=failure_report
                )

            elif task == "table_summary":
                results = process_table_summary_document(
                    doc=doc,
                    failure_report=failure_report
                )

            else:
                results = [
                    unsupported_result(
                        failure_report=failure_report,
                        classification_reason=f"Unknown task: {task}"
                    )
                ]

        finally:
            doc.close()

    output_json = OUTPUT_FOLDER / f"{pdf_path.stem}_results.json"

    print(f"Saving results for {pdf_path.name}...", flush=True)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Saved: {output_json}", flush=True)

    return {
        "document_name": pdf_path.name,
        "failure_report": str(FAILURE_REPORT_PATH) if FAILURE_REPORT_PATH is not None else None,
        "result_file": str(output_json),
        "results": results
    }



def run_single_job(pdf_path, output_folder, task_override=None, failure_report_path=None):
    global TASK_OVERRIDE

    configure_output_paths(output_folder)
    TASK_OVERRIDE = normalize_task_override(task_override)

    result = process_one_pdf(
        pdf_path=Path(pdf_path),
        failure_report_path=Path(failure_report_path) if failure_report_path else None
    )

    with open(COMBINED_OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Single job complete. Results saved to {COMBINED_OUTPUT_JSON}", flush=True)

    return result


def run_batch_mode(input_folder, output_folder):
    global INPUT_FOLDER

    INPUT_FOLDER = Path(input_folder)
    configure_output_paths(output_folder)

    pdf_files = sorted(INPUT_FOLDER.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in {INPUT_FOLDER}", flush=True)
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

    with open(COMBINED_OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"Done. Combined results saved to {COMBINED_OUTPUT_JSON}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="PDF accessibility remediation engine")

    parser.add_argument("--pdf", help="Path to the input PDF")
    parser.add_argument("--report", help="Optional path to the failure report")
    parser.add_argument("--output", help="Path to the output folder")
    parser.add_argument("--task", choices=["table_summary", "alt_text"], help="Task selected by the web UI")

    parser.add_argument("--input-folder", help="Batch input folder")
    parser.add_argument("--output-folder", help="Batch output folder")

    args = parser.parse_args()

    if args.pdf and args.output:
        run_single_job(
            pdf_path=args.pdf,
            failure_report_path=args.report,
            output_folder=args.output,
            task_override=args.task
        )
        return

    if args.input_folder and args.output_folder:
        run_batch_mode(
            input_folder=args.input_folder,
            output_folder=args.output_folder
        )
        return

    raise ValueError(
        "Provide either --pdf --output for single-job mode, "
        "or --input-folder --output-folder for batch mode."
    )


if __name__ == "__main__":
    main()