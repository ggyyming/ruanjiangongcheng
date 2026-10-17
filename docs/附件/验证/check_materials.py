"""Offline structure/reference checks; no browser, payment or model calls."""

from pathlib import Path
import json
import re
import subprocess
import sys
from urllib.parse import unquote
import xml.etree.ElementTree as ET


DOCS = Path(__file__).resolve().parents[2]
PROTOTYPE = DOCS / '附件' / '原型'
MODELS = DOCS / '附件' / '模型'


def check(node='node'):
    reports = ['需求规格说明书.md', '需求分析质量验证报告.md', 'AI智能体使用验证报告.md']
    files = [DOCS / name for name in reports + ['README_报告材料.md']] + list((DOCS / '附件').rglob('*.md'))
    links = 0
    for file in files:
        text = file.read_text(encoding='utf-8')
        assert '\ufffd' not in text, f'损坏字符：{file}'
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if re.match(r'^[a-z]+://|^#', target, re.I):
                continue
            local = unquote(target.split('#', 1)[0].strip('<>'))
            assert (file.parent / local).exists(), f'失效链接：{file.name} -> {target}'
            links += 1
    source_files = sorted(MODELS.glob('*.drawio'))
    assert len(source_files) == 13
    for source in source_files:
        drawing = ET.parse(source)
        assert drawing.find('diagram') is not None
        cells = drawing.findall('.//mxCell')
        cell_ids = {cell.attrib['id'] for cell in cells}
        for cell in cells:
            if cell.get('edge') == '1':
                assert cell.get('source') in cell_ids and cell.get('target') in cell_ids
        ET.parse(source.with_suffix('.svg'))
        assert source.with_suffix('.png').is_file()

    transition_text = (DOCS / '附件/状态转换说明.md').read_text(encoding='utf-8')
    transitions = re.findall(r'^\| ((?:CP|DR)-ST-\d+) \|', transition_text, re.M)
    assert len(transitions) == len(set(transitions)) == 45
    trace = (DOCS / '附件/需求追踪矩阵.md').read_text(encoding='utf-8')
    traced_requirements = re.findall(r'^\| ((?:CP|DR)-R-\d+) \|', trace, re.M)
    assert len(traced_requirements) == len(set(traced_requirements)) == 40
    assert 'DR-R-08' not in traced_requirements
    srs = (DOCS / reports[0]).read_text(encoding='utf-8')
    defined = re.findall(r'^\| ((?:CP|DR)-R-\d+) \|', srs, re.M)
    assert set(traced_requirements) == set(defined)

    result = subprocess.run([node, '-e', 'process.stdout.write(JSON.stringify(require(process.argv[1])))', str(PROTOTYPE / 'scenarios.js')], capture_output=True, text=True, encoding='utf-8', check=True)
    scenarios = json.loads(result.stdout)
    assert len(scenarios) == 17
    scene_text = (DOCS / '附件/场景走查记录.md').read_text(encoding='utf-8')
    assert len(re.findall(r'^## (?:CP|DR)-SC-', scene_text, re.M)) == 18
    assert '## DR-SC-07：' in scene_text  # 新模块的操作计划，与17个引导场景分开
    for scene in scenarios:
        assert f'## {scene["id"]}：' in scene_text
        for step in scene['steps']:
            assert step['transition'] in transitions, step['transition']

    html = (PROTOTYPE / 'index.html').read_text(encoding='utf-8')
    app = (PROTOTYPE / 'app.js').read_text(encoding='utf-8')
    html_ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(html_ids) == len(set(html_ids))
    assert set(re.findall(r'\$\("([^"]+)"\)', app)) <= set(html_ids)
    for target in re.findall(r'(?:src|href)="([^"#]+)"', html):
        assert (PROTOTYPE / target).is_file()
    scripts = ['engine.js', 'scenarios.js', 'app.js', 'classroom.js', 'check-state.cjs', 'check-classroom.cjs']
    for script in scripts:
        subprocess.run([node, '--check', str(PROTOTYPE / script)], check=True, capture_output=True)

    print(f'通过：{len(files)}份Markdown的{links}个本地链接；13组模型；45条转换、40条有效需求；17个引导场景和1个班级模块场景。')
    print('通过：原型页面元素ID/资源引用和6份JavaScript语法检查。')
    print('范围：本脚本只检查离线结构和源码，不执行浏览器或人工走查，不验证真实业务/资金/模型效果。')


if __name__ == '__main__':
    check(sys.argv[1] if len(sys.argv) > 1 else 'node')
