# Sanitization Report

## Scope reviewed

The complete uploaded archive was extracted with path-traversal checks and reviewed across source code, configuration, documentation, comments, compiled caches, nested archives, PDFs, text reports, JSON output, and rendered images. Binary PDF content was searched as text where possible to identify embedded workplace domains, email addresses, links, and document metadata.

Original archive review:

- 139 files
- Approximately 241 MB after extraction
- 124 files excluded entirely
- 15 files retained only as the basis for sanitized or rewritten versions

The exact original-file audit is intentionally kept outside the public repository because original document names can disclose workplace subjects.

## Significant changes

1. **Reduced the repository to one maintainable implementation.** The modular package was retained; duplicate monolithic prototypes, duplicate source copies, compiled caches, generated results, and bundled archives were removed.
2. **Removed all workplace data.** No original PDFs, reports, rendered pages, crops, JSON results, generated databases, or document archives remain.
3. **Removed hard-coded identity and paths.** A named Windows user path and workplace directory assumptions were replaced with project-relative defaults and environment variables.
4. **Made model execution local.** The application now calls Ollama through the local REST API. No external processing server, API key, internal hostname, or hosted model service is required.
5. **Added local CSV retrieval.** Generic `.md` and `.txt` files are embedded through Ollama's `/api/embed` endpoint. Embeddings, text chunks, and source names are written to `data/vector_store.csv`; retrieval uses local cosine similarity.
6. **Generalized remediation output.** References to a named proprietary PDF remediation product were replaced with generic instructions to use an appropriate PDF library or editor.
7. **Added safe configuration.** `.env.example` documents model and directory settings. `.env`, certificates, keys, user data, generated vectors, archives, caches, logs, and virtual environments are ignored.
8. **Added a usable CLI.** The user can select automatic routing or force `alt_text`, `table_summary`, or `semantic_structure`; input/output directories, page limits, retrieval, and vector rebuilding are configurable.
9. **Added synthetic tests.** `scripts/create_sample_data.py` creates non-workplace sample PDFs. No original sample documents are redistributed.
10. **Added publication documentation.** The repository now includes a comprehensive README, removal summary, licensing review, dependency metadata, unit tests, and a repository scanner.

## Configuration values to review or replace

No secrets are required for the default local setup. Review these values in `.env`:

| Value | When to change it |
|---|---|
| `OLLAMA_BASE_URL` | Change only when Ollama is not using the default local endpoint. Do not commit credentials or a private production address. |
| `OLLAMA_CHAT_MODEL` | Set to an installed local model. Image analysis requires vision support. |
| `OLLAMA_EMBED_MODEL` | Set to an installed local embedding model. Rebuild the CSV after changing it. |
| `INPUT_DIRECTORY` | Set to the local folder containing user-supplied PDFs. |
| `OUTPUT_DIRECTORY` | Set to a writable local output folder. |
| `KNOWLEDGE_DIRECTORY` | Set to a folder containing only redistributable generic reference material. |
| `VECTOR_CSV_PATH` | Set to the generated local CSV location. Do not commit the generated file. |
| `MAX_PAGES` and `MAX_IMAGES_PER_PAGE` | Adjust for testing, runtime, and model capacity. |
| `USE_LLM_FOR_SEMANTIC` | Enable only after evaluating the selected model's heading-classification reliability. |

There is no `YOUR_API_KEY` placeholder because the default local Ollama API does not require an API key.

## Removed-file categories

- Workplace PDFs and converted PDFs
- Workplace failure reports and conversion summaries
- Generated JSON output
- Rendered pages and cropped images
- Nested test-data ZIP files
- Monolithic and duplicate Python implementations
- `__pycache__` directories and `.pyc` files
- Hard-coded configuration and original minimal documentation

See `REMOVED_FILES.md` for the public summary. The separate audit delivered with the package contains the exact original paths.

## Verification performed

- Python bytecode compilation succeeded for the complete sanitized repository.
- A wheel build succeeded after package discovery was restricted to the `accessibility_auditor` package.
- Five unit tests passed for task routing and CSV vector-store behavior.
- Synthetic PDFs were generated successfully with no workplace content.
- A mocked local Ollama REST service was used for an end-to-end batch test.
- The end-to-end test successfully completed alternative-text, heading-structure, and table-summary workflows and generated combined JSON output.
- The explicit vector-store rebuild occurred once per run and was then reused.
- The repository scanner reported no configured secret, identity, personal path, email, private key, or unapproved URL pattern in the public source tree.
- Additional searches found no original workplace name, user name, workplace domain, hard-coded user path, proprietary remediation-product name, or remote-server identifier in the publishable code.

The end-to-end test used a mock Ollama-compatible local HTTP service, not a downloaded production model. Model-specific output quality must still be tested with the models selected by the user.

## Step-by-step local test

1. Extract the sanitized folder into a new location that is not inside the workplace repository.
2. Do not copy the original `.git` directory or push the original commit history.
3. Create and activate a Python virtual environment.
4. Install `requirements.txt`.
5. Install Ollama and pull the chat/vision and embedding models configured in `.env`.
6. Copy `.env.example` to `.env` and verify all directories and model names.
7. Run `python scripts/create_sample_data.py`.
8. Run `python -m unittest discover -s tests -v`.
9. Run `python run.py --max-pages 1`.
10. Inspect `output/all_results.json` and the per-document JSON files.
11. Run `python scripts/repository_scan.py` before every public push. Add `--term` for any workplace names, domains, usernames, or identifiers known to you.
12. Confirm `git status` does not include `.env`, PDFs, failure reports, output, vector CSV files, model files, archives, or virtual environments.

## Remaining confidentiality and deployment concerns

- **Git history:** deleting a secret or document from the working tree does not remove it from prior commits. Publish this sanitized folder as a new repository with a new Git history. If any original history is reused, it must be independently rewritten and verified.
- **User inputs:** PDFs and reports may contain personal, regulated, contractual, or confidential information. They are ignored by default, but users must avoid force-adding them.
- **Generated CSV:** the vector CSV stores source text as well as embeddings. It can reproduce content from the knowledge base and must remain uncommitted when sources are private.
- **Model behavior:** local models can hallucinate, omit content, or produce unsafe remediation suggestions. Human review and independent accessibility testing remain necessary.
- **Network exposure:** the default Ollama endpoint is local. Exposing Ollama beyond localhost changes the security model and should be handled outside this template.
- **No direct remediation:** this repository produces suggestions only. A separate implementation is required to apply approved changes to PDF structure.

## Remaining licensing concerns

- PyMuPDF is available under GNU AGPL or a commercial license. Determine whether the planned GitHub publication, deployment method, and any proprietary use satisfy the applicable terms.
- Requests uses Apache License 2.0.
- Ollama and each downloaded model have independent terms.
- No project-level license was added because ownership and sublicensing rights for the retained original code should be confirmed first.
- Do not add workplace logos, templates, documents, standards text, model weights, or third-party assets unless redistribution rights are documented.
