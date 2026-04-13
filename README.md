# llm-kb-parser

Local document → rich JSON parser for LLM knowledge-base ingestion.

Formats (v1): PDF, DOCX, DOC, XLS, XLSX.

Status: **Phase 1 — skeleton + canonical contract.** Parsers are stubs.

See `2026-04-13-llm-kb-document-parser-design.md` for full spec.

## Run

```
venv/bin/python -m kbparser.cli parse <path> --out <dir> [--profile fidelity]
venv/bin/pytest
```

The project is registered on `sys.path` via `site-packages/kbparser.pth`, so
`python -m kbparser.cli` works from any cwd.

### macOS gotcha — hidden-flag .pth files (Python 3.14+)

The virtualenv is deliberately named `venv/` (no leading dot). macOS
auto-flags dotfile directories as `hidden`, and Python 3.14 skips `.pth`
files inside hidden directories, which would break the editable install.
If you recreate the venv, keep the `venv/` name. If something else forces
a hidden flag onto it, clear with `chflags -R nohidden venv`.

## Layout

- `kbparser/model.py` — canonical pydantic schema
- `kbparser/ids.py` — deterministic IDs
- `kbparser/dispatcher.py` — format detection → parser choice
- `kbparser/parsers/` — per-format extractors (stubs in phase 1)
- `kbparser/normalize/` — build canonical document
- `kbparser/records/` — chunker + record export
- `kbparser/validation/` — structural validation
- `kbparser/cli.py` — entrypoint
- `tests/` — unit + fixture tests
