#%%
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # PyMuPDF
import ollama


# ============================================================
# CONFIG
# ============================================================

MODEL = "gemma3:4b"

# For semantic headings, default to deterministic layout rules.
# Local LLMs often truncate long JSON outputs and may over-tag body text.
USE_LLM_FOR_SEMANTIC = False

INPUT_FOLDER = Path(
    r"C:\Users\yorzhou\TTU_code\Accessibility Auditor\Test_input"
)

OUTPUT_FOLDER = Path(
    r"C:\Users\yorzhou\TTU_code\Accessibility Auditor\Test_output"
)
OUTPUT_FOLDER.mkdir(exist_ok=True)

RENDERED_FOLDER = OUTPUT_FOLDER / "rendered_pages"
RENDERED_FOLDER.mkdir(exist_ok=True)

CROPPED_FOLDER = OUTPUT_FOLDER / "cropped_images"
CROPPED_FOLDER.mkdir(exist_ok=True)

COMBINED_OUTPUT_JSON = OUTPUT_FOLDER / "all_results.json"

# These are updated each time a PDF is processed.
PDF_PATH = None
FAILURE_REPORT_PATH = None

RENDER_SCALE = 1.0

# Use 1 while testing. Change to None for the whole PDF.
MAX_PAGES = None

# For alt_text only. Use 2 while testing. Change to None for all images per page.
MAX_IMAGES_PER_PAGE = 2

# FIX: Reduced from 40 → 25.
# Each slim candidate is ~60 tokens; 40 candidates was ~2 400 tokens of candidate
# data alone, which already exceeded the old num_ctx=2048 before instructions
# or the failure report were even included.
MAX_HEADING_CANDIDATES = 80

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

def classify_task_rules(failure_report):
    text = failure_report.lower()
    text = re.sub(r"\s+", " ", text)

    unsupported_patterns = [
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

    semantic_patterns = [
        r"\bheading tags?\b",
        r"\bheading sequence\b",
        r"\bheading hierarchy\b",
        r"\bheader hierarchy\b",
        r"\bheader sequence\b",
        r"\bh[1-6]\b",
        r"\bclause\s+7\.4\.2\b",
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

    if any(re.search(pattern, text) for pattern in semantic_patterns):
        return {
            "task": "semantic_structure",
            "reason": "Rule match: heading hierarchy or H1/H2/H3 issue."
        }

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
            "reason": "Rule match: unsupported low-level PDF issue such as font, CIDSet, ToUnicode, annotation, metadata, form, tab-order, or optional-content problem."
        }

    return {
        "task": "unknown",
        "reason": "No strong rule match."
    }


def build_task_classification_prompt(failure_report):
    return f"""
You are classifying a PDF accessibility failure report.

The remediation system supports ONLY these tasks:

1. semantic_structure
Use this only for heading hierarchy, heading sequence, H1/H2/H3/H4/H5/H6, or document outline problems.

2. alt_text
Use this only for missing, incorrect, or inadequate alternative text for images, figures, non-text content, or decorative images.

3. table_summary
Use this only for table structure, table headers, row headers, column headers, scope attributes, summary attributes, or row/column regularity.

Everything else must be unsupported.

Unsupported examples:
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
  "task": "semantic_structure | alt_text | table_summary | unsupported",
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
        "semantic_structure",
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


def is_bullet_or_list_item(text):
    stripped = text.strip()

    # Keep real numbered headings such as:
    # "1 Introduction", "1. Introduction", "1.2 Scope"
    if is_numbered_heading_pattern(stripped):
        return False

    if stripped.startswith(("•", "-", "–", "—", "*", "◦")):
        return True

    # Lettered list items like "a. Item" or "(b) Item"
    if re.match(r"^\(?[a-zA-Z]\)?[.)]\s+", stripped):
        return True

    # Short numeric list items are usually body/list content.
    # Real numbered headings were already allowed above.
    if re.match(r"^\(?\d{1,3}\)?[.)]\s+", stripped):
        return True

    return False


def is_numbered_heading_pattern(text):
    # Allows headings like "1 Introduction", "1.2 Scope", "2.3.1 Details".
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9]", text.strip()))


def text_word_count(text):
    return len(re.findall(r"[A-Za-z0-9]+", text))


def is_mostly_upper(text):
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False
    return sum(ch.isupper() for ch in letters) / len(letters) >= 0.75


def is_title_like(text):
    words = re.findall(r"[A-Za-z][A-Za-z0-9/&'-]*", text)
    if not words:
        return False

    # A heading often has several important words capitalized, but this is only
    # a weak signal because many procedural documents use sentence case.
    important_words = [w for w in words if len(w) > 2]
    if not important_words:
        return False

    capitalized = sum(w[0].isupper() for w in important_words)
    return capitalized / len(important_words) >= 0.45


def is_short_callout_or_button(text):
    lower = text.lower().strip()
    wc = text_word_count(text)

    if wc > 6:
        return False

    # Generic screenshot/button callout patterns. These are intentionally weak;
    # they only subtract score and do not automatically delete the line.
    starts = (
        "click ", "select ", "enter ", "tap ", "press ", "choose ",
        "search ", "search/", "add ", "input ", "upload "
    )
    return lower.startswith(starts)


def rect_overlap_ratio(bbox, rects):
    line_rect = fitz.Rect(bbox)
    area = line_rect.get_area()

    if area <= 0:
        return 0.0

    best = 0.0

    for rect in rects:
        inter = line_rect & rect
        if not inter.is_empty:
            best = max(best, inter.get_area() / area)

    return best


def get_page_image_rects(page):
    rects = []

    for image_info in page.get_images(full=True):
        xref = image_info[0]
        for rect in page.get_image_rects(xref):
            if rect.get_area() > 0:
                rects.append(rect)

    return rects


def get_text_line_entries(page, page_number):
    entries = []
    text_dict = page.get_text("dict")
    page_rect = page.rect
    image_rects = get_page_image_rects(page)
    entry_num = 1

    for block in text_dict["blocks"]:
        if block["type"] != 0:
            continue

        for line in block["lines"]:
            parts = []
            font_sizes = []
            font_names = []
            font_flags = []
            colors = []

            for span in line["spans"]:
                span_text = span["text"].strip()

                if span_text:
                    parts.append(span_text)
                    font_sizes.append(span.get("size", 0))
                    font_names.append(span.get("font", ""))
                    font_flags.append(span.get("flags", 0))
                    colors.append(span.get("color"))

            value = clean_text(" ".join(parts))

            if value:
                font_size = max(font_sizes) if font_sizes else 0
                font_name_text = " ".join(font_names).lower()
                color_counts = Counter(colors)
                dominant_color = color_counts.most_common(1)[0][0] if color_counts else None

                # PyMuPDF flags are not always reliable across PDFs, so use
                # both flags and font-name text.
                is_bold = (
                    any((flag & 16) for flag in font_flags)
                    or "bold" in font_name_text
                    or "black" in font_name_text
                    or "semibold" in font_name_text
                )
                is_italic = any((flag & 2) for flag in font_flags) or "italic" in font_name_text

                entries.append({
                    "id": f"p{page_number}_entry_{entry_num:03d}",
                    "page_number": page_number,
                    "type": "text",
                    "value": value,
                    "font_size": font_size,
                    "font_names": sorted(set(font_names)),
                    "is_bold": is_bold,
                    "is_italic": is_italic,
                    "color": dominant_color,
                    "coordinates": bbox_to_pixels(line["bbox"]),
                    "pdf_bbox": tuple(line["bbox"]),
                    "page_width": page_rect.width,
                    "page_height": page_rect.height,
                    "image_overlap_ratio": rect_overlap_ratio(line["bbox"], image_rects)
                })

                entry_num += 1

    return entries


def estimate_body_style(entries):
    # Use character-weighted counts so long paragraphs dominate over short labels.
    size_counts = Counter()
    color_counts = Counter()

    for entry in entries:
        text = entry["value"]
        if len(text) < 20:
            continue
        if is_probably_page_number_or_footer(text):
            continue
        if entry.get("image_overlap_ratio", 0) > 0.35:
            continue

        weight = max(len(text), 1)
        size_counts[round(entry.get("font_size", 0), 1)] += weight
        color_counts[entry.get("color")] += weight

    body_size = size_counts.most_common(1)[0][0] if size_counts else 10.0
    body_color = color_counts.most_common(1)[0][0] if color_counts else None

    return body_size, body_color


def repeated_header_footer_texts(entries, page_count):
    by_text = defaultdict(set)

    for entry in entries:
        text = entry["value"].strip().lower()
        y = entry["coordinates"]["y"]
        page_height = entry.get("page_height") or 792

        # Only treat repeated text near the top or bottom as headers/footers.
        near_edge = y < 90 or y > page_height - 90
        if near_edge and len(text) >= 4:
            by_text[text].add(entry["page_number"])

    threshold = max(2, int(page_count * 0.35))
    return {text for text, pages in by_text.items() if len(pages) >= threshold}


def clean_heading_label(text):
    """Clean PDF extraction artifacts without using document-specific wording."""
    text = clean_text(text)

    # Remove common navigation helper text, including partial fragments caused by
    # PDF line splitting, e.g. "(click link to return to".
    text = re.sub(
        r"\(\s*click\s+link\s+to\s+return(?:\s+to)?(?:\s+index)?\s*\)?$",
        "",
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(
        r"\(\s*click\s+link\s+to\s+return.*$",
        "",
        text,
        flags=re.IGNORECASE
    )

    # Normalize spacing artifacts common in extracted PDFs.
    text = re.sub(r"\s+([:;,.])", r"\1", text)
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"(?<=[A-Za-z])\s*-\s*(?=[A-Za-z])", "-", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_toc_key(text):
    return clean_heading_label(text).lower().strip().rstrip(":").strip()


def is_toc_title(text):
    return normalize_toc_key(text) in {
        "contents", "table of contents", "document index", "index"
    }


def toc_pages(entries):
    pages = defaultdict(list)
    for entry in entries:
        pages[entry["page_number"]].append(entry)

    detected = set()

    for page_number, page_entries in pages.items():
        first_lines = [normalize_toc_key(e["value"]) for e in page_entries[:10]]
        if any(line in {"contents", "table of contents", "document index", "index"} for line in first_lines):
            detected.add(page_number)
            continue

        # A page with many leader-dot/page-number entries is probably a TOC.
        toc_like_count = 0
        for e in page_entries:
            t = clean_heading_label(e["value"])
            if re.search(r"\.{3,}\s*\d+$", t) or re.search(r"\s+\d+$", t):
                toc_like_count += 1
        if toc_like_count >= 5:
            detected.add(page_number)

    return detected


def is_probable_toc_entry(entry, toc_page_numbers):
    if entry["page_number"] not in toc_page_numbers:
        return False

    text = entry["value"].strip()

    if is_toc_title(text):
        return False

    # TOC/index entries are navigation links, not the actual section headings.
    return True


def sentence_like(text):
    """Reject many wrapped paragraph lines without hardcoding this document."""
    text = clean_heading_label(text)
    lower = text.lower().strip()
    wc = text_word_count(text)

    if wc <= 3:
        return False

    sentence_starters = (
        "this ", "these ", "if ", "after ", "for ", "the ", "a ", "an ",
        "any ", "note", "select ", "click ", "when ", "before ", "once ",
        "in ", "by ", "as ", "to ", "from ", "do not ", "please ",
        "ensure ", "repeat ", "provide ", "enter ", "upload "
    )

    if lower.startswith(sentence_starters):
        return True

    if text.endswith(".") and wc > 4:
        return True

    if re.search(r"\.\s+[A-Z]", text):
        return True

    # Body lines often contain verbs/modal verbs; headings usually do not.
    if wc > 7 and re.search(
        r"\b(will|must|should|could|would|can|may|are|is|was|were|be|been|being|has|have|had)\b",
        lower
    ):
        return True

    return False


def union_coordinates(entries):
    x0 = min(e["coordinates"]["x"] for e in entries)
    y0 = min(e["coordinates"]["y"] for e in entries)
    x1 = max(e["coordinates"]["x"] + e["coordinates"]["width"] for e in entries)
    y1 = max(e["coordinates"]["y"] + e["coordinates"]["height"] for e in entries)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def union_pdf_bboxes(entries):
    rect = fitz.Rect(entries[0]["pdf_bbox"])
    for entry in entries[1:]:
        rect |= fitz.Rect(entry["pdf_bbox"])
    return tuple(rect)


def merge_same_line_entries(entries):
    """Merge PDF extraction fragments that visually sit on the same line."""
    pages = defaultdict(list)
    for entry in entries:
        pages[entry["page_number"]].append(entry)

    merged = []

    for page_number, page_entries in pages.items():
        page_entries.sort(key=lambda e: (e["coordinates"]["y"], e["coordinates"]["x"]))
        used = [False] * len(page_entries)

        for i, entry in enumerate(page_entries):
            if used[i]:
                continue

            group = [entry]
            used[i] = True
            base_y = entry["coordinates"]["y"]
            base_h = max(entry["coordinates"].get("height", 0), 1)

            changed = True
            while changed:
                changed = False
                last = max(group, key=lambda g: g["coordinates"]["x"] + g["coordinates"]["width"])
                last_right = last["coordinates"]["x"] + last["coordinates"]["width"]

                for j, other in enumerate(page_entries):
                    if used[j]:
                        continue

                    same_baseline = abs(other["coordinates"]["y"] - base_y) <= max(2, base_h * 0.35)
                    gap = other["coordinates"]["x"] - last_right

                    if same_baseline and -3 <= gap <= 35:
                        group.append(other)
                        used[j] = True
                        changed = True

            group.sort(key=lambda g: g["coordinates"]["x"])

            if len(group) == 1:
                merged.append(entry)
                continue

            combined = dict(group[0])
            combined["value"] = clean_text(" ".join(g["value"] for g in group))
            combined["merged_entry_ids"] = [g["id"] for g in group]
            combined["coordinates"] = union_coordinates(group)
            combined["pdf_bbox"] = union_pdf_bboxes(group)
            combined["font_size"] = max(g.get("font_size", 0) for g in group)
            combined["is_bold"] = any(g.get("is_bold", False) for g in group)
            combined["image_overlap_ratio"] = max(g.get("image_overlap_ratio", 0) for g in group)
            merged.append(combined)

    merged.sort(key=lambda e: (e["page_number"], e["coordinates"]["y"], e["coordinates"]["x"]))
    return merged


def add_spacing_features(entries):
    pages = defaultdict(list)
    for entry in entries:
        pages[entry["page_number"]].append(entry)

    for page_entries in pages.values():
        page_entries.sort(key=lambda e: (e["coordinates"]["y"], e["coordinates"]["x"]))

        for i, entry in enumerate(page_entries):
            if i == 0:
                entry["gap_before"] = 999
            else:
                prev = page_entries[i - 1]
                entry["gap_before"] = entry["coordinates"]["y"] - (
                    prev["coordinates"]["y"] + prev["coordinates"]["height"]
                )

            if i == len(page_entries) - 1:
                entry["gap_after"] = 999
            else:
                nxt = page_entries[i + 1]
                entry["gap_after"] = nxt["coordinates"]["y"] - (
                    entry["coordinates"]["y"] + entry["coordinates"]["height"]
                )

    return entries


def common_body_left_x(entries):
    xs = []
    for entry in entries:
        if len(entry.get("value", "")) < 40:
            continue
        if entry.get("image_overlap_ratio", 0) > 0.15:
            continue
        if is_probably_page_number_or_footer(entry.get("value", "")):
            continue
        xs.append(round(entry["coordinates"]["x"] / 5) * 5)

    if not xs:
        return 72

    return Counter(xs).most_common(1)[0][0]


def heading_candidate_score(entry, body_size, body_color, repeated_texts, toc_page_numbers, body_left_x):
    raw_text = entry["value"].strip()
    text = clean_heading_label(raw_text)
    lower = text.lower()
    wc = text_word_count(text)
    score = 0
    reasons = []

    if not text or len(text) < 3:
        return -99, ["empty_or_too_short"]

    if lower in repeated_texts:
        return -99, ["repeated_header_or_footer"]

    if is_probably_page_number_or_footer(text):
        return -99, ["page_number_or_footer"]

    if is_bullet_or_list_item(text):
        return -99, ["bullet_or_list_item"]

    if is_probable_toc_entry(entry, toc_page_numbers):
        return -99, ["toc_navigation_entry"]

    if entry.get("image_overlap_ratio", 0) > 0.25:
        return -99, ["inside_or_over_image"]

    if len(text) > 130:
        return -99, ["too_long"]

    size_delta = entry.get("font_size", 0) - body_size
    left_aligned = entry["coordinates"]["x"] <= body_left_x + 45
    title_like = is_title_like(text)
    numbered = is_numbered_heading_pattern(text)
    upper = is_mostly_upper(text)
    sent = sentence_like(text)
    colon_heading = (
        text.endswith(":")
        or bool(re.search(r"\b(option|part|section|chapter|appendix)\s+[A-Z0-9]+\s*:", text, re.IGNORECASE))
    )

    # Very weak long lines are usually wrapped paragraph text.
    if wc > 18 and not (entry.get("is_bold") or size_delta >= 1.5 or numbered):
        return -99, ["too_many_words_without_strong_style"]

    if is_toc_title(text):
        score += 6
        reasons.append("toc_title")

    if numbered:
        score += 5
        reasons.append("numbered_heading_pattern")

    if size_delta >= 2.5:
        score += 6
        reasons.append("much_larger_than_body")
    elif size_delta >= 1.0:
        score += 4
        reasons.append("larger_than_body")
    elif size_delta >= 0.5:
        score += 2
        reasons.append("slightly_larger_than_body")

    if entry.get("is_bold"):
        score += 3
        reasons.append("bold")

    if entry.get("color") != body_color:
        score += 2
        reasons.append("different_color")

    if title_like:
        score += 1
        reasons.append("title_like_capitalization")

    if upper:
        score += 2
        reasons.append("mostly_uppercase")

    if left_aligned:
        score += 1
        reasons.append("left_aligned")

    if entry.get("gap_before", 0) >= 8:
        score += 1
        reasons.append("space_before")

    if entry.get("gap_after", 0) >= 6:
        score += 1
        reasons.append("space_after")

    if colon_heading and wc <= 10:
        score += 2
        reasons.append("short_colon_heading")

    if sent:
        score -= 5
        reasons.append("sentence_like")

    if is_short_callout_or_button(text):
        score -= 4
        reasons.append("short_callout_or_button")

    # Require at least one strong, general heading signal. This prevents ordinary
    # paragraph fragments from scoring as headings merely because they are short.
    has_core_heading_signal = (
        is_toc_title(text)
        or numbered
        or size_delta >= 1.0
        or entry.get("is_bold")
        or (entry.get("color") != body_color and left_aligned and (title_like or "click link" in raw_text.lower()))
        or (colon_heading and left_aligned and title_like and entry.get("gap_before", 0) >= 8)
    )

    if not has_core_heading_signal:
        return -99, reasons + ["no_core_heading_signal"]

    return score, reasons


def infer_fallback_tag(entry, first_candidate_id, candidate_style_ranks=None):
    text = clean_heading_label(entry["value"])

    if entry["id"] == first_candidate_id:
        return "h1"

    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+", text)
    if numbered:
        depth = numbered.group(1).count(".") + 1
        if depth <= 1:
            return "h2"
        return "h3"

    # Conservative fallback: after the document H1, use H2. This satisfies the
    # no-skipped-heading-level rule and avoids inventing nested H3 levels from
    # weak layout clues. An optional LLM/human review step can refine nesting.
    return "h2"


def get_likely_heading_entries(doc):
    all_entries = []
    page_count = get_page_count(doc)

    for page_index in range(page_count):
        page = doc[page_index]
        page_number = page_index + 1

        print(f"Extracting text lines from page {page_number}...", flush=True)
        all_entries.extend(get_text_line_entries(page, page_number))

    all_entries = merge_same_line_entries(all_entries)
    all_entries = add_spacing_features(all_entries)

    body_size, body_color = estimate_body_style(all_entries)
    repeated_texts = repeated_header_footer_texts(all_entries, page_count)
    toc_page_numbers = toc_pages(all_entries)
    body_left_x = common_body_left_x(all_entries)

    scored = []

    for entry in all_entries:
        score, reasons = heading_candidate_score(
            entry=entry,
            body_size=body_size,
            body_color=body_color,
            repeated_texts=repeated_texts,
            toc_page_numbers=toc_page_numbers,
            body_left_x=body_left_x
        )

        # Higher threshold after stronger filtering. This keeps the fallback
        # conservative and reduces LLM prompt size.
        if score >= 5:
            candidate = dict(entry)
            candidate["value"] = clean_heading_label(candidate["value"])
            candidate["candidate_score"] = score
            candidate["candidate_reasons"] = reasons
            candidate["body_font_size"] = body_size
            candidate["style_key"] = (
                round(candidate.get("font_size", 0), 1),
                bool(candidate.get("is_bold")),
                candidate.get("color"),
                is_mostly_upper(candidate.get("value", ""))
            )
            scored.append(candidate)

    scored.sort(key=lambda e: (e["page_number"], e["coordinates"]["y"], e["coordinates"]["x"]))

    if scored:
        first_candidate_id = scored[0]["id"]
        for candidate in scored:
            candidate["fallback_tag"] = infer_fallback_tag(candidate, first_candidate_id)

    if MAX_HEADING_CANDIDATES is not None and len(scored) > MAX_HEADING_CANDIDATES:
        scored = sorted(scored, key=lambda e: e["candidate_score"], reverse=True)[:MAX_HEADING_CANDIDATES]
        scored.sort(key=lambda e: (e["page_number"], e["coordinates"]["y"], e["coordinates"]["x"]))

    return scored


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

    return entries


# ============================================================
# TASK PROMPTS
# ============================================================

def build_document_semantic_prompt(document_name, heading_candidates, failure_report):
    # Send compact but useful layout/style features. Do not send coordinates;
    # they are re-attached after the model returns source_entry_id values.
    slim_candidates = [
        {
            "id": c["id"],
            "page_number": c["page_number"],
            "value": c["value"],
            "font_size": round(c.get("font_size", 0), 1),
            "is_bold": c.get("is_bold", False),
            "candidate_score": c.get("candidate_score"),
            "reasons": c.get("candidate_reasons", []),
            "fallback_tag": c.get("fallback_tag")
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

Your job:
Choose which candidates are true document headings and assign h1, h2, or h3.

Rules:
- Use only the provided candidates.
- Preserve exact wording from the candidate value.
- Exclude body paragraphs, screenshot callouts, buttons, page headers, page footers, page numbers, bullets, and table-of-contents navigation entries.
- The first returned heading must be h1.
- Do not skip heading levels. Example: h1 -> h3 is invalid; use h1 -> h2 -> h3.
- Repeated levels are allowed. Example: h2 -> h2 -> h2 is valid.
- Returning fewer accurate headings is better than returning many false headings.
- Human review is required before IronPDF applies these tags.

Return only valid JSON with this exact shape:

{{
  "remediation_script": [
    {{
      "page_number": 1,
      "source_entry_id": "p1_entry_001",
      "tag": "h1",
      "text": "Exact heading text"
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
# SEMANTIC STRUCTURE POST-PROCESSING
# ============================================================

def normalize_tag(tag):
    tag = str(tag or "").lower().strip()
    return tag if tag in {"h1", "h2", "h3"} else None


def tag_level(tag):
    return int(tag[1])


def make_fallback_remediation_script(heading_candidates):
    script = []

    for entry in heading_candidates:
        text = clean_heading_label(entry["value"])
        tag = normalize_tag(entry.get("fallback_tag")) or "h2"

        if not text:
            continue

        item = {
            "page_number": entry["page_number"],
            "source_entry_id": entry["id"],
            "tag": tag,
            "text": text,
            "coordinates": entry["coordinates"]
        }

        if entry.get("merged_entry_ids"):
            item["source_entry_ids"] = entry["merged_entry_ids"]

        script.append(item)

    return repair_heading_sequence(script)


def validate_llm_remediation_script(ai, heading_candidates):
    candidates_by_id = {c["id"]: c for c in heading_candidates}
    output = []
    seen_ids = set()

    raw_script = ai.get("remediation_script", [])
    if not isinstance(raw_script, list):
        return []

    for item in raw_script:
        if not isinstance(item, dict):
            continue

        source_id = item.get("source_entry_id")
        if source_id in seen_ids:
            continue

        candidate = candidates_by_id.get(source_id)
        if candidate is None:
            continue

        text = clean_heading_label(candidate["value"])
        if not text:
            continue

        tag = normalize_tag(item.get("tag")) or normalize_tag(candidate.get("fallback_tag")) or "h2"

        out_item = {
            "page_number": candidate["page_number"],
            "source_entry_id": candidate["id"],
            "tag": tag,
            "text": text,
            "coordinates": candidate["coordinates"]
        }
        if candidate.get("merged_entry_ids"):
            out_item["source_entry_ids"] = candidate["merged_entry_ids"]
        output.append(out_item)
        seen_ids.add(source_id)

    output.sort(key=lambda e: (e["page_number"], e["coordinates"]["y"], e["coordinates"]["x"]))
    return repair_heading_sequence(output)


def repair_heading_sequence(script):
    repaired = []

    for item in script:
        tag = normalize_tag(item.get("tag")) or "h2"
        level = tag_level(tag)

        if not repaired:
            # PAC/UA rule: if headings are used, first heading must be H1.
            level = 1
        else:
            previous_level = tag_level(repaired[-1]["tag"])
            if level > previous_level + 1:
                level = previous_level + 1

        fixed = dict(item)
        fixed["tag"] = f"h{level}"
        repaired.append(fixed)

    return repaired

# ============================================================
# TASK PROCESSORS
# ============================================================

def process_semantic_structure_document(doc, failure_report):
    print("Building document-level heading candidate list...", flush=True)

    heading_candidates = get_likely_heading_entries(doc)

    print(f"Heading candidates found: {len(heading_candidates)}", flush=True)

    warnings = []

    if not USE_LLM_FOR_SEMANTIC:
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
            document_name=PDF_PATH.name,
            heading_candidates=heading_candidates,
            failure_report=failure_report
        )

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

        ai = ask_ollama(
            prompt,
            num_ctx=SEMANTIC_NUM_CTX,
            num_predict=SEMANTIC_NUM_PREDICT
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

#multi file
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

def process_one_pdf(pdf_path):
    global PDF_PATH
    global FAILURE_REPORT_PATH

    PDF_PATH = pdf_path
    FAILURE_REPORT_PATH = get_failure_report_path(pdf_path)

    print("=" * 80, flush=True)
    print(f"Processing PDF: {pdf_path.name}", flush=True)

    if FAILURE_REPORT_PATH is None:
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

        output_json = OUTPUT_FOLDER / f"{pdf_path.stem}_results.json"

        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(skipped_result, f, indent=2, ensure_ascii=False)

        return {
            "document_name": pdf_path.name,
            "failure_report": None,
            "result_file": str(output_json),
            "results": skipped_result
        }

    print(f"Reading failure report: {FAILURE_REPORT_PATH.name}", flush=True)
    failure_report = FAILURE_REPORT_PATH.read_text(encoding="utf-8", errors="replace")
    
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
        "failure_report": str(FAILURE_REPORT_PATH),
        "result_file": str(output_json),
        "results": results
    }


def main():
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


if __name__ == "__main__":
    main()

#%%