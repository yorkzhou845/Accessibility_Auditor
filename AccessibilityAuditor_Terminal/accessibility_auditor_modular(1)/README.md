# Accessibility Auditor — Modular Version

This refactor keeps the original pipeline behavior but separates the long file into larger pipeline modules instead of one file per function.

## File layout

```text
accessibility_auditor/
  config.py              # paths, model name, token budgets, max-pages settings
  ollama_client.py       # ask_ollama wrapper and JSON cleanup
  router.py              # rule-based + AI failure-report classification
  text_features.py       # reusable text/heading heuristics
  pdf_utils.py           # page rendering, image/table extraction, PDF coordinates
  heading_detection.py   # document-level heading candidate detection
  prompts.py             # prompts for semantic headings, alt text, table summary
  postprocess.py         # heading tag validation and sequence repair
  processors.py          # semantic/alt-text/table task processors
  file_matching.py       # matching PDFs to failure reports
  main.py                # batch orchestration over the input folder
run.py                   # simple entry point
```

## How to run

1. Edit `accessibility_auditor/config.py` if your input/output paths changed.
2. Make sure Ollama is running and the configured model is installed.
3. From this folder, run:

```bash
python run.py
```

You can also run it as a module:

```bash
python -m accessibility_auditor.main
```

## Main design change

The old global `PDF_PATH` and `FAILURE_REPORT_PATH` state was removed from most logic. The active `pdf_path` is now passed into processors and PDF helper functions that need it for naming rendered/cropped images. This reduces hidden dependencies between modules.
