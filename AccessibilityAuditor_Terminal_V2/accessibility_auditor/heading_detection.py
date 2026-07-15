import re
from collections import Counter, defaultdict

import fitz

from . import config as cfg
from .pdf_utils import get_page_count, get_text_line_entries
from .text_features import (
    clean_heading_label,
    is_bullet_or_list_item,
    is_mostly_upper,
    is_numbered_heading_pattern,
    is_probably_page_number_or_footer,
    is_short_callout_or_button,
    is_title_like,
    is_toc_title,
    normalize_toc_key,
    sentence_like,
    text_word_count,
)


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

    if cfg.MAX_HEADING_CANDIDATES is not None and len(scored) > cfg.MAX_HEADING_CANDIDATES:
        scored = sorted(scored, key=lambda e: e["candidate_score"], reverse=True)[:cfg.MAX_HEADING_CANDIDATES]
        scored.sort(key=lambda e: (e["page_number"], e["coordinates"]["y"], e["coordinates"]["x"]))

    return scored
