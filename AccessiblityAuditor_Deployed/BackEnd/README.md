# Accessibility Auditor GB10 Backend — transient-storage version

This FastAPI backend receives a PDF from the Blazor application, runs the
selected image-captioning and/or table-summary tasks, returns the combined JSON
response, and then deletes the entire GB10 job directory in a `finally` block.

Temporary files are created under:

```text
/tmp/accessibility-auditor-jobs/<job-id>/
```

They exist only while the request is being processed. The job directory is
removed after success, timeout, or failure.

Supported tasks:

- `alt_text`
- `table_summary`
- `alt_text,table_summary`

## Install on GB10

```bash
mkdir -p ~/accessibility-auditor-backend
cd ~/accessibility-auditor-backend
unzip ~/accessibility_auditor_gb10_backend_transient.zip

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Manual test

```bash
export ACCESSIBILITY_AUDITOR_BACKEND_API_KEY="replace-with-a-random-key"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"

python -m uvicorn backend_server:app --host 0.0.0.0 --port 8091
```

Health check:

```bash
curl http://127.0.0.1:8091/health
```

Remediation test:

```bash
curl -X POST http://127.0.0.1:8091/remediate \
  -H "X-API-KEY: replace-with-a-random-key" \
  -F "pdf=@/path/to/input.pdf" \
  -F "tasks=alt_text,table_summary"
```

After the request completes, verify that no job subdirectories remain:

```bash
find /tmp/accessibility-auditor-jobs -mindepth 1 -maxdepth 1 -type d -print
```

## systemd service

```ini
[Unit]
Description=Accessibility Auditor GB10 Backend
After=network.target

[Service]
User=yorzhou
WorkingDirectory=/home/yorzhou/accessibility-auditor-backend
Environment="ACCESSIBILITY_AUDITOR_BACKEND_API_KEY=replace-with-a-random-key"
Environment="OLLAMA_BASE_URL=http://127.0.0.1:11434"
Environment="ACCESSIBILITY_AUDITOR_ENGINE_TIMEOUT_SECONDS=3600"
ExecStart=/home/yorzhou/accessibility-auditor-backend/.venv/bin/python -m uvicorn backend_server:app --host 0.0.0.0 --port 8091
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
