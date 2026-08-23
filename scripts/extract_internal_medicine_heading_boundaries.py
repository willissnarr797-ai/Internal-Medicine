#!/usr/bin/env python3
"""Extract PDF-backed heading boundaries for 内科学 第10版.

The PDF uses a dedicated 10.5 pt FZZYSK1 font for the ``（一）`` class of
subheadings and a 10 pt FZSSK body font immediately after the title.  This
script records the font run, page and vertical position.  It never edits the
PDF or the source Markdown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterable

import pdfplumber
from pypdf import PdfReader


PDF_SHA256 = "c0bb559fa2c8448a54612f7edf751c9342df584d15ce90d0cf7e4f97bf852d78"
EXPECTED_PAGES = 982
EXPECTED_SUBHEADINGS = 1291
MARKER_RE = re.compile(r"^[（(][一二三四五六七八九十百零〇]+[）)]")
FONT_TOKEN = "FZZYSK1"
FONT_SIZE = 10.5
CACHE_VERSION = "internal-medicine-10e-pdf-font-boundary-v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flatten_outline(reader: PdfReader) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def walk(items: Iterable[object], level: int = 0) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            rows.append(
                {
                    "level": level,
                    "page": page,
                    "title": str(getattr(item, "title", item)).replace("\n", " ").strip(),
                }
            )

    walk(reader.outline)
    return rows


def is_title_word(word: dict[str, object]) -> bool:
    return FONT_TOKEN in str(word.get("fontname", "")) and abs(
        float(word.get("size", 0.0)) - FONT_SIZE
    ) < 0.12


def extract_pdf_catalog(
    pdf_path: Path,
    *,
    chapter_pages: set[int] | None = None,
    progress: bool = True,
    strict: bool = True,
) -> dict[str, object]:
    """Return a deterministic font-boundary catalog and selected page text."""

    pdf_path = pdf_path.resolve()
    actual_hash = sha256_file(pdf_path)
    if actual_hash != PDF_SHA256:
        raise RuntimeError(
            f"PDF hash changed: expected {PDF_SHA256}, actual {actual_hash}"
        )

    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    if page_count != EXPECTED_PAGES:
        raise RuntimeError(
            f"PDF page count changed: expected {EXPECTED_PAGES}, actual {page_count}"
        )
    outline = flatten_outline(reader)
    chapter_pages = chapter_pages or set()
    page_texts: dict[str, str] = {}
    boundaries: list[dict[str, object]] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=3,
                keep_blank_chars=False,
                extra_attrs=["fontname", "size"],
            )
            index = 0
            while index < len(words):
                word = words[index]
                if not is_title_word(word) or not MARKER_RE.match(str(word["text"])):
                    index += 1
                    continue

                run = [word]
                following = index + 1
                while following < len(words) and is_title_word(words[following]):
                    run.append(words[following])
                    following += 1

                text = "".join(str(item["text"]) for item in run).strip()
                if not MARKER_RE.match(text):
                    raise RuntimeError(
                        f"Malformed PDF subheading run on page {page_number}: {text!r}"
                    )
                boundaries.append(
                    {
                        "sequence": len(boundaries) + 1,
                        "page": page_number,
                        "top": round(float(run[0]["top"]), 3),
                        "x0": round(float(run[0]["x0"]), 3),
                        "x1": round(float(run[-1]["x1"]), 3),
                        "font": str(run[0]["fontname"]),
                        "size": round(float(run[0]["size"]), 3),
                        "text": text,
                    }
                )
                index = following

            if page_number in chapter_pages:
                page_texts[str(page_number)] = page.extract_text(
                    x_tolerance=2, y_tolerance=3
                ) or ""
            if progress and (
                page_number == 1
                or page_number % 100 == 0
                or page_number == page_count
            ):
                print(f"PDF_FONT_SCAN {page_number}/{page_count}", flush=True)

    if strict and len(boundaries) != EXPECTED_SUBHEADINGS:
        raise RuntimeError(
            "PDF subheading count mismatch: "
            f"expected {EXPECTED_SUBHEADINGS}, actual {len(boundaries)}"
        )

    return {
        "schema_version": CACHE_VERSION,
        "pdf": {
            "path": str(pdf_path),
            "sha256": actual_hash,
            "bytes": pdf_path.stat().st_size,
            "pages": page_count,
            "bookmarks": len(outline),
            "bookmark_levels": {
                str(level): sum(1 for row in outline if row["level"] == level)
                for level in sorted({int(row["level"]) for row in outline})
            },
        },
        "evidence": {
            "font_token": FONT_TOKEN,
            "font_size": FONT_SIZE,
            "body_font_token": "FZSSK",
            "body_font_size": 10.0,
            "method": "dedicated-font-run-boundary",
        },
        "subheading_count": len(boundaries),
        "subheadings": boundaries,
        "chapter_page_texts": page_texts,
    }


def validate_catalog(catalog: dict[str, object], pdf_path: Path) -> None:
    if catalog.get("schema_version") != CACHE_VERSION:
        raise RuntimeError("PDF boundary catalog schema mismatch")
    pdf_meta = catalog.get("pdf")
    if not isinstance(pdf_meta, dict):
        raise RuntimeError("PDF boundary catalog has no PDF metadata")
    if pdf_meta.get("sha256") != sha256_file(pdf_path):
        raise RuntimeError("PDF boundary catalog does not match the current PDF")
    if pdf_meta.get("pages") != EXPECTED_PAGES:
        raise RuntimeError("PDF boundary catalog page count mismatch")
    rows = catalog.get("subheadings")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SUBHEADINGS:
        raise RuntimeError("PDF boundary catalog subheading count mismatch")
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get("sequence") != index:
            raise RuntimeError(f"PDF boundary catalog sequence mismatch at {index}")
        if not MARKER_RE.match(str(row.get("text", ""))):
            raise RuntimeError(f"PDF boundary catalog invalid title at {index}")


def json_text(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(__file__).resolve().parent.parent
    pdf_path = (
        args.pdf.resolve()
        if args.pdf
        else workspace / "999_附件文件夹" / "内科学 第10版(1)带书签.pdf"
    )
    output = args.output.resolve() if args.output else None

    if args.verify_only:
        if output is None or not output.is_file():
            raise RuntimeError("--verify-only requires an existing --output catalog")
        catalog = json.loads(output.read_text(encoding="utf-8-sig"))
        validate_catalog(catalog, pdf_path)
        print(f"PDF_BOUNDARY_VERIFY_OK subheadings={EXPECTED_SUBHEADINGS}")
        return 0

    catalog = extract_pdf_catalog(pdf_path)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json_text(catalog), encoding="utf-8", newline="\n")
    print(
        "PDF_BOUNDARY_EXTRACT_OK "
        f"pages={EXPECTED_PAGES} subheadings={EXPECTED_SUBHEADINGS}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
