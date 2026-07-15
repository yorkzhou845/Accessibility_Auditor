"""Prompt builders. All document-specific context is supplied at runtime."""

from __future__ import annotations

import json

from . import config as cfg


def _reference_section(reference_context: str) -> str:
    return f"""
Local reference context:
{reference_context}

Use the reference context as general guidance only. Base document-specific findings on the provided PDF data.
""".strip()


def build_document_semantic_prompt(
    document_name,
    heading_candidates,
    failure_report,
    reference_context="",
):
    slim_candidates = [
        {
            "id": candidate["id"],
            "page_number": candidate["page_number"],
            "value": candidate["value"],
            "font_size": round(candidate.get("font_size", 0), 1),
            "is_bold": candidate.get("is_bold", False),
            "candidate_score": candidate.get("candidate_score"),
            "reasons": candidate.get("candidate_reasons", []),
            "fallback_tag": candidate.get("fallback_tag"),
        }
        for candidate in heading_candidates
    ]

    return f"""
Task: Semantic Structure Mapping

Document: {document_name}

Failure report:
{failure_report[:cfg.FAILURE_REPORT_CHAR_LIMIT]}

{_reference_section(reference_context)}

Likely heading candidates:
{json.dumps(slim_candidates, indent=2)}

Choose only true document headings and assign h1, h2, or h3.

Rules:
- Use only the provided candidates.
- Preserve exact candidate wording.
- Exclude body paragraphs, controls, page headers, page footers, page numbers, bullets, and table-of-contents navigation entries.
- The first returned heading must be h1.
- Do not skip heading levels.
- Returning fewer accurate headings is preferable to returning false headings.
- Human review is required before applying tags.

Return only valid JSON:
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


def build_alt_text_prompt(
    document_name,
    page_number,
    image_entry,
    failure_report,
    reference_context="",
):
    return f"""
Task: Suggested Alternative Text

Document: {document_name}
Page: {page_number}

Failure report:
{failure_report[:cfg.FAILURE_REPORT_CHAR_LIMIT]}

{_reference_section(reference_context)}

Image metadata:
{json.dumps(image_entry, indent=2)}

Rules:
- If the image is decorative, return empty alt_text and decorative=true.
- If the image contains readable text that is essential, include the essential visible text.
- Otherwise describe the meaningful content concisely, normally in fewer than 25 words.
- Do not begin with "image of" or "picture of" unless needed for clarity.
- Do not claim the suggestion makes the PDF compliant.
- Human review is required before use.

Return only valid JSON:
{{
  "alt_text": "",
  "decorative": false,
  "image_contains_text": false,
  "confidence": 0.0
}}
"""


def build_table_prompt(
    document_name,
    page_number,
    table_entry,
    failure_report,
    reference_context="",
):
    return f"""
Task: Table Representation and Summary

Document: {document_name}
Page: {page_number}

Failure report:
{failure_report[:cfg.FAILURE_REPORT_CHAR_LIMIT]}

{_reference_section(reference_context)}

Detected table data:
{json.dumps(table_entry, indent=2)}

Rules:
- Preserve the detected table data as accurately as possible.
- Produce a Markdown representation.
- Produce one concise sentence describing the table's purpose or main relationship.
- Do not imply that a summary substitutes for correct table tags and header associations.
- Human review is required before use.

Return only valid JSON:
{{
  "markdown_table": "",
  "summary": "",
  "summary_attribute": "",
  "confidence": 0.0
}}
"""
