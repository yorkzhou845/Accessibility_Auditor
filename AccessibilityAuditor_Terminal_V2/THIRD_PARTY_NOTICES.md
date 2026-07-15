# Third-Party Notices and Licensing Review

This file is informational and is not legal advice. Review the exact versions and license files installed in your environment before distribution or deployment.

## PyMuPDF / MuPDF

- Used for PDF parsing, rendering, image extraction, and table detection.
- The official PyMuPDF documentation states that PyMuPDF and MuPDF are available under the GNU AGPL and commercial license agreements.
- Official licensing page: https://pymupdf.readthedocs.io/en/latest/about.html
- Material concern: publishing or deploying an application that uses PyMuPDF may create AGPL obligations unless a commercial license applies. Evaluate this before using the project in a proprietary or hosted product.

## Requests

- Used for local HTTP calls to Ollama.
- Distributed under Apache License 2.0.
- Official project: https://github.com/psf/requests
- License information: https://requests.readthedocs.io/en/latest/api/

## Ollama

- Ollama is installed separately and is not bundled in this repository.
- The application calls the local Ollama REST API.
- Official API documentation: https://docs.ollama.com/api/introduction
- Chat endpoint: https://docs.ollama.com/api/chat
- Embedding endpoint: https://docs.ollama.com/api/embed
- Review the license for the Ollama distribution you install and the separate license or acceptable-use terms for every model you download.

## Models

Model weights are not included. Model terms vary by publisher and model. Do not assume that a model's availability through Ollama grants unrestricted commercial or redistribution rights.

## Original project code and assets

This sanitized package does not assert ownership over any workplace-owned source code, document, logo, template, prompt, dataset, or generated output. No project-level license has been added because the right to sublicense the retained source should be confirmed first.
