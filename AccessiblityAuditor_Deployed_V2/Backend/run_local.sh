#!/usr/bin/env sh
set -eu
python -m uvicorn backend_server:app --host 127.0.0.1 --port 8000
