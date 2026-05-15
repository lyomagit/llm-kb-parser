"""DOC legacy parser — convert to DOCX via LibreOffice headless, reparse.

Runtime policy:
- Locate `soffice` / `libreoffice` on PATH or in standard macOS/Linux locations.
- If missing → raise `DocConverterMissing` with actionable message; CLI turns it
  into a `failed` status (no silent degradation per spec §18).
- If present → convert to a temp dir, feed the resulting .docx through DOCXParser,
  then overwrite source/parse metadata to keep the original DOC path + format,
  add `conversion_used=True`, `conversion_info`, and a warning.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..ids import block_id, section_id, table_id
from ..model import Document, Warning
from ..runtime_tools import LIBREOFFICE, dependency_guidance_text, find_runnable_tool
from ..versioning import PACKAGE_VERSION
from .base import ParseContext, build_source_and_parse, finalize_parse
from .docx import DOCXParser


class DocConverterMissing(RuntimeError):
    pass


class DocConversionTimeout(RuntimeError):
    pass


class DocConversionFailed(RuntimeError):
    pass


class DocConversionNoOutput(RuntimeError):
    pass


@dataclass
class _ConversionResult:
    docx_path: Path
    converter: str
    converter_version: str | None


class DOCParser:
    name = "doc"
    version = PACKAGE_VERSION
    formats = ("doc",)

    def parse(self, ctx: ParseContext) -> Document:
        from .base import _iso_now  # type: ignore

        bin_path = _find_soffice()
        if bin_path is None:
            raise DocConverterMissing(
                "DOC requires LibreOffice (soffice). "
                + dependency_guidance_text()
            )

        started = _iso_now()
        src, parse, did = build_source_and_parse(
            ctx, "doc", self.name, self.version,
            started_at=started,
            confidence=0.7,
            conversion_used=True,
        )

        with tempfile.TemporaryDirectory(prefix="kbparser-doc-") as tmp:
            tmp_dir = Path(tmp)
            result = _convert_to_docx(bin_path, ctx.path, tmp_dir)
            inner_ctx = ParseContext(path=result.docx_path, profile=ctx.profile)
            inner_doc = DOCXParser().parse(inner_ctx)

        inner_doc.id = did
        inner_doc.source = src
        inner_doc.parse = finalize_parse(parse)
        inner_doc.parse.conversion_used = True
        inner_doc.parse.conversion_info = {
            "from_format": "doc",
            "to_format": "docx",
            "converter": result.converter,
            "converter_version": result.converter_version,
        }
        inner_doc.warnings = list(inner_doc.warnings) + [
            Warning(
                code="doc_conversion_lost_styles",
                message=(
                    "DOC → DOCX conversion via LibreOffice may lose "
                    "non-trivial styling, fields, or embedded objects."
                ),
            ),
        ]
        # LibreOffice embeds timestamps into the converted .docx, so its
        # sha256 drifts across runs and so do IDs derived from it. Rebuild
        # every in-document ID against the final DOC doc_id for determinism.
        _rebuild_ids(inner_doc)
        return inner_doc


# ----- LibreOffice discovery + invocation -----

def _find_soffice() -> str | None:
    found = find_runnable_tool(LIBREOFFICE)
    return str(found) if found else None


def _soffice_version(bin_path: str) -> str | None:
    try:
        out = subprocess.run(
            [bin_path, "--version"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        return (out.stdout or out.stderr or "").strip() or None
    except Exception:
        return None


def _convert_to_docx(bin_path: str, src: Path, out_dir: Path) -> _ConversionResult:
    # Isolated UserInstallation prevents concurrent-run lockfile conflicts:
    # each call gets its own LO profile directory.
    user_install = out_dir / "lo-profile"
    user_install.mkdir(exist_ok=True)
    cmd = [
        bin_path, "--headless", "--nologo", "--nofirststartwizard",
        f"-env:UserInstallation=file://{user_install}",
        "--convert-to", "docx",
        "--outdir", str(out_dir),
        str(src),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DocConversionTimeout(f"soffice conversion timed out after {int(exc.timeout)}s") from exc
    except OSError as exc:
        raise DocConversionFailed(f"soffice invocation failed: {exc}") from exc

    if res.returncode != 0:
        raise DocConversionFailed(
            f"soffice conversion failed ({res.returncode}): {(res.stderr or res.stdout or '').strip()}"
        )

    out_docx = out_dir / (src.stem + ".docx")
    if not out_docx.exists():
        raise DocConversionNoOutput(f"soffice produced no output for {src}")

    return _ConversionResult(
        docx_path=out_docx,
        converter=Path(bin_path).name,
        converter_version=_soffice_version(bin_path),
    )


def _rebuild_ids(doc: Document) -> None:
    """Regenerate all in-document IDs using doc.id as the hashing anchor.

    The inner DOCXParser built IDs against the converted .docx's doc_id.
    LibreOffice output is not byte-stable (embedded timestamps) so those IDs
    drift run-to-run. Re-derive every section/block/table ID from the DOC's
    deterministic doc.id and remap all cross-references.
    """
    new_did = doc.id

    # 1. Sections — id depends on path + order (stable inputs).
    sec_old_to_new: dict[str, str] = {}
    for order, sec in enumerate(doc.sections):
        fresh = section_id(new_did, sec.path, order)
        sec_old_to_new[sec.id] = fresh
        sec.id = fresh
    for sec in doc.sections:
        if sec.parent_id:
            sec.parent_id = sec_old_to_new.get(sec.parent_id, sec.parent_id)

    # 2. Tables first (before blocks) — table_ref blocks embed table.id into
    #    their text, which feeds block hashing. Must stabilize table IDs first.
    tbl_old_to_new: dict[str, str] = {}
    for order, t in enumerate(doc.tables):
        if t.section_id:
            t.section_id = sec_old_to_new.get(t.section_id, t.section_id)
        loc = f"section:{t.section_id or 'root'}"
        fresh = table_id(new_did, loc, order)
        tbl_old_to_new[t.id] = fresh
        t.id = fresh

    # 3. Rewrite table_ref block texts with new table IDs (matches DOCXParser
    #    convention "[table <tid>]"), so block anchors hash deterministically.
    for b in doc.blocks:
        if b.type == "table_ref" and b.text:
            for old, new in tbl_old_to_new.items():
                if old in b.text:
                    b.text = b.text.replace(old, new)
                    break

    # 4. Blocks — id depends on (doc_id, section_id, order, anchor[:40]).
    blk_old_to_new: dict[str, str] = {}
    for order, b in enumerate(doc.blocks):
        remapped_sid = sec_old_to_new.get(b.section_id, "") if b.section_id else ""
        anchor = (b.text or "")[:40]
        fresh = block_id(new_did, remapped_sid, order, anchor)
        blk_old_to_new[b.id] = fresh
        b.id = fresh
        if b.section_id:
            b.section_id = sec_old_to_new.get(b.section_id, b.section_id)

    for sec in doc.sections:
        sec.block_ids = [blk_old_to_new.get(x, x) for x in sec.block_ids]
