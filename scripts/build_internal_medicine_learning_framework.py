#!/usr/bin/env python3
"""Build source-linked learning frameworks for every indexed disease.

The script reads the verified 644-item disease inventory and the 131 chapter
Markdown files.  It never edits chapter text.  Derived outputs are written to
``91_疾病学习框架`` and can be reproduced or verified byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


SCHEMA_VERSION = "internal-medicine-10e-learning-framework-v1"
DISEASE_INDEX = "00_全书疾病清单.json"
OUTPUT_DIR = "91_疾病学习框架"
OUTPUT_JSON = "疾病学习框架清单.json"
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

PART_FILES = {
    2: "02_呼吸系统疾病.md",
    3: "03_循环系统疾病.md",
    4: "04_消化系统疾病.md",
    5: "05_泌尿系统疾病.md",
    6: "06_血液系统疾病.md",
    7: "07_内分泌和代谢性疾病.md",
    8: "08_风湿免疫病.md",
    9: "09_理化因素所致疾病.md",
}

PART_NAMES = {
    1: "第一篇 绪论",
    2: "第二篇 呼吸系统疾病",
    3: "第三篇 循环系统疾病",
    4: "第四篇 消化系统疾病",
    5: "第五篇 泌尿系统疾病",
    6: "第六篇 血液系统疾病",
    7: "第七篇 内分泌和代谢性疾病",
    8: "第八篇 风湿免疫病",
    9: "第九篇 理化因素所致疾病",
}

DIMENSION_ORDER = (
    "定义与概述",
    "流行病学",
    "病因与危险因素",
    "发病机制与病理生理",
    "病理",
    "分类分型分期",
    "临床表现",
    "检查与评估",
    "诊断",
    "鉴别诊断",
    "并发症",
    "治疗",
    "预防",
    "预后",
    "随访与管理",
)


@dataclass(frozen=True)
class Template:
    name: str
    route: tuple[str, ...]
    focus: str
    output: str


TEMPLATES = {
    "感染性疾病": Template(
        "感染性疾病",
        (
            "病原体与传播/感染场景",
            "宿主危险因素",
            "感染部位与发病机制",
            "临床综合征",
            "病原学证据与严重度",
            "经验性处置逻辑",
            "目标性治疗逻辑",
            "并发症、隔离与预防",
        ),
        "把病原体、宿主和感染部位连成一条因果链，并区分病原学确诊与经验判断。",
        "画出“暴露/宿主—病原体—器官损伤—诊断证据—处置—预防”流程图。",
    ),
    "肿瘤性疾病": Template(
        "肿瘤性疾病",
        (
            "组织起源与病理类型",
            "危险因素和癌前状态",
            "分子特征",
            "局部与全身表现",
            "确诊路径",
            "分期/危险分层",
            "分层治疗",
            "疗效、复发与预后",
        ),
        "先定病理，再定分期和分子分层，最后把治疗与分层一一对应。",
        "制作“病理—分期—分子标志物—治疗选择—随访终点”五列表。",
    ),
    "心律失常": Template(
        "心律失常",
        (
            "心电图识别",
            "起源与电生理机制",
            "病因和可逆诱因",
            "血流动力学稳定性",
            "急性处理目标",
            "卒中/猝死等风险分层",
            "药物、消融或器械策略",
            "随访与复发预防",
        ),
        "先用频率、节律、P波、QRS和房室关系完成识图，再决定是否需要紧急处置。",
        "输出一张心电图判读卡和一棵“稳定/不稳定—急性/长期”决策树。",
    ),
    "心血管与血流动力学疾病": Template(
        "心血管与血流动力学疾病",
        (
            "解剖定位",
            "危险因素/病因",
            "血流动力学与病理生理",
            "症状体征",
            "心电图/标志物/影像",
            "严重度与风险分层",
            "药物—介入—外科阶梯",
            "二级预防与随访",
        ),
        "把解剖改变转换为血流动力学后果，再解释症状、体征和检查结果。",
        "画一条“结构异常—压力/容量变化—症状体征—检查—治疗靶点”机制链。",
    ),
    "呼吸系统疾病": Template(
        "呼吸系统疾病",
        (
            "解剖部位与病变性质",
            "病因/表型",
            "通气、换气与气体交换",
            "症状体征",
            "肺功能/影像/血气",
            "诊断与鉴别",
            "急性期与稳定期管理",
            "并发症、康复和随访",
        ),
        "抓住气道、肺泡、间质、血管或胸膜定位，并用肺功能、影像和血气相互印证。",
        "制作“定位—功能障碍—关键检查—严重度—急性/长期管理”表。",
    ),
    "消化与肝胆胰疾病": Template(
        "消化与肝胆胰疾病",
        (
            "器官与层次定位",
            "病因和危险因素",
            "病理生理",
            "症状与体征组合",
            "实验室/影像/内镜",
            "诊断和鉴别",
            "并发症",
            "治疗、营养与监测",
        ),
        "先完成器官定位，再用实验室、影像和内镜建立证据链，最后处理并发症。",
        "输出“定位线索—确诊检查—并发症—治疗入口”四栏卡片。",
    ),
    "肾脏疾病": Template(
        "肾脏疾病",
        (
            "肾小球/小管/间质/血管定位",
            "临床综合征",
            "病因与免疫机制",
            "尿液、肾功能和血清学",
            "影像与肾病理",
            "诊断/病理分型",
            "并发症和肾脏保护",
            "治疗与肾替代时机",
        ),
        "先按尿检、eGFR和临床综合征定位，再决定是否需要血清学或肾病理分型。",
        "画出“综合征—尿检—血清学—病理—治疗—肾脏结局”路径。",
    ),
    "血液系统疾病": Template(
        "血液系统疾病",
        (
            "受累细胞谱系",
            "生成减少/破坏增加/分布异常",
            "血常规与涂片",
            "骨髓、免疫表型和遗传学",
            "诊断分类与危险分层",
            "出血/感染/血栓等并发症",
            "病因治疗与支持治疗",
            "疗效判定、复发和预后",
        ),
        "从细胞谱系和计数异常出发，用形态、免疫和遗传证据逐层完成分类。",
        "制作“谱系—血象—骨髓—免疫/遗传—分层—治疗”六列表。",
    ),
    "内分泌轴疾病": Template(
        "内分泌轴疾病",
        (
            "激素轴与反馈关系",
            "功能亢进/减退/抵抗",
            "原发性与继发性定位",
            "病因",
            "临床表现",
            "基础激素与动态试验",
            "影像定位和并发症",
            "治疗替代/抑制与长期监测",
        ),
        "先画反馈轴，再用上下游激素组合定位病变层级，动态试验只回答特定问题。",
        "输出一张激素反馈轴和“激素组合—定位—验证试验—治疗”表。",
    ),
    "代谢与水电解质疾病": Template(
        "代谢与水电解质疾病",
        (
            "核心生化异常",
            "摄入/排出/转移/调节机制",
            "病因分类",
            "实验室模式",
            "临床后果",
            "急症识别",
            "纠正原则与监测",
            "慢性管理和复发预防",
        ),
        "用质量守恒和调节激素解释化验模式，并始终区分总量、浓度和分布变化。",
        "制作“异常值—机制—病因—临床风险—纠正原则—复查指标”表。",
    ),
    "风湿免疫病": Template(
        "风湿免疫病",
        (
            "免疫靶点与机制",
            "器官受累谱",
            "自身抗体与炎症指标",
            "分类/诊断标准",
            "疾病活动度与器官损害",
            "鉴别感染和肿瘤",
            "诱导与维持治疗层级",
            "药物安全和长期监测",
        ),
        "用器官谱和免疫学证据形成模式识别，同时分开活动度、累积损害和治疗副作用。",
        "输出“器官谱—抗体—标准—活动度—治疗层级—监测”矩阵。",
    ),
    "中毒与理化损伤": Template(
        "中毒与理化损伤",
        (
            "暴露史、剂量和时间",
            "毒代动力学/损伤机制",
            "中毒综合征或器官损伤",
            "现场与生命支持",
            "毒物检测和监测",
            "去污、促进排出与解毒剂",
            "并发症与观察终点",
            "职业/环境预防",
        ),
        "先稳定生命体征，再由暴露史和中毒综合征反推毒物；时间窗决定后续措施。",
        "画“暴露—时间轴—综合征—生命支持—特异措施—监测终点”急救流程。",
    ),
    "一般疾病与综合征": Template(
        "一般疾病与综合征",
        (
            "定义和诊断边界",
            "分类",
            "病因与危险因素",
            "发病机制",
            "临床表现",
            "检查与诊断",
            "鉴别和并发症",
            "治疗、预后与预防",
        ),
        "用定义、机制、证据和干预四层组织知识，避免把症状、综合征和病因混为一谈。",
        "完成一张“定义—机制—表现—证据—鉴别—治疗—预后”疾病卡。",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("｜", "|")
    value = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", value)
    value = re.sub(r"\s+", "", value)
    return re.sub(r"[\-‐‑–—·.,，。;；:：/\\|（）()\[\]【】]", "", value).lower()


def heading_key(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^第[一二三四五六七八九十百零〇0-9]+节\s*[|｜]?\s*", "", value)
    value = re.sub(r"^[一二三四五六七八九十百零〇0-9]+[、.]\s*", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十百零〇0-9]+[）)]\s*", "", value)
    value = value.strip("【】[] ")
    return normalize(value)


def parse_heading_text(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        text_value = match.group(2).strip()
        rows.append(
            {
                "level": len(match.group(1)),
                "text": text_value,
                "key": heading_key(text_value),
            }
        )
    return rows


def parse_headings(path: Path) -> list[dict[str, object]]:
    return parse_heading_text(path.read_text(encoding="utf-8-sig"))


def framework_type(row: dict[str, object]) -> str:
    name = str(row["name"])
    part = int(row["part_number"])
    if part == 9 or re.search(r"中毒|毒物|咬伤|淹溺|溺水|冻僵|中暑|热射|热衰竭|高原病|高原[肺脑]水肿|电击", name):
        return "中毒与理化损伤"
    if part == 6:
        return "血液系统疾病"
    if re.search(r"感染|肺炎|结核|曲霉|念珠菌|军团|衣原体|支原体|流行性感冒|病毒|细菌性|脓肿", name):
        return "感染性疾病"
    if re.search(r"癌|肿瘤|淋巴瘤|白血病|骨髓瘤|肉瘤|腺瘤|母细胞瘤|神经内分泌瘤|癌前", name):
        return "肿瘤性疾病"
    if part == 3 and re.search(r"心律失常|心房颤动|心室颤动|扑动|心动过速|心动过缓|期前收缩|传导阻滞|逸搏|预激|窦性停搏|房室交界|病态窦房结", name):
        return "心律失常"
    if part == 8:
        return "风湿免疫病"
    if part == 5:
        return "肾脏疾病"
    if part == 7 and re.search(r"糖尿病|低血糖|肥胖|血脂|代谢|痛风|尿酸|骨质疏松|水过多|水中毒|失水|低.*血症|高.*血症|酸中毒|碱中毒|钾|钠|钙|磷|镁|营养", name):
        return "代谢与水电解质疾病"
    if part == 7:
        return "内分泌轴疾病"
    if part == 3:
        return "心血管与血流动力学疾病"
    if part == 2:
        return "呼吸系统疾病"
    if part == 4:
        return "消化与肝胆胰疾病"
    return "一般疾病与综合征"


def priority(row: dict[str, object], source_scope: str) -> str:
    levels = set(str(value) for value in row.get("structural_levels", []))
    if levels.intersection({"章", "节"}):
        return "A 核心"
    if "结构核心" in row.get("evidence", []):
        return "B 重点"
    if source_scope == "chapter":
        return "A 核心"
    if source_scope.startswith("heading-"):
        level = int(source_scope.split("-", 1)[1])
        if level <= 2:
            return "A 核心"
    if source_scope.startswith("heading-"):
        return "B 重点"
    return "C 扩展"


def find_anchor(
    row: dict[str, object], headings: list[dict[str, object]]
) -> tuple[int | None, dict[str, object] | None]:
    candidates = [str(row["name"]), *(str(value) for value in row.get("aliases", []))]
    candidate_keys = [normalize(value) for value in candidates if normalize(value)]
    best: tuple[int, int, dict[str, object]] | None = None
    for index, heading in enumerate(headings):
        key = str(heading["key"])
        for candidate in candidate_keys:
            score = 0
            if key == candidate:
                score = 1000
            elif key == candidate + "概述":
                score = 950
            elif len(candidate) >= 3 and candidate in key:
                score = 800 - max(0, len(key) - len(candidate))
            elif len(key) >= 3 and key in candidate:
                score = 650 - max(0, len(candidate) - len(key))
            if score and (best is None or score > best[0]):
                best = (score, index, heading)
    if best is None:
        return None, None
    return best[1], best[2]


def dimensions_for_heading(key: str) -> list[str]:
    result: list[str] = []
    rules = (
        ("定义与概述", r"定义|概述|概论|概要"),
        ("流行病学", r"流行病学"),
        ("病因与危险因素", r"病因|危险因素|诱因"),
        ("发病机制与病理生理", r"发病机制|发生机制|病理生理|机制"),
        ("病理", r"病理"),
        ("分类分型分期", r"分类|分型|分期|分级|严重程度|危险分层|风险分层"),
        ("临床表现", r"临床表现|症状|体征"),
        ("检查与评估", r"实验室|检查|影像|心电图|血气|肺功能|内镜|病原学|骨髓|评估"),
        ("诊断", r"诊断"),
        ("鉴别诊断", r"鉴别"),
        ("并发症", r"并发症"),
        ("治疗", r"治疗|处理|救治|复苏|防治"),
        ("预防", r"预防"),
        ("预后", r"预后"),
        ("随访与管理", r"随访|管理|监测"),
    )
    for dimension, pattern in rules:
        if re.search(pattern, key):
            result.append(dimension)
    return result


def source_outline(
    row: dict[str, object], headings: list[dict[str, object]]
) -> tuple[str, list[dict[str, str]], bool, str]:
    anchor_index, anchor = find_anchor(row, headings)
    chapter_title_key = normalize(str(row.get("primary_chapter_title", "")))
    name_keys = [normalize(str(row["name"])), *(normalize(str(v)) for v in row.get("aliases", []))]
    chapter_is_scope = any(key and (key in chapter_title_key or chapter_title_key in key) for key in name_keys)

    if chapter_is_scope:
        scoped = headings
        anchor_text = ""
        source_is_scoped = True
        source_scope = "chapter"
    elif anchor is not None and anchor_index is not None:
        start = anchor_index + 1
        anchor_level = int(anchor["level"])
        scoped: list[dict[str, object]] = []
        for heading in headings[start:]:
            if int(heading["level"]) <= anchor_level:
                break
            scoped.append(heading)
        raw_anchor_text = str(anchor["text"])
        # MinerU section headings use a literal pipe (for example
        # ``第二节 | 急性呼吸衰竭``), which conflicts with Obsidian's wiki-link
        # alias separator. Keep the scope, but link to the chapter in that case.
        anchor_text = "" if re.search(r"[|\[\]]", raw_anchor_text) else raw_anchor_text
        source_is_scoped = True
        source_scope = f"heading-{anchor_level}"
    else:
        scoped = []
        anchor_text = ""
        source_is_scoped = False
        source_scope = "mention"

    modules: dict[str, str] = {}
    for heading in scoped:
        if re.search(r"[|\[\]]", str(heading["text"])):
            continue
        for dimension in dimensions_for_heading(str(heading["key"])):
            modules.setdefault(dimension, str(heading["text"]))
    ordered = [
        {"dimension": dimension, "heading": modules[dimension]}
        for dimension in DIMENSION_ORDER
        if dimension in modules
    ]
    return anchor_text, ordered, source_is_scoped, source_scope


def wiki_link(stem: str, label: str, anchor: str = "") -> str:
    target = stem + (f"#{anchor}" if anchor else "")
    return f"[[{target}|{label}]]"


def dynamic_prompts(row: dict[str, object]) -> list[str]:
    prompts: list[str] = []
    if row.get("aliases"):
        prompts.append("统一中文名、英文名、缩写和别名")
    if row.get("kind") != "疾病/诊断":
        prompts.append("先界定它是疾病组、综合征还是急危重状态")
    if row.get("evidence") == ["索引提及"]:
        prompts.append("确认其在原章节中的上下文及与主病的关系")
    if len(row.get("chapter_mentions", {})) >= 3:
        prompts.append("比较其在不同章节中作为主病、病因、并发症或共病的角色")
    return prompts or ["用一句话定义疾病，并写出一个最关键的鉴别点"]


def build_records(root: Path, source: dict[str, object]) -> list[dict[str, object]]:
    heading_cache: dict[str, list[dict[str, object]]] = {}
    records: list[dict[str, object]] = []
    for row in source["diseases"]:
        chapter_name = str(row["primary_chapter"])
        chapter_path = root / chapter_name
        if not chapter_path.is_file():
            raise RuntimeError(f"Missing primary chapter: {chapter_name}")
        headings = heading_cache.setdefault(chapter_name, parse_headings(chapter_path))
        anchor, modules, scoped, source_scope = source_outline(row, headings)
        template_name = framework_type(row)
        template = TEMPLATES[template_name]
        records.append(
            {
                "name": row["name"],
                "aliases": row.get("aliases", []),
                "kind": row["kind"],
                "evidence": row["evidence"],
                "structural_levels": row.get("structural_levels", []),
                "part_number": row["part_number"],
                "part_title": row["part_title"],
                "priority": priority(row, source_scope),
                "framework_type": template_name,
                "learning_route": list(template.route),
                "learning_focus": template.focus,
                "minimum_output": template.output,
                "primary_chapter": chapter_name,
                "primary_chapter_title": row["primary_chapter_title"],
                "source_anchor": anchor,
                "source_is_scoped": scoped,
                "source_scope": source_scope,
                "source_modules": modules,
                "chapter_mentions": row.get("chapter_mentions", {}),
                "mention_count": row.get("mention_count", 0),
                "review_prompts": dynamic_prompts(row),
            }
        )
    return records


def render_overview(records: list[dict[str, object]], source_hash: str) -> str:
    type_counts = Counter(str(row["framework_type"]) for row in records)
    priority_counts = Counter(str(row["priority"]) for row in records)
    lines = [
        "---",
        'title: "内科学第10版 疾病学习框架总览"',
        f"disease_entries: {len(records)}",
        f"schema_version: {SCHEMA_VERSION}",
        f"source_disease_index_sha256: {source_hash}",
        "---",
        "",
        "# 内科学第10版 疾病学习框架总览",
        "",
        "> [!summary] 使用说明",
        "> 本目录把全书疾病索引转换为学习路线，不替代原书正文。每个疾病均分配一个专业框架、学习优先级、原书入口和最小复习输出。",
        "> A 核心＝章/节级主题；B 重点＝目/亚目/附录级主题；C 扩展＝书末索引或正文提及。",
        "",
        "## 分系统入口",
        "",
    ]
    for part_number, filename in PART_FILES.items():
        count = sum(int(row["part_number"]) == part_number for row in records)
        lines.append(f"- {wiki_link(Path(filename).stem, PART_NAMES[part_number])}：{count} 项")

    lines.extend(
        [
            "",
            "## 通用十问",
            "",
            "无论何种疾病，最终都要能够闭卷回答：",
            "",
            "1. 它是什么，诊断边界在哪里？",
            "2. 如何分类、分型、分期或分层？",
            "3. 主要病因、危险因素和易感人群是什么？",
            "4. 发病机制如何解释病理改变？",
            "5. 核心症状、体征及并发症是什么？",
            "6. 哪些检查用于筛查、确诊、分型和严重度评估？",
            "7. 诊断标准是什么，最关键的鉴别诊断是什么？",
            "8. 治疗目标、急性处置和长期策略分别是什么？",
            "9. 如何判断疗效、预后并安排随访？",
            "10. 如何用一句话、机制图和决策树复述该病？",
            "",
            "## 优先级概览",
            "",
            "| 优先级 | 数量 | 建议 |",
            "|---|---:|---|",
            f"| A 核心 | {priority_counts['A 核心']} | 完成整套疾病卡，并能闭卷画出机制与诊疗路径 |",
            f"| B 重点 | {priority_counts['B 重点']} | 掌握定义、鉴别点、关键检查和处理原则 |",
            f"| C 扩展 | {priority_counts['C 扩展']} | 先明确它与主章节疾病的关系，再按需深入 |",
            "",
            "## 专业框架",
            "",
        ]
    )
    for template_name, template in TEMPLATES.items():
        count = type_counts[template_name]
        if not count:
            continue
        lines.extend(
            [
                f"### {template_name}",
                "",
                f"- 适用条目：{count} 个。",
                f"- 学习主线：{' → '.join(template.route)}。",
                f"- 核心抓手：{template.focus}",
                f"- 最小输出：{template.output}",
                "",
            ]
        )
    lines.extend(
        [
            "## 建议复习节奏",
            "",
            "1. 首轮：按 A → B → C 阅读，先完成定义、机制链和诊断入口。",
            "2. 二轮：闭卷完成各框架规定的最小输出，再回原书补缺。",
            "3. 三轮：围绕相似疾病做横向鉴别表，尤其比较相同症状、检查或并发症。",
            "4. 临考：只看自己无法稳定复述的决策节点，不重复抄写完整正文。",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def module_links(record: dict[str, object]) -> str:
    modules = record["source_modules"]
    if not modules:
        if record["source_is_scoped"]:
            return "原书未使用标准模块标题，按专业框架补齐"
        return "索引/正文提及，先在原章节确认上下文"
    stem = Path(str(record["primary_chapter"])).stem
    values = [
        wiki_link(stem, str(item["dimension"]), str(item["heading"]))
        for item in modules
    ]
    return " · ".join(values)


def render_part(part_number: int, records: list[dict[str, object]]) -> str:
    part_records = sorted(
        (row for row in records if int(row["part_number"]) == part_number),
        key=lambda row: (str(row["priority"]), str(row["framework_type"]), str(row["name"])),
    )
    type_counts = Counter(str(row["framework_type"]) for row in part_records)
    priority_counts = Counter(str(row["priority"]) for row in part_records)
    lines = [
        "---",
        f'title: "{PART_NAMES[part_number]} 疾病学习框架"',
        f"disease_entries: {len(part_records)}",
        f"schema_version: {SCHEMA_VERSION}",
        "---",
        "",
        f"# {PART_NAMES[part_number]}疾病学习框架",
        "",
        f"> 返回 {wiki_link('00_总览', '疾病学习框架总览')}。本篇共 {len(part_records)} 个条目：A 核心 {priority_counts['A 核心']}，B 重点 {priority_counts['B 重点']}，C 扩展 {priority_counts['C 扩展']}。",
        "",
        "## 框架分布",
        "",
        "| 专业框架 | 数量 |",
        "|---|---:|",
    ]
    for template_name in TEMPLATES:
        if type_counts[template_name]:
            lines.append(
                f"| {wiki_link('00_总览', template_name, template_name)} | {type_counts[template_name]} |"
            )

    for priority_name in ("A 核心", "B 重点", "C 扩展"):
        priority_rows = [row for row in part_records if row["priority"] == priority_name]
        if not priority_rows:
            continue
        lines.extend(["", f"## {priority_name}", ""])
        for record in priority_rows:
            stem = Path(str(record["primary_chapter"])).stem
            label = str(record["primary_chapter_title"])
            source = wiki_link(stem, label, str(record["source_anchor"]))
            template_name = str(record["framework_type"])
            evidence = "+".join(str(value) for value in record["evidence"])
            aliases = "、".join(str(value) for value in record["aliases"])
            lines.extend(
                [
                    f"### {record['name']}",
                    "",
                    f"- 定位：{record['kind']} · {wiki_link('00_总览', template_name, template_name)} · {evidence}。",
                    f"- 原书：{source}。",
                    f"- 学习主线：{' → '.join(record['learning_route'])}。",
                    f"- 原书模块：{module_links(record)}。",
                    f"- 最小输出：{record['minimum_output']}",
                    f"- 复习提示：{'；'.join(record['review_prompts'])}。",
                ]
            )
            if aliases:
                lines.append(f"- 别名：{aliases}。")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(
    records: list[dict[str, object]], source_path: Path, source_hash: str
) -> str:
    value = {
        "schema_version": SCHEMA_VERSION,
        "source_disease_index": str(source_path),
        "source_disease_index_sha256": source_hash,
        "disease_count": len(records),
        "framework_counts": dict(Counter(str(row["framework_type"]) for row in records)),
        "priority_counts": dict(Counter(str(row["priority"]) for row in records)),
        "dimension_order": list(DIMENSION_ORDER),
        "records": records,
    }
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def validate(
    outputs: dict[Path, str], records: list[dict[str, object]], source: dict[str, object], root: Path
) -> dict[str, int]:
    if len(records) != int(source["disease_count"]):
        raise RuntimeError("Learning record count differs from disease index")
    source_names = {str(row["name"]) for row in source["diseases"]}
    output_names = [str(row["name"]) for row in records]
    if set(output_names) != source_names or len(output_names) != len(set(output_names)):
        raise RuntimeError("Disease coverage or uniqueness check failed")
    for path, text in outputs.items():
        if CONTROL_RE.search(text):
            raise RuntimeError(f"Control character in output: {path}")
    json.loads(outputs[Path(OUTPUT_JSON)])

    broken_files = 0
    broken_anchors = 0
    broken_anchor_examples: list[str] = []
    heading_cache: dict[str, set[str]] = {}
    combined_markdown = "\n".join(
        value for path, value in outputs.items() if path.suffix == ".md"
    )
    for target in re.findall(r"\[\[([^\]|]+)", combined_markdown):
        stem, _, anchor = target.partition("#")
        relative = Path(stem + ".md")
        source_file = root / f"{stem}.md"
        derived_file = root / OUTPUT_DIR / f"{stem}.md"
        if relative in outputs:
            resolved: Path | None = None
            virtual_text = outputs[relative]
        else:
            resolved = source_file if source_file.is_file() else derived_file
            virtual_text = ""
        if resolved is not None and not resolved.is_file():
            broken_files += 1
            continue
        if anchor:
            if resolved is None:
                anchors = {str(row["text"]) for row in parse_heading_text(virtual_text)}
            else:
                anchors = heading_cache.setdefault(
                    str(resolved),
                    {str(row["text"]) for row in parse_headings(resolved)},
                )
            if anchor not in anchors:
                broken_anchors += 1
                if len(broken_anchor_examples) < 12:
                    broken_anchor_examples.append(target)
    if broken_files or broken_anchors:
        raise RuntimeError(
            f"Broken learning links: files={broken_files}, anchors={broken_anchors}, "
            f"examples={broken_anchor_examples}"
        )
    scoped = sum(bool(row["source_is_scoped"]) for row in records)
    with_modules = sum(bool(row["source_modules"]) for row in records)
    return {
        "diseases": len(records),
        "broken_files": broken_files,
        "broken_anchors": broken_anchors,
        "source_scoped": scoped,
        "with_source_modules": with_modules,
    }


def expected_outputs(
    records: list[dict[str, object]], source_path: Path, source_hash: str
) -> dict[Path, str]:
    outputs = {
        Path("00_总览.md"): render_overview(records, source_hash),
        Path(OUTPUT_JSON): render_json(records, source_path, source_hash),
    }
    for part_number, filename in PART_FILES.items():
        outputs[Path(filename)] = render_part(part_number, records)
    return outputs


def write_or_verify(
    output_dir: Path, outputs: dict[Path, str], verify_only: bool
) -> int:
    if verify_only:
        for relative, text in outputs.items():
            path = output_dir / relative
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                raise RuntimeError(f"Verify-only mismatch: {path}")
        return 0
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative, text in outputs.items():
        path = output_dir / relative
        if path.exists() and path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"Existing derived framework differs; refusing overwrite: {path}")
    changed = 0
    for relative, text in outputs.items():
        path = output_dir / relative
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        temporary = path.with_name(path.name + ".codex-tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
        changed += 1
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(__file__).resolve().parent.parent
    root = workspace / "999_附件文件夹" / "02_内科学第10版_按章节"
    source_path = root / DISEASE_INDEX
    source_hash = sha256_file(source_path)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    records = build_records(root, source)
    outputs = expected_outputs(records, source_path, source_hash)
    validation = validate(outputs, records, source, root)
    stats = {
        **validation,
        "frameworks": dict(Counter(str(row["framework_type"]) for row in records)),
        "priorities": dict(Counter(str(row["priority"]) for row in records)),
        "output_files": len(outputs),
    }
    if args.audit:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print("LEARNING_FRAMEWORK_AUDIT_OK")
        return 0
    changed = write_or_verify(root / OUTPUT_DIR, outputs, args.verify_only)
    print("LEARNING_FRAMEWORK_VERIFY_OK")
    print(json.dumps({**stats, "changed_files": changed}, ensure_ascii=False, indent=2))
    if args.verify_only:
        print("VERIFY_ONLY_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
