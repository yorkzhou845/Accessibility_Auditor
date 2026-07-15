import json

from . import config as cfg


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
{failure_report[:cfg.FAILURE_REPORT_CHAR_LIMIT]}

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
{failure_report[:cfg.FAILURE_REPORT_CHAR_LIMIT]}

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
{failure_report[:cfg.FAILURE_REPORT_CHAR_LIMIT]}

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
