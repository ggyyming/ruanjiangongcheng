"""Build a self-contained local reader from the current reports and PNG models."""

import base64
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
DOCS = ROOT.parent
OUTPUT = ROOT / '实验报告离线阅读.html'
PRIMARY = [ROOT / '规则与模型复核清单.md'] + [DOCS / name for name in (
    '需求规格说明书.md', '需求分析质量验证报告.md', 'AI智能体使用验证报告.md')]


def build():
    files = PRIMARY + [p for p in sorted(ROOT.rglob('*.md')) if p not in PRIMARY and '历史版本' not in p.parts]
    files.append(DOCS / 'README_报告材料.md')
    document_ids = {p.resolve(): f'doc-{i}' for i, p in enumerate(files)}
    pictures = sorted((ROOT / '模型').glob('*.png'))
    assert len(pictures) == 13, '需要13张本地模型PNG'
    picture_ids = {p.resolve(): 'image-' + p.stem for p in pictures}
    titles = {}
    for line in (ROOT / '模型/README.md').read_text(encoding='utf-8').splitlines():
        cells = [part.strip() for part in line.strip('|').split('|')]
        if len(cells) > 1 and re.fullmatch(r'(?:CP|DR)-M-\d+', cells[0]):
            titles[cells[0]] = cells[1]

    def inline(value, source):
        value = escape(value)

        def link(match):
            label, target = match.groups()
            path_part = unescape(target).split('#', 1)[0].strip('<>')
            if re.match(r'^[A-Za-z]+://', path_part):
                return f'{label} <small class="path">（{escape(path_part)}）</small>'
            local = (source.parent / path_part).resolve()
            destination = document_ids.get(local) or picture_ids.get(local) or ('top' if local == OUTPUT else None)
            if destination:
                return f'<a href="#{destination}">{label}</a>'
            return f'{label} <small class="path">（文件位置：{escape(unescape(target))}）</small>'

        value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, value)
        value = re.sub(r'`([^`]+)`', r'<code>\1</code>', value)
        return re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)

    def markdown(text, source):
        lines = text.splitlines()
        output = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if line.startswith('```'):
                i += 1
                code = []
                while i < len(lines) and not lines[i].strip().startswith('```'):
                    code.append(lines[i])
                    i += 1
                output.append('<pre><code>' + escape('\n'.join(code)) + '</code></pre>')
                i += 1
                continue
            heading = re.match(r'^(#{1,6})\s+(.+)', line)
            if heading:
                level = min(6, len(heading[1]) + 1)
                output.append(f'<h{level}>{inline(heading[2], source)}</h{level}>')
            elif line.startswith('|'):
                rows = []
                while i < len(lines) and lines[i].strip().startswith('|'):
                    cells = [cell.strip() for cell in lines[i].strip().strip('|').split('|')]
                    if not all(re.fullmatch(r':?-{2,}:?', cell) for cell in cells):
                        rows.append(cells)
                    i += 1
                output.append('<div class="table-scroll"><table>')
                for index, row in enumerate(rows):
                    tag = 'th' if index == 0 else 'td'
                    output.append('<tr>' + ''.join(f'<{tag}>{inline(cell, source)}</{tag}>' for cell in row) + '</tr>')
                output.append('</table></div>')
                continue
            elif line.startswith('>'):
                quote = []
                while i < len(lines) and lines[i].strip().startswith('>'):
                    quote.append(inline(lines[i].strip()[1:].strip(), source))
                    i += 1
                output.append('<blockquote>' + '<br>'.join(quote) + '</blockquote>')
                continue
            elif re.match(r'^(?:[-*]|\d+\.)\s+', line):
                ordered = bool(re.match(r'^\d+\.', line))
                tag = 'ol' if ordered else 'ul'
                pattern = r'^\d+\.\s+' if ordered else r'^[-*]\s+'
                output.append(f'<{tag}>')
                while i < len(lines) and re.match(pattern, lines[i].strip()):
                    output.append('<li>' + inline(re.sub(pattern, '', lines[i].strip()), source) + '</li>')
                    i += 1
                output.append(f'</{tag}>')
                continue
            else:
                output.append('<p>' + inline(line, source) + '</p>')
            i += 1
        return '\n'.join(output)

    css = '''
    :root{font-family:"Microsoft YaHei","Segoe UI",sans-serif;color:#233448;background:#eef2f6;line-height:1.7}
    *{box-sizing:border-box}body{margin:0}header{background:#173452;color:white;padding:26px 5%}header h1{margin:0;font-size:27px}header p{margin:8px 0 0}
    nav{padding:16px 5%;background:white;border-bottom:1px solid #cdd7e1;display:flex;gap:12px;flex-wrap:wrap}nav a{padding:7px 13px;background:#e7eff8;border-radius:6px}
    main{max-width:1280px;margin:auto;padding:20px}section{background:white;margin:0 0 24px;padding:26px;border:1px solid #d9e1ea;border-radius:10px;scroll-margin-top:15px}
    a{color:#135e9d;text-decoration:underline}h2,h3,h4{line-height:1.5;color:#173f64}h2{font-size:23px}h3{font-size:20px}h4{font-size:17px}
    figure{margin:24px 0 38px;scroll-margin-top:15px}figcaption{font-size:18px;font-weight:600;margin-bottom:10px}img{display:block;width:100%;max-width:1100px;height:auto;border:1px solid #dbe3ec;background:white}
    .table-scroll{overflow-x:auto;margin:18px 0}table{border-collapse:collapse;min-width:650px;width:100%;font-size:14px}td,th{padding:11px;border:1px solid #d3dde7;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#eaf1f8}
    code,pre{font-family:Consolas,"Microsoft YaHei",monospace}code{overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f0f4f8;padding:16px;border-radius:6px}blockquote{margin:15px 0;padding:10px 18px;border-left:4px solid #8fb1cf;background:#f4f7fa}
    .source,.path{color:#66768a;font-size:12px;overflow-wrap:anywhere}.back{font-size:14px;float:right}.notice{padding:16px;background:#eef5fb;border-left:4px solid #4684b8}
    @media(max-width:700px){main{padding:10px}section{padding:16px}header h1{font-size:23px}}
    @media print{nav,.back{display:none}body{background:white}section{border:0;padding:0;page-break-before:always}figure{break-inside:avoid}.table-scroll{overflow:visible}}
    '''
    html = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; img-src data:; style-src &#39;unsafe-inline&#39;">',
            '<title>双主题实验报告离线阅读</title><style>' + css + '</style></head><body>',
            '<header id="top"><h1>双主题实验报告 · 离线阅读</h1><p>复核清单、13张模型图与报告正文均在本文件内，不需要联网或点击对话链接。</p></header>',
            '<nav aria-label="阅读目录">']
    for source in PRIMARY:
        html.append(f'<a href="#{document_ids[source.resolve()]}">{escape(source.stem)}</a>')
    html.extend(['<a href="#campus-models">校园平台8张图</a><a href="#review-models">智能审查5张图</a>',
                 '<a href="#attachments">其他附件及实际反馈</a></nav><main>',
                 '<section><h2>使用说明</h2><p>先阅读复核清单的校园平台部分，点击其中图名即可跳到本文件内对应图片。三份报告和证据也可在本文件阅读。</p>',
                 '<p>字小时按 Ctrl 和 + 放大；按 Ctrl 和 F 查找编号。可把这个 HTML 单文件复制到其他位置，图片仍可查看。</p>',
                 '<p class="notice">这是生成时的阅读快照；编辑原始报告后需重新生成。模型与规则复核结论尚待用户实际反馈，页面可阅读不代表复核已完成。</p></section>'])
    for source in PRIMARY:
        text = source.read_text(encoding='utf-8')
        html.append(f'<section id="{document_ids[source.resolve()]}"><a class="back" href="#top">返回目录</a>')
        html.append(markdown(text, source))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        html.append(f'<p class="source">来源：{escape(str(source))} · 快照摘要 {digest}</p></section>')
    for prefix, section_id, title in [('CP', 'campus-models', '校园平台：8张本地模型'), ('DR', 'review-models', '智能审查：5张本地模型')]:
        html.append(f'<section id="{section_id}"><a class="back" href="#top">返回目录</a><h2>{title}</h2>')
        for picture in pictures:
            if not picture.stem.startswith(prefix):
                continue
            data = picture.read_bytes()
            assert data.startswith(b'\x89PNG\r\n\x1a\n')
            encoded = base64.b64encode(data).decode('ascii')
            assert base64.b64decode(encoded, validate=True) == data
            label = picture.stem + ' ' + titles[picture.stem]
            html.append(f'<figure id="{picture_ids[picture.resolve()]}"><figcaption>{escape(label)}</figcaption>')
            html.append(f'<img src="data:image/png;base64,{encoded}" alt="{escape(label)}" width="1100"><p class="source">本地源图：{escape(str(picture))}</p></figure>')
        html.append('</section>')
    html.append('<section id="attachments"><h2>其他附件及实际反馈</h2><ul>')
    for source in files[len(PRIMARY):]:
        html.append(f'<li><a href="#{document_ids[source.resolve()]}">{escape(source.stem)}</a></li>')
    html.append('</ul></section>')
    for source in files[len(PRIMARY):]:
        html.append(f'<section id="{document_ids[source.resolve()]}"><a class="back" href="#top">返回目录</a>')
        html.append(markdown(source.read_text(encoding='utf-8'), source) + '</section>')
    html.append('</main></body></html>')
    result = '\n'.join(html)
    OUTPUT.write_text(result, encoding='utf-8')

    class Check(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids, self.targets, self.images = set(), [], 0

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs:
                assert attrs['id'] not in self.ids
                self.ids.add(attrs['id'])
            if tag == 'a':
                assert attrs['href'].startswith('#')
                self.targets.append(attrs['href'][1:])
            if tag == 'img':
                assert attrs['src'].startswith('data:image/png;base64,')
                base64.b64decode(attrs['src'].split(',', 1)[1], validate=True)
                self.images += 1
            assert tag not in {'script', 'iframe', 'link'}, '离线文件不加载外部脚本或资源'

    check = Check()
    check.feed(result)
    assert check.images == 13 and set(check.targets) <= check.ids
    print(f'已生成：{OUTPUT}')
    print(f'检查通过：13张图片全部内嵌；{len(files)}份Markdown材料；{len(check.targets)}个页内链接目标有效；无外部资源加载。')
    print('检查范围：文件结构及图片字节，未进行浏览器视觉检查或用户打开确认。')


if __name__ == '__main__':
    build()
