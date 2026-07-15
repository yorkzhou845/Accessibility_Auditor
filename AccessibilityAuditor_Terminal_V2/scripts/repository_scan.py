"""Lightweight pre-publication scan for common sensitive-data patterns."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".example",
    ".gitignore",
    ".csv",
    ".log",
}
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__"}

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "generic secret assignment": re.compile(
        r"(?i)\b(api[_-]?key|password|secret|token)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ),
    "bearer token": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "email address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "Windows user path": re.compile(r"[A-Za-z]:\\" + r"Users\\[^\\\s]+", re.I),
    "Unix home path": re.compile(r"/" + r"home/[^/\s]+"),
    "UNC path": re.compile(r"\\" + r"\\[^\\\s]+\\[^\s]+"),
    "non-local IPv4": re.compile(
        r"\b(?!(?:127|0)\.)(?!10\.)(?!192\.168\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)"
        r"(?:\d{1,3}\.){3}\d{1,3}\b"
    ),
}

ALLOWED_URL_PREFIXES = (
    "http://127.0.0.1",
    "http://localhost",
    "https://docs.ollama.com",
    "https://pymupdf.readthedocs.io",
    "https://requests.readthedocs.io",
    "https://github.com/psf/requests",
)
URL_PATTERN = re.compile(r"https?://[^\s)`>\"]+")


def iter_text_files(root: Path):
    scanner_path = Path(__file__).resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.resolve() == scanner_path:
            continue
        if path.name == ".gitignore" or path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def scan(root: Path, extra_terms: list[str]) -> list[str]:
    findings = []
    term_patterns = [re.compile(re.escape(term), re.I) for term in extra_terms if term]

    for path in iter_text_files(root):
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{relative}:{line_number}: {label}: {line.strip()}")
            for url in URL_PATTERN.findall(line):
                if not url.startswith(ALLOWED_URL_PREFIXES):
                    findings.append(f"{relative}:{line_number}: review URL: {url}")
            for term, pattern in zip(extra_terms, term_patterns):
                if pattern.search(line):
                    findings.append(
                        f"{relative}:{line_number}: custom term '{term}': {line.strip()}"
                    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--term",
        action="append",
        default=[],
        help="Additional workplace name, domain, username, or identifier to search for.",
    )
    args = parser.parse_args()
    findings = scan(ROOT, args.term)

    if findings:
        print("Review the following potential findings:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("No configured sensitive-data patterns were found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
