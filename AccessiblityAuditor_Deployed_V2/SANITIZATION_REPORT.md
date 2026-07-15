# Sanitization Report

## Significant changes

1. Replaced the remote backend configuration with a loopback-only FastAPI backend.
2. Removed backend shared-key authentication and all embedded credentials.
3. Replaced hard-coded chat-model configuration with environment variables.
4. Added local Ollama embedding calls and CSV-based semantic retrieval.
5. Added a safe source guidance CSV and excluded the generated vector CSV.
6. Replaced institutional UI branding with a generic accessible layout.
7. Removed reverse-proxy, institution-specific path-base, hostname, and deployment validation.
8. Replaced frontend server references with `http://127.0.0.1:8000` defaults and a configurable environment variable.
9. Removed build output, IDE metadata, caches, test documents, generated data, and workplace notes.
10. Added a repository-level `.gitignore`, safe example configuration files, tests, local start scripts, documentation, and licensing warnings.
11. Preserved the PDF upload, analysis, structured JSON, conservative PDF editing, result summary, and ZIP download workflow.

## Files and directories removed

- `Keys.txt`
- `Mixed_Tables_Images_Test_Document.pdf`
- `BackEnd/__pycache__/`
- Original external-server-specific backend README and service configuration examples
- `FrontEnd/.vs/`
- `FrontEnd/AccessibilityAuditorApp/bin/`
- `FrontEnd/AccessibilityAuditorApp/obj/`
- `FrontEnd/AccessibilityAuditorApp/AccessibilityAuditorApp.csproj.user`
- Original workplace deployment guide
- Institutional logo image under `wwwroot/images/`
- Vendored Bootstrap directory under `wwwroot/lib/`
- Original secret-bearing development and production appsettings content
- Original remote-backend API-key handling
- Original reverse-proxy and production-host validation code

## Configuration values to review or replace

Backend `.env`:

- `OLLAMA_BASE_URL`
- `OLLAMA_CHAT_MODEL`
- `OLLAMA_EMBEDDING_MODEL`
- `VECTOR_SOURCE_CSV`
- `VECTOR_STORE_CSV`
- `VECTOR_TOP_K`
- `ENGINE_TIMEOUT_SECONDS`
- `MAX_UPLOAD_MB`

Frontend:

- `AccessibilityBackend:BaseUrl`, or `ACCESSIBILITY_BACKEND_BASE_URL`
- Optional `TemporaryStorage:JobsRoot`
- Local frontend launch ports, when the defaults conflict with another application

No API key placeholder remains because the public template is designed for local loopback use.

## Remaining confidentiality and security concerns

- Do not commit PDFs, rendered images, result JSON, ZIP files, logs, or the generated vector store.
- Replace `knowledge_base.csv` only with material you own, created, or are permitted to redistribute.
- A locally bound backend has no authentication. Keep it on `127.0.0.1`; adding public network access requires a separate security design.
- Ollama prompts may contain extracted document content. Only process documents appropriate for the local machine and selected model environment.
- Temporary files may survive an abrupt operating-system or process failure until periodic cleanup or manual removal.
- Run a secret scanner against Git history as well as the working tree. Sanitizing the current files does not remove secrets from prior commits.
- The exposed keys found in the supplied archive should be treated as compromised and revoked or rotated, even though they were removed from this package.

## Remaining licensing concerns

- iTextSharp 5.5.13.5 is legacy software under AGPLv3 or commercial licensing.
- PyMuPDF/MuPDF is under AGPL or commercial licensing.
- The repository owner should not add an MIT, Apache, or other permissive project license without first resolving compatibility and confirming authority over the original workplace-derived code.
- Ollama model licenses are separate from the Ollama client license and must be reviewed model by model.

## Recommended pre-publication checks

1. Revoke the two API keys exposed in the original archive.
2. Create a new Git repository rather than copying workplace Git history.
3. Run a secret scanner such as Gitleaks or TruffleHog on the final directory.
4. Run `git status --ignored` and verify that no PDF, `.env`, generated vector CSV, build output, or temporary file is staged.
5. Obtain written confirmation that the remaining source code may be redistributed.
6. Obtain licensing advice for iTextSharp and PyMuPDF before choosing a repository license.
7. Test with non-confidential PDFs only.
