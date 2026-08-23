#!/usr/bin/env python3
"""Apply source-preserving, PDF-backed heading repairs in memory.

This module is imported by ``build_internal_medicine_book.py``.  Its CLI audits
the source-to-PDF boundary mapping and never overwrites the source Markdown.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from extract_internal_medicine_heading_boundaries import (
    EXPECTED_SUBHEADINGS,
    validate_catalog,
)


SOURCE_BASELINES = {
    "1_内科学.md": {
        "lines": 5601,
        "bytes": 661370,
        "sha256": "437ffb956e5e6b15b5c3eb26b00f7f71eba99625fb5443d8c208d1824e14d409",
    },
    "2_内科学.md": {
        "lines": 4954,
        "bytes": 777787,
        "sha256": "0460f9989fe1a6387a68282e4a0966819e0d31a2eddecaa398ee69576ce34851",
    },
    "3_内科学.md": {
        "lines": 5502,
        "bytes": 741717,
        "sha256": "5a8cafa5b9174bf477ef303be4cda114d86fa2befcbb926e12866f4a5820fbd1",
    },
    "4_内科学.md": {
        "lines": 5275,
        "bytes": 732736,
        "sha256": "effbed98d87e4dc87706cc3b8cc1ff64e01a12e5372fdeb42fa18d86c33f0ac9",
    },
    "5_内科学.md": {
        "lines": 4901,
        "bytes": 701193,
        "sha256": "5682ccaf9b8a66ca6d7f157a9218985f904110df7a090d52c04e64c124041f49",
    },
}
SOURCE_ORDER = ["5_内科学.md", "4_内科学.md", "3_内科学.md", "2_内科学.md", "1_内科学.md"]
CN = "一二三四五六七八九十百零〇"
SECTION_RE = re.compile(rf"^第[{CN}]+节(?:\s*[|｜])?")
PRIMARY_RE = re.compile(rf"^[{CN}]+、")
SUB_RE = re.compile(rf"^[（(][{CN}]+[）)]")
BRACKET_RE = re.compile(r"^(【[^】]+】)(.*)$")
HEADING_RE = re.compile(r"^\s*#{1,6}\s*")
NUMERIC_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s+(?:\d+[.．、]|\d+[）)]|[（(]\d+[）)]|[①②③④⑤⑥⑦⑧⑨⑩]|[A-Za-z][.．、])"
)
DUPLICATE_CHAPTER_TITLES = {
    ("5_内科学.md", 1128): "急性上呼吸道感染和急性气管支气管炎",
    ("4_内科学.md", 1425): "动脉粥样硬化和冠状动脉粥样硬化性心脏病",
    ("2_内科学.md", 1977): "CAR-T 细胞免疫疗法在血液病中的应用",
    ("2_内科学.md", 4885): "水、电解质代谢和酸碱平衡失常",
}
BODY_SUBSECTION_EXCEPTIONS = {
    ("4_内科学.md", 4137): "感染性心内膜炎诊断标准表格中的9pt项目",
    ("4_内科学.md", 4145): "感染性心内膜炎诊断标准表格中的9pt项目",
}
LATEX_GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "lambda": "λ",
    "mu": "μ",
    "omega": "ω",
}
LATEX_GREEK_RE = re.compile(
    r"\$\s*\\(" + "|".join(LATEX_GREEK) + r")\s*\$", re.IGNORECASE
)


@dataclass
class HeadingStats:
    duplicate_chapter_titles_removed: int = 0
    source_body_wrappers_removed: int = 0
    section_h1: int = 0
    primary_h2: int = 0
    subsection_h3: int = 0
    bracket_h4: int = 0
    subsection_inline_splits: int = 0
    bracket_inline_splits: int = 0
    numeric_headings_demoted: int = 0
    pdf_text_mismatches: list[dict[str, object]] = field(default_factory=list)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_and_validate_sources(source_dir: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, expected in SOURCE_BASELINES.items():
        path = source_dir / name
        if not path.is_file():
            raise RuntimeError(f"Missing source Markdown: {path}")
        actual_hash = sha256_file(path)
        actual_bytes = path.stat().st_size
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        if (
            actual_hash != expected["sha256"]
            or actual_bytes != expected["bytes"]
            or len(lines) != expected["lines"]
        ):
            raise RuntimeError(
                f"Source baseline changed: {name}; "
                f"lines={len(lines)} bytes={actual_bytes} sha256={actual_hash}"
            )
        result[name] = lines
    return result


def strip_heading(line: str) -> str:
    return HEADING_RE.sub("", line, count=1)


def normalized_chars(text: str) -> str:
    value = LATEX_GREEK_RE.sub(
        lambda match: LATEX_GREEK[match.group(1).lower()], text
    )
    value = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in value if not ch.isspace())


def normalized_chars_with_boundaries(text: str) -> tuple[str, list[int]]:
    """Normalize text while retaining the source end offset of each character."""

    output: list[str] = []
    boundaries: list[int] = []
    cursor = 0
    for match in LATEX_GREEK_RE.finditer(text):
        for offset, char in enumerate(text[cursor : match.start()], cursor + 1):
            normalized = unicodedata.normalize("NFKC", char)
            for item in normalized:
                if not item.isspace():
                    output.append(item)
                    boundaries.append(offset)
        output.append(LATEX_GREEK[match.group(1).lower()])
        boundaries.append(match.end())
        cursor = match.end()
    for offset, char in enumerate(text[cursor:], cursor + 1):
        normalized = unicodedata.normalize("NFKC", char)
        for item in normalized:
            if not item.isspace():
                output.append(item)
                boundaries.append(offset)
    return "".join(output), boundaries


def title_boundary(source_text: str, pdf_text: str) -> tuple[int, float, str, str]:
    """Map a PDF font-run length to a source character boundary."""

    pdf_norm = normalized_chars(pdf_text)
    source_all, source_boundaries = normalized_chars_with_boundaries(source_text)
    source_norm = source_all[: len(pdf_norm)]
    if len(source_norm) != len(pdf_norm) or not source_boundaries:
        raise RuntimeError(
            f"Unable to map PDF title length: pdf={pdf_text!r}, source={source_text!r}"
        )
    boundary = source_boundaries[len(pdf_norm) - 1]
    similarity = difflib.SequenceMatcher(None, pdf_norm, source_norm).ratio()
    if similarity < 0.72:
        raise RuntimeError(
            "PDF/source title text diverges too far for a reliable font boundary: "
            f"pdf={pdf_text!r}, source_prefix={source_text[:boundary]!r}, score={similarity:.3f}"
        )
    return boundary, similarity, pdf_norm, source_norm


def build_subheading_boundaries(
    sources: dict[str, list[str]], catalog: dict[str, object]
) -> tuple[dict[tuple[str, int], int], list[dict[str, object]]]:
    rows: list[tuple[str, int, str]] = []
    for name in SOURCE_ORDER:
        for number, line in enumerate(sources[name], 1):
            content = strip_heading(line).strip()
            if SUB_RE.match(content) and (name, number) not in BODY_SUBSECTION_EXCEPTIONS:
                rows.append((name, number, content))

    pdf_rows = catalog.get("subheadings")
    if not isinstance(pdf_rows, list):
        raise RuntimeError("PDF catalog has no subheading list")
    if len(rows) != EXPECTED_SUBHEADINGS or len(pdf_rows) != EXPECTED_SUBHEADINGS:
        raise RuntimeError(
            "Source/PDF subheading count mismatch: "
            f"source={len(rows)} pdf={len(pdf_rows)} expected={EXPECTED_SUBHEADINGS}"
        )

    mapping: dict[tuple[str, int], int] = {}
    mismatches: list[dict[str, object]] = []
    for source, pdf_row in zip(rows, pdf_rows, strict=True):
        name, number, content = source
        pdf_text = str(pdf_row.get("text", ""))
        boundary, similarity, pdf_norm, source_norm = title_boundary(content, pdf_text)
        mapping[(name, number)] = boundary
        if pdf_norm != source_norm:
            mismatches.append(
                {
                    "source": f"{name}:{number}",
                    "pdf_page": pdf_row.get("page"),
                    "pdf_text": pdf_text,
                    "source_title": content[:boundary],
                    "similarity": round(similarity, 4),
                }
            )
    return mapping, mismatches


def payload(text: str) -> str:
    result: list[str] = []
    for line in text.splitlines():
        result.append(strip_heading(line))
    return normalized_chars("\n".join(result))


def transform_lines(
    name: str,
    start_line: int,
    lines: list[str],
    *,
    structural_body: bool,
    boundary_map: dict[tuple[str, int], int],
    stats: HeadingStats,
) -> list[str]:
    output: list[str] = []
    for offset, original in enumerate(lines):
        line_number = start_line + offset
        key = (name, line_number)
        stripped = strip_heading(original).strip()

        if key in DUPLICATE_CHAPTER_TITLES:
            expected = normalized_chars(DUPLICATE_CHAPTER_TITLES[key])
            if normalized_chars(stripped) != expected:
                raise RuntimeError(f"Duplicate chapter title changed at {name}:{line_number}")
            stats.duplicate_chapter_titles_removed += 1
            continue
        if stripped == "原始正文" and HEADING_RE.match(original):
            stats.source_body_wrappers_removed += 1
            continue
        if NUMERIC_HEADING_RE.match(original):
            output.append(strip_heading(original))
            stats.numeric_headings_demoted += 1
            continue
        if structural_body and SECTION_RE.match(stripped):
            output.append(f"# {stripped}")
            stats.section_h1 += 1
            continue
        if structural_body and PRIMARY_RE.match(stripped):
            output.append(f"## {stripped}")
            stats.primary_h2 += 1
            continue
        if key in boundary_map:
            boundary = boundary_map[key]
            title = stripped[:boundary].rstrip()
            remainder = stripped[boundary:].lstrip()
            output.append(f"### {title}")
            stats.subsection_h3 += 1
            if remainder:
                output.extend(["", remainder])
                stats.subsection_inline_splits += 1
            continue
        bracket = BRACKET_RE.match(stripped)
        if bracket:
            label, remainder = bracket.groups()
            output.append(f"#### {label}")
            stats.bracket_h4 += 1
            remainder = remainder.lstrip()
            if remainder:
                output.extend(["", remainder])
                stats.bracket_inline_splits += 1
            continue
        output.append(original)
    return output


def validate_payload(
    name: str,
    start_line: int,
    original: list[str],
    transformed: list[str],
) -> None:
    retained: list[str] = []
    for offset, line in enumerate(original):
        key = (name, start_line + offset)
        stripped = strip_heading(line).strip()
        if key in DUPLICATE_CHAPTER_TITLES:
            continue
        if stripped == "原始正文" and HEADING_RE.match(line):
            continue
        retained.append(line)
    before = payload("\n".join(retained))
    after = payload("\n".join(transformed))
    if before != after:
        matcher = difflib.SequenceMatcher(None, before, after)
        first = next((item for item in matcher.get_opcodes() if item[0] != "equal"), None)
        raise RuntimeError(
            f"Payload mismatch in {name}:{start_line}; first_difference={first}"
        )


def audit_all_sources(
    source_dir: Path, catalog_path: Path
) -> tuple[HeadingStats, dict[tuple[str, int], int]]:
    sources = read_and_validate_sources(source_dir)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    pdf_path = source_dir / "内科学 第10版(1)带书签.pdf"
    validate_catalog(catalog, pdf_path)
    boundaries, mismatches = build_subheading_boundaries(sources, catalog)
    stats = HeadingStats(pdf_text_mismatches=mismatches)
    for name in SOURCE_ORDER:
        transformed = transform_lines(
            name,
            1,
            sources[name],
            structural_body=True,
            boundary_map=boundaries,
            stats=stats,
        )
        validate_payload(name, 1, sources[name], transformed)
    return stats, boundaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(__file__).resolve().parent.parent
    source_dir = args.source_dir.resolve() if args.source_dir else workspace / "999_附件文件夹"
    catalog = (
        args.catalog.resolve()
        if args.catalog
        else source_dir / "02_内科学第10版_按章节" / "00_PDF标题边界.json"
    )
    stats, boundaries = audit_all_sources(source_dir, catalog)
    print(
        json.dumps(
            {
                "subheading_boundaries": len(boundaries),
                "pdf_text_mismatches": len(stats.pdf_text_mismatches),
                "payload_verified": True,
                "source_files_unchanged": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("HEADING_BOUNDARY_VERIFY_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
