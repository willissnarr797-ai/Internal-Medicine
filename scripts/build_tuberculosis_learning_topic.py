#!/usr/bin/env python3
"""Build and verify the source-linked tuberculosis learning topic.

The script never edits textbook chapters or disease cards. It owns only:

- 00_地图/结核病学习专题/*.md
- its marked navigation block in 00_地图/00_总目录.md
- scripts/tuberculosis_learning_topic_manifest.json

Usage:
    python -B scripts/build_tuberculosis_learning_topic.py --write
    python -B scripts/build_tuberculosis_learning_topic.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import textwrap
from pathlib import Path

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ROOT = Path(__file__).resolve().parents[1]
TOPIC_ROOT = ROOT / "00_地图" / "结核病学习专题"
INDEX_PATH = ROOT / "00_地图" / "00_总目录.md"
MANIFEST_PATH = ROOT / "scripts" / "tuberculosis_learning_topic_manifest.json"
GENERATED_ON = "2026-08-29"

INDEX_BASELINE_SHA256 = "d6fdf119b62d5bad8195ee482cb4af04431dace3719109a785a342bb8b471558"
INDEX_START = "<!-- tuberculosis-learning-topic:start -->"
INDEX_END = "<!-- tuberculosis-learning-topic:end -->"
INDEX_BLOCK = """<!-- tuberculosis-learning-topic:start -->
## 专题学习

- [[结核病学习专题/00_结核病学习专题|结核病学习专题：诊断—分型—治疗—肺外结核—鉴别—复习]]

<!-- tuberculosis-learning-topic:end -->"""

SOURCE_HASHES = {
    "999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核.md": "20e2092d4961c1ece5802403f453381ce6300aa001f4c25742369d27feea6578",
    "999_附件文件夹/02_内科学第10版_按章节/014_0213_胸膜疾病.md": "d5fe25d3c469499e17132e89ef0e6adb0ab67a60352f5fc7194d4889faca1b06",
    "999_附件文件夹/02_内科学第10版_按章节/040_0407_肠结核和结核性腹膜炎.md": "bc53aa18f5de74bc9b26ab8e6d2407b44a0ec9d382aebc762d00c7c966549146",
    "999_附件文件夹/02_内科学第10版_按章节/027_0309_心包疾病.md": "08c5a3282ab4f7d35d7a0afc5c50d8880530677258fe4ca45e709c835f7e086e",
    "999_附件文件夹/02_内科学第10版_按章节/097_0707_肾上腺疾病.md": "f58f4c02cacca19360bdccc41a75440ab937add3c16a84e2a1d680b457a5fab9",
    "998_疾病卡片/02_呼吸系统疾病/肺结核.md": "651f273a0cfc34a61c145b7079f1c57ad9c93c510cbdaa673c859b5014eeb305",
}

ASSET_HASHES = {
    "999_附件文件夹/images/64d9c068cc3a778e005ab6103b9c4dd761c271edd433373734178e83a3746bb0.jpg": "78818fb31e2d80ae2c775dafb277a2b34265bafe63062047eebe09b43db729c5",
    "999_附件文件夹/images/d7205be23d1c1ec39dc98630adebdd7cdd895c3e42e69ccf858556f925280768.jpg": "fabba0f7be424be1609fbe86b36a4673279bdabf1b25d5f44ed3e05ecb8ced2e",
    "999_附件文件夹/images/ca2eb2871dc9b63a2d2e9f3c6b52f9db48ffd90d08ee0a9c09b26472b228bd8b.jpg": "e7872308de8ab6bb9ab25cf70167a1fd12eb2f29aeddc036c73ce0f992b4bef4",
    "999_附件文件夹/images/84618b708e4c17cda7ff138aa71363b81109c9d48aef9de14f0e6890937a36ba.jpg": "da3e04e75ff710983c50b481a2d06d1b03827f0cee8d4d9a722f8010018545ac",
    "999_附件文件夹/images/db4674259a9777b6d50ddccfb244339fd9e7486267296378ed5dc2a196ca7999.jpg": "96f645f9b793ef46f85cef2f735345e296bcbeefcbcee37cccb2174c6a1f2c3e",
    "999_附件文件夹/images/2e0e0bf978204faec5ac6d5e9c0688beacd54d0b5b5e098f05d4ea79339f7179.jpg": "5f408d8071f384a31b11f89637081e93e6c9aed44e7ee90a640df767b303e0f3",
    "999_附件文件夹/images/7915f5d78e79a611ef4d60b83b07e4b4b7c7563cccf151f53d1f500924ec36a6.jpg": "4e8d9cf653bbd4c8358df7aa6e48fe30c62185220bc7eebe2cdeae45fbe21d16",
    "999_附件文件夹/images/45b0204894ad4fa573d7dc580aca5276a4deb9bd2e8ae94def329ee62b7d7206.jpg": "7530bd3e4ba92204195e27f694ef4184fbf6ee728a9a01fc26f29cf118c92796",
}


def clean(value: str) -> str:
    return textwrap.dedent(value).strip() + "\n"


TOPIC_FILES = {
    "00_结核病学习专题.md": clean(r"""
        ---
        note_type: learning_topic
        topic: 结核病
        discipline: 内科学
        exam_scope: 306西医综合
        source_scope: 本地《内科学》第10版
        evidence_status: textbook_checked
        status: ready_for_review
        created: 2026-08-29
        updated: 2026-08-29
        tags: [结核病, 肺结核, 肺外结核, 306西医综合, 学习专题]
        ---

        # 结核病学习专题

        > [!warning] 使用边界
        > 本专题用于教材学习和306复习，内容严格限定于本地《内科学》第10版及既有肺结核卡片；不是最新临床指南，也不替代诊疗决策。涉及具体患者、耐药方案、特殊人群或药物剂量时，应核对现行指南与医嘱。

        ## 一句话总纲

        **先判断感染是否进展为活动性疾病，再取得病原学/病理学证据，随后明确部位、排菌、耐药和治疗史，最后用联合化疗完成杀菌、灭菌与防耐药。**

        ## 专题导航

        | 学习层 | 进入笔记 | 完成后应能输出 |
        | --- | --- | --- |
        | 总机制 | [[01_感染传播与免疫病理主线]] | 复述“暴露—感染—免疫/变态反应—病理—转归” |
        | 诊断 | [[02_肺结核诊断闭环与分型]] | 按证据层级完成六问诊断闭环 |
        | 治疗 | [[03_抗结核治疗与药物]] | 解释HRZE、A/B/C/D菌群、耐药与不良反应 |
        | 肺外结核 | [[04_肺外结核专题]] | 比较胸膜、肠、腹膜；识别心包和肾上腺线索 |
        | 鉴别 | [[05_鉴别诊断与做题陷阱]] | 处理空洞、积液、回盲部病变及NTM陷阱 |
        | 复习 | [[06_主动回忆与复习清单]] | 完成闭卷问题和1/3/7/14/30天复习 |
        | 审计 | [[07_来源与验证记录]] | 追溯教材、图片、哈希和生成方式 |

        ## 诊断—治疗总图

        ```mermaid
        flowchart LR
            A["暴露或高危宿主"] --> B["结核分枝杆菌感染"]
            B --> C{"仅感染还是活动性疾病？"}
            C -->|无活动证据| D["潜伏感染：评估预防性治疗"]
            C -->|有临床/影像/病理证据| E["活动性结核病"]
            E --> F["确定部位：肺/胸膜/肠/腹膜/其他"]
            F --> G["病原学：涂片/培养/核酸"]
            G --> H["确定排菌、耐药与初复治"]
            H --> I["早期 规律 全程 适量 联合"]
            I --> J["疗效、毒性、依从性与复发监测"]
        ```

        ## 三种使用方式

        - **20分钟速览**：总图 → [[02_肺结核诊断闭环与分型#六问诊断闭环|六问诊断闭环]] → [[03_抗结核治疗与药物#一线药物最小记忆表|一线药物表]] → [[05_鉴别诊断与做题陷阱#高频决策句|高频决策句]]。
        - **60分钟系统学习**：按01→05顺序，每页闭卷回答末尾问题。
        - **长期复习**：进入[[06_主动回忆与复习清单#复习日程|复习日程]]，把错题追加到既有[[998_疾病卡片/02_呼吸系统疾病/肺结核#做题复盘|肺结核卡片·做题复盘]]。

        ## 证据地图

        - 核心主讲：[[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核|教材·肺结核]]。
        - 专节主讲：[[999_附件文件夹/02_内科学第10版_按章节/014_0213_胸膜疾病#（二）结核性胸膜炎|教材·结核性胸膜炎]]；[[999_附件文件夹/02_内科学第10版_按章节/040_0407_肠结核和结核性腹膜炎|教材·肠结核和结核性腹膜炎]]。
        - 提及级延伸：[[999_附件文件夹/02_内科学第10版_按章节/027_0309_心包疾病|教材·心包疾病]]；[[999_附件文件夹/02_内科学第10版_按章节/097_0707_肾上腺疾病|教材·肾上腺疾病]]。
        - 既有备考卡：[[998_疾病卡片/02_呼吸系统疾病/肺结核|肺结核·306疾病卡片]]。

        ## 原书总览图

        ![[999_附件文件夹/images/7915f5d78e79a611ef4d60b83b07e4b4b7c7563cccf151f53d1f500924ec36a6.jpg]]

        *原书《肺结核》章思维导图；图片保持原始本地文件，不复制、不替换。*

        ## 完成标准

        - [ ] 能区分潜伏感染、活动性结核与非活动性肺结核。
        - [ ] 能说出“是否肺结核—是否活动—是否排菌—是否耐药—初治/复治”。
        - [ ] 能写出 `2HRZE/4HR` 并解释每个阶段的目的。
        - [ ] 能比较结核性胸膜炎、肠结核和结核性腹膜炎的证据入口。
        - [ ] 能完成肺癌/肺脓肿/NTM/克罗恩病/恶性积液的关键鉴别。
    """),

    "01_感染传播与免疫病理主线.md": clean(r"""
        ---
        note_type: learning_topic_module
        topic: 结核病
        module: 感染传播与免疫病理
        source_scope: 本地《内科学》第10版
        updated: 2026-08-29
        tags: [结核病, 传播, 免疫, 病理]
        ---

        # 感染传播与免疫病理主线

        > [!book] 原书入口
        > [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【流行病学】|流行病学]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【结核病在人群中的传播】|人群传播]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【结核病在人体的发生与发展】|人体内发生发展]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【病理学】|病理学]]

        ## 一条机制链

        ```mermaid
        flowchart TD
            A["传染源排出含菌飞沫核"] --> B["易感者吸入"]
            B --> C["肺泡巨噬细胞吞噬"]
            C --> D["细胞免疫建立 + 迟发型超敏反应"]
            D --> E{"宿主免疫与菌量/毒力平衡"}
            E -->|控制| F["吸收、纤维化、钙化或潜伏感染"]
            E -->|失衡| G["渗出、干酪样坏死、液化空洞"]
            G --> H["支气管播散、血行播散或肺外累及"]
        ```

        ## 传播必须拆成四问

        | 问题 | 回答框架 | 考试提醒 |
        | --- | --- | --- |
        | 谁排菌？ | 关注活动性且排菌的肺结核病人 | “感染”不等于“有传染性” |
        | 怎么传播？ | 以呼吸道传播主线理解人群传播 | 传播判断要结合排菌与接触场景 |
        | 谁易进展？ | HIV/AIDS、糖尿病、硅沉着病、免疫抑制等宿主因素 | 这些是从感染进展为疾病或结局不良的线索 |
        | 怎么阻断？ | 早发现、规范治疗、病例管理、接触者评估、潜伏感染预防性治疗 | 卡介苗重点保护儿童严重结核类型，并非可靠预防成人肺结核 |

        ## 免疫与病理不要分开背

        | 病理过程 | 形态关键词 | 临床/影像后果 |
        | --- | --- | --- |
        | 渗出 | 充血、水肿、炎细胞渗出 | 新鲜病灶、边缘较模糊，可吸收 |
        | 增生 | 上皮样细胞、朗格汉斯巨细胞、结核结节 | 肉芽肿性反应、纤维化倾向 |
        | 干酪样坏死 | 凝固性坏死样物 | 液化后形成空洞；可播散 |
        | 修复 | 吸收、纤维化、钙化 | 可转为非活动性残留影 |

        > [!exam] 核心因果
        > **细胞免疫有助于控制感染；迟发型超敏反应也参与组织损伤。** 病变不是“细菌单独造成”，而是菌量/毒力与宿主反应共同决定。

        ## 潜伏、活动与非活动

        - **潜伏感染**：已感染，但没有临床结核病，也没有细菌学或影像学活动证据。
        - **活动性结核病**：临床症状/体征及病原学、病理学或影像学存在活动证据。
        - **非活动性肺结核**：影像以钙化、硬结或纤维化为主，痰不排菌且无症状；这是教材诊断程序中的判断，不等同于“从未感染”。

        ## 原书自然过程图

        ![[999_附件文件夹/images/64d9c068cc3a778e005ab6103b9c4dd761c271edd433373734178e83a3746bb0.jpg]]

        *图2-8-1：肺结核病自然过程示意图。*

        ## 闭卷自测

        1. 为什么结核病可同时出现控制感染和组织损伤？
        2. 干酪样坏死怎样连接“空洞—排菌—传播”？
        3. 潜伏感染与活动性结核的分界证据是什么？
        4. 为什么免疫抑制者的PPD可能阴性？
        5. 卡介苗最值得记住的保护重点是什么？

        返回：[[00_结核病学习专题]] · 下一步：[[02_肺结核诊断闭环与分型]]
    """),

    "02_肺结核诊断闭环与分型.md": clean(r"""
        ---
        note_type: learning_topic_module
        topic: 结核病
        module: 肺结核诊断闭环与分型
        source_scope: 本地《内科学》第10版
        updated: 2026-08-29
        tags: [肺结核, 诊断, 分型, 影像]
        ---

        # 肺结核诊断闭环与分型

        > [!book] 原书入口
        > [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【肺结核的诊断】|肺结核的诊断]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【结核病的分类标准】|分类标准]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#（三）病原学检测阴性肺结核|病原学检测阴性肺结核]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【肺结核的记录方式】|记录方式]]

        ## 六问诊断闭环

        1. **是否需要筛查？** 咳嗽、咳痰持续2周以上或咯血；也看午后低热、盗汗、乏力、接触史及肺外结核。
        2. **是否为肺结核？** 流行病学史、症状和影像提出怀疑，以病原学/病理学证据闭环。
        3. **是否活动？** 新鲜渗出、边缘模糊、空洞或播散支持活动；钙化、硬结、纤维化且无症状/不排菌支持非活动。
        4. **是否排菌？** 痰涂片、培养、核酸；排菌判断连接传染源管理。
        5. **是否耐药？** 依据药物敏感性或耐药分子检测，不能凭治疗史猜测。
        6. **初治还是复治？** 既往治疗史直接影响治疗策略。

        ![[999_附件文件夹/images/d7205be23d1c1ec39dc98630adebdd7cdd895c3e42e69ccf858556f925280768.jpg]]

        *图2-8-2：肺结核病诊断流程。*

        ## 证据层级

        | 证据 | 能回答什么 | 不能单独回答什么 |
        | --- | --- | --- |
        | 痰抗酸涂片 | 快速发现抗酸杆菌、评估排菌线索 | 不能区分MTB与NTM；敏感性有限 |
        | 分枝杆菌培养 | 高灵敏病原学证据；可供菌种鉴定和药敏 | 结果较慢 |
        | 核酸检测/Xpert MTB/RIF | 快速检出MTB复合群，并提供利福平耐药相关信息 | 仍需结合临床；不能替代完整药敏思维 |
        | 病理 | 肉芽肿、干酪样坏死等可提供确诊线索 | 需结合病原学和取材背景 |
        | 影像 | 发现、定位、判断范围/活动性、指导取材 | 影像“像结核”不等于确诊 |
        | PPD/IGRA | 支持存在结核感染相关免疫反应 | 不能单独确诊或排除活动性结核，也不能评价疗效 |

        > [!exam] 两个常考反转
        > 1. 涂片阳性只说明有抗酸杆菌，不能自动等于结核分枝杆菌。  
        > 2. PPD/IGRA阳性支持感染，不等于活动性结核；阴性也不能在免疫抑制或重症结核中排除。

        ## 活动性肺结核的五类部位/类型

        | 类型 | 最小识别点 |
        | --- | --- |
        | 原发性肺结核 | 原发综合征或胸内淋巴结结核；儿童多见 |
        | 血行播散性肺结核 | 急性粟粒型强调“两肺均匀、大小和密度一致” |
        | 继发性肺结核 | 成人最常见；浸润、干酪性肺炎、结核球、纤维空洞/毁损肺 |
        | 气管、支气管结核 | 管壁增厚、狭窄/阻塞；支气管镜和取材重要 |
        | 结核性胸膜炎 | 干性、渗出性或结核性脓胸；转入[[04_肺外结核专题#结核性胸膜炎|胸膜专题]] |

        ## 影像识别

        ### 原发综合征

        ![[999_附件文件夹/images/ca2eb2871dc9b63a2d2e9f3c6b52f9db48ffd90d08ee0a9c09b26472b228bd8b.jpg]]

        ### 急性粟粒性肺结核

        ![[999_附件文件夹/images/84618b708e4c17cda7ff138aa71363b81109c9d48aef9de14f0e6890937a36ba.jpg]]

        ### 浸润性肺结核

        ![[999_附件文件夹/images/db4674259a9777b6d50ddccfb244339fd9e7486267296378ed5dc2a196ca7999.jpg]]

        ### 干酪性肺炎

        ![[999_附件文件夹/images/2e0e0bf978204faec5ac6d5e9c0688beacd54d0b5b5e098f05d4ea79339f7179.jpg]]

        ## 病原学检测阴性肺结核

        病原学阴性是“涂片、培养、核酸均阴性”，不是“没有做检查”。教材把诊断拆为三个场景：

        - **肺组织结核**：典型影像，并结合典型症状、免疫学阳性或肺外组织病理证实等条件。
        - **气管支气管结核**：典型影像与支气管镜下结核性改变相互支持。
        - **结核性胸膜炎**：典型影像、渗出液伴ADA升高及免疫学证据共同构成教材标准。

        > [!warning]
        > 病原学阴性不能成为“凭影像直接治疗”的捷径；应主动排除肿瘤、真菌、NTM及其他非结核性疾病，并在治疗前尽量补全病原学、支气管镜或病理证据。

        ## 诊断记录练习

        按“**分类—部位/范围—痰菌—耐药—初复治—并发症/共病**”书写。练习：

        - 继发性肺结核，双上肺，涂（+），利福平敏感，初治。
        - 血行播散性肺结核（急性粟粒型），涂（-），初治，待药敏。

        ## 闭卷自测

        1. 肺结核诊断六问是什么？
        2. 涂片、培养、核酸、PPD/IGRA各自能和不能证明什么？
        3. 结核球与肺癌最先比较哪些影像线索？
        4. “病原学阴性”至少排除了哪三类检测阳性？
        5. 如何书写一条完整肺结核诊断？

        返回：[[00_结核病学习专题]] · 下一步：[[03_抗结核治疗与药物]]
    """),

    "03_抗结核治疗与药物.md": clean(r"""
        ---
        note_type: learning_topic_module
        topic: 结核病
        module: 抗结核治疗与药物
        source_scope: 本地《内科学》第10版
        updated: 2026-08-29
        tags: [结核病, HRZE, 抗结核药, 耐药]
        ---

        # 抗结核治疗与药物

        > [!warning] 用药边界
        > 本页是教材记忆框架，不是处方。耐药结核、肝肾功能异常、妊娠、儿童、HIV共病及严重肺外结核必须依据现行规范个体化处理。

        > [!book] 原书入口
        > [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【结核病的化学治疗】|结核病的化学治疗]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【MDR-TB 或 RR-TB 的治疗】|MDR/RR-TB治疗]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【其他治疗】|其他治疗]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【结核病控制策略与措施】|控制策略]]

        ## 五原则不是口号

        | 原则 | 防止的问题 |
        | --- | --- |
        | 早期 | 尽快降低菌量、组织破坏和传染性 |
        | 规律 | 避免有效药物暴露不稳定和选择耐药菌 |
        | 全程 | 覆盖半静止/间歇生长菌群，降低复发 |
        | 适量 | 在疗效与毒性之间取得平衡 |
        | 联合 | 交叉杀菌并防止单药选择耐药突变菌 |

        ## A/B/C/D菌群与用药逻辑

        | 菌群 | 代谢位置/状态 | 教材中的优势药物记忆 | 意义 |
        | --- | --- | --- | --- |
        | A | 快速繁殖；细胞外、空洞干酪液化部 | H最强，随后S、R、E | 早期杀菌、快速降传染性 |
        | B | 半静止；细胞内酸性环境/坏死组织 | Z最强，随后R、H | 灭菌、防复发 |
        | C | 间歇短暂生长 | R最强，随后H | 灭菌、防复发 |
        | D | 休眠、不繁殖 | 教材称抗结核药无作用 | 解释为什么不能把“联合”理解成无限叠药 |

        ## 一线药物最小记忆表

        | 药物 | 核心定位 | 高频不良反应/监测点 |
        | --- | --- | --- |
        | H 异烟肼 | 早期杀菌强，细胞内外均有效 | 肝损害、周围神经炎；相关风险时关注维生素B6 |
        | R 利福平 | 快速杀菌，对C菌群重要 | 肝损害、过敏；体液橘红；注意相互作用 |
        | Z 吡嗪酰胺 | 酸性环境B菌群 | 肝损害、高尿酸血症、关节痛、胃肠不适 |
        | E 乙胺丁醇 | 联合方案的重要组成 | 视神经炎；治疗前及过程中关注视力/视野 |
        | S 链霉素 | 细胞外碱性环境杀菌 | 耳毒性、前庭损害、肾毒性 |

        > [!exam] 记忆钩子
        > **H神经+肝，R橘红+肝，Z尿酸+肝，E眼，S耳肾。** 口诀只用于提取，答题仍要写出具体不良反应。

        ## 标准方案

        **初治活动性肺结核常用 `2HRZE/4HR`：**

        - 强化期2个月：H、R、Z、E，目标是快速杀菌和降低耐药选择风险。
        - 巩固期4个月：H、R，目标是杀灭残留菌群、降低复发。

        教材同时记录了特定人群的4个月短程方案信息，但明确指出 `2HRZE/4HR` 仍是较稳妥保守的选择；复习时必须区分“教材主要标准方案”和“特定条件下的新方案”。

        ## 复治与耐药的决策边界

        ```mermaid
        flowchart TD
            A["既往治疗失败、复发或不规律治疗"] --> B["取得培养/分子耐药与药敏证据"]
            B --> C{"利福平是否耐药？"}
            C -->|敏感或未知| D["按教材原则评估初治标准方案并等待/完善药敏"]
            C -->|耐药| E["进入RR/MDR-TB路径"]
            E --> F["依据有效药物、既往暴露、毒性与最新规范个体化"]
        ```

        - **复治不等于机械套用固定复治方案。** 教材强调对复治病人进行药敏并按耐药结果制定方案。
        - **MDR-TB**：至少耐异烟肼和利福平；**RR-TB**：利福平耐药。
        - 教材列出的长/短程耐药方案具有版本性，临床应用必须再次核对现行指南。

        ## 治疗监测框架

        | 维度 | 复习时要问 |
        | --- | --- |
        | 疗效 | 症状、影像、痰菌/培养是否按节点改善？ |
        | 依从性 | 是否漏药、中断或自行改变方案？ |
        | 毒性 | 肝功能、视力、听力/肾功能、尿酸及症状是否异常？ |
        | 耐药 | 失败、复发、持续阳性时是否补做培养与药敏？ |
        | 传播控制 | 排菌状态、报告转诊和接触者管理是否完成？ |

        ## 高频陷阱

        - 症状好转不等于可以停药。
        - 单药或不规律联合治疗都可选择耐药菌。
        - 痰菌持续阳性不能只“延长原方案”，必须重新评估依从性、药敏与诊断。
        - 糖皮质激素不是肺结核常规基础治疗；仅在教材限定情形并确保有效抗结核治疗时考虑。

        ## 闭卷自测

        1. 五原则分别在防什么？
        2. H、R、Z分别对应哪些菌群优势？
        3. 写出HRZE五药的一个标志性不良反应。
        4. `2HRZE/4HR` 两阶段目的有什么不同？
        5. 为什么复治病例不能机械套用固定方案？

        返回：[[00_结核病学习专题]] · 下一步：[[04_肺外结核专题]]
    """),

    "04_肺外结核专题.md": clean(r"""
        ---
        note_type: learning_topic_module
        topic: 结核病
        module: 肺外结核
        source_scope: 本地《内科学》第10版
        updated: 2026-08-29
        tags: [肺外结核, 结核性胸膜炎, 肠结核, 结核性腹膜炎]
        ---

        # 肺外结核专题

        ## 总比较

        | 部位 | 主要入口 | 关键证据链 | 最重要鉴别/并发症 |
        | --- | --- | --- | --- |
        | 胸膜 | 发热、胸痛、呼吸困难、渗出性胸水 | 淋巴细胞为主、ADA升高；结合影像、免疫学、病原学/胸膜活检 | 恶性胸水、肺炎旁积液；胸膜增厚、脓胸 |
        | 肠 | 回盲部病变、右下腹痛、排便改变 | 内镜+活检；干酪样肉芽肿/抗酸杆菌/培养或TB-qPCR | 克罗恩病、淋巴瘤、右半结肠癌；梗阻 |
        | 腹膜 | 慢性发热、腹胀、腹水、腹壁柔韧感 | 渗出性淋巴细胞腹水、SAAG<11 g/L、ADA升高；腹腔镜活检 | 腹膜恶性肿瘤、肝硬化腹水；粘连/梗阻/瘘 |
        | 心包（提及级） | 心包炎或大量/血性心包积液伴原发结核线索 | 心包液/病理与全身证据综合 | 特发性、化脓性、肿瘤性心包炎 |
        | 肾上腺（提及级） | 原发性慢性肾上腺皮质功能减退 | 其他部位结核、肾上腺增大或钙化 | 自身免疫、真菌、出血或转移 |

        ## 结核性胸膜炎

        > [!book] [[999_附件文件夹/02_内科学第10版_按章节/014_0213_胸膜疾病#（二）结核性胸膜炎|教材·结核性胸膜炎]]

        ### 诊断闭环

        1. 先证实胸腔积液并判断漏出/渗出。
        2. 结核性胸水常以淋巴细胞为主、ADA升高，但ADA不是脱离背景的单项确诊指标。
        3. 病原学阳性率有限时，胸膜活检或胸腔镜病理可提高证据等级。
        4. 必须并行排除恶性胸水和肺炎旁积液。

        ### 治疗框架

        - 抗结核原则同活动性肺结核。
        - 蛋白含量高、易粘连，教材强调尽快抽液或置管引流。
        - 教材阈值：首次抽液不超过800 ml，以后每次不超过1000 ml，且不宜过快。
        - 警惕胸膜反应和复张后肺水肿；糖皮质激素疗效不确定，仅在教材限定情形考虑。

        ## 肠结核

        > [!book] [[999_附件文件夹/02_内科学第10版_按章节/040_0407_肠结核和结核性腹膜炎|教材·肠结核和结核性腹膜炎]]

        ### 为什么好发回盲部

        - 含菌肠内容物停留时间较长，增加黏膜感染机会。
        - 回盲部淋巴组织丰富，利于细菌侵犯。

        ### 三种病理类型

        | 类型 | 形态 | 症状/并发症倾向 |
        | --- | --- | --- |
        | 溃疡型 | 环形、不规则溃疡；干酪样坏死 | 腹泻、毒血症；修复后可狭窄 |
        | 增生型 | 肠壁增厚、僵硬、瘤样肿块 | 便秘、右下腹包块、梗阻 |
        | 混合型 | 两者并存 | 表现混合 |

        ### 诊断闭环

        回盲部症状/体征 → CT/MRI或造影 → 结肠镜 → 病灶活检。干酪样肉芽肿具有确诊意义；抗酸杆菌、培养或TB-qPCR阳性增强病原学证据。

        ### 手术警报

        完全性梗阻或内科治疗无效、不闭合穿孔/瘘、大出血不能止血、诊断困难需探查。

        ## 结核性腹膜炎

        ### 病理—临床连接

        - **渗出型**：草黄色或淡血性腹水；全身毒血症可明显。
        - **粘连型**：腹膜和肠系膜增厚、肠袢粘连，可致梗阻。
        - **干酪型**：脓肿、窦道或瘘，急腹症和并发症更多。

        ### 腹水证据

        - 多为渗出液，淋巴/单核细胞为主。
        - 教材提示比重常>1.018、蛋白多>30 g/L、白细胞多>500×10⁶/L。
        - `SAAG < 11 g/L` 有助于诊断；ADA尤其ADA2升高可提供支持，但要排除恶性肿瘤。
        - 不典型且无禁忌时，腹腔镜观察并活检具有重要确诊价值。

        ## 提及级跨系统线索

        > [!note]
        > 下列内容在本教材中不是完整结核专章，只作为“看到何种综合征时想到结核病因”的线索，不外推为完整诊疗方案。

        - **心包**：[[999_附件文件夹/02_内科学第10版_按章节/027_0309_心包疾病|心包疾病]]中，结核性心包炎可伴原发结核表现，心包积液可较大量或血性，淋巴细胞较多；须与化脓性和肿瘤性鉴别。
        - **肾上腺**：[[999_附件文件夹/02_内科学第10版_按章节/097_0707_肾上腺疾病|肾上腺疾病]]提示肾上腺结核可导致原发性慢性肾上腺皮质功能减退，常伴其他部位结核，影像可见增大和钙化。

        ## 原书消化系统章节思维导图

        ![[999_附件文件夹/images/45b0204894ad4fa573d7dc580aca5276a4deb9bd2e8ae94def329ee62b7d7206.jpg]]

        ## 闭卷自测

        1. 结核性胸水为什么要尽早引流？两个单次抽液阈值是什么？
        2. 肠结核为什么好发回盲部？
        3. 肠结核与克罗恩病最有力的病理差异是什么？
        4. 结核性腹膜炎的腹水类型、细胞、SAAG和ADA如何组合？
        5. 哪些线索提示结核性心包炎或肾上腺结核？

        返回：[[00_结核病学习专题]] · 下一步：[[05_鉴别诊断与做题陷阱]]
    """),

    "05_鉴别诊断与做题陷阱.md": clean(r"""
        ---
        note_type: learning_topic_module
        topic: 结核病
        module: 鉴别诊断与做题陷阱
        source_scope: 本地《内科学》第10版
        updated: 2026-08-29
        tags: [结核病, 鉴别诊断, 做题陷阱]
        ---

        # 鉴别诊断与做题陷阱

        > [!book] 原书入口
        > [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【鉴别诊断】|肺结核鉴别诊断]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【危险因素】|NTM危险因素]] · [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核#【NTM 肺病】|NTM肺病]] · [[999_附件文件夹/02_内科学第10版_按章节/040_0407_肠结核和结核性腹膜炎|肠结核/腹膜炎鉴别]]

        ## 肺部空洞/肿块

        | 线索 | 肺结核 | 肺脓肿 | 肺癌 |
        | --- | --- | --- | --- |
        | 病程 | 亚急性/慢性，结核中毒症状 | 急性高热、脓臭痰常见 | 进行性，肿瘤相关线索 |
        | 部位/伴随 | 上肺常见，可有卫星灶、播散灶 | 单个液平空洞常见 | 周围型结节/肿块或阻塞性改变 |
        | 空洞 | 形态多样；周围可有卫星灶 | 液平、感染表现突出 | 偏心、壁厚、内壁不规则或结节突起 |
        | 闭环证据 | MTB病原学/病理 | 细菌学与抗感染反应 | 穿刺/支气管镜病理 |

        ## 肺结核与NTM肺病

        | 比较点 | 肺结核 | NTM肺病 |
        | --- | --- | --- |
        | 传播 | 重点关注人群传播与传染源管理 | 多数来自环境；教材提及某些菌种/人群可能人际传播 |
        | 易感背景 | 接触史及免疫抑制等 | 支扩、硅沉着、既往肺结核、免疫抑制等基础更突出 |
        | 抗酸涂片 | 可阳性 | 也可阳性，故不能靠涂片区分 |
        | 鉴别关键 | 培养菌种鉴定、核酸/测序 | 同左；需避免环境污染造成假阳性 |
        | 病理 | 可见典型干酪样坏死 | 肉芽肿常见但干酪样坏死不明显，胶原玻璃样变可提示 |
        | 治疗 | 标准联合抗结核主线 | 多数对常规抗结核药耐药，方案和疗程明显不同 |

        > [!exam] 抗酸阳性陷阱
        > “抗酸杆菌阳性”只能先进入**分枝杆菌病**路径；必须进一步区分MTB与NTM。

        ## 结核性胸水与其他渗出液

        | 类型 | 优先证据 |
        | --- | --- |
        | 结核性 | 淋巴细胞为主、ADA升高，结合接触/结核证据；病原学或胸膜活检提高确定性 |
        | 恶性 | 胸水细胞学或胸膜活检发现恶性细胞 |
        | 肺炎旁/脓胸 | 急性感染背景；中性粒细胞、生化指标、培养及影像分隔帮助决策 |
        | 漏出性积液 | 先考虑心衰、肝硬化、肾病等全身原因，不要直接套“结核” |

        ## 肠结核与克罗恩病

        | 比较点 | 肠结核 | 克罗恩病 |
        | --- | --- | --- |
        | 肠外结核 | 多见 | 一般无 |
        | 病程 | 复发相对少 | 缓解与复发交替 |
        | 溃疡 | 环形、不规则 | 纵行、裂沟状 |
        | 节段性 | 常不明显 | 多节段、跳跃性 |
        | 瘘/腹腔脓肿/肛周病变 | 少见 | 可见 |
        | 病理/病原 | 干酪样肉芽肿、抗酸杆菌可阳性 | 无干酪样肉芽肿，抗酸染色阴性 |
        | 抗结核反应 | 症状和肠道病变可好转 | 无明显改善 |

        > [!warning]
        > “抗结核治疗有效”是教材临床诊断链的一部分，但不应替代治疗前的内镜活检、培养/核酸和恶性肿瘤排除。

        ## 结核性腹膜炎与腹水鉴别

        - **肝硬化腹水**：多为门脉高压性，教材用 `SAAG ≥ 11 g/L` 作为重要线索。
        - **结核性腹膜炎**：多为渗出性、淋巴细胞为主，`SAAG < 11 g/L`、ADA升高支持。
        - **恶性腹水**：寻找癌细胞、原发灶或腹膜/网膜病变；必要时腹腔镜活检。
        - **自发性细菌性腹膜炎**：在肝硬化背景下更关注多形核细胞和普通细菌培养。

        ## 高频决策句

        1. **PPD/IGRA回答“感染免疫反应”，不独立回答“活动性疾病”。**
        2. **影像提出结核可能，病原学/病理学完成确诊。**
        3. **涂片阳性先说“抗酸杆菌”，培养/核酸再区分MTB与NTM。**
        4. **复治先取药敏，不机械套固定复治方案。**
        5. **回盲部环形溃疡+干酪样肉芽肿偏向肠结核；纵行裂沟+跳跃病变偏向克罗恩病。**
        6. **淋巴细胞性积液+ADA高是线索，不是脱离病原/病理和肿瘤排除的终点。**

        ## 闭卷自测

        1. 抗酸涂片阳性为什么不能直接诊断肺结核？
        2. 肺结核空洞与癌性空洞的三个影像差异是什么？
        3. NTM诊断为什么强调多份同一致病菌培养或支气管肺泡灌洗证据？
        4. 肠结核与克罗恩病分别更常见哪种溃疡？
        5. 面对淋巴细胞性胸水或腹水，如何防止“ADA锚定偏差”？

        返回：[[00_结核病学习专题]] · 下一步：[[06_主动回忆与复习清单]]
    """),

    "06_主动回忆与复习清单.md": clean(r"""
        ---
        note_type: learning_topic_module
        topic: 结核病
        module: 主动回忆与复习
        source_scope: 本地《内科学》第10版
        updated: 2026-08-29
        tags: [结核病, 主动回忆, 复习计划, 306西医综合]
        ---

        # 主动回忆与复习清单

        > [!note] 计划性质
        > 这是教材型默认复习路线，不是根据个人考试日期、每日时间或题库完成度定制的计划。错题证据统一回写到[[998_疾病卡片/02_呼吸系统疾病/肺结核#做题复盘|肺结核疾病卡·做题复盘]]。

        ## 闭卷20问

        ### 机制与病理

        1. 结核分枝杆菌进入人体后，细胞免疫与迟发型超敏反应分别意味着什么？
        2. 渗出、增生、干酪样坏死如何决定吸收、纤维化、空洞与播散？
        3. 潜伏感染、活动性结核和非活动性肺结核如何区分？

        ### 诊断

        4. 肺结核六问诊断闭环是什么？
        5. 痰涂片、培养、核酸和药敏分别解决什么问题？
        6. PPD/IGRA为什么既不能确诊也不能排除活动性结核？
        7. 活动性肺结核按部位有哪些类型？
        8. 病原学检测阴性肺结核如何避免成为“排除不充分”的诊断？

        ### 治疗

        9. 早期、规律、全程、适量、联合分别防什么？
        10. A/B/C/D菌群的状态与优势药物如何对应？
        11. 写出 `2HRZE/4HR` 并解释强化期与巩固期。
        12. H、R、Z、E、S各自最标志性的不良反应是什么？
        13. 复治病例为什么必须尽快获得药敏？
        14. MDR-TB与RR-TB如何定义？

        ### 肺外结核与鉴别

        15. 结核性胸膜炎抽液治疗的两个单次阈值是什么？
        16. 肠结核为何好发回盲部？溃疡型与增生型如何区分？
        17. 肠结核与克罗恩病的溃疡、节段和病理差异是什么？
        18. 结核性腹膜炎的腹水细胞、SAAG、ADA怎样组合？
        19. 肺结核与NTM为什么不能靠抗酸涂片区分？
        20. 结核性心包炎和肾上腺结核各用什么综合征入口联想？

        ## 空白输出模板

        ### 诊断六问

        1. 是否需要筛查：
        2. 是否为肺结核：
        3. 是否活动：
        4. 是否排菌：
        5. 是否耐药：
        6. 初治/复治：

        ### 药物五格

        | 药物 | 优势菌群/作用 | 标志性不良反应 | 监测 | 易错点 |
        | --- | --- | --- | --- | --- |
        | H |  |  |  |  |
        | R |  |  |  |  |
        | Z |  |  |  |  |
        | E |  |  |  |  |
        | S |  |  |  |  |

        ## 复习日程

        | 时间 | 闭卷任务 | 达标标准 |
        | --- | --- | --- |
        | 第1天 | 画总图；回答诊断六问；写HRZE | 主干无提示完成≥80% |
        | 第3天 | 口述五类肺结核；完成药物五格 | 不混淆PPD/IGRA、涂片和培养 |
        | 第7天 | 做四组鉴别：空洞、胸水、回盲部、腹水 | 每组至少写3个判别点 |
        | 第14天 | 混合病例输出完整诊断与治疗原则 | 能说明证据不足处和下一检查 |
        | 第30天 | 重做20问并回看错题 | 正确率≥90%，错误已回写卡片 |

        ## 306最小答题骨架

        ```text
        定位：结核暴露/宿主风险 + 器官综合征
        证据：影像定位 → 病原学/病理 → 活动性 → 排菌 → 耐药
        分型：部位 + 病原学 + 耐药 + 初复治
        治疗：早期、规律、全程、适量、联合；说明强化/巩固
        安全：毒性监测 + 依从性 + 传播控制 + 特殊人群复核
        ```

        ## 掌握度清单

        - [ ] 我能在90秒内画出总流程图。
        - [ ] 我不会把PPD/IGRA阳性写成活动性结核确诊。
        - [ ] 我不会把抗酸涂片阳性直接等同MTB。
        - [ ] 我能解释联合用药为何仍要求规律、全程。
        - [ ] 我能从胸膜、肠、腹膜三个入口识别肺外结核。
        - [ ] 我能在答案中主动写出需要排除的肿瘤或NTM。
        - [ ] 我已把做错的题追加到肺结核卡片，而不是覆盖专题正文。

        返回：[[00_结核病学习专题]] · 查来源：[[07_来源与验证记录]]
    """),

    "07_来源与验证记录.md": clean(r"""
        ---
        note_type: provenance_record
        topic: 结核病
        source_scope: 本地《内科学》第10版
        generated_by: scripts/build_tuberculosis_learning_topic.py
        updated: 2026-08-29
        tags: [结核病, 来源记录, 验证]
        ---

        # 来源与验证记录

        ## 来源分级

        | 级别 | 来源 | 用途 |
        | --- | --- | --- |
        | A 核心主讲 | [[999_附件文件夹/02_内科学第10版_按章节/009_0208_肺结核|009·肺结核]] | 流行病学、机制、病理、诊断、分型、治疗、耐药、防控、NTM |
        | A 专节主讲 | [[999_附件文件夹/02_内科学第10版_按章节/014_0213_胸膜疾病#（二）结核性胸膜炎|014·结核性胸膜炎]] | 胸水鉴别、抽液与抗结核治疗 |
        | A 专章主讲 | [[999_附件文件夹/02_内科学第10版_按章节/040_0407_肠结核和结核性腹膜炎|040·肠结核和结核性腹膜炎]] | 消化系统肺外结核 |
        | B 提及级 | [[999_附件文件夹/02_内科学第10版_按章节/027_0309_心包疾病|027·心包疾病]] | 结核性心包炎线索，不扩写完整方案 |
        | B 提及级 | [[999_附件文件夹/02_内科学第10版_按章节/097_0707_肾上腺疾病|097·肾上腺疾病]] | 肾上腺结核线索，不扩写完整方案 |
        | 既有派生层 | [[998_疾病卡片/02_呼吸系统疾病/肺结核|肺结核306疾病卡]] | 快速背诵与错题回写；不作为教材原文证据替代物 |

        ## 版本边界

        - 本专题只整理本地教材，不混入网络指南、题库答案或未提供的真题统计。
        - 治疗方案、耐药结核和特殊人群内容具有版本性；临床使用前必须核对现行规范。
        - 结核性脑膜炎、骨关节结核、泌尿系结核等在当前核心来源中没有完整专章，因此没有被伪装成“已覆盖”。
        - 心包和肾上腺仅按教材提及级证据收录。

        ## 本地图片

        本专题仅嵌入上述教材实际引用且本地存在的8张图片：自然过程、诊断流程、原发综合征、三类影像、肺结核章思维导图和消化系统章节思维导图。未下载、生成或替换任何教材图片。

        ## 写入边界

        - 生成器只拥有 `00_地图/结核病学习专题/*.md`。
        - 总目录只拥有两个标记之间的专题导航块。
        - 教材章节、图片和疾病卡保持只读。
        - 如已生成专题文件被人工修改，后续 `--write` 会停止并提示冲突，不会静默覆盖。

        ## 可复现命令

        ```powershell
        python -B scripts/build_tuberculosis_learning_topic.py --write
        python -B scripts/build_tuberculosis_learning_topic.py --verify-only
        ```

        ## 校验项目

        - 来源文件SHA-256与执行基线一致。
        - 8张引用图片存在、哈希一致并可解码。
        - 派生文件集合、正文哈希及manifest一致。
        - Obsidian文件链接、标题锚点和图片嵌入无断链。
        - 无替换字符或非法控制字符。
        - 总目录入口存在且标记块唯一。
        - 重复执行不产生文件变化。

        返回：[[00_结核病学习专题]]
    """),
}

WIKI_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)\s*$", re.MULTILINE)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_manifest() -> dict | None:
    if not MANIFEST_PATH.exists():
        return None
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def verify_source_hashes() -> list[str]:
    errors: list[str] = []
    for name, expected in SOURCE_HASHES.items():
        path = ROOT / name
        if not path.is_file():
            errors.append(f"missing_source:{name}")
        elif sha256_path(path) != expected:
            errors.append(f"source_hash_mismatch:{name}")
    return errors


def verify_assets() -> list[str]:
    errors: list[str] = []
    try:
        from PIL import Image
    except ImportError:
        return ["pillow_missing_for_image_decode_check"]
    for name, expected in ASSET_HASHES.items():
        path = ROOT / name
        if not path.is_file():
            errors.append(f"missing_asset:{name}")
            continue
        if sha256_path(path) != expected:
            errors.append(f"asset_hash_mismatch:{name}")
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:  # pragma: no cover - diagnostic branch
            errors.append(f"asset_decode_failed:{name}:{exc}")
    return errors


def existing_topic_files() -> set[str]:
    if not TOPIC_ROOT.exists():
        return set()
    return {path.name for path in TOPIC_ROOT.iterdir() if path.is_file()}


def protect_outputs_before_write(manifest: dict | None) -> list[str]:
    errors: list[str] = []
    expected_names = set(TOPIC_FILES)
    extra = existing_topic_files() - expected_names
    for name in sorted(extra):
        errors.append(f"unregistered_topic_file:{name}")

    registered = (manifest or {}).get("outputs", {})
    for name, desired in TOPIC_FILES.items():
        path = TOPIC_ROOT / name
        if not path.exists():
            continue
        if path.read_text(encoding="utf-8") == desired:
            continue
        prior = registered.get(f"00_地图/结核病学习专题/{name}", {}).get("sha256")
        if not prior or sha256_path(path) != prior:
            errors.append(f"manual_edit_conflict:{name}")
    return errors


def ensure_index_block(write: bool) -> tuple[list[str], bool]:
    errors: list[str] = []
    changed = False
    text = INDEX_PATH.read_text(encoding="utf-8")
    start_count = text.count(INDEX_START)
    end_count = text.count(INDEX_END)
    if start_count == 1 and end_count == 1:
        start = text.index(INDEX_START)
        end = text.index(INDEX_END, start) + len(INDEX_END)
        if text[start:end] != INDEX_BLOCK:
            errors.append("index_block_manual_edit_conflict")
        return errors, changed
    if start_count or end_count:
        return ["index_block_marker_mismatch"], changed
    if not write:
        return ["index_block_missing"], changed
    if sha256_path(INDEX_PATH) != INDEX_BASELINE_SHA256:
        return ["index_baseline_changed_before_first_write"], changed
    anchor = "## 总目录"
    if text.count(anchor) != 1:
        return ["index_insertion_anchor_not_unique"], changed
    new_text = text.replace(anchor, f"{INDEX_BLOCK}\n\n{anchor}", 1)
    INDEX_PATH.write_text(new_text, encoding="utf-8", newline="\n")
    changed = True
    return errors, changed


def write_outputs(manifest: dict | None) -> list[str]:
    changed: list[str] = []
    TOPIC_ROOT.mkdir(parents=True, exist_ok=True)
    for name, desired in TOPIC_FILES.items():
        path = TOPIC_ROOT / name
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != desired:
            path.write_text(desired, encoding="utf-8", newline="\n")
            changed.append(rel(path))
    return changed


def resolve_wiki_target(source: Path, raw_target: str) -> tuple[Path, str | None]:
    target = raw_target.split("|", 1)[0].strip()
    if "#" in target:
        path_text, anchor = target.split("#", 1)
    else:
        path_text, anchor = target, None
    if not path_text:
        path = source
    elif "/" in path_text:
        path = ROOT / path_text
    else:
        path = source.parent / path_text
    if not path.suffix:
        path = path.with_suffix(".md")
    return path, anchor


def verify_links() -> tuple[list[str], int, int]:
    errors: list[str] = []
    link_count = 0
    image_count = 0
    for name in TOPIC_FILES:
        source = TOPIC_ROOT / name
        text = source.read_text(encoding="utf-8")
        for match in WIKI_RE.finditer(text):
            embedded, raw_target = match.groups()
            target, anchor = resolve_wiki_target(source, raw_target)
            link_count += 1
            if embedded:
                image_count += 1
            if not target.exists():
                errors.append(f"broken_wikilink:{name}:{raw_target}")
                continue
            if anchor:
                target_text = target.read_text(encoding="utf-8")
                headings = {item.strip().rstrip("#").rstrip() for item in HEADING_RE.findall(target_text)}
                if anchor not in headings:
                    errors.append(f"broken_anchor:{name}:{raw_target}")
    return errors, link_count, image_count


def verify_outputs(manifest: dict | None) -> list[str]:
    errors: list[str] = []
    expected_names = set(TOPIC_FILES)
    actual_names = existing_topic_files()
    for name in sorted(expected_names - actual_names):
        errors.append(f"missing_output:{name}")
    for name in sorted(actual_names - expected_names):
        errors.append(f"unexpected_output:{name}")
    for name, desired in TOPIC_FILES.items():
        path = TOPIC_ROOT / name
        if not path.exists():
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != desired:
            errors.append(f"output_content_mismatch:{name}")
        if "\ufffd" in actual:
            errors.append(f"replacement_character:{name}")
        if CONTROL_RE.search(actual):
            errors.append(f"control_character:{name}")
    if manifest is None:
        errors.append("manifest_missing")
    else:
        registered = manifest.get("outputs", {})
        for name in sorted(expected_names):
            key = f"00_地图/结核病学习专题/{name}"
            path = TOPIC_ROOT / name
            expected_hash = registered.get(key, {}).get("sha256")
            if not expected_hash:
                errors.append(f"manifest_output_missing:{key}")
            elif path.exists() and sha256_path(path) != expected_hash:
                errors.append(f"manifest_output_hash_mismatch:{key}")
    return errors


def build_manifest() -> dict:
    outputs = {}
    for name in sorted(TOPIC_FILES):
        path = TOPIC_ROOT / name
        outputs[rel(path)] = {
            "sha256": sha256_path(path),
            "bytes": path.stat().st_size,
            "lines": len(path.read_text(encoding="utf-8").splitlines()),
        }
    sources = {}
    for name, digest in SOURCE_HASHES.items():
        path = ROOT / name
        sources[name] = {
            "sha256": digest,
            "bytes": path.stat().st_size,
            "lines": len(path.read_text(encoding="utf-8").splitlines()),
        }
    assets = {}
    from PIL import Image
    for name, digest in ASSET_HASHES.items():
        path = ROOT / name
        with Image.open(path) as image:
            dimensions = [image.width, image.height]
        assets[name] = {"sha256": digest, "bytes": path.stat().st_size, "dimensions": dimensions}
    return {
        "schema": "tuberculosis-learning-topic/v1",
        "generated_on": GENERATED_ON,
        "source_scope": "本地《内科学》第10版指定章节与既有肺结核疾病卡；未混入外部指南或题库答案",
        "topic_root": "00_地图/结核病学习专题",
        "index_path": "00_地图/00_总目录.md",
        "index_markers": [INDEX_START, INDEX_END],
        "sources": sources,
        "assets": assets,
        "outputs": outputs,
        "validation": {
            "expected_topic_files": len(TOPIC_FILES),
            "expected_images": len(ASSET_HASHES),
            "manual_edits_protected": True,
            "source_files_read_only": True,
        },
    }


def write_manifest() -> bool:
    desired = json.dumps(build_manifest(), ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    current = MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.exists() else None
    if current == desired:
        return False
    MANIFEST_PATH.write_text(desired, encoding="utf-8", newline="\n")
    return True


def run(write: bool) -> int:
    errors = verify_source_hashes() + verify_assets()
    manifest = read_manifest()
    if write:
        errors += protect_outputs_before_write(manifest)
    if errors:
        print("ERROR Source/asset/protection conflict; no write performed:")
        for item in errors:
            print(f"- {item}")
        return 1

    index_errors, index_changed = ensure_index_block(write=write)
    if index_errors:
        print("ERROR Index conflict:")
        for item in index_errors:
            print(f"- {item}")
        return 1

    changed_files: list[str] = []
    manifest_changed = False
    if write:
        changed_files = write_outputs(manifest)
        manifest_changed = write_manifest()
        manifest = read_manifest()

    errors = []
    errors += verify_source_hashes()
    errors += verify_assets()
    errors += verify_outputs(manifest)
    link_errors, link_count, image_count = verify_links()
    errors += link_errors
    if image_count != len(ASSET_HASHES):
        errors.append(f"embedded_image_count:{image_count}!={len(ASSET_HASHES)}")
    if link_count < 45:
        errors.append(f"wikilink_count_too_low:{link_count}")
    index_errors, _ = ensure_index_block(write=False)
    errors += index_errors

    if errors:
        print("VERIFY_FAILED")
        for item in errors:
            print(f"- {item}")
        return 1

    if write:
        print(
            "WRITE_OK "
            f"changed_files={len(changed_files)} "
            f"index_changed={str(index_changed).lower()} "
            f"manifest_changed={str(manifest_changed).lower()}"
        )
    print(
        "TUBERCULOSIS_TOPIC_VERIFY_OK "
        f"topic_files={len(TOPIC_FILES)} "
        f"sources={len(SOURCE_HASHES)} "
        f"images={image_count} "
        f"wikilinks={link_count} "
        "broken_links=0 broken_anchors=0 control_character_files=0 "
        "source_hashes_unchanged=true"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true", help="write guarded derived artifacts")
    modes.add_argument("--verify-only", action="store_true", help="verify without writing")
    args = parser.parse_args()
    return run(write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
