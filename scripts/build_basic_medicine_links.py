#!/usr/bin/env python3
"""Create an independent, source-linked basic-medicine study atlas.

Only the dedicated output folder is written. Current chapters and old indexes
are read-only. --verify-only checks reproducibility, scope, provenance and links.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import re

import build_internal_medicine_disease_index as inventory
from basic_medicine_knowledge import load

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / '999_附件文件夹/02_内科学第10版_按章节'
OUT = ROOT / '00_地图/全书疾病与基础医学'
CONCEPTS, CHAPTER_MAP, CHAINS = load()
PARTS = {2:'呼吸系统',3:'循环系统',4:'消化系统',5:'泌尿系统',6:'血液系统',7:'内分泌与代谢',8:'风湿免疫',9:'理化因素'}
MECH = re.compile(r'机制|病理|生理|病因')
MORPH = re.compile(r'坏死|纤维化|浸润|增生|萎缩|变性|肉芽肿|硬化|水肿|瘢痕|基底膜|足细胞')
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
# Verified against chapter 029, line 27; used only in this new atlas.
RETRIEVAL_ALIASES={'院内心脏停搏':['院内心脏骤停'],'院外心脏停搏':['院外心脏骤停']}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n'

def plain(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[\[([^]|]+)(?:\|([^]]+))?\]\]', lambda m:m[2] or m[1], text)
    return html.unescape(text).replace('==','').replace('**','').strip()

def norm(text):
    return inventory.match_normalized(plain(text))

def head_key(text):
    text = re.sub(r'^第[^\s|｜]*[章节]\s*[|｜]?\s*', '', text)
    text = re.sub(r'^[（(]?[一二三四五六七八九十百零〇\d]+[）)、.．]\s*', '', text)
    return norm(text)

def link(path, label, anchor=''):
    p = str(path).replace('\\','/')
    if p.endswith('.md'): p = p[:-3]
    return '[['+p+('#'+anchor if anchor else '')+'|'+label.replace('|','／')+']]'

def outlink(name,label=None,anchor=''):
    return link((OUT / name).relative_to(ROOT), label or Path(name).stem, anchor)

def clink(key):
    return outlink('基础机制/'+key+'_'+CONCEPTS[key]['title']+'.md',CONCEPTS[key]['title'])

def source_link(filename, label=None):
    return link((BOOK/filename).relative_to(ROOT),label or filename.split('_',2)[-1][:-3])

def source_data(path):
    raw = path.read_text(encoding='utf-8')
    lines = raw.splitlines()
    fm = re.match(r'\A---\n.*?\n---\n',raw,re.S)
    first = raw[:fm.end()].count('\n') if fm else 0
    headings=[]; paragraphs=[]; current='正文'; mechanism=False; category='正文'
    for index,line in enumerate(lines):
        if index < first: continue
        m=re.match(r'^(#{1,6})\s+(.+)',line)
        if m:
            current=m[2]; headings.append(dict(line=index+1,level=len(m[1]),text=current,key=head_key(current)))
            # Heading levels in OCR are not always nested semantically: reset on a new named module.
            if '【' in current or len(m[1])==1:
                mechanism=bool(MECH.search(current))
                category=('病理生理' if '病理生理' in current else '病理形态' if '病理' in current else
                    '发病机制' if '机制' in current else '病因' if '病因' in current else
                    '临床表现' if '临床表现' in current else '其他')
            elif MECH.search(current): mechanism=True
            elif re.search(r'治疗|诊断|临床表现|辅助检查|预后|预防',current): mechanism=False
            continue
        clean=plain(line)
        if len(clean)<6 or clean=='本章数字资源' or clean.startswith(('>','!','<!--')): continue
        paragraphs.append(dict(line=index+1,raw=line,clean=clean,heading=current,mechanism=mechanism,category=category))
    pages=re.search(r'^printed_pages:\s*"?([^"\n]+)',raw,re.M)
    return dict(lines=lines,headings=headings,paragraphs=paragraphs,pages=pages[1] if pages else '未标注')

def scope_for(row, data):
    names=[norm(v) for v in [row['name'],*row.get('aliases',[]),*RETRIEVAL_ALIASES.get(row['name'],[])]
        if len(norm(v))>=3 or (len(norm(v))==2 and re.search('[\u3400-\u9fff]',v))]
    hits=[h for h in data['headings'] if h['key'] in names]
    if hits:
        h=min(hits,key=lambda h:h['line'])
        end=next((x['line'] for x in data['headings'] if x['line']>h['line'] and x['level']<=h['level']),len(data['lines'])+1)
        return names,'准确标题范围',h['line'],end,h['text']
    if norm(row['primary_chapter_title']) in names:
        return names,'同名章节范围',1,len(data['lines'])+1,row['primary_chapter_title']
    return names,'正文提及范围',0,0,''

def excerpt(clean):
    # Keep complete short sentences where possible; ellipsis explicitly indicates a partial excerpt.
    if len(clean)<=420:return clean
    sentence=re.split(r'(?<=[。；])',clean)
    result=''
    for s in sentence:
        if len(result+s)>420:break
        result+=s
    # Avoid cutting through source equations: omit oversized formula-containing lines.
    if not result and '$' in clean:return '此段含较长公式或表述，请按所列原文行号阅读。'
    return (result or clean[:400])+'……（节录）'

def build_records(rows,cache):
    records=[]
    for num,row in enumerate(rows,1):
        chapter=row['primary_chapter'];data=cache[chapter]
        names,tier,start,end,heading=scope_for(row,data)
        has_name=lambda p:any(n in norm(p['clean']) for n in names)
        if start:
            candidates=[(chapter,p,True) for p in data['paragraphs'] if start<p['line']<end]
        else:
            candidates=[(chapter,p,False) for p in data['paragraphs'] if has_name(p)]
        rank={'病理生理':0,'发病机制':1,'病理形态':2,'病因':3,'临床表现':4,'正文':5,'其他':6}
        candidates.sort(key=lambda item:(rank.get(item[1]['category'],6),not bool(MORPH.search(item[1]['clean'])),not has_name(item[1]),item[1]['line']))
        selected=[]; categories=set()
        for item in candidates:
            if item[1]['category'] not in categories and len(selected)<4:
                selected.append(item);categories.add(item[1]['category'])
        for item in candidates:
            if len(selected)>=4:break
            if item not in selected:selected.append(item)
        if not start:
            for other in sorted(row.get('chapter_mentions',{}),key=lambda n:-row['chapter_mentions'][n]):
                if other==chapter or len(selected)>=4:continue
                found=[p for p in cache[other]['paragraphs'] if has_name(p)]
                found.sort(key=lambda p:(not p['mechanism'],p['line']))
                if found:selected.append((other,found[0],False))
        # The acid-base chapter explicitly sends this topic to Part 5, Chapter 10.
        if row['name']=='代谢性酸中毒' and any('见第五篇第十章' in p['clean'] for _,p,_ in selected):
            target=next(n for n in cache if n.startswith('068_'))
            found=[p for p in cache[target]['paragraphs'] if has_name(p)]
            found.sort(key=lambda p:(not p['mechanism'],p['line']))
            selected.extend((target,p,False) for p in found[:3])
        evidence=[];concept_hits=defaultdict(list)
        for fn,p,scoped in selected:
            idx=len(evidence)+1
            evidence.append(dict(id=idx,chapter=fn,line=p['line'],heading=p['heading'],
                raw_sha256=digest(p['raw'].encode()),excerpt=excerpt(p['clean']),
                role='疾病范围内段落' if scoped else '提及语境，不能单独证明该病机制',
                mechanism_section=p['mechanism']))
            for key,c in CONCEPTS.items():
                words=[w for w in c['keywords'] if w.lower() in p['clean'].lower()]
                if words:concept_hits[key].append(dict(evidence=idx,words=words))
        cid=int(chapter[:3]);pre=CHAPTER_MAP[cid]
        # Keyword-based routes are explicitly labelled as retrieval hints, never asserted causal edges.
        routes=sorted(concept_hits,key=lambda k:(k not in pre,-len(concept_hits[k]),k))[:7]
        only_redirect=bool(evidence) and all(len(e['excerpt'])<60 and '见' in e['excerpt'] for e in evidence)
        records.append(dict(id=f'D{num:04d}',name=row['name'],aliases=row.get('aliases',[]),retrieval_aliases=RETRIEVAL_ALIASES.get(row['name'],[]),
            kind=row['kind'],part=row['part_number'],chapter=chapter,inventory_evidence=row['evidence'],
            scope=tier,scope_heading=heading,scope_lines=[start,end],evidence=evidence,
            prerequisites=pre,concept_routes=[dict(concept=k,basis=concept_hits[k],status='关键词定位线索，需结合语境') for k in routes],
            status='教材仅转引' if only_redirect else ('有疾病范围证据' if start and evidence else ('仅有提及语境' if evidence else '未定位正文证据')),
            morphology_evidence=any(MORPH.search(e['excerpt']) for e in evidence)))
    return records

def page(title,content):
    return '# '+title+'\n\n'+outlink('00_学习总览.md','返回学习总览')+'\n\n'+content.rstrip()+'\n'

def render(records,cache,drift):
    result={};counts=Counter(r['status'] for r in records)
    by_num={int(n[:3]):n for n in cache}
    by_part=defaultdict(list)
    for r in records:by_part[r['part']].append(r)
    intro='''把每个疾病放回这条链上：**正常结构与功能 → 病因作用点 → 分子／细胞损伤 → 组织形态改变 → 功能障碍 → 症状、体征与检查**。最后再理解干预为什么可能有效。

这里的“生理学”回答正常怎样工作，“病理学”回答结构怎样改变，“病理生理学”解释功能怎样失衡。生化、免疫、微生物、遗传和药理帮助补足中间环节。某些功能性疾病没有显著形态病变，不能强行补出病理图像。

```mermaid
flowchart LR
 A[正常解剖与组织结构] --> B[正常生理与生化]
 C[感染 遗传 免疫 代谢 理化因素] --> D[细胞与分子改变]
 D --> E[组织病理改变]
 B --> F[功能障碍及代偿]
 E --> F
 D --> F
 F --> G[症状 体征 检查]
 F --> H[反向追问干预靶点]
```

## 如何使用

1. 先读所在系统的章级主线，补正常功能。
2. 到逐病表定位疾病，读原文证据和基础机制入口。
3. 用自己的话串起因果链；缺哪一环就回教材，不把关键词共现当成因果证明。
4. 用跨系统对照与闭卷题检查是否真正理解。

## 范围和证据边界

本专题以当前《内科学》第10版的131个章节为范围；653个条目来自当前正文和书末索引重建，包含疾病组、综合征及临床状态，不等于653种互不重叠的独立疾病。未整合西氏内科学，也未引用外部基础医学仓库的未核对笔记。

基础机制卡和代表性因果链是教学综合，附对应原书入口；逐病表的短引文来自当前本地正文。**章节先修知识不等于该章每个疾病都具备该机制；关键词入口仅用于定位，未被包装成逐病因果结论。**仅提及的条目明确保留证据层级。教材学习资料不包含新的治疗方案或剂量推荐。
'''
    intro+='\n## 覆盖情况\n\n'+f'- 章节：{len(cache)}；逐病条目：{len(records)}；基础机制：{len(CONCEPTS)}；代表性因果链：{len(CHAINS)}。\n'
    intro+=''.join(f'- {s}：{n}。\n' for s,n in counts.items())
    intro+='- 完成的是全书范围的关联导航与有来源的学习资料；不将自动定位结果宣称为全部疾病的独立机制论证。\n'
    intro+='\n## 分系统学习\n\n| 系统 | 章级主线 | 逐病关联 | 条目数 |\n|---|---|---|---|\n'
    for p,title in PARTS.items():
        intro+=f'| {title} | {outlink(f"系统主线/{p:02d}_{title}.md","正常功能—病变—后果")} | {outlink(f"逐病关联/{p:02d}_{title}.md","逐病证据与入口")} | {len(by_part[p])} |\n'
    intro+='\n## 其他入口\n\n'+ '\n'.join('- '+outlink(n,l) for n,l in [('01_基础机制目录.md','按基础学科和机制学习'),('02_跨系统对照.md','同一机制串联不同系统'),('03_全书疾病检索.md','653项疾病快速检索'),('04_章节覆盖与来源.md','131章覆盖与来源记录'),('05_闭卷自测.md','闭卷推理练习'),('06_证据边界与待核对.md','证据层级、旧索引变动与待核对条目')])
    result['00_学习总览.md']='# 全书疾病与基础医学关联\n\n'+intro+'\n'
    index='| 机制 | 涉及学科 | 学习任务 |\n|---|---|---|\n'
    for key,c in CONCEPTS.items():
        index+=f'| {clink(key)} | {c["disciplines"]} | {c["boundary"]} |\n'
        body=f'## 正常怎样工作\n\n{c["normal"]}\n\n## 哪一步失效，造成什么后果\n\n{c["damage"]}\n\n## 最容易混淆的地方\n\n{c["boundary"]}\n\n## 对照教材\n\n'
        body+='\n'.join('- '+source_link(by_num[n]) for n in c['chapters'])
        body+='\n\n## 从逐病证据反查\n\n以下为原文关键词定位到此主题的条目，不代表这些疾病都共享完全相同的机制。\n\n'
        matched=[r for r in records if any(v['concept']==key for v in r['concept_routes'])]
        for r in matched:
            body+='- '+outlink(f'逐病关联/{r["part"]:02d}_{PARTS[r["part"]]}.md',r['name'],r['id'])+'\n'
        if not matched:body+='本次短引文中没有匹配条目；上方教材仍是本主题的学习入口。\n'
        body+='\n## 主动回忆\n\n- [ ] 描述正常功能，不使用疾病名称替代机制。\n- [ ] 选两种疾病，比较启动因素和共同终末后果。\n- [ ] 解释一个症状或检查结果，并说出该推断不能证明什么。\n'
        result[f'基础机制/{key}_{c["title"]}.md']=page(c['title'],body)
    result['01_基础机制目录.md']=page('基础机制目录',index)
    for part,title in PARTS.items():
        chapters=[n for n in sorted(cache) if int(n.split('_')[1][:2])==part]
        body='这些是按章节安排的先修知识；多病章节应继续进入逐病证据确认具体适用范围。\n\n| 教材章节 | 优先回顾的基础知识 |\n|---|---|\n'
        for fn in chapters:body+='| '+source_link(fn)+' | '+'；'.join(clink(k) for k in CHAPTER_MAP[int(fn[:3])])+' |\n'
        body+='\n## 代表性因果链\n\n'
        for c in CHAINS:
            fn=by_num[c['chapter']]
            if fn not in chapters:continue
            body+=f'### {c["disease"]}\n\n{c["text"]}\n\n**推理题：**{c["question"]}\n\n依据入口：{source_link(fn)}。这是本章教学综合，疾病亚型仍以原文为准。\n\n'
        body+='\n'+outlink(f'逐病关联/{part:02d}_{title}.md','进入本系统所有疾病')
        result[f'系统主线/{part:02d}_{title}.md']=page(title+'：基础医学主线',body)
        body='按现有索引的主要出处分组，分组不等于病因学归属。例如休克虽可能出现在呼吸章节，仍应从循环灌注机制理解。\n\n原文行号指当前章节Markdown文件；节录保留教材措辞及其可能的OCR问题，理解时应查看完整上下文。\n\n'
        for r in by_part[part]:
            body+=f'## {r["id"]}\n\n### {r["name"]}\n\n'
            body+=f'条目性质：{r["kind"]}；证据：**{r["status"]}**；范围：{r["scope"]}。\n\n'
            if r['aliases']:body+='别名：'+'、'.join(r['aliases'])+'。\n\n'
            if r['retrieval_aliases']:body+='本次核对的原文称谓：'+'、'.join(r['retrieval_aliases'])+'（心脏骤停章L27）；旧索引名称保持不变。\n\n'
            body+='教材：'+source_link(r['chapter'])+'。\n\n'
            body+='**章节先修：**'+'；'.join(clink(k) for k in r['prerequisites'])+'。这些是所在章的学习背景。\n\n'
            if r['concept_routes']:
                body+='**本条原文中的基础医学线索：**\n\n'
                for route in r['concept_routes']:
                    basis='；'.join('证据'+str(b['evidence'])+'：'+ '、'.join(b['words']) for b in route['basis'])
                    body+='- '+clink(route['concept'])+'（'+basis+'）。\n'
                body+='\n'
            else:body+='本次短引文未定位特定机制词，不能据此判断该机制不存在。\n\n'
            for e in r['evidence']:
                body+=f'**证据{e["id"]}**：{source_link(e["chapter"])}，L{e["line"]}；{plain(e["heading"])}；{e["role"]}。\n\n'
                body+='> '+e['excerpt'].replace('\n','\n> ')+'\n\n'
            if not r['evidence']:body+='未定位到足够清楚的正文证据，保留条目，回原书索引和全文核对。\n\n'
            body+='**闭卷串联：**正常结构／功能是什么 → 本病影响哪一环 → 哪项结构或功能证据支持 → 能解释什么表现。原文没有给出的环节应标为待补，不凭同章共现补全。\n\n'
        result[f'逐病关联/{part:02d}_{title}.md']=page(title+'：逐病关联',body)
    search='| 疾病／状态 | 所在系统 | 证据层级 |\n|---|---|---|\n'
    for r in sorted(records,key=lambda r:r['name']):
        search+='| '+outlink(f'逐病关联/{r["part"]:02d}_{PARTS[r["part"]]}.md',r['name'],r['id'])+f' | {PARTS[r["part"]]} | {r["status"]} |\n'
    result['03_全书疾病检索.md']=page('全书疾病检索',search)
    coverage='覆盖全部131章，包括总论、症状章和治疗技术章；没有疾病主条目的章节仍登记为基础或支持内容。章级覆盖不等于逐句精读或所有机制已独立核证。\n\n| 章 | 印刷页 | 作为主要出处的条目数 | 基础知识入口 |\n|---|---|---|---|\n'
    for fn,data in sorted(cache.items()):
        coverage+='| '+source_link(fn)+f' | {data["pages"]} | {sum(r["chapter"]==fn for r in records)} | '+'；'.join(clink(k) for k in CHAPTER_MAP[int(fn[:3])])+' |\n'
    result['04_章节覆盖与来源.md']=page('章节覆盖与来源',coverage)
    questions='先闭卷作答，再打开对应系统主线和原文；不以背出药名或诊断数字代替机制。\n\n'
    for i,c in enumerate(CHAINS,1):questions+=f'{i}. **{c["disease"]}：**{c["question"]}（{source_link(by_num[c["chapter"]],"原文") }）\n'
    result['05_闭卷自测.md']=page('闭卷自测',questions)
    boundary='''## 证据如何分层

- **有疾病范围证据**：名称或别名准确匹配章名或标题，短引文位于该范围内；仍可能包含亚型、并发症或鉴别内容，需要读上下文。
- **仅有提及语境**：只能在提及该名称的段落定位；不把该段主病机制移植给被提及疾病。
- **未定位正文证据**：保留检索入口，不编造机制。
- **教材仅转引**：该处只让读者参见其他教材或章节，没有把转引当作已展开的机制。
- **关键词定位线索**：是可复核的词语共现，可能包含否定、比较或鉴别语境，不能独立证明因果关系。
- **教学综合**：基础机制卡与代表性因果链由正常功能和原书疾病章节串联；不冒充原文逐字结论。

## 本次来源核对

旧索引的11个章节哈希与当前正文不同。本次调用既有索引解析器在内存中重建，653个名称集合一致，未改写旧索引。新专题登记当前源文件哈希。今后源文件或人工修改的专题文件发生变化时，脚本拒绝静默覆盖。

病理形态与病理生理分别理解，不能因为标题含“病理生理”就声称已经找到组织形态。未自动分配超敏反应分型；未把同系统的所有疾病套用相同病理。

## 与旧索引哈希不同的章节

'''
    boundary+='\n'.join('- '+source_link(fn) for fn in drift)+'\n\n## 需结合全文确认的条目\n\n'
    for r in records:
        if r['status']!='有疾病范围证据':boundary+='- '+outlink(f'逐病关联/{r["part"]:02d}_{PARTS[r["part"]]}.md',r['name'],r['id'])+'：'+r['status']+'。\n'
    result['06_证据边界与待核对.md']=page('证据边界与待核对',boundary)
    pairs=[('低氧与组织供氧','02','肺炎的肺泡问题、贫血的血红蛋白问题、休克的血流问题与中毒的携氧／用氧问题可以汇合为组织供氧不足。先定位氧运输链的断点，再解释检查。',[7,71,20,126]),('水肿','08','心衰追踪静脉压力，肾病追踪蛋白与钠水处理，肝硬化追踪门静脉、合成与有效循环，ARDS追踪屏障通透性。同一体征不代表同一机制。',[20,60,48,16]),('免疫性损伤','20','Graves病关注受体刺激，狼疮关注多种免疫损伤及免疫复合物，部分血管炎关注血管壁炎症。抗体是线索，其效应机制需逐病确认。',[95,111,114]),('纤维化','12','肺纤维化限制扩张与弥散，肝纤维化改变血流结构，肾脏硬化减少功能单位，系统性硬化症同时涉及血管和多器官基质改变。',[11,48,68,116]),('血栓与出血','19','肺栓塞关注来源与肺循环，冠脉事件关注斑块与局部血栓，DIC关注全身凝血消耗，抗磷脂综合征关注免疫与血栓倾向。',[12,22,86,120]),('生化缺陷与形态','17','铁缺乏、DNA合成障碍与红细胞酶缺陷分别影响血红蛋白合成、细胞成熟及红细胞存活，故不能把贫血只理解为一个低数值。',[72,73,75]),('肾脏与全身稳态','16','肾病不仅改变肌酐，还影响容量、钾和酸碱、红细胞生成、钙磷骨代谢；用各功能模块解释不同并发症。',[64,68,102,104]),('结构损伤与功能异常','33','功能性胃肠病和纤维肌痛需要理解信号加工与调节；缺乏明显形态异常并不等于症状不存在，也不替代必要的器质性病因判断。',[43,124])]
    cross=''
    for title,key,text,nums in pairs:cross+=f'## {title}\n\n{text}\n\n基础入口：{clink(key)}。教材对照：'+ '；'.join(source_link(by_num[n]) for n in nums)+'。\n\n'
    result['02_跨系统对照.md']=page('跨系统机制对照',cross)
    return result

def validate(outputs,records,cache,sources):
    assert len(CHAPTER_MAP)==len(cache)==131
    assert len({r['name'] for r in records})==len(records)==653
    assert all(k in CONCEPTS for keys in CHAPTER_MAP.values() for k in keys)
    lookup={(OUT/n).relative_to(ROOT).as_posix():s for n,s in outputs.items() if n.endswith('.md')}
    errors=[];links=0;evidence=0
    for name,text in outputs.items():
        if CONTROL.search(text):errors.append('control:'+name)
        if not name.endswith('.md'):continue
        for target in re.findall(r'\[\[([^]|]+)(?:\|[^]]*)?\]\]',text):
            links+=1;path,sep,anchor=target.partition('#');path+='.md'
            if path in lookup:target_text=lookup[path]
            elif (ROOT/path).is_file():target_text=(ROOT/path).read_text(encoding='utf-8')
            else:errors.append('link:'+target);continue
            if sep and anchor not in re.findall(r'^#{1,6}\s+(.+)$',target_text,re.M):errors.append('anchor:'+target)
    for r in records:
        for e in r['evidence']:
            evidence+=1;line=cache[e['chapter']]['lines'][e['line']-1]
            if digest(line.encode())!=e['raw_sha256']:errors.append('evidence:'+r['id'])
    for p,h in sources.items():
        if digest((ROOT/p).read_bytes())!=h:errors.append('source changed:'+p)
    if errors:raise RuntimeError('\n'.join(errors[:30]))
    return dict(chapters=len(cache),diseases=len(records),concepts=len(CONCEPTS),representative_chains=len(CHAINS),
        notes=sum(n.endswith('.md') for n in outputs),source_evidence_paragraphs=evidence,wikilinks=links,
        broken_links=0,broken_anchors=0,source_hashes_unchanged=True,evidence_counts=dict(Counter(r['status'] for r in records)))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    chapters=inventory.load_chapters(BOOK)
    idxpath=BOOK/'90_附录/10_中英文名词对照索引.md'
    idx,unparsed=inventory.parse_bilingual_index(idxpath)
    if unparsed:raise RuntimeError('Unparsed source index entries')
    diseases=inventory.build_diseases(chapters,idx)
    current=json.loads(inventory.render_json(diseases,chapters,idx,unparsed))
    old=json.loads((BOOK/'00_全书疾病清单.json').read_text(encoding='utf-8'))
    if {r['name'] for r in current['diseases']}!={r['name'] for r in old['diseases']}:
        raise RuntimeError('Disease inventory changed; inspect coverage before rebuilding')
    source_paths=[BOOK/n for n in current['source_chapter_hashes']]+[idxpath,BOOK/'00_全书疾病清单.json']
    sources={p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in source_paths}
    drift=[n for n,h in current['source_chapter_hashes'].items() if h!=old['source_chapter_hashes'].get(n)]
    cache={n:source_data(BOOK/n) for n in current['source_chapter_hashes']}
    records=build_records(current['diseases'],cache)
    outputs=render(records,cache,drift)
    outputs['关联清单.json']=dumps(dict(schema='basic-medicine-atlas-v1',scope='内科学第10版当前131章及653条目',
        source_hashes=sources,old_index_drift=drift,records=records))
    stats=validate(outputs,records,cache,sources)
    outputs['验证报告.json']=dumps(stats)
    manifest=dict(schema='basic-medicine-atlas-v1',source_hashes=sources,
        generator_hashes={p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in [Path(__file__),Path(__file__).with_name('basic_medicine_knowledge.py')]},
        output_hashes={n:digest(v.encode('utf-8')) for n,v in outputs.items()})
    mp=OUT/'manifest.json'
    if mp.exists():
        previous=json.loads(mp.read_text(encoding='utf-8'))
        if previous['source_hashes']!=sources:raise RuntimeError('Source changes detected; refusing overwrite')
        for n,h in previous['output_hashes'].items():
            if not (OUT/n).is_file() or digest((OUT/n).read_bytes())!=h:raise RuntimeError('Manual output changes: '+n)
        unknown={p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()}-set(previous['output_hashes'])-{'manifest.json'}
        if unknown:raise RuntimeError('Unregistered output files: '+str(unknown))
    outputs['manifest.json']=dumps(manifest)
    changed=0
    for n,value in outputs.items():
        p=OUT/n;data=value.encode('utf-8')
        if p.exists() and p.read_bytes()==data:continue
        if args.verify_only:raise RuntimeError('Output differs or missing: '+n)
        if p.exists() and not mp.exists():raise RuntimeError('Unregistered existing file: '+str(p))
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);changed+=1
    for name,expected in outputs.items():
        if (OUT/name).read_bytes()!=expected.encode('utf-8'):raise RuntimeError('Persistence mismatch: '+name)
    print('BASIC_MEDICINE_LINKS_VERIFY_OK')
    print(dumps({**stats,'changed_files':changed}))

if __name__=='__main__':main()
