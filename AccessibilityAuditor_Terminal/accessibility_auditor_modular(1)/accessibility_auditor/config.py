from pathlib import Path

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

RENDER_SCALE = 1.0

# Use 1 while testing. Change to None for the whole PDF.
MAX_PAGES = None

# For alt_text only. Use 2 while testing. Change to None for all images per page.
MAX_IMAGES_PER_PAGE = 2

# Maximum candidate headings sent to the semantic processor.
MAX_HEADING_CANDIDATES = 80

# Maximum characters of the failure report included in each prompt.
FAILURE_REPORT_CHAR_LIMIT = 1200

# Ollama context / output token budgets.
SEMANTIC_NUM_CTX = 8192
SEMANTIC_NUM_PREDICT = 2000

ALT_TEXT_NUM_CTX = 4096
ALT_TEXT_NUM_PREDICT = 250

TABLE_NUM_CTX = 4096
TABLE_NUM_PREDICT = 600

SYS_PROMPT = """
You are a PDF accessibility remediation assistant.

You only support these three tasks:
1. Automated alt-text generation.
2. Semantic structure mapping.
3. Table summarization.

Do not repair PDF internals such as fonts, CIDSet streams, metadata, signatures, xref tables, or low-level PDF object issues.

Return only valid JSON.
"""
