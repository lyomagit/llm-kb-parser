---
name: llm-kb-parser
description: Local document to rich JSON parser for LLM knowledge-base ingestion (PDF, DOCX, DOC, XLS, XLSX).
---

# llm-kb-parser

Use this skill to parse local documents into JSON format.

## Usage

To parse a file, run the following command from the skill directory or using the absolute path to the virtualenv:

```bash
/Users/username/Desktop/llm-kb-parser/venv/bin/python -m kbparser.cli parse <path-to-document> --out <output-directory> [--profile fidelity]
```

## Available arguments
- `<path>`: The path to the document you want to parse (e.g., .docx, .pdf).
- `--out <dir>`: The directory where the parsed JSON will be saved.
- `--profile fidelity`: (Optional) Use this profile if required.
