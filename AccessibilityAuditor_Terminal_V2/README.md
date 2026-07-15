# Local PDF Accessibility Auditor

A reusable terminal-based Python template for analyzing PDFs and generating human-reviewable accessibility remediation suggestions. The application runs locally, calls a local Ollama instance for chat, vision, and embeddings, and stores retrieval vectors in a local CSV file.

This repository does **not** certify legal or standards compliance and does **not** directly rewrite PDF tag trees. It produces JSON suggestions that a reviewer can validate and apply with an appropriate PDF remediation tool.

## Supported analysis tasks

- **Alternative text:** detects embedded images, crops them, and asks a vision-capable Ollama model for suggested alternative text.
- **Heading structure:** detects likely headings from layout and typography. Deterministic rules are used by default; optional LLM refinement can be enabled.
- **Table representation:** detects tables, requests a Markdown representation, and generates a concise description for human review.
- **Failure-report routing:** maps a matching text failure report to one of the supported tasks or marks it unsupported.
- **Local retrieval:** embeds generic reference material from `knowledge_base/`, stores vectors in `data/vector_store.csv`, and retrieves relevant context with cosine similarity.

## Architecture

```text
PDF + optional failure report
        |
        v
Rule-based / local LLM task router
        |
        +--> PyMuPDF extraction
        |      - text and heading features
        |      - image locations and crops
        |      - detected table cells
        |
        +--> Local retrieval
        |      knowledge_base/*.md or *.txt
        |      -> Ollama /api/embed
        |      -> data/vector_store.csv
        |      -> cosine-similarity search
        |
        v
Ollama /api/chat (local chat or vision model)
        |
        v
JSON suggestions + temporary rendered images in output/
```

### Interface and backend

The uploaded workplace archive was a terminal-only Python project; it did not contain a separate web frontend. In this public version:

- `run.py` is the command-line interface.
- `accessibility_auditor/` is the local processing backend.
- Ollama is the local model service.
- No external accelerator server, hosted model API, internal authentication provider, or remote vector database is required.

## Prerequisites

- Python 3.10 or newer
- Ollama installed and running locally
- A vision-capable chat model for image alternative-text analysis
- An embedding model for local retrieval

Default model configuration:

```text
Chat / vision model: gemma3:4b
Embedding model:     embeddinggemma
Ollama endpoint:     http://127.0.0.1:11434
```

Models can be changed in `.env`.

## Installation

### 1. Create a virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Install and start Ollama

Install Ollama using its official instructions, then pull the configured models:

```bash
ollama pull gemma3:4b
ollama pull embeddinggemma
```

Confirm the local service is available:

```bash
ollama list
```

### 3. Create local configuration

Copy the example file:

PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```bash
cp .env.example .env
```

Edit `.env` when your model names or directories differ. `.env` is excluded from Git.

### 4. Add input files

Place PDFs in `input/`. Automatic routing expects a matching report named:

```text
Example.pdf
Example_Failure_Report.txt
```

A report is optional when `--task` is supplied directly.

## Running the application

Automatic task classification from matching failure reports:

```bash
python run.py
```

Process every PDF as a specific task:

```bash
python run.py --task alt_text
python run.py --task table_summary
python run.py --task semantic_structure
```

Use custom directories:

```bash
python run.py --input /path/to/pdfs --output /path/to/results
```

Rebuild the generated CSV vector store:

```bash
python run.py --rebuild-vector-store
```

Run without embeddings or retrieval:

```bash
python run.py --skip-retrieval
```

Limit processing during testing:

```bash
python run.py --max-pages 1
```

Command reference:

```bash
python run.py --help
```

## Synthetic local test data

Generate three small, non-workplace sample PDFs and matching failure reports:

```bash
python scripts/create_sample_data.py
```

Then run:

```bash
python run.py --max-pages 1
```

The generated sample inputs are ignored by Git.

## Configuration values

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama host. Keep this local unless you intentionally configure another environment. |
| `OLLAMA_CHAT_MODEL` | `gemma3:4b` | Chat model; must support vision for image analysis. |
| `OLLAMA_EMBED_MODEL` | `embeddinggemma` | Embedding model used to build and query the CSV vector store. |
| `INPUT_DIRECTORY` | `./input` | Folder containing PDFs and optional failure reports. |
| `OUTPUT_DIRECTORY` | `./output` | Generated JSON, page renders, and image crops. |
| `KNOWLEDGE_DIRECTORY` | `./knowledge_base` | Generic `.md` and `.txt` retrieval sources. |
| `VECTOR_CSV_PATH` | `./data/vector_store.csv` | Generated local vector database. |
| `USE_RETRIEVAL` | `true` | Enables local embedding and retrieval. |
| `REBUILD_VECTOR_STORE` | `false` | Forces CSV regeneration on startup. |
| `USE_LLM_FOR_SEMANTIC` | `false` | Enables LLM refinement of deterministic heading candidates. |
| `MAX_PAGES` | `all` | Optional page limit per PDF. |
| `MAX_IMAGES_PER_PAGE` | `2` | Optional image limit per page. |

No API key is required for Ollama's default local API. Do not add cloud credentials or private server values to `.env.example`.

## Output

The application writes:

- `output/<document>_results.json` for each PDF
- `output/all_results.json` for the batch
- `output/rendered_pages/` for temporary page renders
- `output/cropped_images/` for temporary image crops
- `data/vector_store.csv` for generated embeddings and source chunks

All of these generated files are excluded through `.gitignore`.

## What was generalized or removed

- Removed all original workplace documents, reports, generated analysis output, rendered assets, and bundled archives.
- Removed duplicate monolithic source versions and compiled Python caches.
- Replaced hard-coded Windows user paths with project-relative defaults and environment variables.
- Removed references to specific institutions, internal infrastructure, remote servers, and named proprietary remediation products.
- Replaced the Python Ollama package wrapper with direct local REST calls to Ollama's documented `/api/chat` and `/api/embed` endpoints.
- Added a generated CSV vector store instead of a hosted or service-based vector database.
- Added synthetic test-data generation rather than redistributing workplace documents.
- Added `.env.example`, `.gitignore`, dependency metadata, tests, licensing notes, and a sanitization report.

No authentication implementation was present in the uploaded terminal archive. The sanitized project does not add one.

## Known limitations

- Suggestions require human review and may be inaccurate.
- Table detection depends on the PDF's visual and text structure and may miss scanned or irregular tables.
- Image extraction may include logos, backgrounds, or repeated assets that require reviewer judgment.
- The project analyzes PDFs but does not currently inject tags, alternative text, or table metadata into the source file.
- Scanned PDFs may require OCR before meaningful text or table analysis. OCR is not included.
- Model quality, latency, context size, and model licensing depend on the locally selected Ollama models.
- The CSV vector store is intended for small local knowledge collections, not large-scale production retrieval.

## Files that must not be committed

Do not commit:

- `.env`
- workplace or user PDFs
- failure reports containing private information
- generated `output/` contents
- `data/vector_store.csv`
- virtual environments
- model files
- logs, caches, archives, or extracted document images

Run the repository scanner before publishing:

```bash
python scripts/repository_scan.py
```

## Licensing and ownership

No project-level open-source license has been added. Before selecting a license, confirm that you own or have permission to redistribute every retained source file. Absence of a license generally means others do not receive permission to reuse the project beyond rights provided by law.

PyMuPDF is offered under the GNU AGPL or a commercial license. Confirm that your intended publication and deployment comply with the applicable license. Requests is distributed under Apache License 2.0. Ollama and each downloaded model have separate terms that should be reviewed independently. See `THIRD_PARTY_NOTICES.md`.

## Repository review records

- `SANITIZATION_REPORT.md` summarizes the changes, configuration replacements, testing, and residual concerns.
- `REMOVED_FILES.md` lists original files excluded from the public package.
- `THIRD_PARTY_NOTICES.md` records major third-party licensing considerations.
