# PDF Accessibility Auditor — Local Portfolio Template

This project is a local PDF accessibility remediation prototype. A user uploads a PDF through a .NET Blazor interface and selects one or both supported tasks:

- Generate suggested alternative text for detected images.
- Generate a Markdown representation and concise summary for detected tables.

The Python backend analyzes the PDF with PyMuPDF, calls locally hosted Ollama models, retrieves relevant guidance from a CSV-backed vector store, and returns structured JSON. The .NET frontend uses iTextSharp to apply supported updates to tagged PDF structure elements and packages the edited PDF with a human-readable review summary.

This is an assistive workflow, not an automated accessibility certification tool. Every generated result requires human review.

## Architecture

```text
Browser
  -> Blazor Server frontend (.NET 10)
  -> local FastAPI backend (127.0.0.1:8000)
  -> PyMuPDF extraction and rendering
  -> Ollama chat/vision model for captions and summaries
  -> Ollama embedding model for local guidance retrieval
  -> generated CSV vector store
  -> JSON remediation instructions
  -> iTextSharp PDF structure updates
  -> edited PDF + review summary ZIP
```

## Technology stack

- Frontend: ASP.NET Core Blazor Server, .NET 10, C#
- PDF editing: iTextSharp 5.5.13.5
- Backend: Python 3.10+, FastAPI, Uvicorn
- PDF analysis: PyMuPDF
- Local AI: Ollama
- Vector storage: CSV with JSON-encoded embedding vectors

## Prerequisites

Install:

1. .NET 10 SDK
2. Python 3.10 or later
3. Ollama
4. A local Ollama model capable of image input for alt-text generation
5. A local Ollama embedding model

Default model examples:

```bash
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

Model names are configurable. The chat model must support images when image captioning is selected.

## Backend setup

From `Backend`:

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python build_vector_store.py
.\run_local.ps1
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python build_vector_store.py
./run_local.sh
```

The backend health endpoint is:

```text
http://127.0.0.1:8000/health
```

The generated `Backend/data/vector_store.csv` is intentionally excluded from Git. It is rebuilt from `Backend/data/knowledge_base.csv` by calling the configured Ollama embedding model.

## Backend configuration

Copy `.env.example` to `.env` and change values as needed.

| Variable | Purpose | Default |
|---|---|---|
| `OLLAMA_BASE_URL` | Local Ollama HTTP endpoint | `http://127.0.0.1:11434` |
| `OLLAMA_CHAT_MODEL` | Chat/vision model used for remediation | `gemma3:4b` |
| `OLLAMA_EMBEDDING_MODEL` | Embedding model used for retrieval | `nomic-embed-text` |
| `VECTOR_SOURCE_CSV` | Safe source guidance CSV | `data/knowledge_base.csv` |
| `VECTOR_STORE_CSV` | Generated CSV vector database | `data/vector_store.csv` |
| `VECTOR_TOP_K` | Number of retrieved guidance entries | `3` |
| `ENGINE_TIMEOUT_SECONDS` | Per-task processing timeout | `3600` |
| `MAX_UPLOAD_MB` | Backend upload limit | `100` |

No backend API key is required because this template is designed to bind to the local loopback interface. Do not expose the development backend directly to the public internet without adding an appropriate deployment and authentication layer.

## Frontend setup

Keep the backend running, then open a second terminal:

```bash
cd Frontend/AccessibilityAuditorApp
dotnet restore
dotnet run
```

Open the localhost address printed by `dotnet run`.

The frontend defaults to `http://127.0.0.1:8000`. To use another local address, either edit `AccessibilityBackend:BaseUrl` in `appsettings.Development.json` or set:

```text
ACCESSIBILITY_BACKEND_BASE_URL=YOUR_LOCAL_BACKEND_URL
```

`appsettings.example.json` documents the configurable frontend values. Do not store real production secrets in committed appsettings files.

## Local CSV retrieval flow

1. `knowledge_base.csv` contains generic, project-authored accessibility guidance without embeddings.
2. `build_vector_store.py` sends each guidance entry to the configured Ollama embedding model.
3. Embeddings are written to `vector_store.csv` as JSON arrays.
4. During remediation, the backend embeds a task-specific query.
5. Cosine similarity selects the most relevant local guidance entries.
6. Retrieved guidance is included in the Ollama remediation prompt.

Edit `knowledge_base.csv` to supply your own public or properly licensed guidance. Rebuild the vector store after changes.

## Testing the sanitized project

### 1. Static Python checks

```bash
cd Backend
python -m compileall .
pip install -r requirements-dev.txt
pytest -q
```

### 2. Verify Ollama

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

Confirm that the configured chat and embedding models are present.

### 3. Build the CSV vector store

```bash
python build_vector_store.py
```

Confirm that `data/vector_store.csv` is created locally and remains ignored by Git.

### 4. Start and test the backend

```bash
python -m uvicorn backend_server:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
```

Optional direct API test:

```bash
curl -X POST http://127.0.0.1:8000/remediate \
  -F "pdf=@YOUR_INPUT_FILE.pdf" \
  -F "tasks=table_summary"
```

### 5. Build the frontend

```bash
cd Frontend/AccessibilityAuditorApp
dotnet restore
dotnet build
```

### 6. End-to-end test

1. Start Ollama.
2. Start the FastAPI backend.
3. Start the Blazor frontend.
4. Upload a PDF you are authorized to process.
5. Select one or both tasks.
6. Download the generated ZIP.
7. Inspect both the PDF and `accessibility_remediation_summary.txt`.
8. Validate the PDF with an accessibility checker and manual assistive-technology testing.

## Generalized or removed workplace features

- Removed the external compute-server dependency and changed the integration to a local FastAPI service.
- Removed shared API-key authentication used between the original frontend and backend.
- Removed institutional authentication, reverse-proxy, hosting, and path-base assumptions.
- Removed company branding, logos, template layout, contact details, and institutional links.
- Removed internal deployment instructions, usernames, server addresses, file paths, and service definitions.
- Removed bundled workplace test documents and generated data.
- Replaced the remote vector or server assumptions with a generated local CSV vector store.
- Added safe example configuration and generic project-authored retrieval guidance.

## Known limitations

- Alt-text quality depends on the selected vision model and document context.
- Table detection depends on PyMuPDF extraction and may miss complex, scanned, or visually constructed tables.
- Direct PDF structure updates work best on already tagged PDFs with identifiable `/Figure` and `/Table` elements.
- The application does not reconstruct reading order, heading hierarchy, table header associations, forms, annotations, fonts, or other PDF internals.
- Generated output does not establish WCAG, PDF/UA, Section 508, or legal compliance.
- Temporary files are deleted after processing, but a process crash may leave short-lived files in the operating system temporary directory until cleanup.
- The project has not been tested against every Ollama model or operating system.

## Files that must not be committed

The root `.gitignore` excludes:

- `.env` and local secret/configuration variants
- Python virtual environments and caches
- `.NET` build output and Visual Studio metadata
- Generated `vector_store.csv`
- Uploaded PDFs and generated PDFs
- Rendered pages, cropped images, result JSON, ZIP packages, temporary jobs, and logs

Before each public push, run `git status --ignored` and a repository-wide secret scan.

## Licensing

No project-wide license is granted by this sanitized package. The repository owner should add only a license they are authorized to grant.

Important dependency concerns:

- iTextSharp 5 is a legacy, dual-licensed dependency available under AGPLv3 or a commercial license.
- PyMuPDF/MuPDF is also offered under AGPL or commercial terms.
- These licenses may impose source-disclosure and distribution obligations. Obtain legal review before publishing or deploying under a non-AGPL license.
- Ollama's Python client and FastAPI use permissive licenses, but model licenses vary by model. Review the license and acceptable-use terms for every model you distribute or recommend.

See `THIRD_PARTY_NOTICES.md` and `SANITIZATION_REPORT.md` before publication.
