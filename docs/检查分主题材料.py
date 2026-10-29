"""Check split report scopes, local references, model exports and retained evidence."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote
import hashlib
import json
import re
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent

def table_blocks(text):
    return re.findall(r'(?:^\|[^\n]*\n?)+', text, re.M)

def check_tables(text, name):
    for block in table_blocks(text):
        rows = block.strip().splitlines()
        assert len(rows) >= 2, (name, '孤立表格行', rows[0])
        cells = [c.strip() for c in rows[1].strip('|').split('|')]
        assert all(re.fullmatch(r':?-{3,}:?', c) for c in cells), (name, '缺少Markdown表格分隔行', rows[0])
        columns = len(rows[0].strip('|').split('|'))
        assert all(len(row.strip('|').split('|')) == columns for row in rows), (name, '表格列数不一致')

def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()

for folder, prefix, expected in [
    ('校园物品流转平台', 'CP', (27, 8, 37, 11)),
    ('需求文档智能审查系统', 'DR', (13, 5, 15, 7)),
]:
    root = BASE / folder
    requirements, models, states, scenes = expected
    def asset(name):
        attachment = root / '附件'
        if prefix != 'CP':
            return attachment / ('模型' if name == '模型图片' else name)
        if name == '模型图片': return attachment / '02_模型图/01_查看图片'
        if name == '模型': return attachment / '02_模型图'
        if name == '模型/修订模型清单.json': return attachment / '08_维护工具/修订模型清单.json'
        if name.startswith('模型/'):
            leaf = name.split('/', 1)[1]
            suffix = Path(leaf).suffix
            if suffix in {'.png', '.drawio', '.svg'}:
                category = {'.png': '01_查看图片', '.drawio': '02_可编辑源文件', '.svg': '03_SVG矢量图'}[suffix]
                return attachment / '02_模型图' / category / leaf
            return attachment / '02_模型图' / leaf
        if name == '原型': return attachment / '03_场景与原型/原型'
        if name == '历史版本': return attachment / '07_历史版本'
        if name == '验证': return attachment / '04_验证证据'
        if name == '场景走查记录.md': return attachment / '03_场景与原型' / name
        if name in {'业务细则确认记录.md', '规则与模型复核清单.md', '状态转换说明.md', '需求追踪矩阵.md'}:
            return attachment / '01_规则与数据' / name
        return attachment / name
    reports = ['需求规格说明书.md', '需求分析质量验证报告.md', 'AI智能体使用验证报告.md']
    for name in reports:
        assert (root / name).is_file(), name
        check_tables((root / name).read_text(encoding='utf-8'), root / name)
    srs = (root / reports[0]).read_text(encoding='utf-8')
    if prefix == 'CP':
        metadata = []
        for name in reports:
            report_text = (root / name).read_text(encoding='utf-8')
            group = re.search(r'^- 小组编号：([^\n]*)', report_text, re.M).group(1).strip()
            members = re.search(r'^- 成员名单：([^\n]*)', report_text, re.M).group(1).strip()
            metadata.append((group, members))
            assert '文档版本：1.0。' in report_text, (name, '当前版本未同步')
        assert len(set(metadata)) == 1 and metadata[0][0] == '9', '小组信息未同步'
        decisions = (asset('业务细则确认记录.md')).read_text(encoding='utf-8')
        decision_ids = re.findall(r'^## (CP-D-\d+)：', decisions, re.M)
        assert len(decision_ids) == 23 and set(decision_ids) == {f'CP-D-{i:02d}' for i in range(1, 24)}, '业务细则缺失或重复'
        assert '不采集或持久化真实个人数据' in srs, '数据阶段边界未同步'
    other = 'DR' if prefix == 'CP' else 'CP'
    assert not re.search(rf'{other}-(?:R|BR|UC|Q)-\d+', srs), '需求正文混入另一主题'
    for name in reports[1:]:
        text = (root / name).read_text(encoding='utf-8')
        assert 'B5' in text if name.startswith('AI') else '## A.8' in text
    counts = (
        len(re.findall(rf'^\| {prefix}-R-\d+ \|', (asset('需求追踪矩阵.md')).read_text(encoding='utf-8'), re.M)),
        len(list(asset('模型图片').glob('*.png'))),
        len(re.findall(rf'^\| {prefix}-ST-\d+ \|', (asset('状态转换说明.md')).read_text(encoding='utf-8'), re.M)),
        len(re.findall(rf'^## {prefix}-SC-\d+', (asset('场景走查记录.md')).read_text(encoding='utf-8'), re.M)),
    )
    assert counts == expected, (folder, counts, expected)
    definitions = set(re.findall(rf'^\|\s*({prefix}-R-\d+)\s*\|', srs, re.M))
    traced = re.findall(rf'^\|\s*({prefix}-R-\d+)\s*\|', (asset('需求追踪矩阵.md')).read_text(encoding='utf-8'), re.M)
    assert len(traced) == len(set(traced)) and set(traced) == definitions, (folder, '需求定义与追踪编号不一致')
    scene_text = (asset('场景走查记录.md')).read_text(encoding='utf-8')
    scene_definitions = set(re.findall(rf'^## ({prefix}-SC-\d+)', scene_text, re.M))
    scene_index = re.findall(rf'^\| ({prefix}-SC-\d+) ', scene_text, re.M)
    assert len(scene_index) == len(set(scene_index)) and set(scene_index) == scene_definitions, (folder, '场景目录与正文不一致')
    for name in ['需求追踪矩阵.md', '状态转换说明.md', '场景走查记录.md', '规则与模型复核清单.md', '模型/README.md']:
        check_tables(asset(name).read_text(encoding='utf-8'), name)
    revision_path = asset('模型/修订模型清单.json')
    revisions = json.loads(revision_path.read_text(encoding='utf-8'))['sha256'] if revision_path.exists() else {}
    if revisions:
        expected_revisions = {f'CP-M-{i:02d}.{ext}' for i in [3, 4, 5, 6, 7, 8] for ext in ['drawio', 'svg', 'png']}
        assert prefix == 'CP' and set(revisions) == expected_revisions, '只允许清单列明的六组本轮修订模型'
    for png in asset('模型图片').glob('*.png'):
        for suffix in ['.png', '.svg', '.drawio']:
            local = asset(f'模型/{png.stem}{suffix}')
            if local.name in revisions:
                assert hashlib.sha256(local.read_bytes()).hexdigest() == revisions[local.name], local
            else:
                assert digest(local) == digest(BASE / '附件/模型' / local.name), local
            if suffix != '.png':
                ET.parse(local)
    checked_links = 0
    for md in root.rglob('*.md'):
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', md.read_text(encoding='utf-8')):
            target = target.split('#', 1)[0].strip('<>')
            if not target or re.match(r'\w+://', target):
                continue
            path = (md.parent / target).resolve()
            assert path.is_relative_to(root.resolve()), (md, '跨文件夹引用', target)
            assert path.exists(), (md, '引用缺失', target)
            checked_links += 1
    # History, original feedback and the shared executable are copied without edits.
    for sub in ['原型', '历史版本', '验证']:
        collection = asset(sub)
        assert collection.is_dir(), collection
        for path in collection.rglob('*'):
            if path.is_file():
                relative = path.relative_to(collection)
                if prefix == 'CP' and sub == '历史版本' and relative.parts[0] == '校园模型_v0.1':
                    original = BASE / '附件/模型' / path.name
                elif prefix == 'CP' and sub == '历史版本' and relative.parts[0] == '联合审查模型_v0.1':
                    original = BASE / '附件/历史版本/模型_v0.1' / path.name
                else:
                    original = BASE / '附件' / sub / relative
                assert original.is_file() and digest(original) == digest(path), path
    assert (asset('实验报告离线阅读.html')).is_file()
    if prefix == 'CP':
        class HtmlLinks(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links, self.ids = [], set()
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if 'id' in attrs: self.ids.add(attrs['id'])
                if tag == 'a': self.links.append(attrs['href'])
        navigation = asset('00_附件导航.html')
        nav_text = navigation.read_text(encoding='utf-8')
        nav = HtmlLinks()
        nav.feed(nav_text)
        for link in nav.links:
            path, sep, fragment = link.partition('#')
            target = (navigation.parent / unquote(path)).resolve()
            assert target.is_relative_to(root.resolve()) and target.exists(), (navigation, link)
            if sep:
                destination = HtmlLinks()
                destination.feed(target.read_text(encoding='utf-8'))
                assert fragment in destination.ids, (navigation, link, '页内目标不存在')
        assert re.findall(r'<h2>(\d{2}) ', nav_text) == [f'{i:02d}' for i in range(1, 9)], '附件导航分类顺序错误'
        print(f'通过：校园附件导航{len(nav.links)}个本地入口及页内目标；分类01至08顺序正确。')
    print(f'通过：{folder}，三份报告；需求/图/状态/场景={counts}；{checked_links}个本地引用有效且未越出文件夹；模型版本和历史证据核验通过。')
print('范围：只核验拆分内容、文件引用及复制完整性，不增加业务或人工走查结论。')
