import re

from .ollama_client import ask_ollama


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
