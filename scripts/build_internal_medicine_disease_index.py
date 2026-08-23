#!/usr/bin/env python3
"""Build a source-linked disease inventory for the flat 内科学第10版 chapters.

The inventory has two evidence tiers:
1. ``结构核心``: the name appears as a chapter, section, or primary heading;
2. ``索引提及``: the name appears in the book's bilingual term index and is
   mapped back to a chapter by printed page and/or literal body occurrence.

Chapter Markdown is read-only.  Only the two derived disease-index artifacts
are written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


SCHEMA_VERSION = "internal-medicine-10e-disease-index-v1"
OUTPUT_MARKDOWN = "00_全书疾病索引.md"
OUTPUT_JSON = "00_全书疾病清单.json"
CHAPTER_FILE_RE = re.compile(r"^(\d{3})_(\d{2})(\d{2})_(.+)\.md$")
SECTION_RE = re.compile(r"^#\s+第[^\s]*节(?:\s*[|｜])?\s*(.+?)\s*$")
PRIMARY_RE = re.compile(r"^##\s+[一二三四五六七八九十百零〇]+、\s*(.+?)\s*$")
SUBSECTION_RE = re.compile(r"^###\s+[（(][一二三四五六七八九十百零〇]+[）)]\s*(.+?)\s*$")
APPENDIX_HEADING_RE = re.compile(r"^##\s+\[附[^\]]*\]\s*(.+?)\s*$")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

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

EXACT_EXCLUDES = {
    "绪论",
    "总论",
    "总 论",
    "概述",
    "概 述",
    "概论",
    "概 论",
    "内科学概况",
    "如何学习内科学",
    "代谢",
    "激素",
    "内分泌系统",
    "临床表现",
    "功能诊断",
    "定位诊断",
    "病因诊断",
    "获得性",
    "遗传性",
    "特发性",
    "下丘脑的解剖结构与功能",
    "成人先天性心脏病的介入治疗",
    "先天性心脏病的其他介入治疗术",
    "心血管疾病的诊断",
    "心血管疾病的治疗",
    "消化系统重要诊疗技术",
    "内分泌学原理",
    "内分泌和代谢性疾病的诊断",
    "内分泌和代谢性疾病的治疗",
    "内分泌腺功能亢进的治疗",
    "内分泌腺功能减退的治疗",
    "抗心律失常药物的合理应用",
    "心律失常的介入治疗和手术治疗",
    "呼吸支持技术",
    "人工气道的建立与管理",
    "正压机械通气",
    "体外膜肺氧合",
    "氧疗",
    "导管消融",
    "经导管封堵术",
    "经皮球囊肺动脉瓣成形术",
    "心脏电复律与电除颤",
    "心血管植入型电子器械",
    "肾脏替代治疗",
    "造血干细胞移植",
    "输血和输血反应",
    "CAR-T细胞免疫疗法在血液病中的应用",
    "先天性肾上腺皮质增生症的治疗",
    "其他间质性肺疾病",
    "其他心血管疾病",
    "肿瘤心脏病学",
    "烟草病学",
    "血液病学",
    "丙型肝炎病毒",
    "乙型肝炎病毒",
    "外周血游离肿瘤DNA",
    "肿瘤突变负荷",
    "抑癌基因",
    "移植物抗白血病",
    "相关性疾病",
    "栓塞",
    "血栓形成",
    "急性上呼吸道感染和急性气管支气管炎",
    "肺炎支原体肺炎、衣原体肺炎与肺军团病",
    "动脉粥样硬化和冠状动脉粥样硬化性心脏病",
    "不稳定型心绞痛和非ST段抬高型心肌梗死",
    "心室扑动与心室颤动",
    "心包积液及心脏压塞",
    "嗜铬细胞瘤和副神经节瘤",
    "糖尿病与冠心病",
    "糖尿病与心力衰竭",
    "糖尿病与高血压",
    "肠结核和结核性腹膜炎",
    "胆囊结石及胆囊炎",
    "肝外胆管结石及胆管炎",
    "低血糖症与胰岛素瘤",
    "甲状腺结节和甲状腺癌",
    "肢端肥大症和巨人症",
    "水过多和水中毒",
    "钾缺乏和低钾血症",
    "白细胞减少和粒细胞缺乏症",
    "感染",
    "炎症",
    "出血",
    "腹痛",
    "并发症",
    "慢性并发症",
    "心脏并发症",
    "胆囊结石的并发症",
    "胰腺局部并发症",
    "中枢神经系统疾病",
    "感染性疾病",
    "遗传性疾病",
    "遗传和代谢性疾病",
    "血液系统疾病",
    "腹部疾病",
    "腹部以外疾病或全身性疾病",
    "冲动形成异常",
    "冲动传导异常",
    "循环障碍",
    "复合性止血机制异常",
    "慢性理化刺激及炎症",
    "抗凝及纤维蛋白溶解异常",
    "抗反流屏障结构与功能异常",
    "激素分泌异常",
    "血液流变学异常",
    "血管壁异常",
    "心脏病变和心力衰竭",
    "等渗性失水及低渗性失水",
    "肝损伤和胆源性胰腺炎",
    "肾脏病变和其他共病",
}

EXACT_INCLUDES = {
    "冠状动脉痉挛",
    "房室交界性逸搏与心律",
    "甲状腺肿",
    "甲状腺结节",
    "胆囊结石",
    "肝外胆管结石",
    "消化性溃疡",
    "胃溃疡",
    "十二指肠溃疡",
    "肺气肿",
    "无症状性血尿和/或蛋白尿",
    "水过多",
    "钾缺乏",
    "血脂异常",
    "门静脉高压",
    "左侧门静脉高压",
    "肺动脉高压",
    "阻塞性睡眠呼吸暂停",
    "流行性感冒",
    "三尖瓣下移畸形",
    "幽门梗阻",
    "无症状胆囊结石",
    "有症状胆囊结石",
    "原发性色素沉着结节性肾上腺皮质病和ACTH非依赖性肾上腺大结节性增生",
    "先天性类脂性肾上腺增生",
    "高原肺水肿",
    "高原脑水肿",
    "脾功能亢进",
    "弥散性血管内凝血",
    "系统性红斑狼疮",
    "风湿热",
    "原发性骨髓纤维化",
    "甲状腺危象",
    "黏液性水肿昏迷",
}

STRUCTURAL_EXPANSIONS = {
    "贫血概述": ["贫血"],
    "出血性疾病概述": ["出血性疾病"],
    "急性上呼吸道感染和急性气管支气管炎": [
        "急性上呼吸道感染",
        "急性气管支气管炎",
    ],
    "肺炎支原体肺炎、衣原体肺炎与肺军团病": [
        "肺炎支原体肺炎",
        "衣原体肺炎",
        "肺军团病",
    ],
    "动脉粥样硬化和冠状动脉粥样硬化性心脏病": [
        "动脉粥样硬化",
        "冠状动脉粥样硬化性心脏病",
    ],
    "不稳定型心绞痛和非ST段抬高型心肌梗死": [
        "不稳定型心绞痛",
        "非ST段抬高型心肌梗死",
    ],
    "心室扑动与心室颤动": ["心室扑动", "心室颤动"],
    "心包积液及心脏压塞": ["心包积液", "心脏压塞"],
    "嗜铬细胞瘤和副神经节瘤": ["嗜铬细胞瘤", "副神经节瘤"],
    "糖尿病与冠心病": ["糖尿病", "冠心病"],
    "糖尿病与心力衰竭": ["糖尿病", "心力衰竭"],
    "糖尿病与高血压": ["糖尿病", "高血压"],
    "肠结核和结核性腹膜炎": ["肠结核", "结核性腹膜炎"],
    "胆囊结石及胆囊炎": ["胆囊结石", "胆囊炎"],
    "肝外胆管结石及胆管炎": ["肝外胆管结石", "胆管炎"],
    "低血糖症与胰岛素瘤": ["低血糖症", "胰岛素瘤"],
    "甲状腺结节和甲状腺癌": ["甲状腺结节", "甲状腺癌"],
    "肢端肥大症和巨人症": ["肢端肥大症", "巨人症"],
    "水过多和水中毒": ["水过多", "水中毒"],
    "钾缺乏和低钾血症": ["钾缺乏", "低钾血症"],
    "白细胞减少和粒细胞缺乏症": ["白细胞减少", "粒细胞缺乏症"],
    "心脏骤停与心脏性猝死": ["心脏骤停", "心脏性猝死"],
}

ENDING_EXCLUDES = (
    "的分类",
    "概述",
    "概要",
    "治疗",
    "疗法",
    "技术",
    "检查",
    "试验",
    "成像",
    "造影",
    "监测",
    "管理",
    "应用",
    "原理",
    "的并发症",
)

ACTION_PREFIX_EXCLUDES = (
    "去除",
    "处理",
    "控制",
    "确定有无",
    "确定消化道出血",
    "引起",
    "防治",
    "预防",
)

DISEASE_CN_RE = re.compile(
    r"(?:"
    r"病|疾病|综合征|症|炎|癌|瘤|肿瘤|中毒|感染|衰竭|休克|"
    r"贫血|白血病|淋巴瘤|骨髓瘤|血症|结核|紫癜|血友病|血栓|梗死|"
    r"心绞痛|心律失常|心动过速|心动过缓|颤动|扑动|期前收缩|传导阻滞|"
    r"缺损|未闭|狭窄|反流|夹层|硬化|心脏病|心肌病|心包炎|肾损伤|"
    r"肾病|肾炎|肝病|肝炎|肝硬化|肺炎|肺结核|肺脓肿|哮喘|支气管炎|"
    r"关节炎|血管炎|肌病|硬化症|高血压|糖尿病|低血糖|肥胖|痛风|"
    r"骨质疏松|淹溺|冻僵|中暑|高原病|电击|咬伤|酸中毒|碱中毒|"
    r"失常|障碍|异常|缺乏|缺陷|增多|减少|停搏|压塞|积液|气胸|"
    r"出血|腹痛|腹泻|便秘|失水|水中毒|窦瘤|冠状动脉瘘|心肌桥|"
    r"主动脉缩窄|动脉导管未闭|卵圆孔未闭|二叶主动脉瓣|"
    r"房性逸搏与心律|发育障碍|雄激素过多"
    r")$"
)

DISEASE_EN_RE = re.compile(
    r"\b(?:disease|syndrome|cancer|carcinoma|tumou?r|neoplasm|leukemia|"
    r"lymphoma|myeloma|anemia|pneumonia|infection|infective|infarction|"
    r"angina|failure|shock|poisoning|toxicity|arthritis|vasculitis|myopathy|"
    r"sclerosis|gout|obesity|diabetes|hypoglycemia|hyperglycemic|hyperuricemia|"
    r"osteoporosis|ulcer|hemorrhage|bleeding|injury|dysfunction|anomaly|defect|"
    r"aplasia|hyperplasia|malformation|pancreatitis|hepatitis|nephritis|colitis|"
    r"thyroiditis|cholangitis|cholecystitis|hypertension|arrhythmia|fibrillation|"
    r"tachycardia|bradycardia|block|stenosis|regurgitation|thrombosis|embolism|"
    r"purpura|hemophilia|asthma|tuberculosis|abscess|cirrhosis|drowning|"
    r"heatstroke|goiter|sarcoidosis|bronchiectasis|cardiomyopathy|nephropathy|"
    r"encephalopathy|ophthalmopathy|myositis|arteritis|fibrosis|deficiency)\b",
    re.IGNORECASE,
)

CLINICAL_STATE_RE = re.compile(
    r"(?:衰竭|休克|中毒|淹溺|中暑|冻僵|电击|酸中毒|碱中毒|"
    r"低[^\s]{0,8}血症|高[^\s]{0,8}血症|心脏骤停|猝死|出血|积液|"
    r"气胸|腹痛|腹泻|便秘|失水|水中毒|心动过速|心动过缓|颤动|"
    r"扑动|期前收缩|传导阻滞|停搏|压塞|危象|昏迷)$"
)

GROUP_RE = re.compile(r"(?:疾病|肿瘤|白血病|淋巴瘤|心律失常)$")

MANUAL_ALIASES = {
    "冠状动脉粥样硬化性心脏病": ["冠心病"],
    "慢性阻塞性肺疾病": ["慢阻肺病", "COPD"],
    "肺军团病": ["军团菌肺炎"],
    "2019冠状病毒病": ["新型冠状病毒肺炎", "COVID-19"],
    "原发性慢性肾上腺皮质功能减退症": ["Addison病"],
    "甲状腺功能亢进症": ["甲亢"],
    "甲状腺功能减退症": ["甲减"],
    "慢性肺源性心脏病": ["肺源性心脏病"],
    "阻塞性睡眠呼吸暂停": ["阻塞性睡眠呼吸暂停低通气综合征"],
    "非酒精性脂肪性肝病": ["非酒精性脂肪肝"],
    "红细胞葡萄糖-6-磷酸脱氢酶缺乏症": [
        "红细胞葡萄糖-6- 磷酸脱氢酶(G-6-PD)缺乏症"
    ],
    "镇静催眠药中毒": ["急性镇静催眠药中毒"],
}

ALIAS_TO_CANONICAL_RAW = {
    alias: canonical
    for canonical, aliases in MANUAL_ALIASES.items()
    for alias in aliases
}


@dataclass
class Chapter:
    path: Path
    filename: str
    stem: str
    global_number: int
    part_number: int
    local_number: int
    title: str
    printed_start: int
    printed_end: int
    text: str
    body: str
    normalized_body: str


@dataclass
class Disease:
    name: str
    evidence: set[str] = field(default_factory=set)
    structural_levels: set[str] = field(default_factory=set)
    structural_chapters: set[str] = field(default_factory=set)
    index_pages: set[int] = field(default_factory=set)
    english: set[str] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)
    chapter_mentions: dict[str, int] = field(default_factory=dict)
    primary_chapter: str = ""
    part_number: int = 0
    kind: str = "疾病/诊断"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("｜", "|").replace("，", ",")
    value = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" |,，。;；:")
    value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", value)
    value = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u3400-\u9fff])", "", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[A-Za-z0-9])", "", value)
    value = re.sub(r"(?<=\d)\s+(?=型)", "", value)
    return value


ALIAS_TO_CANONICAL = {
    normalized_name(alias): normalized_name(canonical)
    for alias, canonical in ALIAS_TO_CANONICAL_RAW.items()
}


def match_normalized(value: str) -> str:
    value = normalized_name(value).lower()
    return re.sub(r"[\s\-‐‑–—·.,，。/（）()\[\]【】]", "", value)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.search(text.replace("\r\n", "\n"))
    if not match:
        raise RuntimeError("Chapter has no YAML frontmatter")
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"')
    return result


def body_after_frontmatter(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    match = FRONTMATTER_RE.search(normalized)
    return normalized[match.end() :] if match else normalized


def load_chapters(root: Path) -> list[Chapter]:
    paths = sorted(
        path for path in root.glob("*.md") if CHAPTER_FILE_RE.match(path.name)
    )
    if len(paths) != 131:
        raise RuntimeError(f"Expected 131 renamed chapter files, found {len(paths)}")
    chapters: list[Chapter] = []
    for path in paths:
        match = CHAPTER_FILE_RE.match(path.name)
        assert match is not None
        global_number, part_number, local_number = map(int, match.groups()[:3])
        text = path.read_text(encoding="utf-8-sig")
        meta = parse_frontmatter(text)
        if int(meta.get("global_chapter", -1)) != global_number:
            raise RuntimeError(f"Filename/YAML global chapter mismatch: {path.name}")
        if int(meta.get("part_number", -1)) != part_number:
            raise RuntimeError(f"Filename/YAML part mismatch: {path.name}")
        printed = meta.get("printed_pages", "")
        page_match = re.fullmatch(r"(\d+)-(\d+)", printed)
        if page_match:
            printed_start, printed_end = map(int, page_match.groups())
        else:
            printed_start = printed_end = global_number
        body = body_after_frontmatter(text)
        chapters.append(
            Chapter(
                path=path,
                filename=path.name,
                stem=path.stem,
                global_number=global_number,
                part_number=part_number,
                local_number=local_number,
                title=normalized_name(meta.get("title", match.group(4))),
                printed_start=printed_start,
                printed_end=printed_end,
                text=text,
                body=body,
                normalized_body=match_normalized(body),
            )
        )
    expected = list(range(1, 132))
    actual = [chapter.global_number for chapter in chapters]
    if actual != expected:
        raise RuntimeError("Chapter global numbering is not continuous 001-131")
    return chapters


def is_disease_like(name: str, english: str = "") -> bool:
    name = normalized_name(name)
    if not name or name in EXACT_EXCLUDES:
        return False
    if name.endswith("病学"):
        return False
    if name in EXACT_INCLUDES:
        return True
    if name.startswith(ACTION_PREFIX_EXCLUDES):
        return False
    if any(name.endswith(suffix) for suffix in ENDING_EXCLUDES):
        return False
    if len(name) > 52:
        return False
    if DISEASE_CN_RE.search(name):
        return True
    if english and DISEASE_EN_RE.search(english):
        return True
    return False


def disease_kind(name: str) -> str:
    if CLINICAL_STATE_RE.search(name):
        return "综合征/临床状态"
    if GROUP_RE.search(name):
        return "疾病组"
    return "疾病/诊断"


def structural_candidates(chapters: list[Chapter]) -> list[tuple[str, str, Chapter]]:
    rows: list[tuple[str, str, Chapter]] = []
    for chapter in chapters:
        rows.append((chapter.title, "章", chapter))
        for line in chapter.body.splitlines():
            match = SECTION_RE.match(line)
            if match:
                rows.append((normalized_name(match.group(1)), "节", chapter))
                continue
            match = PRIMARY_RE.match(line)
            if match:
                rows.append((normalized_name(match.group(1)), "目", chapter))
                continue
            match = SUBSECTION_RE.match(line)
            if match:
                rows.append((normalized_name(match.group(1)), "亚目", chapter))
                continue
            match = APPENDIX_HEADING_RE.match(line)
            if match:
                rows.append((normalized_name(match.group(1)), "附", chapter))
    return rows


def split_index_segments(line: str) -> list[str]:
    """Split MinerU-concatenated index entries at page-to-next-term seams."""

    candidates = [match.end() for match in re.finditer(r"\d{1,3}", line)]
    splits: list[int] = []
    last = 0
    for position in candidates:
        before = line[last:position]
        after = line[position:]
        if not re.search(r"[A-Za-z]", before):
            continue
        if re.match(
            r"\s*(?:(?:[A-Z][A-Za-z0-9 .+\-/]{0,22})?[\u3400-\u9fff])"
            r"[^\u3000\n]{0,58}(?:\u3000+|\s{2,})[A-Za-z]",
            after,
        ):
            splits.append(position)
            last = position
    if not splits:
        return [line]
    result: list[str] = []
    start = 0
    for end in splits:
        result.append(line[start:end].strip())
        start = end
    result.append(line[start:].strip())
    return [value for value in result if value]


def parse_bilingual_index(index_path: Path) -> tuple[list[dict[str, object]], list[str]]:
    text = body_after_frontmatter(index_path.read_text(encoding="utf-8-sig"))
    entries: list[dict[str, object]] = []
    unparsed: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        for segment in split_index_segments(line):
            match = re.match(
                r"^(?P<cn>.{1,70}?)(?:\u3000+|\s{2,})"
                r"(?P<en>[A-Za-z0-9α-ωΑ-Ω].*?)"
                r"(?:\u3000+|\s+)"
                r"(?P<pages>\d{1,3}(?:\s*,\s*\d{1,3})*)\s*$",
                segment,
            )
            if not match:
                # A few official entries intentionally have no printed page.
                no_page = re.match(
                    r"^(?P<cn>.{1,70}?)(?:\u3000+|\s{2,})(?P<en>[A-Za-z0-9].+?)\s*$",
                    segment,
                )
                if no_page:
                    english = no_page.group("en").strip()
                    pages: list[int] = []
                    # MinerU occasionally joins a printed page directly to an
                    # all-caps abbreviation, for example ``SCAD232``.
                    joined_page = re.search(r"(?<=[A-Za-z)])(\d{1,3})$", english)
                    if joined_page:
                        page = int(joined_page.group(1))
                        if 1 <= page <= 900:
                            pages = [page]
                            english = english[: joined_page.start()].rstrip()
                    entries.append(
                        {
                            "name": normalized_name(no_page.group("cn")),
                            "english": english,
                            "pages": pages,
                        }
                    )
                elif re.search(r"[\u3400-\u9fff]", segment):
                    unparsed.append(segment)
                continue
            pages = [int(value) for value in re.findall(r"\d{1,3}", match.group("pages"))]
            entries.append(
                {
                    "name": normalized_name(match.group("cn")),
                    "english": match.group("en").strip(),
                    "pages": pages,
                }
            )
    # One source line omits the page after IIP and runs the next official entry
    # into its English field. Split that source defect without changing source.
    for entry in entries:
        if entry["name"] != "特发性间质性肺炎":
            continue
        english = str(entry["english"])
        seam = " 特发性膜性肾病"
        if seam in english:
            first_english, second = english.split(seam, 1)
            entry["english"] = first_english.strip()
            entries.append(
                {
                    "name": "特发性膜性肾病",
                    "english": second.strip(),
                    "pages": list(entry["pages"]),
                }
            )
            break
    return entries, unparsed


def chapter_for_page(chapters: list[Chapter], page: int) -> Chapter | None:
    return next(
        (
            chapter
            for chapter in chapters
            if chapter.printed_start <= page <= chapter.printed_end
        ),
        None,
    )


def build_diseases(
    chapters: list[Chapter], index_entries: list[dict[str, object]]
) -> dict[str, Disease]:
    diseases: dict[str, Disease] = {}

    def get(name: str) -> Disease:
        raw_name = normalized_name(name)
        normalized = ALIAS_TO_CANONICAL.get(raw_name, raw_name)
        if normalized not in diseases:
            diseases[normalized] = Disease(name=normalized, kind=disease_kind(normalized))
        if raw_name != normalized:
            diseases[normalized].aliases.add(raw_name)
        return diseases[normalized]

    for name, level, chapter in structural_candidates(chapters):
        expanded_names = STRUCTURAL_EXPANSIONS.get(name, [name])
        for expanded_name in expanded_names:
            if name not in STRUCTURAL_EXPANSIONS and not is_disease_like(expanded_name):
                continue
            disease = get(expanded_name)
            disease.evidence.add("结构核心")
            disease.structural_levels.add(level)
            disease.structural_chapters.add(chapter.filename)

    for entry in index_entries:
        name = str(entry["name"])
        english = str(entry["english"])
        if not is_disease_like(name, english):
            continue
        disease = get(name)
        disease.evidence.add("索引提及")
        disease.english.add(english)
        disease.index_pages.update(int(page) for page in entry["pages"])

    for canonical, aliases in MANUAL_ALIASES.items():
        if canonical not in diseases:
            continue
        diseases[canonical].aliases.update(aliases)

    for disease in diseases.values():
        search_names = [disease.name, *sorted(disease.aliases)]
        for chapter in chapters:
            count = 0
            for name in search_names:
                needle = match_normalized(name)
                if needle:
                    count += chapter.normalized_body.count(needle)
            if count:
                disease.chapter_mentions[chapter.filename] = count

        candidates: list[Chapter] = []
        structural_matches = [
            chapter
            for chapter in chapters
            if chapter.filename in disease.structural_chapters
        ]
        disease_keys = {
            match_normalized(value)
            for value in [disease.name, *sorted(disease.aliases)]
            if match_normalized(value)
        }

        def structural_rank(chapter: Chapter) -> tuple[int, str]:
            title_key = match_normalized(chapter.title)
            if title_key in disease_keys:
                return (0, chapter.filename)
            if any(key in title_key or title_key in key for key in disease_keys):
                return (1, chapter.filename)
            return (2, chapter.filename)

        candidates.extend(sorted(structural_matches, key=structural_rank))
        for page in sorted(disease.index_pages):
            chapter = chapter_for_page(chapters, page)
            if chapter:
                candidates.append(chapter)
        if disease.chapter_mentions:
            ranked = sorted(
                disease.chapter_mentions.items(), key=lambda item: (-item[1], item[0])
            )
            candidates.extend(
                chapter
                for filename, _ in ranked
                for chapter in chapters
                if chapter.filename == filename
            )
        if candidates:
            primary = candidates[0]
            disease.primary_chapter = primary.filename
            disease.part_number = primary.part_number
        else:
            disease.part_number = 1
    return diseases


def chapter_link(filename: str, label: str | None = None) -> str:
    stem = Path(filename).stem
    return f"[[{stem}|{label or stem}]]"


def render_markdown(
    diseases: dict[str, Disease], chapters: list[Chapter], parse_stats: dict[str, int]
) -> str:
    by_filename = {chapter.filename: chapter for chapter in chapters}
    counts_by_part: dict[int, Counter[str]] = defaultdict(Counter)
    for disease in diseases.values():
        counts_by_part[disease.part_number][disease.kind] += 1
        counts_by_part[disease.part_number]["total"] += 1

    core_count = sum("结构核心" in disease.evidence for disease in diseases.values())
    index_only_count = sum(
        disease.evidence == {"索引提及"} for disease in diseases.values()
    )
    lines = [
        "---",
        'title: "内科学 第10版全书疾病索引"',
        f"source_chapters: {len(chapters)}",
        f"disease_entries: {len(diseases)}",
        f"structural_core_entries: {core_count}",
        f"index_only_entries: {index_only_count}",
        f"schema_version: {SCHEMA_VERSION}",
        "---",
        "",
        "# 内科学 第10版全书疾病索引",
        "",
        "> [!summary] 收录口径",
        "> 收录可作为诊断名称的疾病、疾病组、综合征、感染、中毒和急危重状态。排除症状体征、检查、药物、治疗方法、解剖及泛化叙述。",
        "> “结构核心”来自章、节、目、亚目及附录标题；“索引提及”来自原书中英文名词对照索引，并以印刷页或正文精确名称回链章节。",
        "",
        "## 全书概览",
        "",
        f"- 章节：{len(chapters)}；疾病条目：{len(diseases)}。",
        f"- 结构核心：{core_count}；仅在书末索引/正文中提及：{index_only_count}。",
        f"- 成功解析书末索引条目：{parse_stats['parsed_index_entries']}；未可靠解析片段：{parse_stats['unparsed_index_segments']}（未据此强行造词）。",
        "- “文本提及次数”为名称及已列别名的字面匹配，仅用于导航，不表示患病率或重要性。",
        "",
        "| 篇 | 疾病/诊断 | 疾病组 | 综合征/临床状态 | 合计 |",
        "|---|---:|---:|---:|---:|",
    ]
    for part_number in range(1, 10):
        counter = counts_by_part[part_number]
        lines.append(
            f"| {PART_NAMES[part_number]} | {counter['疾病/诊断']} | {counter['疾病组']} | "
            f"{counter['综合征/临床状态']} | {counter['total']} |"
        )

    for part_number in range(1, 10):
        part_items = [
            disease for disease in diseases.values() if disease.part_number == part_number
        ]
        if not part_items:
            continue
        lines.extend(["", f"## {PART_NAMES[part_number]}", ""])
        for kind in ("疾病/诊断", "疾病组", "综合征/临床状态"):
            items = sorted(
                (disease for disease in part_items if disease.kind == kind),
                key=lambda disease: disease.name,
            )
            if not items:
                continue
            lines.extend([f"### {kind}", "", "| 名称 | 证据 | 主要章节 | 涉及章节 | 文本提及 |", "|---|---|---|---:|---:|"])
            for disease in items:
                evidence = "+".join(sorted(disease.evidence))
                if disease.structural_levels:
                    evidence += f"（{'/'.join(sorted(disease.structural_levels))}）"
                aliases = (
                    f"<br><small>别名：{'、'.join(sorted(disease.aliases))}</small>"
                    if disease.aliases
                    else ""
                )
                primary = by_filename.get(disease.primary_chapter)
                primary_link = (
                    chapter_link(primary.filename, primary.title) if primary else "—"
                )
                chapter_count = len(disease.chapter_mentions)
                mention_count = sum(disease.chapter_mentions.values())
                lines.append(
                    f"| {disease.name}{aliases} | {evidence} | {primary_link} | "
                    f"{chapter_count} | {mention_count} |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(
    diseases: dict[str, Disease],
    chapters: list[Chapter],
    index_entries: list[dict[str, object]],
    unparsed: list[str],
) -> str:
    by_filename = {chapter.filename: chapter for chapter in chapters}
    rows: list[dict[str, object]] = []
    for disease in sorted(diseases.values(), key=lambda item: (item.part_number, item.name)):
        primary = by_filename.get(disease.primary_chapter)
        rows.append(
            {
                "name": disease.name,
                "aliases": sorted(disease.aliases),
                "english": sorted(disease.english),
                "kind": disease.kind,
                "evidence": sorted(disease.evidence),
                "structural_levels": sorted(disease.structural_levels),
                "part_number": disease.part_number,
                "part_title": PART_NAMES.get(disease.part_number, ""),
                "primary_chapter": disease.primary_chapter,
                "primary_chapter_title": primary.title if primary else "",
                "index_pages": sorted(disease.index_pages),
                "chapter_mentions": dict(sorted(disease.chapter_mentions.items())),
                "mention_count": sum(disease.chapter_mentions.values()),
            }
        )
    value = {
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "include": "diagnoses, disease groups, syndromes, infections, poisonings, and acute clinical states",
            "exclude": "symptoms/signs, tests, drugs, treatments, anatomy, and generic prose",
            "evidence_tiers": ["结构核心", "索引提及"],
        },
        "source_chapter_count": len(chapters),
        "source_chapter_hashes": {
            chapter.filename: sha256_file(chapter.path) for chapter in chapters
        },
        "parsed_index_entries": len(index_entries),
        "unparsed_index_segment_count": len(unparsed),
        "unparsed_index_segments": unparsed,
        "disease_count": len(rows),
        "diseases": rows,
    }
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def validate_outputs(markdown: str, json_text: str, root: Path) -> dict[str, int]:
    if CONTROL_RE.search(markdown) or CONTROL_RE.search(json_text):
        raise RuntimeError("Generated disease index contains control characters")
    value = json.loads(json_text)
    rows = value.get("diseases")
    if not isinstance(rows, list) or len(rows) != value.get("disease_count"):
        raise RuntimeError("Disease JSON count mismatch")
    names = [str(row["name"]) for row in rows]
    if len(names) != len(set(names)):
        raise RuntimeError("Duplicate disease names remain")
    broken = 0
    for target in re.findall(r"\[\[([^\]|#]+)", markdown):
        if not (root / f"{target}.md").is_file():
            broken += 1
    if broken:
        raise RuntimeError(f"Generated disease index has {broken} broken chapter links")
    empty_primary = sum(1 for row in rows if not row.get("primary_chapter"))
    return {
        "diseases": len(rows),
        "broken_links": broken,
        "empty_primary_chapters": empty_primary,
    }


def write_or_verify(
    root: Path,
    markdown: str,
    json_value: str,
    verify_only: bool,
    refresh: bool = False,
) -> int:
    expected = {
        root / OUTPUT_MARKDOWN: markdown.encode("utf-8"),
        root / OUTPUT_JSON: json_value.encode("utf-8"),
    }
    if verify_only:
        for path, data in expected.items():
            if not path.is_file() or path.read_bytes() != data:
                raise RuntimeError(f"Verify-only mismatch: {path}")
        return 0
    if refresh:
        markdown_path = root / OUTPUT_MARKDOWN
        json_path = root / OUTPUT_JSON
        if markdown_path.exists() != json_path.exists():
            raise RuntimeError("Derived disease-index pair is incomplete; refusing refresh")
        if markdown_path.is_file() and json_path.is_file():
            old_json = json.loads(json_path.read_text(encoding="utf-8"))
            new_json = json.loads(json_value)
            if old_json.get("schema_version") != SCHEMA_VERSION:
                raise RuntimeError("Existing disease index has an unexpected schema")
            if old_json.get("source_chapter_hashes") != new_json.get("source_chapter_hashes"):
                raise RuntimeError("Source chapter hashes changed; refusing disease-index refresh")
            if SCHEMA_VERSION not in markdown_path.read_text(encoding="utf-8"):
                raise RuntimeError("Existing disease Markdown lacks expected provenance")
            if abs(markdown_path.stat().st_mtime_ns - json_path.stat().st_mtime_ns) > 2_000_000_000:
                raise RuntimeError("Derived pair timestamps diverged; possible manual edit")
    for path, data in expected.items():
        if path.exists() and path.read_bytes() != data and not refresh:
            raise RuntimeError(
                f"Existing derived disease index differs; refusing overwrite: {path}"
            )
    changed = 0
    for path, data in expected.items():
        if path.is_file() and path.read_bytes() == data:
            continue
        temporary = path.with_name(path.name + ".codex-tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        changed += 1
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--refresh", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(__file__).resolve().parent.parent
    root = workspace / "999_附件文件夹" / "02_内科学第10版_按章节"
    chapters = load_chapters(root)
    index_path = root / "90_附录" / "10_中英文名词对照索引.md"
    index_entries, unparsed = parse_bilingual_index(index_path)
    diseases = build_diseases(chapters, index_entries)
    parse_stats = {
        "parsed_index_entries": len(index_entries),
        "unparsed_index_segments": len(unparsed),
    }
    markdown = render_markdown(diseases, chapters, parse_stats)
    json_value = render_json(diseases, chapters, index_entries, unparsed)
    validation = validate_outputs(markdown, json_value, root)

    tier_counts = Counter(
        "core" if "结构核心" in disease.evidence else "index_only"
        for disease in diseases.values()
    )
    kind_counts = Counter(disease.kind for disease in diseases.values())
    if args.audit:
        print(
            json.dumps(
                {
                    "chapters": len(chapters),
                    "structural_candidates": len(structural_candidates(chapters)),
                    "parsed_index_entries": len(index_entries),
                    "unparsed_index_segments": len(unparsed),
                    "diseases": len(diseases),
                    "core": tier_counts["core"],
                    "index_only": tier_counts["index_only"],
                    "kinds": dict(kind_counts),
                    **validation,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("DISEASE_INDEX_AUDIT_OK")
        return 0

    changed = write_or_verify(
        root, markdown, json_value, args.verify_only, refresh=args.refresh
    )
    print("DISEASE_INDEX_VERIFY_OK")
    print(f"diseases={len(diseases)}")
    print(f"structural_core={tier_counts['core']}")
    print(f"index_only={tier_counts['index_only']}")
    print(f"broken_links={validation['broken_links']}")
    print(f"empty_primary_chapters={validation['empty_primary_chapters']}")
    print(f"changed_files={changed}")
    if args.verify_only:
        print("VERIFY_ONLY_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
