import re


def clean_text(text):
    return " ".join(text.split())


def is_probably_page_number_or_footer(text):
    lower = text.lower().strip()

    if re.fullmatch(r"page\s+\d+\s*(of|/|\|)\s*\d+", lower):
        return True

    if re.fullmatch(r"\d+\s*(/|\|)\s*\d+", lower):
        return True

    if re.fullmatch(r"-?\s*\d+\s*-?", lower):
        return True

    return False


def is_numbered_heading_pattern(text):
    # Allows headings like "1 Introduction", "1.2 Scope", "2.3.1 Details".
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9]", text.strip()))


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
