#!/usr/bin/env python3
"""Add source-grounded memorization editions to all internal-medicine chapters.

The diagnosis-vault convention is preserved: the extracted textbook text stays
in place, while a replaceable ``|背诵版`` block is appended to the same note.
The block is generated only from the note's own source text.  It does not add
clinical claims from outside the supplied textbook.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


BUILD_DATE = "2026-07-24"
METHOD = "source-grounded-structuring-v1"
PACKAGE_PREFIX = "02_"
PACKAGE_TOKEN = "10"
START_MARKER = "<!-- memorization:start -->"
END_MARKER = "<!-- memorization:end -->"
SUPPORT_START = "<!-- memorization-support:start -->"
SUPPORT_END = "<!-- memorization-support:end -->"
MEMORY_INDEX_NAME = "背诵版索引.md"
MANIFEST_NAME = "internal_medicine_memorization_manifest.json"

PAGE_MARKER_RE = re.compile(r"<!--\s*source_pdf_page:\s*(\d+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BRACKET_LABEL_RE = re.compile(r"^【([^】]+)】\s*(.*)$")
PAREN_HEADING_RE = re.compile(
    r"^([（(][一二三四五六七八九十百]+[）)])\s*(.*)$"
)
CHAPTER_TITLE_RE = re.compile(r"^第.+章")
PART_TITLE_RE = re.compile(r"^第.+篇")
WHITESPACE_RE = re.compile(r"[ \t\u00a0\u3000]+")
CJK_WRAP_SPACE_RE = re.compile(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])")
NORMALIZE_RE = re.compile(r"[\s|｜、，。:：·\-_/（）()\[\]【】]+")
NUMBER_ITEM_RE = re.compile(
    r"^(?:\d+[.．、]|[（(][一二三四五六七八九十百]+[）)]|[①②③④⑤⑥⑦⑧⑨⑩])"
)
NUMBER_TOKEN_RE = re.compile(
    r"(?:"
    r"[<>≤≥=]\s*\d|"
    r"\d+(?:\.\d+)?\s*(?:%|％|mmHg|kPa|mmol/L|mol/L|mg|g|kg|μg|"
    r"mL|ml|L|cm|mm|m²|次/分|次|天|小时|分钟|周|月|年|岁|℃)|"
    r"\d+\s*[～~—-]\s*\d+"
    r")",
    re.IGNORECASE,
)
REFERENCE_NOISE_RE = re.compile(
    r"(?:doi:|et\s+al\.|vol\.|edition|publisher|press\b)",
    re.IGNORECASE,
)
FACT_NOISE_RE = re.compile(
    r"^(?:表\s*\d|图\s*\d|text复制|\[object Object\])",
    re.IGNORECASE,
)
NEW_BLOCK_RE = re.compile(
    r"^(?:"
    r"\d+[.．、]|"
    r"[（(][一二三四五六七八九十百]+[）)]|"
    r"[①②③④⑤⑥⑦⑧⑨⑩]|"
    r"[一二三四五六七八九十百]+、|"
    r"第.+[篇章节]|"
    r"[-*+]\s|>|```|"
    r"(?:表|图)\s*\d"
    r")"
)
HEADING_TERM_RE = re.compile(
    r"(?:"
    r"病史|症状|体征|病因|因素|危险因素|发病机制|病理|病理生理|"
    r"分类|分类法|分型|分期|分级|表现|检查|检测|分析|评估|评价|"
    r"标准|原则|程序|方法|依据|诊断|鉴别|鉴别诊断|治疗|处理|方案|"
    r"预防|预后|并发症|药物|试验|活检|管理|教育|目的|梗阻|"
    r"概念|概述|休克|高压|急症|障碍|部位|"
    r"手术治疗|介入治疗|放射治疗|实验室和辅助检查|术"
    r")$"
)
HEADING_BODY_JOIN_RE = re.compile(
    r"^(.{1,40}?(?:"
    r"病史|症状|体征|病因|因素|危险因素|发病机制|病理|病理生理|"
    r"分类|分型|分期|分级|分类法|表现|心电图特征|检查|检测|"
    r"分析|评估|评价|标准|原则|程序|方法|依据|诊断|鉴别|鉴别诊断|"
    r"治疗|处理|方案|预防|预后|并发症|目的|梗阻|型"
    r"))"
    r"(是|为|指|系|根据|目前|主要|通常|包括|可见|早期|起病|"
    r"缓慢|促进|发生|当|对于|由于|绝大多数)"
    r"(.{8,})$"
)

CANONICAL_LABELS = [
    ("定义与分类", ("定义", "概述", "分类", "分型")),
    ("流行病学", ("流行病学",)),
    ("病因", ("病因", "危险因素", "病原体")),
    ("发病机制与病理", ("发病机制", "病理生理", "病理", "机制")),
    ("临床表现", ("临床表现", "症状", "体征")),
    (
        "检查",
        (
            "实验室检查",
            "辅助检查",
            "影像学检查",
            "特殊检查",
            "心电图",
        ),
    ),
    ("诊断与鉴别", ("诊断", "鉴别诊断", "病情评估", "严重程度")),
    ("治疗", ("治疗", "处理", "防治", "急救")),
    ("并发症", ("并发症",)),
    ("预后与预防", ("预后", "预防", "随访", "管理")),
]

FACT_KEYWORD_WEIGHTS = {
    "最常见": 7,
    "首选": 7,
    "禁忌": 6,
    "诊断标准": 6,
    "特征性": 6,
    "典型": 5,
    "主要": 4,
    "包括": 4,
    "分为": 4,
    "表现为": 4,
    "提示": 4,
    "诊断": 3,
    "鉴别": 3,
    "治疗": 3,
    "应": 2,
    "需": 2,
    "预后": 2,
    "并发": 2,
}


@dataclass
class Segment:
    title: str
    level: int
    parent: str
    page: int
    order: int
    raw_lines: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)


@dataclass
class ChapterResult:
    path: Path
    relative_path: str
    title: str
    part: str
    page_start: int
    page_end: int
    source_body_chars: int
    source_base_sha256: str
    initial_extraction_sha256: str | None
    block: str
    block_sha256: str
    segment_count: int
    selected_segment_count: int
    fact_count: int
    numeric_fact_count: int
    mode: str = "generated"
    anchor: str = ""
    current_file_sha256: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Internal-medicine package root.")
    parser.add_argument("--write", action="store_true", help="Update all selected notes.")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate the existing memorization blocks and manifest.",
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        help="Write only generated memorization blocks to this directory.",
    )
    parser.add_argument(
        "--match",
        action="append",
        default=[],
        help="Only process filenames containing this substring; repeatable.",
    )
    parser.add_argument("--max-files", type=int, help="Limit selected files.")
    return parser.parse_args()


def find_root(workspace: Path, requested: Path | None) -> Path:
    if requested:
        root = requested if requested.is_absolute() else workspace / requested
        root = root.resolve()
    else:
        candidates = [
            path
            for path in workspace.iterdir()
            if path.is_dir()
            and path.name.startswith(PACKAGE_PREFIX)
            and PACKAGE_TOKEN in path.name
            and (path / "internal_medicine_10e_inventory.json").is_file()
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"Expected one internal-medicine package, found {len(candidates)}."
            )
        root = candidates[0].resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root


def chapter_files(root: Path) -> list[Path]:
    return sorted(root.glob("[0-9][0-9]_*/*章_*.md"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def yaml_value(text: str, key: str, default: str = "") -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    if not match:
        return default
    value = match.group(1).strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value.strip('"')
    return value


def yaml_int(text: str, key: str, default: int = 0) -> int:
    value = yaml_value(text, key, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def normalize(text: str) -> str:
    return NORMALIZE_RE.sub("", text).lower()


def clean_heading(text: str) -> str:
    value = WHITESPACE_RE.sub(" ", text).strip()
    value = CJK_WRAP_SPACE_RE.sub("", value)
    value = value.replace(" | ", " ｜ ").replace("|", "｜")
    return value


def split_spaced_title_body(rest: str) -> tuple[str, str] | None:
    for match in re.finditer(r"\s+", rest):
        label = rest[: match.start()].strip()
        inline = rest[match.end() :].strip()
        if label and inline.startswith(label) and len(normalize(label)) <= 45:
            return label, inline

    candidates: list[tuple[int, int, str, str]] = []
    for match in re.finditer(r"\s+", rest):
        left = rest[: match.start()].strip()
        right = rest[match.end() :].strip()
        left_length = len(normalize(left))
        if (
            not left
            or not right
            or left_length > 80
            or len(normalize(right)) < 10
            or any(mark in left for mark in ("。", "！", "？", "；"))
        ):
            continue
        score = 0
        if any(mark in right for mark in ("，", "。", "；", "：", "！", "？")):
            score += 4
        if 2 <= left_length <= 45:
            score += 2
        if HEADING_TERM_RE.search(left):
            score += 6
        if left.endswith(("）", ")", "】")):
            score += 6
        if re.match(
            r"^(?:是|为|指|系|根据|目前|主要|通常|包括|发生|当|对于|"
            r"由于|绝大多数|本病|病人|患者|有|在|经|由|即|\d)",
            right,
        ):
            score += 4
        if score >= 6:
            candidates.append((score, left_length, left, right))
    if candidates:
        _, _, label, inline = max(candidates, key=lambda item: (item[0], -item[1]))
        return label, inline
    return None


def split_heading_inline(heading: str) -> tuple[str, str]:
    """Separate an extracted heading label from body text on the same line."""

    spaced = WHITESPACE_RE.sub(" ", heading).strip()
    label_match = BRACKET_LABEL_RE.match(spaced)
    if label_match:
        return clean_heading(label_match.group(1)), label_match.group(2).strip()

    paren_match = PAREN_HEADING_RE.match(spaced)
    if not paren_match:
        numbered_inline = re.match(
            r"^((?:第.+步|[一二三四五六七八九十]+、).+?)\s+"
            r"([（(]\d+[）)].+)$",
            spaced,
        )
        if numbered_inline:
            return (
                clean_heading(numbered_inline.group(1)),
                numbered_inline.group(2).strip(),
            )
        if re.match(r"^第.+步", spaced):
            split = split_spaced_title_body(spaced)
            if split:
                return clean_heading(split[0]), split[1]
        return clean_heading(spaced), ""
    prefix, rest = paren_match.groups()
    rest = rest.strip()
    if "：" in rest:
        label, inline = rest.split("：", 1)
        if (
            len(normalize(label)) <= 40
            and len(normalize(inline)) >= 8
            and not any(mark in label for mark in ("。", "！", "？", "；"))
        ):
            return clean_heading(f"{prefix} {label}"), inline.strip()

    split = split_spaced_title_body(rest)
    if split:
        return clean_heading(f"{prefix} {split[0]}"), split[1]

    for length in range(2, min(40, len(rest) // 2) + 1):
        label = rest[:length]
        if rest[length:].startswith(label):
            return clean_heading(f"{prefix} {label}"), rest[length:]

    joined_match = HEADING_BODY_JOIN_RE.match(rest)
    if joined_match:
        label, starter, inline = joined_match.groups()
        return clean_heading(f"{prefix} {label}"), f"{starter}{inline}"
    return clean_heading(f"{prefix} {rest}"), ""


def strip_existing_block(text: str) -> str:
    if START_MARKER not in text:
        return text.rstrip() + "\n"
    before, rest = text.split(START_MARKER, 1)
    if END_MARKER not in rest:
        raise ValueError("Memorization start marker exists without end marker.")
    _, after = rest.split(END_MARKER, 1)
    return (before.rstrip() + "\n" + after.lstrip("\n")).rstrip() + "\n"


def strip_memorization_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return text
    try:
        end = lines.index("---", 1)
    except ValueError:
        return text
    header = [
        line
        for line in lines[1:end]
        if not line.startswith("memorization_status:")
        and not line.startswith("memorization_updated:")
        and not line.startswith("memorization_method:")
    ]
    return "\n".join(["---", *header, "---", *lines[end + 1 :]]) + (
        "\n" if text.endswith("\n") else ""
    )


def add_memorization_frontmatter(text: str) -> str:
    base = strip_memorization_frontmatter(text)
    lines = base.splitlines()
    if not lines or lines[0] != "---":
        return base
    try:
        end = lines.index("---", 1)
    except ValueError:
        return base
    additions = [
        "memorization_status: generated",
        f"memorization_updated: {BUILD_DATE}",
        f"memorization_method: {METHOD}",
    ]
    return "\n".join([*lines[:end], *additions, *lines[end:]]) + "\n"


def source_body(text: str) -> str:
    clean = strip_existing_block(text)
    marker = "## 正文"
    if marker not in clean:
        raise ValueError("Missing '## 正文' marker.")
    return clean.split(marker, 1)[1].strip()


def is_curated_body(body: str) -> bool:
    signatures = (
        "## 一、全章总框架",
        "# 全章高频鉴别表",
        "# 全章数字速记",
        "# 主动回忆题",
        "# 终极背诵串联",
    )
    return sum(signature in body for signature in signatures) >= 3


def is_chapter_heading(heading: str, chapter_title: str) -> bool:
    if not CHAPTER_TITLE_RE.match(heading):
        return False
    left = normalize(heading)
    right = normalize(chapter_title)
    return bool(left == right or left in right or right in left)


def join_wrapped_lines(lines: Iterable[str]) -> str:
    values = [WHITESPACE_RE.sub(" ", line).strip() for line in lines if line.strip()]
    if not values:
        return ""
    result = values[0]
    for value in values[1:]:
        if not result:
            result = value
            continue
        left = result[-1]
        right = value[0]
        if (
            "\u3400" <= left <= "\u9fff"
            and "\u3400" <= right <= "\u9fff"
        ) or left in "，。；：、（）【】":
            separator = ""
        elif left == "-":
            separator = ""
        else:
            separator = " "
        result += separator + value
    return result.strip()


def should_merge_paragraph(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left.endswith(("。", "！", "？", "；", "：", ".", "!", "?", ";", ":")):
        return False
    wrapped_section_sentence = bool(re.match(r"^第.+[篇章节][。；，]", right))
    if (
        (NEW_BLOCK_RE.match(right) and not wrapped_section_sentence)
        or right.startswith(("【", "|"))
    ):
        return False
    if FACT_NOISE_RE.match(left) or FACT_NOISE_RE.match(right):
        return False
    return True


def looks_like_flat_table(text: str) -> bool:
    """Detect PDF tables flattened into an unreadable single text row."""

    punctuation = sum(text.count(mark) for mark in "，。；：！？、")
    token_count = len(text.split())
    return len(text) > 180 and token_count >= 25 and punctuation <= 8


def is_low_quality_fact(text: str) -> bool:
    return (
        bool(FACT_NOISE_RE.match(text))
        or looks_like_flat_table(text)
        or len(text) > 650
    )


def paragraphs_from_lines(lines: list[str]) -> list[str]:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                paragraphs.append(current)
                current = []
            continue
        if line.startswith("<!--"):
            continue
        if line in {"本章数字资源", "扫描图片", "体验 AR", "体验AR"}:
            continue
        if PART_TITLE_RE.match(line) and len(normalize(line)) < 20:
            continue
        if NUMBER_ITEM_RE.match(line) and current:
            paragraphs.append(current)
            current = [line]
            continue
        current.append(line)
    if current:
        paragraphs.append(current)
    output: list[str] = []
    for paragraph in paragraphs:
        text = join_wrapped_lines(paragraph)
        text = re.sub(r"\s+([，。；：！？、）])", r"\1", text)
        text = re.sub(r"([（])\s+", r"\1", text)
        if text:
            output.append(text)
    merged: list[str] = []
    for text in output:
        if merged and should_merge_paragraph(merged[-1], text):
            merged[-1] = join_wrapped_lines([merged[-1], text])
        else:
            merged.append(text)
    return merged


def split_long_unit(text: str) -> list[str]:
    if len(text) <= 430:
        return [text]
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[。！？；])\s*", text)
        if item.strip()
    ]
    if len(sentences) <= 1:
        return [text]
    units: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > 430:
            units.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        units.append(current)
    return units


def unit_score(text: str, index: int) -> int:
    score = 10 if index == 0 else 0
    for keyword, weight in FACT_KEYWORD_WEIGHTS.items():
        if keyword in text:
            score += weight
    if NUMBER_TOKEN_RE.search(text):
        score += 4
    if NUMBER_ITEM_RE.match(text):
        score += 4
    if 25 <= len(text) <= 280:
        score += 2
    if len(text) > 650:
        score -= 5
    if REFERENCE_NOISE_RE.search(text):
        score -= 8
    if FACT_NOISE_RE.match(text):
        score -= 20
    if looks_like_flat_table(text):
        score -= 20
    return score


def max_facts_for_title(title: str) -> int:
    if any(keyword in title for keyword in ("治疗", "处理", "临床表现", "诊断")):
        return 6
    return 4


def select_facts(units: list[str], title: str) -> list[str]:
    if not units:
        return []
    scored = [
        (unit_score(text, index), index, text)
        for index, text in enumerate(units)
        if not is_low_quality_fact(text)
    ]
    if not scored:
        return []
    count = max_facts_for_title(title)
    selected = sorted(scored, key=lambda item: (-item[0], item[1]))[:count]
    selected.sort(key=lambda item: item[1])
    facts: list[str] = []
    seen: set[str] = set()
    for _, _, text in selected:
        key = normalize(text)[:180]
        if not key or key in seen:
            continue
        seen.add(key)
        facts.append(text)
    return facts


def parse_segments(body: str, chapter_title: str, page_start: int) -> list[Segment]:
    segments: list[Segment] = []
    current_page = page_start
    current_parent = ""
    current = Segment(
        title="概述",
        level=2,
        parent="",
        page=page_start,
        order=0,
    )
    segments.append(current)
    order = 1

    for raw_line in body.splitlines():
        page_match = PAGE_MARKER_RE.search(raw_line)
        if page_match:
            current_page = int(page_match.group(1))
            continue
        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            level = len(heading_match.group(1))
            raw_heading = WHITESPACE_RE.sub(" ", heading_match.group(2)).strip()
            heading = clean_heading(raw_heading)
            if heading in {"正文", "章节提纲（依据 PDF 书签）"}:
                continue
            if is_chapter_heading(heading, chapter_title):
                continue

            heading, inline = split_heading_inline(raw_heading)
            if not inline and any(mark in heading for mark in ("。", "！", "？")):
                # PDF layout recovery can misclassify a wrapped body line as H1/H2.
                # Keep it as source text in the current section instead of
                # inventing a new framework branch.
                current.raw_lines.append(heading)
                continue
            if BRACKET_LABEL_RE.match(raw_heading):
                level = 3
            elif level == 1 and not is_chapter_heading(heading, chapter_title):
                level = 2

            if level <= 2:
                current_parent = heading
                parent = ""
            else:
                parent = current_parent
            current = Segment(
                title=heading,
                level=level,
                parent=parent,
                page=current_page,
                order=order,
            )
            order += 1
            if inline:
                current.raw_lines.append(inline)
            segments.append(current)
            continue
        current.raw_lines.append(raw_line)

    output: list[Segment] = []
    for segment in segments:
        paragraphs = paragraphs_from_lines(segment.raw_lines)
        units = []
        for paragraph in paragraphs:
            units.extend(split_long_unit(paragraph))
        segment.units = [
            unit
            for unit in units
            if len(normalize(unit)) >= 8
            and not is_chapter_heading(unit, chapter_title)
        ]
        segment.facts = select_facts(segment.units, segment.title)
        if segment.facts:
            output.append(segment)
    return output


def category_for_title(title: str) -> str | None:
    for category, keywords in CANONICAL_LABELS:
        if any(keyword in title for keyword in keywords):
            return category
    return None


def segment_priority(segment: Segment) -> int:
    score = 0
    if category_for_title(segment.title):
        score += 12
    if segment.level <= 2:
        score += 8
    if NUMBER_TOKEN_RE.search("".join(segment.facts)):
        score += 3
    score += min(len(segment.facts), 5)
    return score


def select_segments(segments: list[Segment], global_max: int = 72) -> list[Segment]:
    if len(segments) <= global_max:
        return segments
    groups: OrderedDict[str, list[Segment]] = OrderedDict()
    for segment in segments:
        key = segment.parent or (
            segment.title if segment.level <= 2 else "本章核心"
        )
        groups.setdefault(key, []).append(segment)
    per_group = max(4, min(10, global_max // max(1, len(groups))))
    selected: list[Segment] = []
    for items in groups.values():
        ranked = sorted(
            items,
            key=lambda item: (-segment_priority(item), item.order),
        )[:per_group]
        selected.extend(ranked)
    selected = sorted(
        selected,
        key=lambda item: (-segment_priority(item), item.order),
    )[:global_max]
    return sorted(selected, key=lambda item: item.order)


def framework_titles(segments: list[Segment]) -> list[str]:
    majors = []
    for segment in segments:
        if segment.level <= 2 and segment.title != "概述":
            title = segment.title
        elif not segment.parent:
            title = category_for_title(segment.title) or segment.title
        else:
            continue
        if normalize(title) not in {normalize(item) for item in majors}:
            majors.append(title)
    if not majors:
        for segment in segments:
            category = category_for_title(segment.title)
            if category and category not in majors:
                majors.append(category)
    return majors[:18]


def source_mainline(segments: list[Segment]) -> list[str]:
    categories = []
    for segment in segments:
        category = category_for_title(segment.title)
        if category and category not in categories:
            categories.append(category)
    if not categories:
        categories = framework_titles(segments)[:6]
    return categories


def first_fact_by_category(segments: list[Segment]) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for segment in segments:
        category = category_for_title(segment.title)
        if not category or category in seen or not segment.facts:
            continue
        seen.add(category)
        rows.append((category, segment.facts[0], segment.page))
    return rows


def numeric_facts(segments: list[Segment], limit: int = 15) -> list[tuple[str, str, int]]:
    candidates = []
    seen: set[str] = set()
    for segment in segments:
        for unit in segment.units:
            match = NUMBER_TOKEN_RE.search(unit)
            if (
                not match
                or REFERENCE_NOISE_RE.search(unit)
                or is_low_quality_fact(unit)
            ):
                continue
            key = normalize(unit)[:200]
            if key in seen:
                continue
            seen.add(key)
            score = unit_score(unit, 1)
            if any(token in unit for token in ("诊断", "分级", "标准", "首选", "应")):
                score += 5
            candidates.append((score, segment.order, match.group(0), unit, segment.page))
    selected = sorted(candidates, key=lambda item: (-item[0], item[1]))[:limit]
    selected.sort(key=lambda item: item[1])
    return [(token, text, page) for _, _, token, text, page in selected]


def escape_table(text: str) -> str:
    value = text.replace("|", "｜").replace("\n", " ")
    return WHITESPACE_RE.sub(" ", value).strip()


def compact_excerpt(text: str, limit: int = 180) -> str:
    clean = escape_table(text)
    if len(clean) <= limit:
        return clean
    sentences = re.split(r"(?<=[。！？；])", clean)
    result = ""
    for sentence in sentences:
        if result and len(result) + len(sentence) > limit:
            break
        result += sentence
    if result and len(result) >= 50:
        return result.rstrip() + "……"
    return clean[:limit].rstrip() + "……"


def format_fact(text: str) -> str:
    value = text.strip()
    if value.startswith("- "):
        return value
    return f"- {value}"


def grouped_segments(segments: list[Segment]) -> OrderedDict[str, list[Segment]]:
    groups: OrderedDict[str, list[Segment]] = OrderedDict()
    for segment in segments:
        if segment.parent:
            key = segment.parent
        elif segment.level <= 2 and segment.title != "概述":
            key = segment.title
        else:
            key = "本章核心"
        groups.setdefault(key, []).append(segment)
    return groups


def build_block(
    title: str,
    part: str,
    page_start: int,
    page_end: int,
    segments: list[Segment],
) -> tuple[str, dict[str, int]]:
    selected = select_segments(segments)
    framework = framework_titles(segments)
    mainline = source_mainline(segments)
    core_rows = first_fact_by_category(segments)
    numbers = numeric_facts(segments)
    groups = grouped_segments(selected)
    fact_count = sum(len(segment.facts) for segment in selected)

    rows = [
        START_MARKER,
        "",
        f"# {title}｜背诵版",
        "",
        "## 0. 本章背诵目标",
        "",
        f"掌握 **{title}** 的核心概念、临床线索、诊断路径与处理原则。",
        "",
        f"> 所属：{part}；原文范围：PDF 第 {page_start}-{page_end} 页。",
        "",
        "> [!note] 使用方法",
        "> 先按总框架闭卷复述，再用“核心速查—分节背诵—高频数字—自测题”查漏。",
        "> 本背诵版仅从本章原文抽取和重排，不新增教材外结论；图表、公式和完整语境请核对上方原始正文与 PDF。",
        "",
        "### 背诵主线",
        "",
        "> " + (" → ".join(mainline) if mainline else "概念 → 结构 → 临床意义 → 应用"),
        "",
        "---",
        "",
        "## 1. 总框架",
        "",
        "```text",
        title,
    ]
    if framework:
        for index, item in enumerate(framework):
            branch = "└─" if index == len(framework) - 1 else "├─"
            rows.append(f"{branch} {item}")
    else:
        rows.append("└─ 按原文章节顺序复述")
    rows.extend(["```", "", "---", "", "## 2. 核心速查", ""])

    if core_rows:
        rows.extend(
            [
                "| 板块 | 原文核心线索 | PDF页 |",
                "|---|---|---:|",
            ]
        )
        for category, fact, page in core_rows:
            rows.append(
                f"| {escape_table(category)} | {compact_excerpt(fact)} | {page} |"
            )
    else:
        rows.append("- 本章以原文分节为主，请按下方“分节背诵”复述。")

    rows.extend(["", "---", "", "## 3. 分节背诵", ""])
    for group_index, (group, items) in enumerate(groups.items(), 1):
        rows.extend([f"### 3.{group_index} {group}", ""])
        for segment in items:
            if segment.title not in {group, "概述"}:
                rows.extend([f"#### {segment.title}", ""])
            for fact in segment.facts:
                rows.append(format_fact(fact))
            rows.append("")

    rows.extend(["---", "", "## 4. 高频数字与阈值", ""])
    if numbers:
        rows.extend(
            [
                "| 数字/阈值 | 原文要点 | PDF页（约） |",
                "|---|---|---:|",
            ]
        )
        for token, fact, page in numbers:
            rows.append(
                f"| {escape_table(token)} | {compact_excerpt(fact, 220)} | {page} |"
            )
    else:
        rows.append("- 本章未从文本层稳定提取出适合单列的数字阈值。")

    questions = []
    if mainline:
        questions.append(f"不看原文，按“{' → '.join(mainline)}”复述本章。")
    for item in framework[:6]:
        questions.append(f"“{item}”应掌握哪些核心概念、临床线索和处理原则？")
    for category, _, _ in core_rows:
        if category == "诊断与鉴别":
            questions.append("本章诊断依据、鉴别诊断和严重程度评估分别是什么？")
        elif category == "治疗":
            questions.append("本章治疗目标、主要措施、适应证及风险点是什么？")
    deduped_questions = []
    for question in questions:
        if question not in deduped_questions:
            deduped_questions.append(question)
    rows.extend(["", "---", "", "## 5. 高频易错点", ""])
    rows.extend(
        [
            "- [ ] 不把“危险因素/病因”与“发病机制”混为一谈。",
            "- [ ] 诊断依据、鉴别诊断、严重程度评估分别复述。",
            "- [ ] 治疗时区分一般处理、病因治疗、对症治疗与并发症处理。",
            "- [ ] 数字、剂量、禁忌证和时效性建议必须回看原文，并结合当前可靠指南复核。",
            "",
            "---",
            "",
            "## 6. 自测题",
            "",
        ]
    )
    for index, question in enumerate(deduped_questions[:10], 1):
        rows.append(f"{index}. {question}")
    rows.extend(
        [
            "",
            "> [!warning] 自动结构化边界",
            "> 背诵版是原文的检索与复述辅助，不替代教材正文、图表或最新临床指南。",
            "",
            END_MARKER,
            "",
        ]
    )
    block = "\n".join(rows)
    stats = {
        "segment_count": len(segments),
        "selected_segment_count": len(selected),
        "fact_count": fact_count,
        "numeric_fact_count": len(numbers),
    }
    return block, stats


def initial_hash_map(root: Path) -> dict[str, str]:
    inventory_path = root / "internal_medicine_10e_inventory.json"
    if not inventory_path.is_file():
        return {}
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    output = {}
    for item in inventory.get("files", []):
        path = item.get("path")
        digest = item.get("sha256")
        if path and digest:
            output[str(path).replace("\\", "/")] = str(digest)
    return output


def process_chapter(
    root: Path,
    path: Path,
    initial_hashes: dict[str, str],
) -> ChapterResult:
    original = path.read_text(encoding="utf-8")
    no_block = strip_existing_block(original)
    base = strip_memorization_frontmatter(no_block)
    body = source_body(base)
    title = yaml_value(base, "title", path.stem)
    part = yaml_value(base, "part", path.parent.name)
    page_start = yaml_int(base, "pdf_page_start")
    page_end = yaml_int(base, "pdf_page_end")
    relative = path.relative_to(root).as_posix()
    if is_curated_body(body):
        heading_count = sum(1 for line in body.splitlines() if HEADING_RE.match(line))
        bullet_count = sum(
            1
            for line in body.splitlines()
            if re.match(r"^(?:[-*+]|\d+[.．、])\s+", line)
        )
        return ChapterResult(
            path=path,
            relative_path=relative,
            title=title,
            part=part,
            page_start=page_start,
            page_end=page_end,
            source_body_chars=len(body),
            source_base_sha256=sha256_text(base),
            initial_extraction_sha256=initial_hashes.get(relative),
            block="",
            block_sha256=sha256_text(body),
            segment_count=heading_count,
            selected_segment_count=heading_count,
            fact_count=bullet_count,
            numeric_fact_count=len(NUMBER_TOKEN_RE.findall(body)),
            mode="curated",
            anchor="一、全章总框架",
        )

    segments = parse_segments(body, title, page_start)
    block, stats = build_block(
        title,
        part,
        page_start,
        page_end,
        segments,
    )
    return ChapterResult(
        path=path,
        relative_path=relative,
        title=title,
        part=part,
        page_start=page_start,
        page_end=page_end,
        source_body_chars=len(body),
        source_base_sha256=sha256_text(base),
        initial_extraction_sha256=initial_hashes.get(relative),
        block=block,
        block_sha256=sha256_text(block),
        segment_count=stats["segment_count"],
        selected_segment_count=stats["selected_segment_count"],
        fact_count=stats["fact_count"],
        numeric_fact_count=stats["numeric_fact_count"],
        mode="generated",
        anchor=f"{title}｜背诵版",
    )


def render_current_file(path: Path, block: str) -> str:
    original = path.read_text(encoding="utf-8")
    base = strip_existing_block(original)
    enriched = add_memorization_frontmatter(base)
    return enriched.rstrip() + "\n\n" + block


def direct_anchor_link(root: Path, result: ChapterResult) -> str:
    target = (
        f"{root.name}/{result.relative_path[:-3]}"
        f"#{result.anchor}"
    )
    suffix = "（已精修）" if result.mode == "curated" else ""
    return f"[[{target}|{result.title}{suffix}]]"


def build_index(root: Path, results: list[ChapterResult]) -> str:
    grouped: OrderedDict[str, list[ChapterResult]] = OrderedDict()
    for result in results:
        grouped.setdefault(result.part, []).append(result)
    curated_count = sum(result.mode == "curated" for result in results)
    generated_count = sum(result.mode == "generated" for result in results)
    rows = [
        "---",
        "type: study_index",
        "status: complete",
        'source: "内科学 第10版"',
        f"created: {BUILD_DATE}",
        f"updated: {BUILD_DATE}",
        "---",
        "",
        "# 内科学第10版背诵版索引",
        "",
        "> 自动整理章节在同一文件末尾追加可直接跳转的 `｜背诵版`；已有人工精修背诵正文原样保留。",
        "",
        "## 使用顺序",
        "",
        "1. 先看每章背诵版的“总框架”，闭卷说出主线。",
        "2. 用“核心速查”和“分节背诵”补齐结构。",
        "3. 单独复述数字阈值，再完成自测题。",
        "4. 图表、公式、剂量、禁忌证和动态临床建议回看原文/PDF，并用当前指南复核。",
        "",
        "## 生成范围",
        "",
        f"- 章节：{len(results)}",
        f"- 自动生成：{generated_count}；已有精修并保留：{curated_count}",
        f"- 方法：`{METHOD}`",
        "- 内容边界：只从本章原文抽取和重排，不新增教材外结论。",
        f"- 机器清单：[[{MANIFEST_NAME}|{MANIFEST_NAME}]]",
        "",
        "## 篇章入口",
        "",
    ]
    for part, items in grouped.items():
        rows.extend([f"### {part}", ""])
        for item in items:
            rows.append(f"- {direct_anchor_link(root, item)}")
        rows.append("")
    return "\n".join(rows).rstrip() + "\n"


def replace_support_block(text: str, block: str) -> str:
    if SUPPORT_START in text:
        before, rest = text.split(SUPPORT_START, 1)
        if SUPPORT_END not in rest:
            raise ValueError("Support start marker exists without end marker.")
        _, after = rest.split(SUPPORT_END, 1)
        base = before.rstrip() + "\n" + after.lstrip("\n")
    else:
        base = text.rstrip() + "\n"
    return base.rstrip() + "\n\n" + block.rstrip() + "\n"


def write_support_files(root: Path, results: list[ChapterResult]) -> None:
    index_path = root / "00_地图" / MEMORY_INDEX_NAME
    index_path.write_text(build_index(root, results), encoding="utf-8", newline="\n")
    support_link = (
        f"[[{root.name}/00_地图/{MEMORY_INDEX_NAME[:-3]}|"
        "内科学第10版背诵版索引]]"
    )
    curated_count = sum(result.mode == "curated" for result in results)
    generated_count = sum(result.mode == "generated" for result in results)
    map_block = "\n".join(
        [
            SUPPORT_START,
            "",
            "## 背诵版入口",
            "",
            f"- {support_link}",
            f"- 自动生成 {generated_count} 章；已有人工精修并原样保留 {curated_count} 章。",
            "- 自动整理章节的原始正文保留在同一文件上方，末尾为可替换的 `｜背诵版`。",
            "",
            SUPPORT_END,
        ]
    )
    for relative in ("00_地图/大纲.md", "00_地图/复习.md"):
        path = root / relative
        text = path.read_text(encoding="utf-8")
        path.write_text(
            replace_support_block(text, map_block),
            encoding="utf-8",
            newline="\n",
        )

    source_path = root / "000_内科学第10版来源索引.md"
    source_text = source_path.read_text(encoding="utf-8")
    source_block = "\n".join(
        [
            SUPPORT_START,
            "",
            "## 背诵版整理",
            "",
            f"- 已完成章节：{len(results)}/{len(chapter_files(root))}",
            f"- 自动生成：{generated_count}；已有精修并保留：{curated_count}。",
            f"- 入口：{support_link}",
            f"- 生成方法：`{METHOD}`，仅从每章原始正文抽取和重排。",
            f"- 当前文件校验：[[{MANIFEST_NAME}|{MANIFEST_NAME}]]。",
            "- 初始提取清单继续保留原始来源哈希；背诵增强后的当前文件哈希记录在新清单中。",
            "",
            SUPPORT_END,
        ]
    )
    source_path.write_text(
        replace_support_block(source_text, source_block),
        encoding="utf-8",
        newline="\n",
    )


def manifest_payload(root: Path, results: list[ChapterResult]) -> dict[str, object]:
    source_digest = hashlib.sha256()
    for result in sorted(results, key=lambda item: item.relative_path):
        source_digest.update(result.relative_path.encode("utf-8"))
        source_digest.update(b"\0")
        source_digest.update(result.source_base_sha256.encode("ascii"))
        source_digest.update(b"\n")
    return {
        "source": "内科学 第10版",
        "root": str(root),
        "generated_at": BUILD_DATE,
        "method": METHOD,
        "chapter_count": len(results),
        "generated_chapter_count": sum(
            result.mode == "generated" for result in results
        ),
        "curated_chapter_count": sum(result.mode == "curated" for result in results),
        "source_base_aggregate_sha256": source_digest.hexdigest(),
        "start_marker": START_MARKER,
        "end_marker": END_MARKER,
        "chapters": [
            {
                "path": result.relative_path,
                "title": result.title,
                "part": result.part,
                "pdf_page_start": result.page_start,
                "pdf_page_end": result.page_end,
                "source_body_chars": result.source_body_chars,
                "source_base_sha256": result.source_base_sha256,
                "initial_extraction_sha256": result.initial_extraction_sha256,
                "memorization_block_sha256": result.block_sha256,
                "current_file_sha256": result.current_file_sha256,
                "segment_count": result.segment_count,
                "selected_segment_count": result.selected_segment_count,
                "fact_count": result.fact_count,
                "numeric_fact_count": result.numeric_fact_count,
                "mode": result.mode,
                "anchor": result.anchor,
            }
            for result in results
        ],
    }


def verify(root: Path) -> tuple[bool, list[str], dict[str, int]]:
    issues: list[str] = []
    files = chapter_files(root)
    manifest_path = root / MANIFEST_NAME
    manifest = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        issues.append(f"Missing {MANIFEST_NAME}")

    manifest_rows = {
        str(item["path"]): item for item in manifest.get("chapters", [])
    }
    for path in files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        row = manifest_rows.get(relative, {})
        mode = row.get("mode", "generated")
        if mode == "curated":
            try:
                curated = is_curated_body(source_body(text))
            except ValueError:
                curated = False
            if not curated:
                issues.append(f"Curated structure missing: {relative}")
        else:
            if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
                issues.append(f"Marker count: {relative}")
            if "｜背诵版" not in text:
                issues.append(f"Missing memorization title: {relative}")
            if "memorization_status: generated" not in text:
                issues.append(f"Missing memorization frontmatter: {relative}")
            if START_MARKER in text and len(text.split(START_MARKER, 1)[-1]) < 900:
                issues.append(f"Memorization block too short: {relative}")
        if "\ufffd" in text:
            issues.append(f"Replacement character: {relative}")

    manifest_count = int(manifest.get("chapter_count", 0)) if manifest else 0
    if manifest_count != len(files):
        issues.append(
            f"Manifest chapter count mismatch: {manifest_count} vs {len(files)}"
        )
    for path in files:
        relative = path.relative_to(root).as_posix()
        row = manifest_rows.get(relative)
        if not row:
            issues.append(f"Missing manifest row: {relative}")
            continue
        if row.get("current_file_sha256") != sha256_file(path):
            issues.append(f"Current SHA-256 mismatch: {relative}")

    index_path = root / "00_地图" / MEMORY_INDEX_NAME
    if not index_path.is_file():
        issues.append(f"Missing 00_地图/{MEMORY_INDEX_NAME}")
    stats = {
        "chapter_files": len(files),
        "chapter_blocks": sum(
            1
            for path in files
            if START_MARKER in path.read_text(encoding="utf-8")
        ),
        "curated_chapters": sum(
            1 for item in manifest_rows.values() if item.get("mode") == "curated"
        ),
        "manifest_rows": len(manifest_rows),
        "issues": len(issues),
    }
    return not issues, issues, stats


def select_files(files: list[Path], matches: list[str], max_files: int | None) -> list[Path]:
    selected = files
    if matches:
        selected = [
            path
            for path in files
            if any(token in path.name for token in matches)
        ]
    if max_files is not None:
        selected = selected[:max_files]
    return selected


def main() -> int:
    args = parse_args()
    workspace = Path.cwd().resolve()
    root = find_root(workspace, args.root)

    if args.verify_only:
        ok, issues, stats = verify(root)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        for issue in issues:
            print(f"ISSUE {issue}")
        print("VERIFY_OK" if ok else "VERIFY_FAILED")
        return 0 if ok else 1

    files = select_files(chapter_files(root), args.match, args.max_files)
    initial_hashes = initial_hash_map(root)
    results = []
    for index, path in enumerate(files, 1):
        result = process_chapter(root, path, initial_hashes)
        results.append(result)
        print(
            f"{index:03d}/{len(files):03d} {result.relative_path} "
            f"mode={result.mode} "
            f"segments={result.segment_count} selected={result.selected_segment_count} "
            f"facts={result.fact_count} block_chars={len(result.block)}"
        )

    if args.preview_dir:
        preview_dir = (
            args.preview_dir
            if args.preview_dir.is_absolute()
            else workspace / args.preview_dir
        )
        preview_dir.mkdir(parents=True, exist_ok=True)
        for result in results:
            target = preview_dir / result.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            preview = (
                result.block
                if result.mode == "generated"
                else (
                    f"# {result.title}｜已有人工精修背诵正文\n\n"
                    f"- 原文件：`{result.relative_path}`\n"
                    "- 批处理将原样保留，不追加自动摘要。\n"
                )
            )
            target.write_text(preview, encoding="utf-8", newline="\n")
        print(f"PREVIEW_WROTE {len(results)} files to {preview_dir}")

    if not args.write:
        return 0

    if len(results) != len(chapter_files(root)):
        raise RuntimeError(
            "Refusing partial --write. Run without --match/--max-files for a full batch."
        )
    for result in results:
        if result.mode == "generated":
            content = render_current_file(result.path, result.block)
            result.path.write_text(content, encoding="utf-8", newline="\n")
        result.current_file_sha256 = sha256_file(result.path)

    write_support_files(root, results)
    manifest = manifest_payload(root, results)
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    ok, issues, stats = verify(root)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    for issue in issues:
        print(f"ISSUE {issue}")
    print("VERIFY_OK" if ok else "VERIFY_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
