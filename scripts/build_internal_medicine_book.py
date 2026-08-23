#!/usr/bin/env python3
"""Build and verify a flat, source-preserving Obsidian edition of 内科学第10版."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from pypdf import PdfReader

from extract_internal_medicine_heading_boundaries import (
    EXPECTED_PAGES,
    EXPECTED_SUBHEADINGS,
    PDF_SHA256,
    extract_pdf_catalog,
    flatten_outline,
    json_text,
    validate_catalog,
)
from repair_internal_medicine_headings import (
    BODY_SUBSECTION_EXCEPTIONS,
    DUPLICATE_CHAPTER_TITLES,
    HeadingStats,
    SOURCE_BASELINES,
    SOURCE_ORDER,
    build_subheading_boundaries,
    normalized_chars,
    read_and_validate_sources,
    strip_heading,
    transform_lines,
    validate_payload,
)


BOOK_TITLE = "内科学 第10版"
BUILD_VERSION = "internal-medicine-10e-flat-chapters-v1"
HEADING_VERSION = "pdf-font-evidence-v2"
OUTPUT_NAME = "02_内科学第10版_按章节"
EXPECTED_CHAPTERS = 131
EXPECTED_APPENDICES = 11
EXPECTED_SECTIONS = 186
EXPECTED_IMAGES = 361
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?:<)?([^)>]+?)(?:>)?\)")
WIKI_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
CHAPTER_RE = re.compile(r"^第.+?章\s*(.*)$")
PART_RE = re.compile(r"^第.+?篇\s*(.*)$")
SECTION_TEXT_RE = re.compile(r"^第[一二三四五六七八九十百零〇]+节")
PRIMARY_TEXT_RE = re.compile(r"^[一二三四五六七八九十百零〇]+、")
AUTHOR_RE = re.compile(r"^[（(](?=[^）)]*[\u3400-\u9fff])[^（）()]{2,20}[）)]$")
ENUM_AUTHOR_RE = re.compile(r"^[（(][一二三四五六七八九十百零〇\d]+[）)]$")
INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


PART_SOURCE_RANGES = {
    1: (("5_内科学.md", 876), ("5_内科学.md", 959)),
    2: (("5_内科学.md", 960), ("5_内科学.md", 4864)),
    3: (("5_内科学.md", 4901), ("4_内科学.md", 4836)),
    4: (("4_内科学.md", 4865), ("3_内科学.md", 2749)),
    5: (("3_内科学.md", 2776), ("3_内科学.md", 4655)),
    6: (("3_内科学.md", 4666), ("2_内科学.md", 2042)),
    7: (("2_内科学.md", 2059), ("1_内科学.md", 944)),
    8: (("1_内科学.md", 961), ("1_内科学.md", 2544)),
    9: (("1_内科学.md", 2553), ("1_内科学.md", 4304)),
}

APPENDIX_SPECS = [
    ("01_前置页.md", "前置页", ("5_内科学.md", 1), ("5_内科学.md", 875), "front_matter"),
    ("02_第二篇_推荐阅读.md", "第二篇 推荐阅读", ("5_内科学.md", 4865), ("5_内科学.md", 4900), "recommended"),
    ("03_第三篇_推荐阅读.md", "第三篇 推荐阅读", ("4_内科学.md", 4837), ("4_内科学.md", 4864), "recommended"),
    ("04_第四篇_推荐阅读.md", "第四篇 推荐阅读", ("3_内科学.md", 2750), ("3_内科学.md", 2775), "recommended"),
    ("05_第五篇_推荐阅读.md", "第五篇 推荐阅读", ("3_内科学.md", 4656), ("3_内科学.md", 4665), "recommended"),
    ("06_第六篇_推荐阅读.md", "第六篇 推荐阅读", ("2_内科学.md", 2043), ("2_内科学.md", 2058), "recommended"),
    ("07_第七篇_推荐阅读.md", "第七篇 推荐阅读", ("1_内科学.md", 945), ("1_内科学.md", 960), "recommended"),
    ("08_第八篇_推荐阅读.md", "第八篇 推荐阅读", ("1_内科学.md", 2545), ("1_内科学.md", 2552), "recommended"),
    ("09_第九篇_推荐阅读.md", "第九篇 推荐阅读", ("1_内科学.md", 4305), ("1_内科学.md", 4320), "recommended"),
    ("10_中英文名词对照索引.md", "中英文名词对照索引", ("1_内科学.md", 4321), ("1_内科学.md", 5496), "index"),
    ("11_彩图与后置页.md", "彩图与后置页", ("1_内科学.md", 5497), ("1_内科学.md", 5601), "back_matter"),
]


@dataclass
class Part:
    number: int
    title: str
    page: int
    chapters: list["Chapter"]
    recommended_page: int | None = None


@dataclass
class Chapter:
    part_number: int
    local_number: int
    bookmark_title: str
    title: str
    page_start: int
    page_end: int = 0
    global_number: int = 0
    anchor_global: int = 0
    anchor_window: str = ""
    source_start: int = 0
    source_end: int = 0
    filename: str = ""


class Corpus:
    def __init__(self, sources: dict[str, list[str]]) -> None:
        self.sources = sources
        self.offsets: dict[str, int] = {}
        self.global_lines: list[tuple[str, int, str]] = []
        for name in SOURCE_ORDER:
            self.offsets[name] = len(self.global_lines)
            self.global_lines.extend(
                (name, number, line)
                for number, line in enumerate(sources[name], 1)
            )

        cjk: list[str] = []
        char_lines: list[int] = []
        for global_index, (_, _, line) in enumerate(self.global_lines):
            for char in line:
                if "\u3400" <= char <= "\u9fff":
                    cjk.append(char)
                    char_lines.append(global_index)
        self.cjk = "".join(cjk)
        self.cjk_line_indices = char_lines

    def loc(self, name: str, line: int) -> int:
        if name not in self.offsets or not 1 <= line <= len(self.sources[name]):
            raise RuntimeError(f"Invalid source location: {name}:{line}")
        return self.offsets[name] + line - 1

    def line_to_cjk_left(self, global_line: int) -> int:
        return bisect.bisect_left(self.cjk_line_indices, global_line)

    def line_to_cjk_right(self, global_line: int) -> int:
        return bisect.bisect_right(self.cjk_line_indices, global_line)

    def segments(self, start: int, end: int) -> list[tuple[str, int, int, list[str]]]:
        if not (0 <= start <= end < len(self.global_lines)):
            raise RuntimeError(f"Invalid global source range: {start}-{end}")
        result: list[tuple[str, int, int, list[str]]] = []
        cursor = start
        while cursor <= end:
            name, line_no, _ = self.global_lines[cursor]
            segment_start = line_no
            values: list[str] = []
            while cursor <= end and self.global_lines[cursor][0] == name:
                values.append(self.global_lines[cursor][2])
                cursor += 1
            result.append((name, segment_start, segment_start + len(values) - 1, values))
        return result

    def range_label(self, start: int, end: int) -> list[str]:
        return [f"{name}:{a}-{b}" for name, a, b, _ in self.segments(start, end)]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utf8(text: str) -> bytes:
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def safe_filename(value: str, max_length: int = 80) -> str:
    value = INVALID_FILENAME_RE.sub("_", value)
    value = re.sub(r"\s+", "", value).strip(" ._")
    value = re.sub(r"_+", "_", value)
    return value[:max_length].rstrip(" ._") or "未命名"


def chapter_topic(bookmark_title: str) -> str:
    match = CHAPTER_RE.match(bookmark_title)
    return (match.group(1) if match else bookmark_title).strip().replace(" ", "")


def part_topic(title: str) -> str:
    match = PART_RE.match(title)
    return (match.group(1) if match else title).strip().replace(" ", "")


def parse_book_structure(pdf_path: Path) -> tuple[list[Part], list[dict[str, object]]]:
    reader = PdfReader(str(pdf_path))
    if len(reader.pages) != EXPECTED_PAGES:
        raise RuntimeError("PDF page count changed")
    rows = flatten_outline(reader)
    if len(rows) != 335:
        raise RuntimeError(f"PDF bookmark count changed: {len(rows)}")

    parts: list[Part] = []
    current: Part | None = None
    structural_level1: list[tuple[int, str, int, Part]] = []
    for row in rows:
        level, page, title = int(row["level"]), int(row["page"]), str(row["title"])
        if level == 0:
            current = Part(len(parts) + 1, title, page, [])
            parts.append(current)
        elif level == 1 and current is not None:
            structural_level1.append((page, title, level, current))
            if CHAPTER_RE.match(title):
                current.chapters.append(
                    Chapter(
                        part_number=current.number,
                        local_number=len(current.chapters) + 1,
                        bookmark_title=title,
                        title=chapter_topic(title),
                        page_start=page,
                    )
                )
            elif "推荐阅读" in title:
                current.recommended_page = page

    if len(parts) != 9 or sum(len(part.chapters) for part in parts) != 130:
        raise RuntimeError(
            f"Unexpected book structure: parts={len(parts)} formal_chapters={sum(len(p.chapters) for p in parts)}"
        )

    intro = Chapter(1, 0, "绪论", "绪论", parts[0].page)
    parts[0].chapters = [intro]
    all_chapters = [chapter for part in parts for chapter in part.chapters]
    for global_number, chapter in enumerate(all_chapters, 1):
        chapter.global_number = global_number
        part = parts[chapter.part_number - 1]
        if chapter.global_number == 1:
            chapter.filename = "第001章_第一篇_绪论.md"
        else:
            chapter.filename = (
                f"第{global_number:03d}章_第{chapter.part_number}篇"
                f"第{chapter.local_number:02d}章_{safe_filename(chapter.title)}.md"
            )

    for part_index, part in enumerate(parts):
        next_part_page = parts[part_index + 1].page if part_index + 1 < len(parts) else EXPECTED_PAGES + 1
        entries: list[tuple[int, Chapter | None]] = [(c.page_start, c) for c in part.chapters]
        if part.recommended_page:
            entries.append((part.recommended_page, None))
        entries.sort(key=lambda item: item[0])
        for index, (page, chapter) in enumerate(entries):
            if chapter is None:
                continue
            following = entries[index + 1][0] if index + 1 < len(entries) else next_part_page
            chapter.page_end = following - 1
    return parts, rows


def cjk_only(text: str) -> str:
    return "".join(char for char in text if "\u3400" <= char <= "\u9fff")


def locate_chapter_anchors(
    corpus: Corpus, parts: list[Part], catalog: dict[str, object]
) -> None:
    page_texts = catalog.get("chapter_page_texts")
    if not isinstance(page_texts, dict):
        raise RuntimeError("PDF catalog lacks chapter start-page text")

    for part in parts:
        range_start = corpus.loc(*PART_SOURCE_RANGES[part.number][0])
        range_end = corpus.loc(*PART_SOURCE_RANGES[part.number][1])
        lower_char = corpus.line_to_cjk_left(range_start)
        upper_char = corpus.line_to_cjk_right(range_end)
        previous_char = lower_char
        for chapter in part.chapters:
            if chapter.global_number == 1:
                chapter.anchor_global = range_start
                chapter.anchor_window = cjk_only(corpus.global_lines[range_start][2])
                continue
            text = str(page_texts.get(str(chapter.page_start), ""))
            if not text:
                raise RuntimeError(
                    f"Missing PDF start-page text for {chapter.bookmark_title} page {chapter.page_start}"
                )
            pdf_cjk = cjk_only(text)
            topic = cjk_only(chapter.title)
            topic_at = pdf_cjk.find(topic)
            search_from = topic_at + len(topic) if topic_at >= 0 else 0
            located: tuple[int, str] | None = None
            for offset in range(search_from, max(search_from, len(pdf_cjk) - 31)):
                window = pdf_cjk[offset : offset + 32]
                if len(window) < 32:
                    break
                position = corpus.cjk.find(window, max(previous_char, lower_char), upper_char)
                if position < 0:
                    continue
                second = corpus.cjk.find(window, position + 1, upper_char)
                if second >= 0:
                    continue
                located = (position, window)
                break
            if located is None:
                raise RuntimeError(
                    f"No unique 32-CJK anchor for {chapter.bookmark_title} on PDF page {chapter.page_start}"
                )
            position, window = located
            chapter.anchor_global = corpus.cjk_line_indices[position]
            chapter.anchor_window = window
            if not range_start <= chapter.anchor_global <= range_end:
                raise RuntimeError(f"Anchor outside part range: {chapter.bookmark_title}")
            previous_char = position + 1


def is_end_marker(line: str) -> bool:
    value = strip_heading(line).strip()
    if value == "本章思维导图":
        return True
    return bool(AUTHOR_RE.fullmatch(value) and not ENUM_AUTHOR_RE.fullmatch(value))


def assign_chapter_source_ranges(corpus: Corpus, parts: list[Part]) -> None:
    for part in parts:
        part_start = corpus.loc(*PART_SOURCE_RANGES[part.number][0])
        part_end = corpus.loc(*PART_SOURCE_RANGES[part.number][1])
        chapters = part.chapters
        chapters[0].source_start = part_start
        for index, chapter in enumerate(chapters[:-1]):
            following = chapters[index + 1]
            candidates = [
                global_index
                for global_index in range(chapter.anchor_global, following.anchor_global)
                if is_end_marker(corpus.global_lines[global_index][2])
            ]
            if not candidates:
                raise RuntimeError(
                    f"No chapter-end evidence between {chapter.bookmark_title} and {following.bookmark_title}"
                )
            marker = max(candidates)
            if following.anchor_global - marker > 120:
                raise RuntimeError(
                    f"Chapter boundary gap is too large ({following.anchor_global-marker} lines): "
                    f"{chapter.bookmark_title} -> {following.bookmark_title}"
                )
            chapter.source_end = marker
            following.source_start = marker + 1
        chapters[-1].source_end = part_end

        for chapter in chapters:
            if not (
                part_start
                <= chapter.source_start
                <= chapter.anchor_global
                <= chapter.source_end
                <= part_end
            ):
                raise RuntimeError(f"Invalid chapter range: {chapter.bookmark_title}")
            marker_count = sum(
                1
                for index in range(chapter.anchor_global, chapter.source_end + 1)
                if is_end_marker(corpus.global_lines[index][2])
            )
            if marker_count == 0:
                raise RuntimeError(f"No end marker within chapter: {chapter.bookmark_title}")


def source_coverage(corpus: Corpus, parts: list[Part]) -> list[int]:
    coverage = [0] * len(corpus.global_lines)
    for chapter in (chapter for part in parts for chapter in part.chapters):
        for index in range(chapter.source_start, chapter.source_end + 1):
            coverage[index] += 1
    for _, _, start, end, _ in APPENDIX_SPECS:
        a = corpus.loc(*start)
        b = corpus.loc(*end)
        for index in range(a, b + 1):
            coverage[index] += 1
    bad = [index for index, count in enumerate(coverage) if count != 1]
    if bad:
        samples = [
            f"{corpus.global_lines[index][0]}:{corpus.global_lines[index][1]}={coverage[index]}"
            for index in bad[:20]
        ]
        raise RuntimeError(f"Source line coverage failure: {samples}")
    return coverage


def yaml_list(values: list[str], indent: int = 2) -> str:
    prefix = " " * indent
    return "\n".join(f"{prefix}- {json.dumps(value, ensure_ascii=False)}" for value in values)


def navigation_block(previous: str | None, following: str | None, *, appendix: bool = False) -> str:
    toc = "../00_章节导航" if appendix else "00_章节导航"
    items = []
    if previous:
        items.append(f"[[{previous}|上一章]]")
    items.append(f"[[{toc}|总目录]]")
    if following:
        items.append(f"[[{following}|下一章]]")
    return "> [!info] 导航\n> " + " · ".join(items)


def rewrite_image_paths(text: str, prefix: str) -> str:
    return re.sub(r"(!\[[^\]]*\]\()(<?)images/", rf"\1\2{prefix}", text)


def render_chapter(
    chapter: Chapter,
    part: Part,
    corpus: Corpus,
    boundary_map: dict[tuple[str, int], int],
    stats: HeadingStats,
    previous: str | None,
    following: str | None,
) -> tuple[str, list[str]]:
    transformed_all: list[str] = []
    source_files: list[str] = []
    for name, line_start, _, lines in corpus.segments(chapter.source_start, chapter.source_end):
        transformed = transform_lines(
            name,
            line_start,
            lines,
            structural_body=True,
            boundary_map=boundary_map,
            stats=stats,
        )
        validate_payload(name, line_start, lines, transformed)
        transformed_all.extend(transformed)
        if name not in source_files:
            source_files.append(name)

    body = rewrite_image_paths("\n".join(transformed_all), "../images/")
    ranges = corpus.range_label(chapter.source_start, chapter.source_end)
    printed = (
        f"{chapter.page_start - 31}-{chapter.page_end - 31}"
        if chapter.page_start >= 32
        else "front-matter"
    )
    frontmatter = "\n".join(
        [
            "---",
            f"title: {json.dumps(chapter.title, ensure_ascii=False)}",
            f"book: {json.dumps(BOOK_TITLE, ensure_ascii=False)}",
            f"global_chapter: {chapter.global_number}",
            f"part_number: {chapter.part_number}",
            f"part_title: {json.dumps(part.title, ensure_ascii=False)}",
            f"chapter_number_in_part: {chapter.local_number}",
            f"original_chapter_title: {json.dumps(chapter.bookmark_title, ensure_ascii=False)}",
            "source_files:",
            yaml_list(source_files),
            "source_ranges:",
            yaml_list(ranges),
            f"pdf_physical_pages: {json.dumps(f'{chapter.page_start}-{chapter.page_end}')}",
            f"printed_pages: {json.dumps(printed)}",
            f"previous: {json.dumps(previous or '', ensure_ascii=False)}",
            f"next: {json.dumps(following or '', ensure_ascii=False)}",
            'toc: "00_章节导航"',
            f"heading_rules: {json.dumps(HEADING_VERSION)}",
            "source_content_rewritten: false",
            "---",
        ]
    )
    content = f"{frontmatter}\n\n{navigation_block(previous, following)}\n\n{body.strip()}\n"
    return content, ranges


def render_appendix(
    filename: str,
    title: str,
    start: tuple[str, int],
    end: tuple[str, int],
    kind: str,
    corpus: Corpus,
    boundary_map: dict[tuple[str, int], int],
    stats: HeadingStats,
) -> tuple[str, list[str]]:
    a, b = corpus.loc(*start), corpus.loc(*end)
    transformed_all: list[str] = []
    source_files: list[str] = []
    for name, line_start, _, lines in corpus.segments(a, b):
        transformed = transform_lines(
            name,
            line_start,
            lines,
            structural_body=False,
            boundary_map=boundary_map,
            stats=stats,
        )
        validate_payload(name, line_start, lines, transformed)
        transformed_all.extend(transformed)
        if name not in source_files:
            source_files.append(name)
    body = rewrite_image_paths("\n".join(transformed_all), "../../images/")
    ranges = corpus.range_label(a, b)
    frontmatter = "\n".join(
        [
            "---",
            f"title: {json.dumps(title, ensure_ascii=False)}",
            f"book: {json.dumps(BOOK_TITLE, ensure_ascii=False)}",
            f"appendix_kind: {json.dumps(kind)}",
            "source_files:",
            yaml_list(source_files),
            "source_ranges:",
            yaml_list(ranges),
            'toc: "../00_章节导航"',
            f"heading_rules: {json.dumps(HEADING_VERSION)}",
            "source_content_rewritten: false",
            "---",
        ]
    )
    content = (
        f"{frontmatter}\n\n# {title}\n\n{navigation_block(None, None, appendix=True)}"
        f"\n\n{body.strip()}\n"
    )
    return content, ranges


def image_status(source_dir: Path) -> dict[str, int]:
    target = source_dir / "images"
    manifest_path = source_dir / OUTPUT_NAME / "00_图片恢复清单.json"
    restored = 0
    missing = EXPECTED_IMAGES
    decode_failures = 0
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            rows = manifest.get("images", [])
            if isinstance(rows, list):
                restored = sum(
                    1
                    for row in rows
                    if isinstance(row, dict)
                    and (target / str(row.get("filename", ""))).is_file()
                    and sha256_file(target / str(row["filename"])) == row.get("sha256")
                )
                missing = EXPECTED_IMAGES - restored
                decode_failures = int(manifest.get("decode_failures", 0))
        except Exception:
            restored = 0
            missing = EXPECTED_IMAGES
    return {"restored": restored, "missing": missing, "decode_failures": decode_failures}


def build_navigation(parts: list[Part]) -> str:
    lines = [
        "---",
        f"title: {json.dumps(BOOK_TITLE + '章节导航', ensure_ascii=False)}",
        f"chapter_count: {EXPECTED_CHAPTERS}",
        f"appendix_count: {EXPECTED_APPENDICES}",
        "---",
        "",
        f"# {BOOK_TITLE}章节导航",
        "",
        "> 131 个扁平章节文件；前置页、推荐阅读、索引和后置页位于 `90_附录`。",
        "",
    ]
    for part in parts:
        lines.extend([f"## {part.title}", ""])
        for chapter in part.chapters:
            label = (
                f"第{chapter.global_number:03d}章 · {chapter.title}"
                if chapter.global_number > 1
                else "第001章 · 绪论"
            )
            lines.append(f"- [[{Path(chapter.filename).stem}|{label}]]")
        lines.append("")
    lines.extend(["## 附录", ""])
    for filename, title, *_ in APPENDIX_SPECS:
        lines.append(f"- [[90_附录/{Path(filename).stem}|{title}]]")
    return "\n".join(lines).rstrip() + "\n"


def build_source_record(
    source_dir: Path,
    parts: list[Part],
    corpus: Corpus,
    image_stats: dict[str, int],
    boundary_mismatches: list[dict[str, object]],
) -> str:
    lines = [
        "# 来源与拆分记录",
        "",
        "## 原始文件基线",
        "",
        "原始 Markdown、PDF 与 MinerU 图片包均只读；脚本只写派生目录和公共图片目录。",
        "",
        "| 顺序 | 文件 | 行数 | 字节 | SHA-256 |",
        "|---:|---|---:|---:|---|",
    ]
    for order, name in enumerate(SOURCE_ORDER, 1):
        item = SOURCE_BASELINES[name]
        lines.append(
            f"| {order} | `{name}` | {item['lines']} | {item['bytes']} | `{item['sha256']}` |"
        )
    lines.extend(
        [
            f"| PDF | `内科学 第10版(1)带书签.pdf` | {EXPECTED_PAGES} 页 | 185781452 | `{PDF_SHA256}` |",
            "",
            "## 结构证据与拆分规则",
            "",
            "- PDF：9 个篇书签、130 个正式章书签；第一篇“绪论”无二级章书签，按章等价单元补入，合计 131 章。",
            "- 每个正式章以 PDF 起始页正文中的唯一 32 个连续汉字锚点定位；每个章尾再由作者署名或“本章思维导图”复核。",
            "- PDF 第 593 页的断裂书签 `第三节 | 红细胞葡萄糖` + `6磷酸脱氢酶缺乏症` 仅在结构记录中合并；来源正文保持原样。",
            "- 文件接缝：`5→4`、`3→2` 为章节转换；`4→3`、`2→1` 为同章连续段落，均按已有空行连接，不进行无换行拼接。",
            "- 章节正文只删除 4 行 PDF 已确认的重复章名；没有 `## 原始正文` 包装行。其余只改 Markdown 标题符号、换行、空白和图片相对路径。",
            "- 图片路径：根部章节 `../images/`；附录 `../../images/`。",
            "",
            "## 章节来源映射",
            "",
            "| 全书章序 | 篇 | 原章 | 文件 | 来源行 | PDF 物理页 | 印刷页 | 32字锚点 |",
            "|---:|---|---|---|---|---:|---|---|",
        ]
    )
    for part in parts:
        for chapter in part.chapters:
            printed = (
                f"{chapter.page_start-31}-{chapter.page_end-31}"
                if chapter.page_start >= 32
                else "前置页"
            )
            ranges = "<br>".join(corpus.range_label(chapter.source_start, chapter.source_end))
            lines.append(
                f"| {chapter.global_number:03d} | {part.title} | {chapter.bookmark_title} | "
                f"`{chapter.filename}` | {ranges} | {chapter.page_start}-{chapter.page_end} | "
                f"{printed} | `{chapter.anchor_window}` |"
            )
    lines.extend(
        [
            "",
            "## 标题与图片验证",
            "",
            f"- PDF 10.5pt 专用标题字体边界：{EXPECTED_SUBHEADINGS} 个；9pt 表格正文例外：{len(BODY_SUBSECTION_EXCEPTIONS)} 个。",
            f"- PDF/Markdown 标题文字存在字符表示差异但字体边界仍可一一映射：{len(boundary_mismatches)} 个。",
            f"- 图片：已恢复 {image_stats['restored']}，缺失 {image_stats['missing']}，解码失败 {image_stats['decode_failures']}。",
            "- 所有 26,233 行来源恰好归属一个章节或附录；无遗漏、无重叠。",
            "",
            "## 附录范围",
            "",
        ]
    )
    for filename, title, start, end, _ in APPENDIX_SPECS:
        lines.append(f"- `90_附录/{filename}`：{title}；`{start[0]}:{start[1]}-{end[0]}:{end[1]}`")
    return "\n".join(lines).rstrip() + "\n"


def count_headings(markdowns: dict[str, str], content_paths: set[str]) -> dict[str, int]:
    counts = {f"h{level}": 0 for level in range(1, 7)}
    for path, text in markdowns.items():
        if path not in content_paths:
            continue
        for line in text.splitlines():
            match = re.match(r"^(#{1,6})\s+", line)
            if match:
                counts[f"h{len(match.group(1))}"] += 1
    return counts


def build_heading_record(
    stats: HeadingStats,
    heading_counts: dict[str, int],
    boundary_mismatches: list[dict[str, object]],
) -> str:
    lines = [
        "# 标题层次修复记录",
        "",
        "## 规则与结果",
        "",
        "- `第×节` → H1。",
        "- `一、二、三……` → H2（仅章节正文；目录条目不机械提升）。",
        "- `（一）（二）……` → H3，标题边界由 PDF 10.5pt FZZYSK1 字体与 10pt 正文字体的切换确定。",
        "- 所有行首 `【……】` → H4；同一行正文移至下一段，字符与顺序不变。",
        "- 数字、带圈数字和字母正文编号若误带 Markdown 标题符号，恢复为普通正文。",
        "",
        f"- 删除重复章标题：{stats.duplicate_chapter_titles_removed} 行。",
        f"- 删除 `原始正文` 包装：{stats.source_body_wrappers_removed} 行。",
        f"- 第×节转 H1：{stats.section_h1} 行。",
        f"- 中文主序号转 H2：{stats.primary_h2} 行。",
        f"- PDF 确认子标题转 H3：{stats.subsection_h3} 行。",
        f"- 行首方括号标签转 H4：{stats.bracket_h4} 行。",
        f"- “（一）”类标题与正文拆行：{stats.subsection_inline_splits} 行。",
        f"- `【……】正文` 拆行：{stats.bracket_inline_splits} 行。",
        f"- 数字误标题降为正文：{stats.numeric_headings_demoted} 行。",
        "",
        "## 最终内容文件标题计数",
        "",
        f"- H1：{heading_counts['h1']}；H2：{heading_counts['h2']}；H3：{heading_counts['h3']}；H4：{heading_counts['h4']}。",
        f"- H5：{heading_counts['h5']}；H6：{heading_counts['h6']}。",
        "",
        "## PDF 例外",
        "",
        "- `4_内科学.md:4137` 与 `4_内科学.md:4145` 是感染性心内膜炎诊断标准表内的 9pt 项目，保留为正文编号，不提升为 H3。",
        "- PDF 第 593 页节书签文字断裂，按印刷正文和来源正文修复结构名称，不改来源字符。",
        f"- PDF 字体标题与 Markdown 表示不完全相同但边界可靠的项目：{len(boundary_mismatches)} 个，主要为 LaTeX 希腊字母与印刷字符的表示差异。",
        "",
        "## 正文无损证明",
        "",
        "每个来源片段在转换前后均去除 Markdown 标题符号和空白后逐字符比较。仅排除 4 行授权删除的重复章名；比较全部通过，正文字符数量、内容和顺序一致。",
        "",
        "已吸收的人工标题示例：无（执行前不存在派生章节或人工修改）。",
    ]
    return "\n".join(lines).rstrip() + "\n"


def validate_generated(
    markdowns: dict[str, str],
    content_paths: set[str],
    heading_counts: dict[str, int],
    image_stats: dict[str, int],
    *,
    final_images_required: bool,
) -> dict[str, int | bool]:
    chapter_paths = [path for path in content_paths if not path.startswith("90_附录/")]
    appendix_paths = [path for path in content_paths if path.startswith("90_附录/")]
    if len(chapter_paths) != EXPECTED_CHAPTERS or len(appendix_paths) != EXPECTED_APPENDICES:
        raise RuntimeError("Generated chapter/appendix count mismatch")

    combined = "\n".join(markdowns[path] for path in sorted(content_paths))
    duplicate_chapter_headings = len(
        re.findall(r"^#\s+第[^\n]*章", combined, flags=re.MULTILINE)
    )
    wrappers = len(re.findall(r"^##\s+原始正文\s*$", combined, flags=re.MULTILINE))
    if duplicate_chapter_headings or wrappers:
        raise RuntimeError(
            f"Wrapper headings remain: chapter={duplicate_chapter_headings} source_body={wrappers}"
        )
    if heading_counts["h5"] or heading_counts["h6"]:
        raise RuntimeError("H5/H6 headings remain")
    if heading_counts["h3"] != EXPECTED_SUBHEADINGS:
        raise RuntimeError(f"H3 count mismatch: {heading_counts['h3']}")

    bad_sections = 0
    bad_primary = 0
    bad_brackets = 0
    inline_brackets = 0
    numeric_headings = 0
    for path in content_paths:
        for line in markdowns[path].splitlines():
            stripped = strip_heading(line).strip()
            if SECTION_TEXT_RE.match(stripped) and not line.startswith("# "):
                # The front-matter table of contents is source text, not body hierarchy.
                if path != "90_附录/01_前置页.md":
                    bad_sections += 1
            if PRIMARY_TEXT_RE.match(stripped) and not line.startswith("## "):
                # Front-matter contents are intentionally not promoted.
                if path != "90_附录/01_前置页.md":
                    bad_primary += 1
            if stripped.startswith("【") and not line.startswith("#### "):
                bad_brackets += 1
            if re.match(r"^####\s+【[^】]+】\S", line):
                inline_brackets += 1
            if re.match(r"^#{1,6}\s+(?:\d+[.．、）)]|[（(]\d+[）)]|[①②③④⑤⑥⑦⑧⑨⑩]|[A-Za-z][.．、])", line):
                numeric_headings += 1
    if any([bad_sections, bad_primary, bad_brackets, inline_brackets, numeric_headings]):
        raise RuntimeError(
            "Heading verification failed: "
            f"sections={bad_sections} primary={bad_primary} brackets={bad_brackets} "
            f"inline_brackets={inline_brackets} numeric={numeric_headings}"
        )

    all_paths = set(markdowns)
    broken_links = 0
    for source_path, text in markdowns.items():
        parent = PurePosixPath(source_path).parent
        for target in WIKI_RE.findall(text):
            candidate = PurePosixPath(target.strip())
            if candidate.suffix.lower() != ".md":
                candidate = candidate.with_suffix(".md")
            resolved_parts: list[str] = []
            for part in (parent / candidate).parts:
                if part == ".":
                    continue
                if part == "..":
                    if resolved_parts:
                        resolved_parts.pop()
                    continue
                resolved_parts.append(part)
            resolved = PurePosixPath(*resolved_parts).as_posix()
            if resolved not in all_paths:
                broken_links += 1
    if broken_links:
        raise RuntimeError(f"Broken wiki links: {broken_links}")

    control_files = sum(1 for text in markdowns.values() if CONTROL_RE.search(text))
    if control_files:
        raise RuntimeError(f"Unexpected control characters in {control_files} files")

    image_refs = []
    for path in content_paths:
        image_refs.extend(IMAGE_RE.findall(markdowns[path]))
    missing_derived_images = image_stats["missing"]
    if final_images_required and (
        image_stats["restored"] != EXPECTED_IMAGES
        or missing_derived_images
        or image_stats["decode_failures"]
    ):
        raise RuntimeError(f"Final image verification failed: {image_stats}")

    return {
        "chapter_files": len(chapter_paths),
        "appendix_files": len(appendix_paths),
        "chapter_folders": 0,
        "broken_wiki_links": broken_links,
        "control_character_files": control_files,
        "derived_image_references": len(image_refs),
        "missing_derived_images": missing_derived_images,
    }


def manifest_for(
    markdowns: dict[str, str],
    chapter_meta: dict[str, dict[str, object]],
    catalog_bytes: bytes,
    image_manifest_path: Path,
    verification: dict[str, int | bool],
) -> dict[str, object]:
    rows = []
    for path in sorted(markdowns):
        data = utf8(markdowns[path])
        meta = chapter_meta.get(path, {})
        rows.append(
            {
                "relative_path": path,
                "bytes": len(data),
                "sha256": sha256_bytes(data),
                "chapter_number": meta.get("chapter_number"),
                "source_ranges": meta.get("source_ranges", []),
                "pdf_pages": meta.get("pdf_pages"),
                "heading_rules_version": HEADING_VERSION,
            }
        )
    auxiliary = [
        {
            "relative_path": "00_PDF标题边界.json",
            "bytes": len(catalog_bytes),
            "sha256": sha256_bytes(catalog_bytes),
        }
    ]
    if image_manifest_path.is_file():
        auxiliary.append(
            {
                "relative_path": "00_图片恢复清单.json",
                "bytes": image_manifest_path.stat().st_size,
                "sha256": sha256_file(image_manifest_path),
            }
        )
    return {
        "schema_version": BUILD_VERSION,
        "book": BOOK_TITLE,
        "source_order": SOURCE_ORDER,
        "source_baselines": SOURCE_BASELINES,
        "pdf_sha256": PDF_SHA256,
        "heading_rules_version": HEADING_VERSION,
        "chapter_count": EXPECTED_CHAPTERS,
        "appendix_count": EXPECTED_APPENDICES,
        "derived_markdown": rows,
        "auxiliary_files": auxiliary,
        "verification": verification,
    }


def preflight_existing(target: Path) -> dict[str, object] | None:
    if not target.exists():
        return None
    files = [path for path in target.rglob("*") if path.is_file()]
    if not files:
        return None
    manifest_path = target / "00_拆分清单.json"
    if not manifest_path.is_file():
        # A lone image manifest can be created by the independent restore script.
        allowed = {target / "00_图片恢复清单.json"}
        if set(files).issubset(allowed):
            return None
        raise RuntimeError(
            "Output directory is non-empty but has no split manifest; refusing to overwrite"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("schema_version") != BUILD_VERSION:
        raise RuntimeError("Existing split manifest version is not recognized")
    listed_md: set[str] = set()
    for row in manifest.get("derived_markdown", []):
        rel = str(row["relative_path"])
        listed_md.add(rel)
        path = target / Path(rel)
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            raise RuntimeError(f"Manual derived-file change detected: {path}")
    actual_md = {
        path.relative_to(target).as_posix() for path in target.rglob("*.md") if path.is_file()
    }
    if actual_md != listed_md:
        raise RuntimeError(
            f"Unexpected or missing derived Markdown: {sorted(actual_md ^ listed_md)}"
        )
    for row in manifest.get("auxiliary_files", []):
        path = target / Path(str(row["relative_path"]))
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            raise RuntimeError(f"Manual auxiliary-file change detected: {path}")
    return manifest


def write_expected(target: Path, expected: dict[str, bytes], *, verify_only: bool) -> int:
    if verify_only:
        missing = []
        changed = []
        for rel, data in expected.items():
            path = target / Path(rel)
            if not path.is_file():
                missing.append(rel)
            elif path.read_bytes() != data:
                changed.append(rel)
        if missing or changed:
            raise RuntimeError(f"Verify-only mismatch: missing={missing} changed={changed}")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    changed = 0
    for rel, data in expected.items():
        path = target / Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_bytes() == data:
            continue
        temporary = path.with_name(path.name + ".codex-tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        changed += 1
    return changed


def build(args: argparse.Namespace) -> int:
    workspace = Path(__file__).resolve().parent.parent
    source_dir = workspace / "999_附件文件夹"
    target = source_dir / OUTPUT_NAME
    pdf_path = source_dir / "内科学 第10版(1)带书签.pdf"
    if sha256_file(pdf_path) != PDF_SHA256:
        raise RuntimeError("Source PDF hash changed")
    sources = read_and_validate_sources(source_dir)
    preflight_existing(target)
    corpus = Corpus(sources)
    parts, _ = parse_book_structure(pdf_path)
    formal_pages = {
        chapter.page_start
        for part in parts
        for chapter in part.chapters
        if chapter.global_number > 1
    }

    catalog_path = target / "00_PDF标题边界.json"
    catalog: dict[str, object] | None = None
    if catalog_path.is_file():
        candidate = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
        validate_catalog(candidate, pdf_path)
        cached_pages = candidate.get("chapter_page_texts")
        if isinstance(cached_pages, dict) and formal_pages.issubset(
            {int(key) for key in cached_pages}
        ):
            catalog = candidate
            print("PDF_BOUNDARY_CACHE_OK", flush=True)
    if catalog is None:
        if args.verify_only:
            raise RuntimeError("Verify-only cannot rebuild a missing/incomplete PDF boundary cache")
        catalog = extract_pdf_catalog(
            pdf_path, chapter_pages=formal_pages, progress=True, strict=True
        )

    boundary_map, boundary_mismatches = build_subheading_boundaries(sources, catalog)
    locate_chapter_anchors(corpus, parts, catalog)
    assign_chapter_source_ranges(corpus, parts)
    source_coverage(corpus, parts)

    all_chapters = [chapter for part in parts for chapter in part.chapters]
    stats = HeadingStats(pdf_text_mismatches=boundary_mismatches)
    markdowns: dict[str, str] = {}
    content_paths: set[str] = set()
    chapter_meta: dict[str, dict[str, object]] = {}

    for index, chapter in enumerate(all_chapters):
        previous = Path(all_chapters[index - 1].filename).stem if index > 0 else None
        following = (
            Path(all_chapters[index + 1].filename).stem
            if index + 1 < len(all_chapters)
            else None
        )
        content, ranges = render_chapter(
            chapter,
            parts[chapter.part_number - 1],
            corpus,
            boundary_map,
            stats,
            previous,
            following,
        )
        markdowns[chapter.filename] = content
        content_paths.add(chapter.filename)
        chapter_meta[chapter.filename] = {
            "chapter_number": chapter.global_number,
            "source_ranges": ranges,
            "pdf_pages": f"{chapter.page_start}-{chapter.page_end}",
        }

    for filename, title, start, end, kind in APPENDIX_SPECS:
        content, ranges = render_appendix(
            filename, title, start, end, kind, corpus, boundary_map, stats
        )
        rel = f"90_附录/{filename}"
        markdowns[rel] = content
        content_paths.add(rel)
        chapter_meta[rel] = {
            "chapter_number": None,
            "source_ranges": ranges,
            "pdf_pages": None,
        }

    if stats.duplicate_chapter_titles_removed != len(DUPLICATE_CHAPTER_TITLES):
        raise RuntimeError("Not all confirmed duplicate chapter titles were removed")
    if stats.section_h1 != EXPECTED_SECTIONS:
        raise RuntimeError(f"Section heading count mismatch: {stats.section_h1}")
    if stats.subsection_h3 != EXPECTED_SUBHEADINGS:
        raise RuntimeError(f"PDF-backed H3 count mismatch: {stats.subsection_h3}")

    image_stats = image_status(source_dir)
    markdowns["00_章节导航.md"] = build_navigation(parts)
    markdowns["00_来源与拆分记录.md"] = build_source_record(
        source_dir, parts, corpus, image_stats, boundary_mismatches
    )
    # The heading record itself is excluded from content heading statistics.
    provisional_counts = count_headings(markdowns, content_paths)
    markdowns["00_标题层次修复记录.md"] = build_heading_record(
        stats, provisional_counts, boundary_mismatches
    )
    heading_counts = count_headings(markdowns, content_paths)
    if heading_counts != provisional_counts:
        raise RuntimeError("Heading count changed while rendering audit records")

    final_images_required = args.verify_only or image_stats["restored"] == EXPECTED_IMAGES
    verification = validate_generated(
        markdowns,
        content_paths,
        heading_counts,
        image_stats,
        final_images_required=final_images_required,
    )

    catalog_bytes = utf8(json_text(catalog))
    image_manifest_path = target / "00_图片恢复清单.json"
    manifest = manifest_for(
        markdowns, chapter_meta, catalog_bytes, image_manifest_path, verification
    )
    manifest_bytes = utf8(json_text(manifest))
    expected = {path: utf8(text) for path, text in markdowns.items()}
    expected["00_PDF标题边界.json"] = catalog_bytes
    expected["00_拆分清单.json"] = manifest_bytes
    if image_manifest_path.is_file():
        expected["00_图片恢复清单.json"] = image_manifest_path.read_bytes()

    changed = write_expected(target, expected, verify_only=args.verify_only)

    # Re-check every source after all derived writes.
    read_and_validate_sources(source_dir)
    if sha256_file(pdf_path) != PDF_SHA256:
        raise RuntimeError("Source PDF changed during execution")

    print("CHAPTER_VERIFY_OK")
    print("chapter_folders=0")
    print(f"chapter_files={verification['chapter_files']}")
    print(f"appendix_files={verification['appendix_files']}")
    print(f"broken_wiki_links={verification['broken_wiki_links']}")
    print("HEADING_VERIFY_OK")
    print("chapter_headings=0")
    print("source_body_wrappers=0")
    print(f"h1_sections_and_appendices={heading_counts['h1']}")
    print(f"h2_primary={heading_counts['h2']}")
    print(f"h3_subsections={heading_counts['h3']}")
    print(f"h4_brackets={heading_counts['h4']}")
    print("h5_h6=0")
    print("source_hashes_unchanged=true")
    print(f"changed_files={changed}")
    if args.verify_only:
        print("VERIFY_ONLY_OK")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    return build(parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
