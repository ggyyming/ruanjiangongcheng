"""Generate editable draw.io sources and SVG exports; optional PNG when Pillow exists."""

from html import escape
from math import atan2, cos, sin
from pathlib import Path
import textwrap
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
FONT = "C:/Windows/Fonts/msyh.ttc"


def n(key, label, x, y, w=180, h=66, shape="state"):
    return dict(id=key, label=label, x=x, y=y, w=w, h=h, shape=shape)


def e(source, target, label="", at=None, both=False):
    return dict(source=source, target=target, label=label, at=at, both=both)


MODELS = [
    dict(id="CP-M-01", title="校园平台：系统上下文", kind="context", height=680,
         note="关联 CP-R-01～27。仅本校参与流转；第三方须支持所需结算及退款能力，尚未核实。原型全部模拟。",
         nodes=[n("sys", "校园二手交易\n与物品流转平台", 540, 320, 300, 150, "box"),
                n("owner", "物主（本校用户）", 150, 180, shape="box"),
                n("app", "申请人（本校用户）", 150, 440, shape="box"),
                n("admin", "管理员", 920, 180, shape="box"),
                n("pay", "第三方支付服务", 920, 440, shape="box"),
                n("guest", "访客／未认证用户", 540, 100, shape="box")],
         edges=[e("owner", "sys", "发布、选择\n交付与归还", (315, 225), True),
                e("app", "sys", "申请、支付\n确认与协商", (315, 455), True),
                e("admin", "sys", "身份／物品审核\n争议介入", (765, 225), True),
                e("sys", "pay", "支付、退款\n结算及回执", (765, 490), True),
                e("guest", "sys", "浏览已审核公开信息", (540, 205), True)]),
    dict(id="CP-M-02", title="校园平台：核心用例图", kind="usecase", height=790,
         note="矩形 «actor» 表示参与者；椭圆表示用例；框为系统边界，关联线不表示执行先后。CP-UC-00～07。",
         boundary=(285, 70, 510, 600),
         nodes=[n("guest", "«actor» 访客", 125, 95, 150, 50, "box"),
                n("owner", "«actor»\n物主", 125, 200, 150, 70, "box"),
                n("app", "«actor»\n申请人", 125, 510, 150, 70, "box"),
                n("admin", "«actor»\n管理员", 955, 200, 150, 70, "box"),
                n("pay", "«actor»\n第三方支付服务", 955, 510, 170, 75, "box"),
                n("browse", "CP-UC-00\n浏览公开物品", 420, 140, 220, 76, "ellipse"),
                n("identity", "CP-UC-07\n校内身份审核", 665, 140, 220, 76, "ellipse"),
                n("publish", "CP-UC-01\n发布及内容审核", 420, 285, 220, 76, "ellipse"),
                n("choose", "CP-UC-02\n申请、选择与预留", 665, 285, 220, 76, "ellipse"),
                n("sale", "CP-UC-03\n买卖／赠送交付", 420, 430, 220, 76, "ellipse"),
                n("loan", "CP-UC-04\n借用、延期与归还", 665, 430, 220, 76, "ellipse"),
                n("cancel", "CP-UC-05\n取消、撤销与退款", 420, 575, 220, 76, "ellipse"),
                n("loss", "CP-UC-06\n逾期及赔偿处理", 665, 575, 220, 76, "ellipse")],
         edges=[e(a, b) for a, targets in {
             "guest": ["browse"],
             "owner": ["browse", "identity", "publish", "choose", "sale", "loan", "cancel", "loss"],
             "app": ["browse", "identity", "choose", "sale", "loan", "cancel", "loss"],
             "admin": ["identity", "publish", "loss"], "pay": ["sale", "loan", "cancel"]
         }.items() for b in targets]),
    dict(id="CP-M-03", title="校园平台：借用记录状态图", kind="state", height=810,
         note="CP-UC-04、06；对象为单次借用记录，非物品或资金。借出与归还分别确认；赔偿结清不等于归还。",
         nodes=[n("start", "", 100, 130, 22, 22, "start"),
                n("wait", "待交付", 300, 130), n("active", "借用中", 700, 130),
                n("return", "待另一方归还确认", 700, 380, 220),
                n("returned", "已归还", 700, 620),
                n("dispute", "争议处理中", 300, 380),
                n("comp", "赔偿结清", 300, 620), n("end", "", 500, 690, 26, 26, "end")],
         edges=[e("start", "wait", "CP-ST-04\n选定借用者", (155, 80)),
                e("wait", "active", "CP-ST-10\n日期双确认、有押金时付清\n双方确认借出", (500, 125)),
                e("active", "return", "CP-ST-11\n一方确认交还／收回", (850, 265)),
                e("return", "returned", "CP-ST-12\n双方确认归还", (850, 510)),
                e("active", "dispute", "CP-ST-29\n提交损坏／丢失争议", (495, 270)),
                e("dispute", "comp", "CP-ST-19\n丢失赔偿已履行并确认", (145, 510)),
                e("returned", "end"), e("comp", "end")]),
    dict(id="CP-M-04", title="校园平台：资金处理状态图", kind="state", height=850,
         note="CP-UC-03、04、05；对象为货款或押金记录。实物、支付、结算、退款分别表示；失败处置及结算后售后待确认。",
         nodes=[n("unpaid", "未支付", 180, 135), n("paying", "支付处理中", 530, 135),
                n("paid", "已支付", 880, 135), n("settling", "结算处理中", 880, 390),
                n("settled", "已结算到账", 880, 660), n("refunding", "退款处理中", 390, 390),
                n("refunded", "已退款到账", 180, 660), n("failed", "退款失败\n后续处理待确认", 570, 660, 210, 86)],
         edges=[e("unpaid", "paying", "CP-ST-20\n发起支付", (350, 100)),
                e("paying", "paid", "CP-ST-21\n有效成功回执", (705, 100)),
                e("paid", "settling", "CP-ST-06\n买卖双方确认交付", (880, 270)),
                e("settling", "settled", "CP-ST-22\n结算到账回执", (880, 525)),
                e("paid", "refunding", "CP-ST-12／13／17\n归还／取消／撤销生效\n满足相应无争议退款条件", (525, 255)),
                e("refunding", "refunded", "CP-ST-24\n退款到账回执", (180, 520)),
                e("refunding", "failed", "CP-ST-23\n退款失败回执", (570, 520))]),
    dict(id="CP-M-05", title="校园平台：新增借用资格状态图", kind="state", height=500,
         note="CP-UC-06；对象为用户的逾期新增借用限制。其他限制与身份审核不随之解除；已有归还仍可处理（边界待复核）。",
         nodes=[n("allowed", "无本项限制", 245, 240, 220, 80), n("blocked", "新增借用受限", 835, 240, 220, 80)],
         edges=[e("allowed", "blocked", "CP-ST-31\n逾期未有效结束", (540, 165)),
                e("blocked", "allowed", "CP-ST-25\n全部逾期逐笔归还或赔偿结清\n且相关争议均关闭", (540, 330))]),
    dict(id="DR-M-01", title="课程需求审查：系统上下文", kind="context", height=680,
         note="关联 DR-R-01～07、09～14；DR-R-08 已撤销。学生限本组；教师负责教学班全组作品。模板为本组设定。",
         nodes=[n("sys", "课程需求文档\n智能审查系统", 540, 320, 300, 150, "box"),
                n("student", "学生作者（本组）", 150, 210, shape="box"),
                n("teacher", "教师（负责教学班）", 150, 470, 220, shape="box"),
                n("model", "模型服务\n原型仅预置模拟", 920, 220, 210, 90, "box"),
                n("template", "本组模板\nTPL-COURSE-01 v0.1", 920, 480, 230, 90, "box")],
         edges=[e("student", "sys", "上传、查看\n修订与复审", (315, 215), True),
                e("teacher", "sys", "逐条复核\n确认问题解决", (315, 470), True),
                e("sys", "model", "待审文本\n候选问题", (765, 150), True),
                e("template", "sys", "八项内容\n检查口径", (765, 550))]),
    dict(id="DR-M-02", title="课程需求审查：核心用例图", kind="usecase", height=860,
         note="学生负责本组文档，教师从负责教学班总览进入各组作品复核。关系见 DR-M-05；不代表真实教师参与。",
         boundary=(330, 70, 430, 680),
         nodes=[n("student", "«actor»\n学生作者", 140, 260, 170, 80, "box"),
                n("teacher", "«actor»\n教学班负责教师", 940, 260, 200, 80, "box"),
                n("model", "«actor»\n模型服务（原型模拟）", 940, 510, 230, 90, "box"),
                n("upload", "DR-UC-01\n上传及原文定位", 545, 140, 280, 80, "ellipse"),
                n("review", "DR-UC-02\n生成四类问题候选", 545, 270, 280, 80, "ellipse"),
                n("decide", "DR-UC-03\n教师逐条复核", 545, 400, 280, 80, "ellipse"),
                n("revise", "DR-UC-04\n新版本复审与解决确认", 545, 535, 310, 80, "ellipse"),
                n("classwork", "DR-UC-05\n教学班与各组作品总览", 545, 675, 310, 80, "ellipse")],
         edges=[e("student", "upload"), e("student", "review"), e("student", "revise"),
                e("teacher", "classwork"), e("teacher", "decide"), e("teacher", "revise"), e("model", "review"), e("model", "revise")]),
    dict(id="DR-M-03", title="课程需求审查：审查任务状态图", kind="state", height=640,
         note="DR-UC-01、02、04；对象为一次版本的审查任务。DR-ST-01／09 创建首版／新版任务，旧任务保留；失败不等于没有问题。",
         nodes=[n("none", "未开始", 170, 150), n("queued", "待执行", 540, 150),
                n("running", "执行中", 900, 150), n("done", "已完成", 900, 450),
                n("failed", "失败", 540, 450)],
         edges=[e("none", "queued", "DR-ST-01／09\n上传首版／新版", (350, 100)),
                e("queued", "running", "DR-ST-02\n开始审查", (720, 115)),
                e("running", "done", "DR-ST-03\n形成审查结果", (900, 300)),
                e("running", "failed", "DR-ST-04\n服务／处理失败", (650, 300))]),
    dict(id="DR-M-04", title="课程需求审查：问题跟踪状态图", kind="state", height=760,
         note="DR-UC-03、04；对象为问题跟踪，原版本教师决定保留。已解决为新增跟踪确认，不覆盖历史；未提示不自动解决。",
         nodes=[n("pending", "待教师复核", 180, 150, 210), n("confirmed", "已确认", 590, 150),
                n("hold", "待核实", 180, 440), n("rejected", "已驳回", 590, 440),
                n("resolved", "解决已确认\n新增跟踪记录", 940, 150, 220, 90)],
         edges=[e("pending", "confirmed", "DR-ST-05\n教师确认并记录理由", (390, 110)),
                e("pending", "hold", "DR-ST-06\n教师保留待核实", (180, 295)),
                e("pending", "rejected", "DR-ST-12\n教师驳回并记录理由", (370, 235)),
                e("hold", "confirmed", "DR-ST-05\n补充依据后教师确认", (490, 350)),
                e("confirmed", "resolved", "DR-ST-10\n核对新版并确认解决", (755, 80))]),
]

MODELS.extend([
    dict(id="DR-M-05", title="课程教学班与作品归属（关系示意）", kind="domain", height=900,
         note="DR-R-09、12、13、14；连线注明归属与数量。当前单主审/组作品数量为候选约束；跨课程、学期分别建教学班。",
         nodes=[n("teacher", "教师\n教师编号", 160, 150, 210, 90, "box"),
                n("classroom", "课程教学班\n班编号、课程、学期\n负责教师编号", 550, 150, 240, 100, "box"),
                n("group", "课程小组\n组编号、教学班编号", 550, 405, 240, 90, "box"),
                n("student", "班内学生\n学生编号、组归属", 160, 405, 210, 90, "box"),
                n("work", "小组作品\n作品编号、教学班、组", 940, 405, 240, 90, "box"),
                n("version", "文档版本\n作品编号、版本编号\n原文与提交记录", 940, 690, 240, 100, "box"),
                n("run", "审查任务及复核\n关联作品版本\n问题与教师决定", 550, 690, 240, 100, "box")],
         edges=[e("teacher", "classroom", "1名教师 → 0..*个教学班\n本次候选每班1名主审", (350, 95)),
                e("classroom", "group", "1个教学班 → 0..*个组\n每组属于1个教学班", (550, 280)),
                e("group", "student", "每组1..*名班内学生\n每人本班最多1组（候选）", (350, 340)),
                e("group", "work", "每组0..1份本次任务作品\n未提交组也在班级总览", (750, 340)),
                e("work", "version", "1份作品 → 1..*版本\n新版不覆盖旧版", (940, 550)),
                e("version", "run", "1个版本 → 0..*次审查\n决定不跨组/跨作品混写", (745, 650))]),
    dict(id="CP-M-06", title="校园平台：物品及撤销状态（分对象）", kind="state", height=850,
         note="CP-UC-01、02、03、05；上部为物品，下部为流转撤销，分别建模。CP-ST-14 下架保持；撤销后重新开放待确认。",
         nodes=[n("draft", "草稿", 160, 140), n("pending", "待审核", 540, 140),
                n("available", "可申请", 920, 140), n("reserved", "已预留", 920, 430),
                n("done", "已成交／赠送完成", 540, 430, 230), n("removed", "已下架", 160, 430),
                n("revoking", "流转：撤销协商中", 260, 660, 240), n("revoked", "流转：已撤销", 790, 660, 220)],
         edges=[e("draft", "pending", "CP-ST-01\n认证物主提交", (350, 100)),
                e("pending", "available", "CP-ST-02\n管理员审核通过", (730, 100)),
                e("available", "reserved", "CP-ST-04\n物主选定申请人", (1030, 285)),
                e("reserved", "available", "CP-ST-13\n交付前取消、仍可展示", (760, 285)),
                e("reserved", "done", "CP-ST-06\n买卖／赠送双确认", (730, 505)),
                e("revoking", "revoked", "CP-ST-17\n双方同意且未交付／退回双确认", (525, 605))]),
    dict(id="CP-M-07", title="校园平台：延期申请状态", kind="state", height=500,
         note="CP-UC-04；对象为单次延期申请。待同意不改变原日期；仅建模申请与同意均在原到期前的路径，跨到期点审批待确认。",
         nodes=[n("none", "尚未申请", 180, 220), n("pending", "待物主同意", 550, 220), n("approved", "已同意", 920, 220)],
         edges=[e("none", "pending", "CP-ST-26\n借用者到期前申请", (365, 160)),
                e("pending", "approved", "CP-ST-27\n物主到期前同意", (735, 160))]),
    dict(id="CP-M-08", title="校园平台：流转申请状态", kind="state", height=660,
         note="CP-UC-02、05；对象为单个申请。物主选一人时，选中者与其他申请分别变化；关闭的申请不因取消自动恢复。",
         nodes=[n("none", "无申请", 170, 150), n("pending", "待选择", 540, 150),
                n("chosen", "已选中", 920, 150), n("closed", "已关闭", 540, 440),
                n("cancelled", "已取消", 920, 440)],
         edges=[e("none", "pending", "CP-ST-03\n认证申请人提交", (355, 100)),
                e("pending", "chosen", "CP-ST-04\n物主选择本申请", (730, 100)),
                e("pending", "closed", "CP-ST-04\n物主选择其他人", (540, 290)),
                e("chosen", "cancelled", "CP-ST-13／14\n本次取消生效", (920, 300))]),
])


def lines(text, width=18):
    return [part for raw in text.split("\n") for part in (textwrap.wrap(raw, width) or [""]) ]


def endpoints(a, b):
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    if abs(dx) >= abs(dy):
        direction = 1 if dx >= 0 else -1
        return (a["x"] + direction * a["w"] / 2, a["y"]), (b["x"] - direction * b["w"] / 2, b["y"])
    direction = 1 if dy >= 0 else -1
    return (a["x"], a["y"] + direction * a["h"] / 2), (b["x"], b["y"] - direction * b["h"] / 2)


def build(model):
    width, height = 1100, model["height"]
    nodes = {item["id"]: item for item in model["nodes"]}
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<g font-family="Microsoft YaHei, sans-serif" fill="#253b50">']
    drawing = ET.Element("mxfile", host="app.diagrams.net", version="24.0.0")
    diagram = ET.SubElement(drawing, "diagram", id=model["id"], name=model["title"])
    graph = ET.SubElement(diagram, "mxGraphModel", pageWidth=str(width), pageHeight=str(height), page="1")
    root = ET.SubElement(graph, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    raster = None
    try:
        from PIL import Image, ImageDraw, ImageFont
        raster = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(raster)
        fonts = {size: ImageFont.truetype(FONT, size) for size in (13, 15, 22)}
    except ImportError:
        pass

    def text(x, y, value, size=15, wrap=18, background=False):
        rows = lines(value, wrap)
        line_height = size + 6
        top = y - (len(rows) - 1) * line_height / 2
        if background and value:
            boxw = max(len(row) for row in rows) * size + 10
            boxh = len(rows) * line_height
            svg.append(f'<rect x="{x-boxw/2}" y="{top-size}" width="{boxw}" height="{boxh}" fill="white" opacity="0.94"/>')
            if raster:
                draw.rectangle((x-boxw/2, top-size, x+boxw/2, top-size+boxh), fill="white")
        for index, row in enumerate(rows):
            yy = top + index * line_height
            svg.append(f'<text x="{x}" y="{yy}" text-anchor="middle" dominant-baseline="middle" font-size="{size}">{escape(row)}</text>')
            if raster:
                draw.text((x, yy), row, font=fonts[size], fill="#253b50", anchor="mm")

    def rect(x, y, w, h, shape="box"):
        fill, stroke = "#edf4fb", "#356d96"
        if shape in ("start", "end", "ellipse"):
            svg.append(f'<ellipse cx="{x}" cy="{y}" rx="{w/2}" ry="{h/2}" fill="{stroke if shape == "start" else fill}" stroke="{stroke}" stroke-width="2"/>')
            if raster:
                draw.ellipse((x-w/2, y-h/2, x+w/2, y+h/2), fill=stroke if shape == "start" else fill, outline=stroke, width=2)
            if shape == "end":
                svg.append(f'<circle cx="{x}" cy="{y}" r="{w/2-5}" fill="{stroke}"/>')
                if raster:
                    draw.ellipse((x-w/2+5, y-h/2+5, x+w/2-5, y+h/2-5), fill=stroke)
        else:
            radius = 17 if shape == "state" else 3
            svg.append(f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
            if raster:
                draw.rounded_rectangle((x-w/2, y-h/2, x+w/2, y+h/2), radius=radius, fill=fill, outline=stroke, width=2)

    text(width/2, 30, f'{model["id"]}  {model["title"]}', 22, 60)
    if "boundary" in model:
        x, y, w, h = model["boundary"]
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#a6b6c6" stroke-dasharray="7 4"/>')
        if raster:
            draw.rectangle((x, y, x+w, y+h), outline="#a6b6c6", width=1)
        cell = ET.SubElement(root, "mxCell", id="boundary", value="系统边界", style="rounded=0;fillColor=none;dashed=1;verticalAlign=top;", vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), attrib={"as": "geometry"})

    for index, edge in enumerate(model["edges"]):
        a, b = nodes[edge["source"]], nodes[edge["target"]]
        start, end = endpoints(a, b)
        reciprocal = any(other["source"] == edge["target"] and other["target"] == edge["source"] for other in model["edges"])
        if reciprocal and a["y"] == b["y"]:
            offset = -20 if a["x"] < b["x"] else 20
            start = (start[0], start[1] + offset)
            end = (end[0], end[1] + offset)
        elif reciprocal and a["x"] == b["x"]:
            offset = 20 if a["y"] < b["y"] else -20
            start = (start[0] + offset, start[1])
            end = (end[0] + offset, end[1])
        svg.append(f'<path d="M {start[0]} {start[1]} L {end[0]} {end[1]}" fill="none" stroke="#72879a" stroke-width="1.8"/>')
        if raster:
            draw.line((start, end), fill="#72879a", width=2)
        def arrow(p, q):
            angle = atan2(q[1]-p[1], q[0]-p[0])
            points = [q, (q[0]-12*cos(angle-.42), q[1]-12*sin(angle-.42)), (q[0]-12*cos(angle+.42), q[1]-12*sin(angle+.42))]
            svg.append('<polygon points="' + " ".join(f"{x},{y}" for x, y in points) + '" fill="#72879a"/>')
            if raster:
                draw.polygon(points, fill="#72879a")
        association = model["kind"] in ("usecase", "domain")
        if not association:
            arrow(start, end)
            if edge["both"]:
                arrow(end, start)
        at = edge["at"] or ((start[0]+end[0])/2, (start[1]+end[1])/2)
        text(*at, edge["label"], 13, 22, True)
        style = "endArrow=none;" if association else "endArrow=block;"
        if edge["both"]:
            style += "startArrow=block;"
        if reciprocal and a["y"] == b["y"]:
            anchor = "0.25" if a["x"] < b["x"] else "0.75"
            style += f"exitY={anchor};entryY={anchor};"
        elif reciprocal and a["x"] == b["x"]:
            anchor = "0.65" if a["y"] < b["y"] else "0.35"
            style += f"exitX={anchor};entryX={anchor};"
        cell = ET.SubElement(root, "mxCell", id=f"edge{index}", value=edge["label"], style=style+"html=0;", edge="1", parent="1", source=edge["source"], target=edge["target"])
        ET.SubElement(cell, "mxGeometry", relative="1", attrib={"as": "geometry"})
    for item in model["nodes"]:
        rect(item["x"], item["y"], item["w"], item["h"], item["shape"])
        text(item["x"], item["y"], item["label"], 15, 22)
        shape_style = "ellipse;" if item["shape"] in ("ellipse", "start", "end") else "rounded=1;arcSize=20;" if item["shape"] == "state" else "rounded=0;"
        if item["shape"] == "end":
            shape_style = "shape=doubleEllipse;"
        cell = ET.SubElement(root, "mxCell", id=item["id"], value=item["label"], style=shape_style+"whiteSpace=wrap;html=0;fontSize=15;fillColor=#edf4fb;strokeColor=#356d96;", vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(item["x"]-item["w"]/2), y=str(item["y"]-item["h"]/2), width=str(item["w"]), height=str(item["h"]), attrib={"as": "geometry"})
    text(width/2, height-62, model["note"], 13, 72)
    caption = "v0.2 · 教学班组织修订 · 待用户复核" if model["id"].startswith("DR-") else "v0.1 · 依据用户选定设定推导 · 人工模型复核待开展"
    text(width/2, height-20, caption, 13, 80)
    svg.extend(["</g>", "</svg>"])
    (ROOT / f'{model["id"]}.svg').write_text("\n".join(svg), encoding="utf-8")
    ET.ElementTree(drawing).write(ROOT / f'{model["id"]}.drawio', encoding="utf-8", xml_declaration=True)
    if raster:
        raster.save(ROOT / f'{model["id"]}.png')
    ET.parse(ROOT / f'{model["id"]}.svg')
    ET.parse(ROOT / f'{model["id"]}.drawio')


if __name__ == "__main__":
    for model in MODELS:
        build(model)
    print(f"已生成并检查 {len(MODELS)} 份 draw.io 源文件和 SVG 导出；有 Pillow 时同时生成 PNG。")
