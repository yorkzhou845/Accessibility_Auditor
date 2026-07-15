#%%
import json
import time
from pathlib import Path

import fitz  # PyMuPDF
import ollama


# ============================================================
# CONFIG
# ============================================================

MODEL = "gemma3:4b"

PDF_PATH = Path(
    r"C:\Users\yorzhou\TTU_code\Accessibility Auditor\Test_input\CRTravelReportsWithPreAppImport.pdf"
)

FAILURE_REPORT_PATH = Path(
    r"C:\Users\yorzhou\TTU_code\Accessibility Auditor\Test_input\CRTravelReportsWithPreAppImport_Failure_Report.txt"
)

OUTPUT_FOLDER = Path(
    r"C:\Users\yorzhou\TTU_code\Accessibility Auditor\Test_output"
)
OUTPUT_FOLDER.mkdir(exist_ok=True)

RENDERED_FOLDER = OUTPUT_FOLDER / "rendered_pages"
RENDERED_FOLDER.mkdir(exist_ok=True)

CROPPED_FOLDER = OUTPUT_FOLDER / "cropped_images"
CROPPED_FOLDER.mkdir(exist_ok=True)

OUTPUT_JSON = OUTPUT_FOLDER / "results.json"

RENDER_SCALE = 1.0

# Use 1 while testing. Change to None for the whole PDF.
MAX_PAGES = None

# For alt_text only. Use 2 while testing. Change to None for all images per page.
MAX_IMAGES_PER_PAGE = 2

# FIX: Reduced from 40 → 25.
# Each slim candidate is ~60 tokens; 40 candidates was ~2 400 tokens of candidate
# data alone, which already exceeded the old num_ctx=2048 before instructions
# or the failure report were even included.
MAX_HEADING_CANDIDATES = None

# Maximum characters of the failure report included in each prompt.
# The failure report is typically short, but cap it to avoid surprises.
FAILURE_REPORT_CHAR_LIMIT = 1200

# ── Ollama context / output token budgets ────────────────────────────────────
#
# Semantic task token budget rationale:
#   Input:  25 slim candidates × ~60 tok  ≈  1 500 tok
#           failure report excerpt         ≈    300 tok
#           instructions + JSON schema     ≈    250 tok
#           ─────────────────────────────────────────────
#           Total input estimate           ≈  2 050 tok   (well within 8 192)
#
#   Output: 25 remediation entries × ~50 tok each  ≈  1 250 tok
#           JSON wrapper overhead                   ≈     50 tok
#           ─────────────────────────────────────────────
#           Total output estimate          ≈  1 300 tok
#
# The old values (num_ctx=2048, num_predict=150) meant the model received a
# truncated prompt AND was forbidden from writing more than ~3 JSON entries
# before being cut off — causing consistent parse failures.
#
SEMANTIC_NUM_CTX     = 8192   # was 2048
SEMANTIC_NUM_PREDICT = 2000   # was 150

# Alt-text: one cropped image + a short prompt → small context is fine.
ALT_TEXT_NUM_CTX     = 4096
ALT_TEXT_NUM_PREDICT = 250

# Table: Markdown output can be verbose; give a generous output budget.
TABLE_NUM_CTX        = 4096
TABLE_NUM_PREDICT    = 600    # was 400


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYS_PROMPT = """
You are a PDF accessibility remediation assistant.

You only support these three tasks:
1. Automated alt-text generation.
2. Semantic structure mapping.
3. Table summarization.

Do not repair PDF internals such as fonts, CIDSet streams, metadata, signatures, xref tables, or low-level PDF object issues.

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
    user_message = {
        "role": "user",
        "content": prompt
    }

    if image_path is not None:
        user_message["images"] = [str(image_path)]

    print("Calling Ollama...", flush=True)
    start = time.time()

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": SYS_PROMPT
            },
            user_message
        ],
        format="json",
        options={
            "temperature": 0,
            "num_ctx": num_ctx,
            "num_predict": num_predict
        }
    )

    print("Ollama finished in", round(time.time() - start, 2), "seconds", flush=True)

    content = response["message"]["content"].strip()

    print("Raw Ollama output:")
    print(content)

    # Remove markdown code fences if the model adds them.
    if content.startswith("```json"):
        content = content.replace("```json", "").replace("```", "").strip()
    elif content.startswith("```"):
        content = content.replace("```", "").strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print("Ollama did not return valid JSON. Using fallback object.", flush=True)

        return {
            "_parse_error": True,
            "raw_output": content,
            "warnings": [
                "Ollama did not return valid JSON."
            ]
        }


# ============================================================
# ROUTER
# ============================================================

def classify_task_with_llm(failure_report):
    text = failure_report.lower()

    if "heading" in text or "h1" in text or "heading tags" in text:
        return {
            "task": "semantic_structure",
            "reason": "The failure report concerns heading tags and heading sequence."
        }

    if "alt" in text or "alternative text" in text or "figure" in text or "image" in text:
        return {
            "task": "alt_text",
            "reason": "The failure report concerns image or non-text alternative text."
        }

    if "table" in text or "summary" in text or "scope attribute" in text:
        return {
            "task": "table_summary",
            "reason": "The failure report concerns table structure or table summary."
        }

    return {
        "task": "unsupported",
        "reason": "The failure report does not match the three supported tasks."
    }


# ============================================================
# PDF HELPERS
# ============================================================

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


def get_text_line_entries(page, page_number):
    entries = []
    text_dict = page.get_text("dict")
    entry_num = 1

    for block in text_dict["blocks"]:
        if block["type"] != 0:
            continue

        for line in block["lines"]:
            parts = []
            font_sizes = []

            for span in line["spans"]:
                span_text = span["text"].strip()

                if span_text:
                    parts.append(span_text)
                    font_sizes.append(span.get("size", 0))

            value = clean_text(" ".join(parts))

            if value:
                entries.append({
                    "id": f"p{page_number}_entry_{entry_num:03d}",
                    "page_number": page_number,
                    "type": "text",
                    "value": value,
                    "font_size": max(font_sizes) if font_sizes else 0,
                    "coordinates": bbox_to_pixels(line["bbox"])
                })

                entry_num += 1

    return entries


def get_likely_heading_entries(doc):
    candidates = []
    page_count = get_page_count(doc)

    for page_index in range(page_count):
        page = doc[page_index]
        page_number = page_index + 1

        print(f"Extracting heading candidates from page {page_number}...", flush=True)

        entries = get_text_line_entries(page, page_number)

        for entry in entries:
            text = entry["value"].strip()
            lower = text.lower()
            SENTENCE_STARTERS = (
                "this ", "to ", "if ", "after ", "for ", "the ", "a ",
                "any ", "note:", "select ", "click ", "when ", "before ",
                "once ", "in ", "by ", "as "
            )
            if lower.startswith(SENTENCE_STARTERS):
                continue
            # Skip empty/short junk
            if not text or len(text) < 3:
                continue

            # Skip repeated header/footer text
            if "ttuhsc finance systems management" in lower:
                continue

            if "page " in lower and "|" in lower:
                continue

            # Skip bullets/lists. These should be <li>, not headings.
            if text.startswith("•") or text.startswith("-"):
                continue

            # Skip normal sentence-like body text.
            if text.endswith("."):
                continue

            # Skip long paragraph-like lines.
            if len(text) > 120:
                continue

            is_heading = False

            # Strong heading signals in this document
            if "travel expense report" in lower:
                is_heading = True

            if "document index" in lower:
                is_heading = True

            if "(click link to return to index)" in lower:
                is_heading = True

            # Common section titles from this document
            known_section_terms = [
                "confirm traveler dashboard",
                "create new expense report",
                "verify report type",
                "import pre-approval",
                "verify and save basic trip information",
                "add advance transactions",
                "add bta transactions",
                "edit or create travel expense line items",
                "meals, lodging, and mileage",
                "meals-itemized",
                "lodging",
                "mileage/google maps",
                "report submission",
                "submitted report routing",
                "submitted report options",
                "contacts"
            ]

            if any(term in lower for term in known_section_terms):
                is_heading = True

            if is_heading:
                candidates.append(entry)

    if MAX_HEADING_CANDIDATES is not None:
        return candidates[:MAX_HEADING_CANDIDATES]

    return candidates


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

    crop_path = CROPPED_FOLDER / f"page_{page_number}_{image_entry['id']}.png"
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

    return entries


# ============================================================
# TASK PROMPTS
# ============================================================

def build_document_semantic_prompt(document_name, heading_candidates, failure_report):
    # FIX: Strip coordinates from the candidate objects sent to the model.
    # The model only needs id, page_number, value, and font_size to decide
    # h1/h2/h3. Coordinates are needed downstream (for IronPDF injection) but
    # are irrelevant to the tagging decision and roughly double the token cost
    # of the candidate list.
    slim_candidates = [
        {
            "id": c["id"],
            "page_number": c["page_number"],
            "value": c["value"],
            "font_size": round(c["font_size"], 1)
        }
        for c in heading_candidates
    ]

    return f"""
Task: Semantic Structure Mapping

Document:
{document_name}

Failure Report:
{failure_report[:FAILURE_REPORT_CHAR_LIMIT]}

Likely Heading Candidates From the PDF:
{json.dumps(slim_candidates, indent=2)}

The failure report says the document has an invalid heading-tag sequence.

Your job:
Create a document-level heading remediation script.

Rules:
- Use only the provided heading candidates.
- Preserve exact wording.
- Assign h1, h2, or h3.
- H1 must be the first heading.
- Do not skip heading levels.
- Repeated heading levels are allowed.
- Ignore normal paragraph text and button labels.
- Include page_number, source_entry_id, tag, and text for every entry.
- Human review is required before IronPDF applies these tags.

Return only valid JSON:

{{
  "remediation_script": [
    {{
      "page_number": 1,
      "source_entry_id": "p1_entry_001",
      "tag": "h1",
      "text": ""
    }}
  ],
  "confidence": 0.0
}}
"""


def build_alt_text_prompt(document_name, page_number, image_entry, failure_report):
    return f"""
Task: Automated Alt-Text Generation

Document:
{document_name}

Page:
{page_number}

Failure Report:
{failure_report[:FAILURE_REPORT_CHAR_LIMIT]}

Image Entry:
{json.dumps(image_entry, indent=2)}

Generate suggested alt text for this image.

Rules:
- If the image is decorative, return empty alt_text and decorative=true.
- If the image contains readable text, alt_text should contain the visible text.
- Otherwise, describe the meaningful content of the image in under 25 words.
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


def build_table_prompt(document_name, page_number, table_entry, failure_report):
    return f"""
Task: Table Summarization

Document:
{document_name}

Page:
{page_number}

Failure Report:
{failure_report[:FAILURE_REPORT_CHAR_LIMIT]}

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


# ============================================================
# TASK PROCESSORS
# ============================================================

def process_semantic_structure_document(doc, failure_report):
    print("Building document-level heading candidate list...", flush=True)

    heading_candidates = get_likely_heading_entries(doc)

    print(f"Heading candidates found: {len(heading_candidates)}", flush=True)

    prompt = build_document_semantic_prompt(
        document_name=PDF_PATH.name,
        heading_candidates=heading_candidates,
        failure_report=failure_report
    )

    # Diagnostic: print estimated token usage so overload issues are visible.
    est_input_tokens = estimate_tokens(prompt)
    print(
        f"Estimated prompt tokens: ~{est_input_tokens} "
        f"(num_ctx={SEMANTIC_NUM_CTX}, num_predict={SEMANTIC_NUM_PREDICT})",
        flush=True
    )
    if est_input_tokens > SEMANTIC_NUM_CTX * 0.80:
        print(
            "WARNING: Prompt may be approaching the context limit. "
            "Consider reducing MAX_HEADING_CANDIDATES further.",
            flush=True
        )

    # FIX: num_ctx 2048→8192, num_predict 150→2000.
    # The old values truncated the input and prevented the model from writing
    # more than ~3 JSON entries, causing consistent parse failures.
    ai = ask_ollama(
        prompt,
        num_ctx=SEMANTIC_NUM_CTX,
        num_predict=SEMANTIC_NUM_PREDICT
    )

    warnings = []

    # If Ollama fails to return valid JSON, use the rule-based fallback.
    if ai.get("_parse_error") or "remediation_script" not in ai:
        fallback_script = []

        for entry in heading_candidates:
            text = entry["value"].strip()
            lower = text.lower()

            # Remove repeated link helper text from the visible heading label.
            clean_heading_text = text.replace("(click link to return to index)", "").strip()

            if "travel expense report – after trip" in lower:
                tag = "h1"

            elif "document index" in lower:
                tag = "h2"

            elif "meals-itemized" in lower:
                tag = "h3"

            elif lower == "lodging":
                tag = "h3"

            elif "mileage/google maps" in lower:
                tag = "h3"

            elif "submitted report routing" in lower:
                tag = "h3"

            elif "submitted report options" in lower:
                tag = "h3"

            else:
                tag = "h2"

            fallback_script.append({
                "page_number": entry["page_number"],
                "source_entry_id": entry["id"],
                "tag": tag,
                "text": clean_heading_text,
                "coordinates": entry["coordinates"]
            })

        ai = {
            "remediation_script": fallback_script,
            "confidence": 0.5
        }

        warnings.append(
            "Used fallback heading assignment because Ollama did not return valid JSON."
        )

    else:
        # Ollama succeeded: re-attach coordinates from the original candidates
        # (they were stripped from the prompt to save tokens but are needed for
        # IronPDF injection). Match on source_entry_id.
        coord_lookup = {c["id"]: c["coordinates"] for c in heading_candidates}

        for item in ai["remediation_script"]:
            entry_id = item.get("source_entry_id")
            item["coordinates"] = coord_lookup.get(entry_id)

    return {
        "document_name": PDF_PATH.name,
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


def unsupported_result(failure_report, classification_reason):
    return {
        "document_name": PDF_PATH.name,
        "task": "unsupported",
        "classification_reason": classification_reason,
        "remediations": [],
        "warnings": [
            "No LLM remediation was generated because this failure is outside the three supported project tasks."
        ],
        "failure_report": failure_report
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("Reading failure report...", flush=True)
    failure_report = FAILURE_REPORT_PATH.read_text(encoding="utf-8")

    print("Classifying failure report...", flush=True)
    classification = classify_task_with_llm(failure_report)

    task = classification["task"]

    print("Detected task:", task, flush=True)
    print("Reason:", classification["reason"], flush=True)

    if task == "unsupported":
        results = [
            unsupported_result(
                failure_report=failure_report,
                classification_reason=classification["reason"]
            )
        ]

    else:
        print("Opening PDF...", flush=True)
        doc = fitz.open(PDF_PATH)

        if task == "semantic_structure":
            results = [
                process_semantic_structure_document(
                    doc=doc,
                    failure_report=failure_report
                )
            ]

        elif task == "alt_text":
            results = process_alt_text_document(
                doc=doc,
                failure_report=failure_report
            )

        elif task == "table_summary":
            results = process_table_summary_document(
                doc=doc,
                failure_report=failure_report
            )

        doc.close()

    print("Saving results...", flush=True)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Done. Results saved to {OUTPUT_JSON}", flush=True)


if __name__ == "__main__":
    main()

#%%