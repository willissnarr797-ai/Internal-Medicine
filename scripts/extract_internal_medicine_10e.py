#!/usr/bin/env python3
"""Split the bookmarked Chinese textbook PDF into an Obsidian source package.

The source PDF is never modified.  The generated package follows the layout of
the existing Cecil Essentials package: numbered part folders, per-part README
files, one Markdown file per chapter, maps, a source index, and a JSON
inventory.  PDF page markers remain in the Markdown so every extraction can be
traced back to the source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import pdfplumber
from pypdf import PdfReader


BUILD_DATE = "2026-07-24"
PACKAGE_NAME = "02_内科学第10版_2026-07-24"
BOOK_TITLE = "内科学 第10版"
SOURCE_TYPE = "中文医学教材"

CHAPTER_RE = re.compile(r"^第.+章")
PART_PREFIX_RE = re.compile(r"^第.+篇\s*")
CHAPTER_PREFIX_RE = re.compile(r"^第.+章\s*")
INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FOOTER_ARTIFACT_RE = re.compile(
    r"(iinndddd|IINNDDDD|22002244|2024//|篇篇\.\.|௉|྘|໓ଌ)",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"[ \t\u00a0\u3000]+")
NORMALIZE_TITLE_RE = re.compile(r"[\s|｜、，。:：·\-_/（）()\[\]【】]+")
CJK_WRAP_SPACE_RE = re.compile(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])")

CN_NUM = "一二三四五六七八九十百零〇"
PRIMARY_HEADING_RE = re.compile(rf"^[{CN_NUM}]+、\s*")
PAREN_HEADING_RE = re.compile(rf"^[（(][{CN_NUM}]+[）)]\s*")
NUMBERED_ITEM_RE = re.compile(r"^\d+[.．、]\s*")
BRACKET_HEADING_RE = re.compile(r"^【[^】]{1,40}】")
FIGURE_TABLE_RE = re.compile(r"^(图|表)\s*\d")


@dataclass
class Bookmark:
    level: int
    page: int
    title: str


@dataclass
class Entry:
    title: str
    page_start: int
    page_end: int = 0
    kind: str = "chapter"
    sections: list[Bookmark] = field(default_factory=list)
    global_chapter: int | None = None
    filename: str = ""
    output_relpath: str = ""
    extracted_pages: list[int] = field(default_factory=list)
    char_count: int = 0
    title_match: bool = False


@dataclass
class Part:
    number: int
    title: str
    bookmark_page: int
    dirname: str
    entries: list[Entry] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        type=Path,
        help="Source PDF. Defaults to the largest PDF in the workspace root.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        help=f"Output package. Defaults to 999_附件文件夹/{PACKAGE_NAME}.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Generate the package. Without this flag, only print the bookmark map.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate an existing generated package without re-extracting the PDF.",
    )
    return parser.parse_args()


def find_source_pdf(workspace: Path, requested: Path | None) -> Path:
    if requested:
        pdf = requested if requested.is_absolute() else workspace / requested
        pdf = pdf.resolve()
    else:
        candidates = list(workspace.glob("*.pdf"))
        if not candidates:
            raise FileNotFoundError("No PDF was found in the workspace root.")
        pdf = max(candidates, key=lambda item: item.stat().st_size).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    return pdf


def flatten_outline(reader: PdfReader) -> list[Bookmark]:
    rows: list[Bookmark] = []

    def walk(items: Iterable[object], level: int = 0) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            title = str(getattr(item, "title", item)).replace("\n", " ").strip()
            rows.append(Bookmark(level=level, page=page, title=title))

    walk(reader.outline)
    return rows


def filename_safe(text: str, max_length: int = 92) -> str:
    value = INVALID_FILENAME_RE.sub("_", text)
    value = WHITESPACE_RE.sub(" ", value).strip(" ._")
    value = CJK_WRAP_SPACE_RE.sub("", value)
    value = value.replace("，", "_").replace(",", "_")
    value = re.sub(r"_+", "_", value)
    return value[:max_length].rstrip(" ._") or "未命名"


def topic_from_part(title: str) -> str:
    return PART_PREFIX_RE.sub("", title).strip()


def topic_from_chapter(title: str) -> str:
    topic = CHAPTER_PREFIX_RE.sub("", title).strip() or title.strip()
    return CJK_WRAP_SPACE_RE.sub("", topic)


def display_chapter_title(title: str) -> str:
    match = re.match(r"^(第.+?章)\s*(.*)$", title)
    if not match:
        return CJK_WRAP_SPACE_RE.sub("", title)
    prefix, topic = match.groups()
    topic = CJK_WRAP_SPACE_RE.sub("", topic.strip())
    return f"{prefix} {topic}".rstrip()


def build_parts(
    bookmarks: list[Bookmark], page_count: int
) -> tuple[list[Part], list[dict[str, object]]]:
    part_marks = [row for row in bookmarks if row.level == 0]
    parts: list[Part] = []
    current_part: Part | None = None
    current_entry: Entry | None = None

    for row in bookmarks:
        if row.level == 0:
            part_number = len(parts) + 1
            current_part = Part(
                number=part_number,
                title=row.title,
                bookmark_page=row.page,
                dirname=f"{part_number:02d}_{filename_safe(topic_from_part(row.title))}",
            )
            parts.append(current_part)
            current_entry = None
        elif row.level == 1 and current_part is not None:
            display_title = (
                display_chapter_title(row.title)
                if CHAPTER_RE.match(row.title)
                else row.title
            )
            if CHAPTER_RE.match(display_title):
                kind = "chapter"
            elif "推荐阅读" in display_title:
                kind = "recommended_reading"
            elif "索引" in display_title:
                kind = "index"
            else:
                kind = "supplement"
            current_entry = Entry(title=display_title, page_start=row.page, kind=kind)
            current_part.entries.append(current_entry)
        elif row.level >= 2 and current_entry is not None:
            current_entry.sections.append(row)

    # The first part (绪论) has no level-1 chapter bookmark.  Treat its prose as
    # a chapter-equivalent so the package remains complete and navigable.
    if parts and not parts[0].entries:
        next_part_page = parts[1].bookmark_page if len(parts) > 1 else page_count + 1
        parts[0].entries.append(
            Entry(
                title=topic_from_part(parts[0].title),
                page_start=parts[0].bookmark_page,
                page_end=next_part_page - 1,
                kind="part_introduction",
            )
        )

    # The source PDF has one known broken bookmark on page 593.  Keep the raw
    # bookmark map unchanged, but repair the derived chapter outline using the
    # visually verified heading on that page.
    for part in parts:
        for entry in part.entries:
            if entry.title != "第六章 溶血性贫血":
                continue
            repaired_sections: list[Bookmark] = []
            index = 0
            while index < len(entry.sections):
                current = entry.sections[index]
                following = (
                    entry.sections[index + 1]
                    if index + 1 < len(entry.sections)
                    else None
                )
                if (
                    current.page == 593
                    and current.title == "6磷酸脱氢酶缺乏症"
                    and following is not None
                    and following.page == 593
                    and following.title.startswith("第三节")
                ):
                    repaired_sections.append(
                        Bookmark(
                            level=2,
                            page=593,
                            title="第三节 | 红细胞葡萄糖-6-磷酸脱氢酶缺乏症",
                        )
                    )
                    index += 2
                    continue
                repaired_sections.append(current)
                index += 1
            entry.sections = repaired_sections

    global_chapter = 0
    for part_index, part in enumerate(parts):
        next_part_page = (
            parts[part_index + 1].bookmark_page
            if part_index + 1 < len(parts)
            else page_count + 1
        )
        for entry_index, entry in enumerate(part.entries):
            if not entry.page_end:
                entry.page_end = (
                    part.entries[entry_index + 1].page_start - 1
                    if entry_index + 1 < len(part.entries)
                    else next_part_page - 1
                )
            if entry.kind in {"chapter", "part_introduction"}:
                global_chapter += 1
                entry.global_chapter = global_chapter
                entry.filename = (
                    f"第{global_chapter:03d}章_"
                    f"{filename_safe(topic_from_chapter(entry.title))}.md"
                )
            elif entry.kind == "recommended_reading":
                entry.filename = "900_推荐阅读.md"
            elif entry.kind == "index":
                entry.filename = "901_中英文名词对照索引.md"
            else:
                entry.filename = f"910_{filename_safe(entry.title)}.md"
            entry.output_relpath = f"{part.dirname}/{entry.filename}"

    front_groups = [
        {
            "filename": "001_版权、编者与教材说明.md",
            "title": "版权、编者与教材说明",
            "page_start": 1,
            "page_end": 5,
        },
        {
            "filename": "002_序言与第十轮教材修订说明.md",
            "title": "序言与第十轮教材修订说明",
            "page_start": 6,
            "page_end": 9,
        },
        {
            "filename": "003_主审、主编与副主编简介.md",
            "title": "主审、主编与副主编简介",
            "page_start": 10,
            "page_end": 14,
        },
        {
            "filename": "004_前言.md",
            "title": "前言",
            "page_start": 15,
            "page_end": 17,
        },
        {
            "filename": "005_目录.md",
            "title": "目录",
            "page_start": 18,
            "page_end": 31,
        },
    ]
    return parts, front_groups


def normalize_title(text: str) -> str:
    return NORMALIZE_TITLE_RE.sub("", text).lower()


def page_looks_like_part_title(text: str, part_title: str) -> bool:
    normalized = normalize_title(text)
    target = normalize_title(part_title)
    return bool(target and target in normalized and len(normalized) < len(target) + 50)


def clean_page_text(text: str, physical_page: int) -> str:
    text = text.replace("\x00", "").replace("\r", "\n")
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    cleaned: list[str] = []
    printed_page = physical_page - 31 if physical_page >= 32 else None

    for index, line in enumerate(lines):
        if not line:
            continue
        if FOOTER_ARTIFACT_RE.search(line):
            continue
        near_edge = index < 3 or index >= max(0, len(lines) - 3)
        if near_edge and line.isdigit():
            number = int(line)
            if number == physical_page or number == physical_page - 1:
                continue
            if printed_page is not None and number == printed_page:
                continue
        cleaned.append(line)

    return markdownize_lines(cleaned)


def markdownize_lines(lines: list[str]) -> str:
    """Add conservative headings while preserving the extracted reading order."""
    output: list[str] = []
    for line in lines:
        normalized = line.strip()
        if not normalized:
            continue
        if CHAPTER_RE.match(normalized):
            output.extend(["", f"# {normalized}", ""])
        elif re.match(r"^第.+节(?:\s*[|｜])?", normalized):
            output.extend(["", f"## {normalized}", ""])
        elif PRIMARY_HEADING_RE.match(normalized):
            output.extend(["", f"## {normalized}", ""])
        elif PAREN_HEADING_RE.match(normalized):
            output.extend(["", f"### {normalized}", ""])
        elif normalized in {"推荐阅读", "中英文名词对照索引"}:
            output.extend(["", f"## {normalized}", ""])
        elif BRACKET_HEADING_RE.match(normalized):
            output.extend(["", f"### {normalized}", ""])
        elif FIGURE_TABLE_RE.match(normalized):
            output.extend(["", normalized, ""])
        elif NUMBERED_ITEM_RE.match(normalized):
            output.extend(["", normalized])
        else:
            output.append(normalized)

    # Single line breaks keep the PDF reading order without pretending that
    # tables or figure captions were reconstructed perfectly.
    result = "\n".join(output)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def extract_pages(pdf_path: Path) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        for index, page in enumerate(pdf.pages, 1):
            raw = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            pages.append(clean_page_text(raw, index))
            if index == 1 or index % 25 == 0 or index == total:
                print(f"EXTRACTED {index}/{total}", flush=True)
    return pages


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def page_marker(page: int) -> str:
    if page >= 32:
        return f"<!-- source_pdf_page: {page}; printed_page: {page - 31} -->"
    return f"<!-- source_pdf_page: {page}; front_matter_page -->"


def render_page_range(
    page_texts: list[str],
    start: int,
    end: int,
    *,
    skip_part_title: str | None = None,
) -> tuple[str, list[int]]:
    blocks: list[str] = []
    included: list[int] = []
    for page_number in range(start, end + 1):
        text = page_texts[page_number - 1]
        if skip_part_title and page_looks_like_part_title(text, skip_part_title):
            continue
        included.append(page_number)
        if text:
            blocks.append(f"{page_marker(page_number)}\n\n{text}")
        else:
            blocks.append(
                f"{page_marker(page_number)}\n\n"
                "> [!warning] 本页未提取到文本；图像或版式内容请查看原 PDF。"
            )
    return "\n\n".join(blocks).strip(), included


def chapter_markdown(
    part: Part,
    entry: Entry,
    body: str,
    pdf_name: str,
    pdf_sha256: str,
) -> str:
    page_start = min(entry.extracted_pages) if entry.extracted_pages else entry.page_start
    page_end = max(entry.extracted_pages) if entry.extracted_pages else entry.page_end
    section_rows = []
    for section in entry.sections:
        section_rows.append(
            f"- {section.title.replace('|', '｜')}（PDF 第 {section.page} 页，"
            f"教材页 {section.page - 31}）"
        )
    if not section_rows:
        section_rows = ["- 本章无下级书签；请结合正文标题复习。"]

    recall_rows = []
    for section in entry.sections:
        clean_title = section.title.replace("|", "｜")
        recall_rows.append(
            f"- [ ] 复述“{clean_title}”：定义、机制、临床表现、诊断与治疗要点各是什么？"
        )
    if not recall_rows:
        recall_rows = [
            "- [ ] 用自己的话复述本章主线：定义/病因 -> 机制 -> 临床表现 -> 诊断/鉴别 -> 治疗/预后。"
        ]

    title = entry.title
    global_number = entry.global_chapter or 0
    return (
        "---\n"
        "type: source_chapter\n"
        "status: extracted\n"
        f"chapter_global: {global_number}\n"
        f"title: {yaml_quote(title)}\n"
        f"part: {yaml_quote(part.title)}\n"
        f"source: {yaml_quote(BOOK_TITLE)}\n"
        f"source_type: {yaml_quote(SOURCE_TYPE)}\n"
        f"source_pdf: {yaml_quote(pdf_name)}\n"
        f"source_pdf_sha256: {pdf_sha256}\n"
        f"pdf_page_start: {page_start}\n"
        f"pdf_page_end: {page_end}\n"
        f"created: {BUILD_DATE}\n"
        f"updated: {BUILD_DATE}\n"
        "tags:\n"
        "  - 内科学\n"
        "  - 第10版\n"
        "  - 来源章节\n"
        "---\n\n"
        f"# {title}\n\n"
        "> [!note] 来源与复习定位\n"
        f"> - 所属：{part.title}\n"
        f"> - 原书：[[{pdf_name}]]\n"
        f"> - 页码：PDF 第 {page_start}-{page_end} 页"
        f"（教材页 {page_start - 31}-{page_end - 31}）\n"
        "> - 提取方式：PDF 文本层自动提取；图像、复杂表格、公式和跨栏版式必须回看原 PDF。\n"
        "> - 临床提示：教材出版后可能有指南更新，剂量、禁忌证和决策阈值应用当前可靠来源复核。\n\n"
        "## 章节提纲（依据 PDF 书签）\n\n"
        + "\n".join(section_rows)
        + "\n\n## 主动回忆卡\n\n"
        + "\n".join(recall_rows)
        + "\n\n## 易混点与数字\n\n"
        "- [ ] 汇总本章阈值、分期、剂量和时间窗，并标明教材页码。\n"
        "- [ ] 对照相近疾病，整理诊断线索、鉴别要点和治疗边界。\n"
        "- [ ] 涉及动态临床建议时，用当前指南复核后再转入正式笔记。\n\n"
        "## 正文\n\n"
        + body
        + "\n"
    )


def supplementary_markdown(
    part: Part,
    entry: Entry,
    body: str,
    pdf_name: str,
    pdf_sha256: str,
) -> str:
    page_start = min(entry.extracted_pages) if entry.extracted_pages else entry.page_start
    page_end = max(entry.extracted_pages) if entry.extracted_pages else entry.page_end
    return (
        "---\n"
        f"type: {entry.kind}\n"
        "status: extracted\n"
        f"title: {yaml_quote(entry.title)}\n"
        f"part: {yaml_quote(part.title)}\n"
        f"source: {yaml_quote(BOOK_TITLE)}\n"
        f"source_pdf: {yaml_quote(pdf_name)}\n"
        f"source_pdf_sha256: {pdf_sha256}\n"
        f"pdf_page_start: {page_start}\n"
        f"pdf_page_end: {page_end}\n"
        f"created: {BUILD_DATE}\n"
        f"updated: {BUILD_DATE}\n"
        "---\n\n"
        f"# {entry.title}\n\n"
        f"> 来源：[[{pdf_name}]]，PDF 第 {page_start}-{page_end} 页。"
        "文本由 PDF 文本层自动提取，复杂版式请回看原 PDF。\n\n"
        + body
        + "\n"
    )


def front_note_markdown(
    group: dict[str, object],
    body: str,
    pdf_name: str,
    pdf_sha256: str,
) -> str:
    title = str(group["title"])
    start = int(group["page_start"])
    end = int(group["page_end"])
    return (
        "---\n"
        "type: source_front_matter\n"
        "status: extracted\n"
        f"title: {yaml_quote(title)}\n"
        f"source: {yaml_quote(BOOK_TITLE)}\n"
        f"source_pdf: {yaml_quote(pdf_name)}\n"
        f"source_pdf_sha256: {pdf_sha256}\n"
        f"pdf_page_start: {start}\n"
        f"pdf_page_end: {end}\n"
        f"created: {BUILD_DATE}\n"
        f"updated: {BUILD_DATE}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"> 来源：[[{pdf_name}]]，PDF 第 {start}-{end} 页。"
        "文本由 PDF 文本层自动提取，复杂版式请回看原 PDF。\n\n"
        + body
        + "\n"
    )


def local_wikilink(target_relpath: str, label: str) -> str:
    target = target_relpath[:-3] if target_relpath.endswith(".md") else target_relpath
    return f"[[{target}|{label}]]"


def vault_wikilink(package_rel: str, target_relpath: str, label: str) -> str:
    target = target_relpath[:-3] if target_relpath.endswith(".md") else target_relpath
    return f"[[{package_rel}/{target}|{label}]]"


def build_readme(part: Part) -> str:
    chapter_entries = [
        entry for entry in part.entries if entry.kind in {"chapter", "part_introduction"}
    ]
    other_entries = [
        entry for entry in part.entries if entry.kind not in {"chapter", "part_introduction"}
    ]
    rows = []
    for entry in chapter_entries:
        label = (
            f"{entry.title}（全书序号 {entry.global_chapter:03d}）"
            if entry.global_chapter is not None
            else entry.title
        )
        rows.append(f"- {local_wikilink(entry.filename, label)}")
    if other_entries:
        rows.append("\n## 篇末资料")
        for entry in other_entries:
            rows.append(f"- {local_wikilink(entry.filename, entry.title)}")
    return (
        f"# {part.title}\n\n"
        f"> PDF 篇章书签页：第 {part.bookmark_page} 页。"
        "章节文件按全书顺序统一编号，正文标题保留原书篇内章号。\n\n"
        "## 章节\n\n"
        + "\n".join(rows)
        + "\n\n## 本篇复习建议\n\n"
        "- 先按 README 顺序通读，再依据每章书签小节做主动回忆。\n"
        "- 数字、分期、药物剂量、禁忌证和治疗时间窗需回看原 PDF 并结合当前指南复核。\n"
        "- 自动提取内容用于检索与学习导航；图像、复杂表格和公式以原 PDF 为准。\n"
    )


def build_front_readme(front_groups: list[dict[str, object]]) -> str:
    rows = []
    for group in front_groups:
        rows.append(
            f"- {local_wikilink(str(group['filename']), str(group['title']))}"
            f"（PDF 第 {group['page_start']}-{group['page_end']} 页）"
        )
    return (
        "# 前置资料\n\n"
        "> 收录书名、版权、编者、序言、前言与原书目录。"
        "正文学习请从 `01_绪论` 开始。\n\n"
        "## 文件\n\n"
        + "\n".join(rows)
        + "\n"
    )


def build_full_toc(parts: list[Part], package_rel: str) -> str:
    chapter_count = sum(
        1
        for part in parts
        for entry in part.entries
        if entry.kind in {"chapter", "part_introduction"}
    )
    rows = [
        f"# {BOOK_TITLE} 全书总目录",
        "",
        "> 按 PDF 书签和实际页码生成；全书序号仅用于确保 Obsidian 文件名唯一。",
        "",
        "## 总览",
        "",
        f"- 篇：{len(parts)}",
        f"- 章节文件：{chapter_count}",
        f"- PDF 书签：335",
        "",
        "## 篇与章节",
        "",
    ]
    for part in parts:
        rows.extend(
            [
                f"### {part.dirname}",
                "",
                f"- {vault_wikilink(package_rel, f'{part.dirname}/README.md', part.title + '目录')}",
            ]
        )
        for entry in part.entries:
            label = entry.title
            if entry.global_chapter is not None:
                label += f"（全书序号 {entry.global_chapter:03d}）"
            rows.append(
                f"- {vault_wikilink(package_rel, entry.output_relpath, label)}"
            )
        rows.append("")
    return "\n".join(rows).rstrip() + "\n"


def build_outline_map(parts: list[Part], package_rel: str) -> str:
    rows = [
        "# 内科学第10版大纲",
        "",
        f"- {vault_wikilink(package_rel, '00_地图/内科学第10版_全书_总目录.md', '全书总目录')}",
        f"- {vault_wikilink(package_rel, '00_前置资料/README.md', '前置资料')}",
    ]
    for part in parts:
        rows.append(
            f"- {vault_wikilink(package_rel, f'{part.dirname}/README.md', part.title)}"
        )
    return "\n".join(rows) + "\n"


def build_review_map(parts: list[Part], package_rel: str) -> str:
    rows = [
        "# 内科学第10版复习",
        "",
        "## 使用顺序",
        "",
        "- 先看 `00_地图/大纲.md` 和各篇 README，确认篇章顺序。",
        "- 每章先用书签提纲闭卷复述，再核对正文；复杂图表回看 PDF。",
        "- 诊疗阈值、药物剂量、禁忌证和指南时效性不以本次自动提取作为最终依据。",
        "",
        "## 篇入口",
        "",
    ]
    for part in parts:
        rows.append(
            f"- {vault_wikilink(package_rel, f'{part.dirname}/README.md', part.title)}"
        )
    return "\n".join(rows) + "\n"


def build_bookmark_map(bookmarks: list[Bookmark]) -> str:
    rows = [
        "# PDF 书签与页码映射",
        "",
        "> 页码均为 PDF 物理页码；正文教材页通常为 PDF 页码减 31。",
        "",
        "| 层级 | PDF页 | 教材页 | 书签 |",
        "|---:|---:|---:|---|",
    ]
    for row in bookmarks:
        printed = str(row.page - 31) if row.page >= 32 else "前置"
        title = row.title.replace("|", "｜")
        rows.append(f"| {row.level} | {row.page} | {printed} | {title} |")
    return "\n".join(rows) + "\n"


def build_source_index(
    pdf_path: Path,
    pdf_sha256: str,
    page_count: int,
    bookmark_count: int,
    parts: list[Part],
    output_file_count: int,
    extracted_page_count: int,
    unassigned_pages: list[int],
    no_text_pages: list[int],
) -> str:
    chapter_count = sum(
        1
        for part in parts
        for entry in part.entries
        if entry.kind in {"chapter", "part_introduction"}
    )
    rows = [
        "---",
        "type: source_index",
        "status: extracted",
        f"source: {yaml_quote(BOOK_TITLE)}",
        f"source_type: {yaml_quote(SOURCE_TYPE)}",
        f"created: {BUILD_DATE}",
        f"updated: {BUILD_DATE}",
        "---",
        "",
        f"# {BOOK_TITLE}来源索引",
        "",
        "## 归档范围",
        "",
        f"- 原始 PDF：[[{pdf_path.name}]]",
        f"- PDF 页数：{page_count}",
        f"- PDF 书签：{bookmark_count}",
        f"- SHA-256：`{pdf_sha256}`",
        f"- 篇：{len(parts)}",
        f"- 章节文件：{chapter_count}",
        f"- 来源包文件：{output_file_count}",
        f"- 有正文页码标记：{extracted_page_count}",
        f"- 未并入正文的篇标题页：{', '.join(map(str, unassigned_pages))}",
        f"- 无可提取文本页：{', '.join(map(str, no_text_pages))}",
        "",
        "## 使用原则",
        "",
        "- 原始 PDF 保持不改动；本目录只保存由文本层派生的可检索 Markdown、导航与机器清单。",
        "- 每页保留隐藏的 PDF 物理页码标记，便于回到原书核对。",
        "- 自动提取不保证图像、复杂表格、公式、跨栏和脚注的完整版式；这些内容必须查看原 PDF。",
        "- 涉及药物剂量、禁忌证、指南阈值和临床决策时，应使用当前可靠来源复核。",
        "",
        "## 篇章概览",
        "",
        "| 篇 | 章节文件 | PDF书签页 |",
        "|---|---:|---:|",
    ]
    for part in parts:
        count = sum(
            1
            for entry in part.entries
            if entry.kind in {"chapter", "part_introduction"}
        )
        rows.append(f"| {part.title} | {count} | {part.bookmark_page} |")
    rows.extend(
        [
            "",
            "## 质量提示",
            "",
            "- 原 PDF 的第六篇第六章在 PDF 第 593 页存在书签文字断裂；原始书签映射保留原状，派生章节提纲已按页面标题合并修复。",
            "- 未并入正文的页面仅为篇标题页；各篇 README 已保留篇名与篇书签页。",
            "- 图片型页面或无文本层页面会显示警告提示，不会伪造内容。",
            "- 机器清单：[[internal_medicine_10e_inventory.json|internal_medicine_10e_inventory.json]]",
        ]
    )
    return "\n".join(rows) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def verify_package(target: Path) -> tuple[bool, list[str], dict[str, int]]:
    issues: list[str] = []
    inventory_path = target / "internal_medicine_10e_inventory.json"
    if not inventory_path.is_file():
        return False, ["Missing internal_medicine_10e_inventory.json"], {}
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected_files = [str(item["path"]) for item in inventory.get("files", [])]
    for relative in expected_files:
        if not (target / relative).is_file():
            issues.append(f"Missing file: {relative}")

    markdown_files = list(target.rglob("*.md"))
    for md_file in markdown_files:
        text = md_file.read_text(encoding="utf-8")
        if "\ufffd" in text:
            issues.append(f"Replacement character: {md_file.relative_to(target)}")
        if md_file.name != "README.md" and md_file.parent.name != "00_地图":
            if not text.startswith("---\n"):
                issues.append(f"YAML does not start on line 1: {md_file.relative_to(target)}")

    expected_chapters = int(inventory.get("chapter_file_count", 0))
    actual_chapters = len(list(target.glob("[0-9][0-9]_*/*章_*.md")))
    if actual_chapters != expected_chapters:
        issues.append(
            f"Chapter count mismatch: expected {expected_chapters}, got {actual_chapters}"
        )

    link_pattern = re.compile(r"\[\[([^|\]#]+)")
    missing_links: set[str] = set()
    for md_file in markdown_files:
        text = md_file.read_text(encoding="utf-8")
        for raw_target in link_pattern.findall(text):
            link_target = raw_target.strip()
            if link_target.endswith(".pdf"):
                continue
            first_component = link_target.replace("\\", "/").split("/", 1)[0]
            if first_component == target.name:
                candidate = target.parent / link_target
            elif link_target.startswith("999_附件文件夹/"):
                candidate = target.parent.parent / link_target
            else:
                candidate = md_file.parent / link_target
            if candidate.suffix:
                possibilities = [candidate]
            else:
                possibilities = [
                    candidate.with_suffix(".md"),
                    candidate / "README.md",
                    candidate.with_suffix(".json"),
                ]
            exists = any(item.is_file() for item in possibilities)
            if not exists and "/" not in link_target and "\\" not in link_target:
                # Obsidian also resolves unique basename links across the vault.
                basename = Path(link_target).name
                global_possibilities = [
                    *target.rglob(f"{basename}.md"),
                    *target.rglob(f"{basename}.json"),
                ]
                if Path(basename).suffix:
                    global_possibilities.extend(target.rglob(basename))
                exists = any(item.is_file() for item in global_possibilities)
            if not exists:
                missing_links.add(f"{md_file.relative_to(target)} -> {link_target}")
    for missing in sorted(missing_links):
        issues.append(f"Missing wikilink: {missing}")

    stats = {
        "markdown_files": len(markdown_files),
        "chapter_files": actual_chapters,
        "expected_files": len(expected_files),
        "issues": len(issues),
    }
    return not issues, issues, stats


def generate(
    workspace: Path,
    pdf_path: Path,
    target: Path,
    reader: PdfReader,
    bookmarks: list[Bookmark],
    parts: list[Part],
    front_groups: list[dict[str, object]],
) -> None:
    if target.exists() and not target.is_dir():
        raise RuntimeError(f"Target exists and is not a directory: {target}")

    print("Computing source SHA-256...", flush=True)
    pdf_sha256 = sha256_file(pdf_path)
    print(f"SHA256 {pdf_sha256}", flush=True)
    page_texts = extract_pages(pdf_path)
    no_text_pages = [
        page_number
        for page_number, page_text in enumerate(page_texts, 1)
        if not page_text.strip()
    ]

    package_rel = target.relative_to(workspace).as_posix()
    generated: dict[str, str] = {}

    # Front matter.
    generated["00_前置资料/README.md"] = build_front_readme(front_groups)
    for group in front_groups:
        body, _ = render_page_range(
            page_texts,
            int(group["page_start"]),
            int(group["page_end"]),
        )
        generated[f"00_前置资料/{group['filename']}"] = front_note_markdown(
            group, body, pdf_path.name, pdf_sha256
        )

    # Parts and chapter-equivalent entries.
    for part_index, part in enumerate(parts):
        generated[f"{part.dirname}/README.md"] = build_readme(part)
        next_part_title = (
            parts[part_index + 1].title if part_index + 1 < len(parts) else None
        )
        for entry in part.entries:
            skip_title = (
                next_part_title if entry.kind == "part_introduction" else None
            )
            body, included_pages = render_page_range(
                page_texts,
                entry.page_start,
                entry.page_end,
                skip_part_title=skip_title,
            )
            entry.extracted_pages = included_pages
            entry.char_count = len(body)
            entry.title_match = (
                normalize_title(entry.title)
                in normalize_title(page_texts[entry.page_start - 1])[:500]
            )
            if entry.kind in {"chapter", "part_introduction"}:
                rendered = chapter_markdown(
                    part, entry, body, pdf_path.name, pdf_sha256
                )
            else:
                rendered = supplementary_markdown(
                    part, entry, body, pdf_path.name, pdf_sha256
                )
            generated[entry.output_relpath] = rendered

    # Maps.
    generated["00_地图/内科学第10版_全书_总目录.md"] = build_full_toc(
        parts, package_rel
    )
    generated["00_地图/大纲.md"] = build_outline_map(parts, package_rel)
    generated["00_地图/复习.md"] = build_review_map(parts, package_rel)
    generated["00_地图/PDF书签与页码映射.md"] = build_bookmark_map(bookmarks)

    # Source index is counted after the rest of the generated content.
    source_index_name = "000_内科学第10版来源索引.md"
    projected_count = len(generated) + 2  # source index + inventory
    covered_pages = set(range(1, 32))
    for part in parts:
        for entry in part.entries:
            covered_pages.update(entry.extracted_pages)
    unassigned_pages = [
        page_number
        for page_number in range(1, len(reader.pages) + 1)
        if page_number not in covered_pages
    ]
    generated[source_index_name] = build_source_index(
        pdf_path,
        pdf_sha256,
        len(reader.pages),
        len(bookmarks),
        parts,
        projected_count,
        len(covered_pages),
        unassigned_pages,
        no_text_pages,
    )

    for relative, content in sorted(generated.items()):
        write_text(target / relative, content)

    file_records = []
    for relative in sorted(generated):
        output_path = target / relative
        file_records.append(
            {
                "path": relative,
                "bytes": output_path.stat().st_size,
                "sha256": sha256_file(output_path),
            }
        )

    entry_records = []
    for part in parts:
        for entry in part.entries:
            entry_records.append(
                {
                    "part": part.title,
                    "kind": entry.kind,
                    "title": entry.title,
                    "global_chapter": entry.global_chapter,
                    "path": entry.output_relpath,
                    "pdf_page_start": (
                        min(entry.extracted_pages)
                        if entry.extracted_pages
                        else entry.page_start
                    ),
                    "pdf_page_end": (
                        max(entry.extracted_pages)
                        if entry.extracted_pages
                        else entry.page_end
                    ),
                    "extracted_pages": entry.extracted_pages,
                    "section_bookmarks": [
                        {"title": item.title, "pdf_page": item.page}
                        for item in entry.sections
                    ],
                    "char_count": entry.char_count,
                    "title_match_on_start_page": entry.title_match,
                }
            )

    inventory = {
        "source_title": BOOK_TITLE,
        "source_pdf": str(pdf_path),
        "source_pdf_filename": pdf_path.name,
        "source_pdf_sha256": pdf_sha256,
        "source_pdf_bytes": pdf_path.stat().st_size,
        "pdf_pages": len(reader.pages),
        "pdf_bookmarks": len(bookmarks),
        "pdf_bookmark_levels": {
            str(level): sum(1 for item in bookmarks if item.level == level)
            for level in sorted({item.level for item in bookmarks})
        },
        "target_root": str(target),
        "assessed_at": BUILD_DATE,
        "part_count": len(parts),
        "chapter_file_count": sum(
            1
            for part in parts
            for entry in part.entries
            if entry.kind in {"chapter", "part_introduction"}
        ),
        "front_matter_file_count": len(front_groups),
        "supplement_file_count": sum(
            1
            for part in parts
            for entry in part.entries
            if entry.kind not in {"chapter", "part_introduction"}
        ),
        "parts": [
            {
                "number": part.number,
                "title": part.title,
                "dirname": part.dirname,
                "bookmark_page": part.bookmark_page,
                "entry_count": len(part.entries),
            }
            for part in parts
        ],
        "entries": entry_records,
        "extracted_page_marker_count": len(covered_pages),
        "unassigned_title_pages": unassigned_pages,
        "no_text_layer_pages": no_text_pages,
        "files": file_records
        + [
            {
                "path": "internal_medicine_10e_inventory.json",
                "bytes": None,
                "sha256": None,
            }
        ],
        "extraction": {
            "engine": "pdfplumber",
            "method": "PDF text layer",
            "page_markers_preserved": True,
            "complex_layout_requires_pdf_review": True,
        },
    }
    write_text(
        target / "internal_medicine_10e_inventory.json",
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
    )
    print(f"WROTE {len(inventory['files'])} files to {target}", flush=True)


def print_dry_run(
    pdf_path: Path,
    reader: PdfReader,
    bookmarks: list[Bookmark],
    parts: list[Part],
    target: Path,
) -> None:
    print(f"PDF: {pdf_path}")
    print(f"TARGET: {target}")
    print(f"PAGES: {len(reader.pages)}")
    print(f"BOOKMARKS: {len(bookmarks)}")
    print(
        "BOOKMARK_LEVELS:",
        {
            level: sum(1 for item in bookmarks if item.level == level)
            for level in sorted({item.level for item in bookmarks})
        },
    )
    chapter_count = 0
    for part in parts:
        chapters = [
            entry
            for entry in part.entries
            if entry.kind in {"chapter", "part_introduction"}
        ]
        chapter_count += len(chapters)
        print(
            f"{part.dirname}: {part.title} | chapters={len(chapters)} "
            f"| entries={len(part.entries)} | bookmark_page={part.bookmark_page}"
        )
        for entry in part.entries:
            print(
                f"  {entry.kind:20s} {entry.page_start:03d}-{entry.page_end:03d} "
                f"{entry.filename} <- {entry.title}"
            )
    print(f"CHAPTER_FILES: {chapter_count}")


def main() -> int:
    args = parse_args()
    workspace = Path.cwd().resolve()
    pdf_path = find_source_pdf(workspace, args.pdf)
    target = (
        args.target.resolve()
        if args.target
        else (workspace / "999_附件文件夹" / PACKAGE_NAME).resolve()
    )

    if args.verify_only:
        ok, issues, stats = verify_package(target)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        for issue in issues:
            print(f"ISSUE {issue}")
        print("VERIFY_OK" if ok else "VERIFY_FAILED")
        return 0 if ok else 1

    reader = PdfReader(str(pdf_path))
    bookmarks = flatten_outline(reader)
    parts, front_groups = build_parts(bookmarks, len(reader.pages))
    print_dry_run(pdf_path, reader, bookmarks, parts, target)

    if not args.write:
        return 0

    generate(
        workspace,
        pdf_path,
        target,
        reader,
        bookmarks,
        parts,
        front_groups,
    )
    ok, issues, stats = verify_package(target)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    for issue in issues:
        print(f"ISSUE {issue}")
    print("VERIFY_OK" if ok else "VERIFY_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
