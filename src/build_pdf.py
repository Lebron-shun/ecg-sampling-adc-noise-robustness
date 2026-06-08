"""Build a visually verifiable final PDF directly from actual project results."""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from build_report import fmt, markdown_report, read_inputs, summary_text
from project_core import FIGURES_DIR, REPORT_DIR, ensure_project_dirs


BLUE = colors.HexColor("#276FBF")
DARK = colors.HexColor("#183153")
TEAL = colors.HexColor("#1B998B")
LIGHT = colors.HexColor("#EAF1F8")
GRAY = colors.HexColor("#657786")


def styles():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "BodyCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=10,
            leading=16,
            textColor=DARK,
            alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "SmallCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=8.5,
            leading=12,
            textColor=GRAY,
            alignment=TA_LEFT,
        ),
        "table_header": ParagraphStyle(
            "TableHeaderCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=8.5,
            leading=12,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "title": ParagraphStyle(
            "TitleCN",
            parent=base["Title"],
            fontName="STSong-Light",
            fontSize=23,
            leading=33,
            textColor=DARK,
            alignment=TA_CENTER,
            spaceAfter=15,
        ),
        "subtitle": ParagraphStyle(
            "SubtitleCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=12,
            leading=18,
            textColor=GRAY,
            alignment=TA_CENTER,
            spaceAfter=15,
        ),
        "h1": ParagraphStyle(
            "H1CN",
            parent=base["Heading1"],
            fontName="STSong-Light",
            fontSize=15,
            leading=21,
            textColor=BLUE,
            spaceBefore=12,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2CN",
            parent=base["Heading2"],
            fontName="STSong-Light",
            fontSize=12,
            leading=17,
            textColor=DARK,
            spaceBefore=9,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "caption": ParagraphStyle(
            "CaptionCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=8.8,
            leading=12,
            textColor=GRAY,
            alignment=TA_CENTER,
            spaceAfter=9,
        ),
        "keyword": ParagraphStyle(
            "KeywordCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=9.5,
            leading=14,
            textColor=DARK,
            leftIndent=12,
            rightIndent=12,
            spaceAfter=8,
        ),
    }


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def p_md(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def figure(filename: str, caption: str, styles_map: dict, max_width=6.5 * inch, max_height=6.2 * inch):
    path = FIGURES_DIR / filename
    with PILImage.open(path) as image:
        width, height = image.size
    scale = min(max_width / width, max_height / height)
    flowable = Image(str(path), width=width * scale, height=height * scale)
    flowable.hAlign = "CENTER"
    return KeepTogether([flowable, Spacer(1, 4), p(caption, styles_map["caption"])])


def styled_table(headers: list[str], rows: list[list[str]], widths: list[float], styles_map: dict) -> Table:
    data = [[p(f"<b>{header}</b>", styles_map["table_header"]) for header in headers]]
    data.extend([[p(str(value), styles_map["small"]) for value in row] for row in rows])
    table = Table(data, colWidths=[width * inch for width in widths], repeatRows=1, hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7C6D8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8FC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def styled_table_md(headers: list[str], rows: list[list[str]], widths: list[float], styles_map: dict) -> Table:
    data = [[p(f"<b>{escape(header)}</b>", styles_map["table_header"]) for header in headers]]
    data.extend([[p_md(str(value), styles_map["small"]) for value in row] for row in rows])
    table = Table(data, colWidths=[width * inch for width in widths], repeatRows=1, hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7C6D8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8FC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def clean_markdown_text(text: str) -> str:
    text = text.replace("**", "")
    text = text.replace("`", "")
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", text)
    return text.strip()


def split_markdown_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [clean_markdown_text(cell.strip()) for cell in cells]


def markdown_table_widths(column_count: int) -> list[float]:
    presets = {
        2: [2.3, 4.2],
        3: [1.55, 2.2, 2.75],
        4: [1.25, 1.75, 1.75, 1.75],
        5: [1.35, 1.05, 1.25, 1.25, 1.55],
    }
    if column_count in presets:
        return presets[column_count]
    return [6.5 / column_count] * column_count


def add_markdown_table(story: list, lines: list[str], index: int, styles_map: dict) -> int:
    headers = split_markdown_row(lines[index])
    rows: list[list[str]] = []
    index += 2
    while index < len(lines) and lines[index].strip().startswith("|"):
        rows.append(split_markdown_row(lines[index]))
        index += 1
    story.append(styled_table_md(headers, rows, markdown_table_widths(len(headers)), styles_map))
    story.append(Spacer(1, 7))
    return index


def markdown_to_story(markdown: str, styles_map: dict) -> list:
    story: list = []
    lines = markdown.splitlines()
    try:
        index = lines.index("## 摘要")
    except ValueError:
        index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("### "):
            story.append(p_md(clean_markdown_text(line[4:]), styles_map["h2"]))
            index += 1
            continue
        if line.startswith("## "):
            if line.startswith("## 4 "):
                story.append(PageBreak())
            story.append(p_md(clean_markdown_text(line[3:]), styles_map["h1"]))
            index += 1
            continue
        image_match = re.match(r"!\[(.*?)\]\((.*?)\)", line)
        if image_match:
            caption, image_path = image_match.groups()
            story.append(figure(Path(image_path).name, clean_markdown_text(caption), styles_map, max_height=4.75 * inch))
            index += 1
            continue
        if line.startswith("|") and index + 1 < len(lines) and "---" in lines[index + 1]:
            index = add_markdown_table(story, lines, index, styles_map)
            continue
        if line.startswith("- "):
            items = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(clean_markdown_text(lines[index].strip()[2:]))
                index += 1
            story.extend(bullet_list(items, styles_map))
            continue
        ordered_match = re.match(r"\d+\.\s+(.*)", line)
        if ordered_match:
            items = []
            while index < len(lines):
                match = re.match(r"\d+\.\s+(.*)", lines[index].strip())
                if not match:
                    break
                items.append(clean_markdown_text(match.group(1)))
                index += 1
            story.extend(bullet_list(items, styles_map))
            continue
        story.append(p_md(clean_markdown_text(line), styles_map["body"]))
        index += 1
    return story


def bullet_list(items: list[str], styles_map: dict) -> list[Paragraph]:
    return [
        Paragraph(f"•　{item}", ParagraphStyle(f"bullet-{index}", parent=styles_map["body"], leftIndent=14, firstLineIndent=-10))
        for index, item in enumerate(items)
    ]


def page_decor(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7E0EA"))
    canvas.setLineWidth(0.5)
    canvas.line(0.72 * inch, 0.58 * inch, 7.78 * inch, 0.58 * inch)
    canvas.setFont("STSong-Light", 8)
    canvas.setFillColor(GRAY)
    canvas.drawString(0.72 * inch, 0.36 * inch, "生物医学电子（2）课程大作业")
    canvas.drawRightString(7.78 * inch, 0.36 * inch, f"第 {doc.page} 页")
    canvas.restoreState()


def build_pdf(path: Path) -> None:
    ensure_project_dirs()
    data = read_inputs()
    s = summary_text(data)
    st = styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.72 * inch,
        title="面向可穿戴心电监护的ECG采样率、ADC有效位数与抗噪性能联合设计",
        author="生物医学电子（2）课程大作业",
    )
    story = []

    story.extend(
        [
            Spacer(1, 0.65 * inch),
            p("生物医学电子（2）课程大作业", st["subtitle"]),
            Spacer(1, 0.18 * inch),
            p("面向可穿戴心电监护的ECG采样率、<br/>ADC有效位数与抗噪性能联合设计", st["title"]),
            p("基于公开数据集的虚拟采集系统设计与定量性能评价", st["subtitle"]),
            Spacer(1, 0.28 * inch),
            styled_table(
                ["项目关键结果", "数值"],
                [
                    ["推荐配置", s["configuration"]],
                    ["干净条件合并F1", f"{s['clean_f1']}%"],
                    ["数据率降低", f"{s['bitrate_reduction']}%"],
                    ["R峰时间误差中位数", f"{s['timing']} ms"],
                ],
                [3.7, 2.1],
                st,
            ),
            Spacer(1, 0.55 * inch),
            p("姓名：提交前填写　学号：提交前填写　班级：提交前填写", st["subtitle"]),
            p("完成日期：2026年6月", st["subtitle"]),
            p("GitHub：https://github.com/Lebron-shun/ecg-sampling-adc-noise-robustness", st["small"]),
            p("交互展示：https://lebron-shun.github.io/ecg-sampling-adc-noise-robustness/", st["small"]),
            PageBreak(),
        ]
    )
    story.extend(markdown_to_story(markdown_report(data, s), st))
    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    return

    story.append(p("摘要", st["h1"]))
    story.append(
        p(
            f"面向长时程可穿戴心电监护中的存储、传输与抗噪权衡，本项目构建了可复现的虚拟ECG采集系统，"
            f"系统研究采样率与ADC有效位数对R峰检测的联合影响。实验使用MIT-BIH Arrhythmia Database的48条动态心电记录，"
            f"以及MIT-BIH Noise Stress Test Database中12条标准电极运动伪影记录。虚拟采集链路包含0.5-40 Hz前端响应、"
            f"抗混叠重采样、固定10 mV满量程量化和固定参数XQRS检测器。对5种采样率和6种有效位数组成的30种配置进行全因子评价。"
            f"结果推荐<b>{s['configuration']}</b>：干净条件合并F1为{s['clean_f1']}%，相对360 Hz / 11 bit参考配置下降{s['clean_drop']}个百分点，"
            f"同时将单通道原始数据率降低{s['bitrate_reduction']}%。在SNR不低于6 dB的标准运动伪影条件下，相对参考配置的最差F1下降为"
            f"{s['noise_worst_drop']}个百分点。该结论适用于R峰与RR间期监测，不能外推到临床诊断或真实硬件功耗。",
            st["body"],
        )
    )
    story.append(p("<b>关键词：</b>心电信号；采样率；ADC有效位数；R峰检测；运动伪影；可穿戴监护", st["keyword"]))

    story.append(p("1　引言与医学应用背景", st["h1"]))
    story.append(
        p(
            "动态心电监护需要长时间采集人体表面ECG，并从中提取R峰、RR间期和心率。可穿戴设备通常受到电池、存储空间和无线传输带宽限制。"
            "提高采样率和ADC位数能够保留更多波形细节，但也增加数据率与处理负担；过度降低配置则可能使QRS波失真、R峰定位误差增加，"
            "并降低噪声环境下的检测可靠性。因此，需要围绕具体监测任务在信号质量与资源开销之间进行联合设计。",
            st["body"],
        )
    )
    story.append(
        p(
            "本项目将任务限定为R峰监测，不进行疾病分类。在统一算法、固定输入量程和公开数据条件下，定量研究采样率、有效位数和运动伪影的联合影响，"
            "并寻找性能与数据率之间的工程折中。",
            st["body"],
        )
    )
    story.append(figure("figure_01_system_diagram.png", "图1　系统总体框图", st, max_height=2.4 * inch))

    story.append(p("2　系统设计原理与关键技术方案", st["h1"]))
    story.append(p("2.1　系统组成与设计约束", st["h2"]))
    story.append(
        p(
            "虚拟系统由表面电极、保护与仪表放大、0.5-40 Hz模拟前端、可配置采样与量化、数字QRS检测和结果输出组成。"
            "本作业实际实现虚拟采集与数字处理模块，不声称制作真实医疗硬件。",
            st["body"],
        )
    )
    story.append(
        styled_table(
            ["设计项目", "参数", "设计依据"],
            [
                ["输入信号", "单导联ECG", "面向心率与RR间期监测"],
                ["前端通带", "0.5-40 Hz", "保留主要QRS信息并抑制漂移与高频噪声"],
                ["输入满量程", "10 mV峰峰值", "与MIT-BIH原始量化范围一致"],
                ["候选采样率", "360/250/180/125/100 Hz", "覆盖参考与低数据率配置"],
                ["候选有效位数", "11/10/9/8/7/6 bit", "原始数据上限为11 bit"],
            ],
            [1.25, 2.0, 3.5],
            st,
        )
    )
    story.append(p("2.2　采样、量化与数据率", st["h2"]))
    story.append(
        p(
            "固定满量程为10 mV峰峰值，N位ADC量化步长为：<b>LSB = 10 mV / 2<super>N</super></b>。"
            "单通道无压缩原始数据率为：<b>R = f<sub>s</sub> × N</b>。100 Hz虽然满足40 Hz带宽的奈奎斯特条件，"
            "但只留下10 Hz模拟抗混叠过渡带；因此最终推荐同时考虑数字性能与模拟滤波可实现性。",
            st["body"],
        )
    )
    story.append(
        styled_table(
            ["有效位数", "LSB (µV)", "360 Hz数据率 (bit/s)"],
            [["11", "4.883", "3960"], ["9", "19.531", "3240"], ["8", "39.063", "2880"], ["7", "78.125", "2520"], ["6", "156.250", "2160"]],
            [1.8, 2.0, 2.8],
            st,
        )
    )

    story.append(p("3　方法与实现过程", st["h1"]))
    story.append(p("3.1　开源数据与实验矩阵", st["h2"]))
    story.append(
        p(
            "MIT-BIH Arrhythmia Database包含48条约30分钟双通道动态ECG，采样率360 Hz，原始分辨率11 bit，并带专家复核逐搏标注。"
            "MIT-BIH Noise Stress Test Database提供以记录118和119构建的标准电极运动伪影压力测试记录，SNR为24、18、12、6、0和-6 dB。",
            st["body"],
        )
    )
    story.append(
        styled_table(
            ["实验", "记录", "因素", "目的"],
            [
                ["干净条件全因子", "MIT-BIH 48条", "5采样率 × 6位数", "评价采样与量化影响"],
                ["标准抗噪压力测试", "NSTDB 12条", "30配置 × 6个SNR", "评价运动伪影鲁棒性"],
                ["定位敏感性分析", "同上", "±150 ms与±75 ms", "识别低采样率时间代价"],
            ],
            [1.55, 1.45, 1.75, 2.0],
            st,
        )
    )
    story.append(figure("figure_02_experiment_workflow.png", "图2　虚拟采集与实验评价流程", st, max_height=2.4 * inch))
    story.append(p("3.2　信号处理与评价", st["h2"]))
    story.append(
        p(
            "每条记录选取第一通道，先通过0.5-40 Hz四阶Butterworth零相位带通模型，再使用带抗混叠滤波的多相重采样生成目标采样率。"
            "量化过程固定10 mV满量程，不对各记录单独归一化。所有配置使用固定设置的WFDB XQRS检测器。检测结果与人工标注在±150 ms内一对一匹配；"
            "另以±75 ms窗口进行定位敏感性分析。NSTDB主分析仅评价官方交替模式中的已知噪声区间，并在边界去除0.2 s。",
            st["body"],
        )
    )
    story.append(
        p(
            "核心指标为灵敏度、阳性预测率和F1，同时计算R峰时间误差、量化均方根误差、量化信噪比、削顶率、数据率和每天存储量。"
            "统计分析以记录为单位，采用bootstrap置信区间、配对Wilcoxon检验和Holm多重比较校正。",
            st["body"],
        )
    )
    story.append(figure("figure_03_waveform_comparison.png", "图3　不同虚拟采集配置的代表性ECG波形", st, max_height=5.6 * inch))

    story.append(p("4　结果展示与性能评价", st["h1"]))
    story.append(p("4.1　干净条件全因子结果", st["h2"]))
    story.append(figure("figure_04_clean_heatmaps.png", "图4　干净条件下30种配置的F1与R峰时间误差", st, max_height=4.5 * inch))
    comparison_configs = [(360, 11), (360, 6), (250, 8), (180, 8), (125, 8), (100, 6)]
    comparison_rows = []
    for fs, bits in comparison_configs:
        row = data["clean"][(data["clean"].target_fs_hz == fs) & (data["clean"].bits == bits)].iloc[0]
        comparison_rows.append(
            [
                f"{fs} Hz / {bits} bit",
                fmt(row["pooled_f1_pct"], 3),
                fmt(row["f1_drop_from_reference_pp"], 3),
                fmt(row["median_timing_error_ms"], 2),
                str(int(row["raw_bitrate_bps"])),
            ]
        )
    story.append(
        styled_table(
            ["配置", "F1 (%)", "相对下降 (pp)", "时间误差 (ms)", "数据率 (bit/s)"],
            comparison_rows,
            [1.45, 1.05, 1.35, 1.35, 1.45],
            st,
        )
    )
    story.append(
        p(
            f"推荐配置<b>{s['configuration']}</b>在干净条件下获得{s['clean_f1']}%的合并F1，参考配置为{s['clean_ref_f1']}%，下降{s['clean_drop']}个百分点；"
            f"R峰时间误差中位数为{s['timing']} ms。以记录为重采样单位的bootstrap显示，推荐配置相对参考配置的宏平均F1下降95%置信区间为"
            f"{s['bootstrap_low']}至{s['bootstrap_high']}个百分点；配对Wilcoxon检验经Holm校正后的p值为{s['holm_p']}。"
            f"在20个探索性交互对比中，有{s['interaction_count']}个区间未跨越零，且效应量很小。",
            st["body"],
        )
    )
    story.append(figure("figure_08_record_distribution.png", "图5　参考配置与推荐配置的逐记录F1分布", st, max_height=4.7 * inch))

    story.append(p("4.2　标准运动伪影抗噪性能", st["h2"]))
    story.append(figure("figure_05_noise_robustness.png", "图6　不同SNR下候选配置的R峰检测性能", st, max_height=4.7 * inch))
    noise_rows = [
        [str(int(row.snr_db)), fmt(row.pooled_f1_pct_reference, 2), fmt(row.pooled_f1_pct_chosen, 2), fmt(row.drop_pp, 2)]
        for row in data["noise_compare"].sort_values("snr_db", ascending=False).itertuples()
    ]
    story.append(styled_table(["SNR (dB)", "参考F1 (%)", "推荐F1 (%)", "相对下降 (pp)"], noise_rows, [1.4, 1.7, 1.7, 1.7], st))
    story.append(
        p(
            f"噪声增强后所有配置的绝对性能均下降。推荐配置在SNR不低于6 dB时相对参考配置的最差下降为{s['noise_worst_drop']}个百分点；"
            f"全部噪声水平中的最低F1为{s['noise_lowest_f1']}%。强运动伪影下的主要限制逐渐转向检测器鲁棒性和输入污染，而不是ADC位数本身。",
            st["body"],
        )
    )
    story.append(figure("figure_07_severe_noise_heatmap.png", "图7　严重运动伪影下的全因子性能", st, max_height=4.8 * inch))

    story.append(PageBreak())
    story.append(p("4.3　性能与资源权衡", st["h2"]))
    story.append(figure("figure_06_pareto_tradeoff.png", "图8　干净条件性能与原始数据率权衡", st, max_height=4.8 * inch))
    story.append(
        p(
            f"推荐配置的数据率为{s['bitrate']} bit/s，每天单通道原始存储约{s['storage']} MiB，相对360 Hz / 11 bit参考配置减少{s['bitrate_reduction']}%。"
            "所有满足预设干净条件性能、相对抗噪退化和时间误差约束的配置均保持360 Hz，表明在本任务与噪声模型下，降低有效位数比降低采样率更稳健。",
            st["body"],
        )
    )

    story.append(p("5　讨论与改进分析", st["h1"]))
    story.append(p("5.1　主要发现与工程意义", st["h2"]))
    story.append(
        p(
            "采样率和有效位数应根据具体生理信号任务联合优化，而不能只根据波形视觉效果或单一理论指标选择。干净条件下R峰检出率容易接近性能上限，"
            "但时间误差可以更早揭示低采样率代价；标准运动伪影进一步显示，采样率下降会明显损害检测器抗噪性能，而有效位数下降影响较小。"
            "数据率降低可直接减少存储与传输负担，也可能降低系统工作量；但本项目没有真实硬件，不能将数据率下降写成实测功耗下降。",
            st["body"],
        )
    )
    story.append(p("5.2　局限性", st["h2"]))
    story.extend(
        bullet_list(
            [
                "原始数据已经以360 Hz、11 bit数字化，只能可信研究降采样和降低有效位数。",
                "零相位离线滤波不等价于实时因果模拟前端，尚未验证群时延、元件误差与安全性。",
                "标准噪声压力测试不能完全代表长期真实佩戴中的全部干扰。",
                "结论仅适用于R峰监测，不能外推到ST段分析、形态诊断或临床决策。",
                "XQRS设置保持固定，结果包含特定检测器与采集参数之间的交互。",
            ],
            st,
        )
    )
    story.append(p("5.3　后续改进", st["h2"]))
    story.append(
        p(
            "后续应搭建真实模拟前端与ADC硬件，测量共模抑制、实时延迟和实际功耗；加入信号质量指数，在低质量片段拒绝输出；"
            "比较因果滤波与不同QRS检测算法，并使用真实可穿戴运动数据进行外部验证。",
            st["body"],
        )
    )

    story.append(p("6　结论", st["h1"]))
    story.append(
        p(
            f"本项目完成了ECG采样率、ADC有效位数与抗噪性能的全因子联合设计。基于48条动态ECG和12条标准运动伪影记录，"
            f"推荐<b>{s['configuration']}</b>作为R峰监测任务的工程折中方案。该配置保持与参考配置接近的R峰检测性能，同时将原始数据率降低{s['bitrate_reduction']}%。"
            "研究结果支持任务导向的低数据率采集设计，同时强调严重运动伪影、真实因果前端和临床用途仍需进一步验证。",
            st["body"],
        )
    )

    story.append(p("参考文献", st["h1"]))
    references = [
        "[1] Moody GB, Mark RG. The impact of the MIT-BIH Arrhythmia Database. IEEE Engineering in Medicine and Biology Magazine, 2001, 20(3):45-50.",
        "[2] Goldberger AL, et al. PhysioBank, PhysioToolkit, and PhysioNet. Circulation, 2000, 101(23):e215-e220.",
        "[3] MIT-BIH Arrhythmia Database. PhysioNet. https://physionet.org/content/mitdb/1.0.0/",
        "[4] MIT-BIH Noise Stress Test Database. PhysioNet. https://physionet.org/content/nstdb/1.0.0/",
        "[5] WFDB Python Package Documentation. https://wfdb.readthedocs.io/",
    ]
    for reference in references:
        story.append(p(reference, st["small"]))

    story.append(p("附录A　复现说明", st["h1"]))
    story.append(
        p(
            "项目提供完整源代码、固定参数配置、软件依赖、数据下载脚本、SHA-256数据清单、逐记录结果、聚合结果与自动制图脚本。"
            "执行顺序：python src/download_data.py；python src/run_experiments.py --mode all --workers 8；"
            "python src/analyze_results.py；python src/build_report.py。",
            st["body"],
        )
    )
    story.append(
        styled_table(
            ["审核项目", "审核结果"],
            [
                ["数据完整性", "60条记录均可读取，采样率360 Hz，标注非空"],
                ["实验覆盖", "48条干净记录×30配置；12条噪声记录×30配置"],
                ["计数守恒", "全部结果满足TP+FN=参考心搏数，TP+FP=检测心搏数"],
                ["失败任务", "0条记录失败"],
                ["可复现性", "配置、依赖、下载清单、逐记录CSV和脚本齐全"],
            ],
            [1.5, 5.1],
            st,
        )
    )

    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)


def main() -> None:
    path = REPORT_DIR / "final_report.pdf"
    build_pdf(path)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
