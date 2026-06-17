#!/usr/bin/env python3
"""生成小红书发布后复盘 HTML 看板。"""

from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "reports"

DIMENSIONS = [
    "入口吸引力",
    "标题搜索力",
    "正文承接力",
    "收藏价值",
    "评论互动",
    "转化/关注潜力",
]

METRICS = [
    ("exposure", "曝光", ["曝光", "展现", "impressions"]),
    ("views", "阅读/点击", ["阅读", "点击", "浏览", "观看", "views", "clicks"]),
    ("likes", "点赞", ["点赞", "赞", "likes"]),
    ("favorites", "收藏", ["收藏", "fav", "favorites", "collects"]),
    ("comments", "评论", ["评论", "comments"]),
    ("shares", "分享", ["分享", "转发", "shares"]),
    ("follows", "关注", ["关注", "涨粉", "follows"]),
    ("conversions", "转化", ["转化", "成交", "咨询", "conversions"]),
]

COLORS = ["#ff2442", "#0f766e", "#f59e0b", "#2563eb", "#7c3aed", "#db2777"]


class ReportError(Exception):
    """报告生成错误。"""


def emit(data: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"JSON 格式错误：{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReportError("复盘 JSON 顶层必须是 object")
    return raw


def sanitize_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned or "review-report"


def resolve_output(args: argparse.Namespace, data: dict[str, Any]) -> Path:
    if args.output:
        return Path(args.output).expanduser().resolve()

    report_id = args.report_id or str(data.get("report_id") or "")
    if not report_id:
        title = str(data.get("note", {}).get("title") or "review")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_id = f"{sanitize_id(title)[:48]}-{stamp}"
    output_dir = Path(args.output_dir or DEFAULT_OUTPUT_DIR)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    return output_dir / f"{sanitize_id(report_id)}.html"


def parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "数据不足", "未知"}:
        return None
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    elif text.lower().endswith("k"):
        multiplier = 1000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def format_number(value: float | None) -> str:
    if value is None:
        return "数据不足"
    if value >= 10000:
        return f"{value / 10000:.1f}万"
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.1f}"


def clamp_score(value: Any) -> float | None:
    number = parse_number(value)
    if number is None:
        return None
    return max(0.0, min(100.0, number))


def metric_value(metrics: dict[str, Any], key: str, aliases: list[str]) -> float | None:
    if key in metrics:
        return parse_number(metrics.get(key))
    for alias in aliases:
        if alias in metrics:
            return parse_number(metrics.get(alias))
    return None


def normalize_metrics(raw: Any) -> list[dict[str, Any]]:
    metrics = raw if isinstance(raw, dict) else {}
    result = []
    for key, label, aliases in METRICS:
        value = metric_value(metrics, key, aliases)
        result.append({"key": key, "label": label, "value": value})
    return result


def find_score_entry(raw_scores: Any, dimension: str) -> Any:
    if isinstance(raw_scores, dict):
        return raw_scores.get(dimension)
    if isinstance(raw_scores, list):
        for item in raw_scores:
            if isinstance(item, dict) and item.get("dimension") == dimension:
                return item
            if isinstance(item, dict) and item.get("name") == dimension:
                return item
    return None


def normalize_scores(raw_scores: Any) -> list[dict[str, Any]]:
    scores = []
    for dimension in DIMENSIONS:
        entry = find_score_entry(raw_scores, dimension)
        score = None
        evidence = "数据不足，建议补充更多表现数据。"
        confidence = "低"
        if isinstance(entry, dict):
            score = clamp_score(entry.get("score", entry.get("分数")))
            evidence = str(entry.get("evidence") or entry.get("证据") or evidence)
            confidence = str(entry.get("confidence") or entry.get("置信度") or confidence)
        elif isinstance(entry, (int, float, str)):
            score = clamp_score(entry)
            if score is None and str(entry).strip():
                evidence = str(entry)
        scores.append(
            {
                "dimension": dimension,
                "score": score,
                "evidence": evidence,
                "confidence": confidence,
            }
        )
    return scores


def average_score(scores: list[dict[str, Any]]) -> float | None:
    values = [item["score"] for item in scores if item.get("score") is not None]
    if not values:
        return None
    return sum(values) / len(values)


def normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [tag.strip() for tag in re.split(r"[\s,，]+", value) if tag.strip()]
    return []


def resolve_image_path(src: str, base_dir: Path) -> Path | None:
    path = Path(src).expanduser()
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend([base_dir / path, ROOT / path])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def embed_image(src: str, base_dir: Path) -> tuple[str | None, str]:
    if src.startswith("data:image/"):
        return src, "内嵌图片"
    if re.match(r"^https?://", src):
        return None, f"远程图片未内嵌：{src}"
    path = resolve_image_path(src, base_dir)
    if not path:
        return None, f"图片文件不可用：{src}"
    mime, _ = mimetypes.guess_type(str(path))
    if not mime or not mime.startswith("image/"):
        return None, f"不是可展示图片：{src}"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}", path.name


def normalize_images(note: dict[str, Any], base_dir: Path) -> list[dict[str, str | None]]:
    raw_images = note.get("images") or note.get("image_paths") or note.get("图片") or []
    if isinstance(raw_images, (str, dict)):
        raw_images = [raw_images]
    result = []
    if not isinstance(raw_images, list):
        return result
    for index, item in enumerate(raw_images, start=1):
        caption = f"图{index}"
        src = ""
        if isinstance(item, str):
            src = item
        elif isinstance(item, dict):
            src = str(item.get("path") or item.get("src") or item.get("url") or item.get("data_uri") or "")
            caption = str(item.get("caption") or item.get("label") or caption)
        if not src:
            continue
        data_uri, status = embed_image(src, base_dir)
        result.append({"caption": caption, "src": data_uri, "status": status})
    return result


def as_items(value: Any) -> list[dict[str, str]]:
    if not value:
        return []
    raw = value if isinstance(value, list) else [value]
    result = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            result.append({"title": f"条目 {index}", "body": item})
        elif isinstance(item, dict):
            title = str(
                item.get("title")
                or item.get("problem")
                or item.get("hypothesis")
                or item.get("name")
                or f"条目 {index}"
            )
            parts = []
            for key in ("reason", "evidence", "change", "success_metric", "action", "body", "risk"):
                if item.get(key):
                    parts.append(str(item[key]))
            body = "；".join(parts) if parts else json.dumps(item, ensure_ascii=False)
            result.append({"title": title, "body": body})
    return result


def text_block(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return '<span class="muted">未提供</span>'
    return "<br>".join(escape(line) for line in text.splitlines())


def tag_html(tags: list[str]) -> str:
    if not tags:
        return '<span class="muted">未提供标签</span>'
    return "".join(f'<span class="tag">{escape(tag if tag.startswith("#") else "#" + tag)}</span>' for tag in tags)


def radar_chart(scores: list[dict[str, Any]]) -> str:
    size = 360
    cx = cy = size / 2
    radius = 118
    levels = []
    for ratio in (0.2, 0.4, 0.6, 0.8, 1.0):
        points = []
        for index in range(len(DIMENSIONS)):
            angle = -math.pi / 2 + 2 * math.pi * index / len(DIMENSIONS)
            points.append(f"{cx + radius * ratio * math.cos(angle):.1f},{cy + radius * ratio * math.sin(angle):.1f}")
        levels.append(f'<polygon points="{" ".join(points)}" class="radar-grid"/>')

    axes = []
    labels = []
    polygon_points = []
    for index, item in enumerate(scores):
        angle = -math.pi / 2 + 2 * math.pi * index / len(DIMENSIONS)
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        axes.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" class="radar-axis"/>')
        label_x = cx + (radius + 34) * math.cos(angle)
        label_y = cy + (radius + 34) * math.sin(angle)
        anchor = "middle"
        if label_x < cx - 20:
            anchor = "end"
        elif label_x > cx + 20:
            anchor = "start"
        value = item.get("score")
        score_text = "数据不足" if value is None else f"{value:.0f}"
        labels.append(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="{anchor}" class="radar-label">'
            f"{escape(item['dimension'])}<tspan x=\"{label_x:.1f}\" dy=\"15\">{escape(score_text)}</tspan></text>"
        )
        ratio = (value or 0) / 100
        polygon_points.append(f"{cx + radius * ratio * math.cos(angle):.1f},{cy + radius * ratio * math.sin(angle):.1f}")

    return (
        '<svg class="chart radar" viewBox="0 0 360 360" role="img" aria-label="六维雷达图">'
        + "".join(levels)
        + "".join(axes)
        + f'<polygon points="{" ".join(polygon_points)}" class="radar-area"/>'
        + "".join(labels)
        + "</svg>"
    )


def bar_chart(metrics: list[dict[str, Any]]) -> str:
    values = [item["value"] for item in metrics if item.get("value") is not None]
    if not values:
        return '<div class="empty-chart">暂无可绘制的指标数据</div>'
    max_value = max(values) or 1
    width = 760
    height = 300
    left = 54
    bottom = 54
    top = 24
    chart_h = height - top - bottom
    bar_gap = 14
    bar_w = (width - left - 28 - bar_gap * (len(metrics) - 1)) / len(metrics)
    bars = []
    for index, item in enumerate(metrics):
        value = item.get("value")
        x = left + index * (bar_w + bar_gap)
        bar_h = 0 if value is None else chart_h * value / max_value
        y = top + chart_h - bar_h
        color = COLORS[index % len(COLORS)]
        label = escape(item["label"])
        number = escape(format_number(value))
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="5" fill="{color}"/>'
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle" class="bar-value">{number}</text>'
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 25}" text-anchor="middle" class="bar-label">{label}</text>'
        )
    return (
        '<svg class="chart bar" viewBox="0 0 760 300" role="img" aria-label="指标柱状图">'
        f'<line x1="{left}" y1="{top + chart_h}" x2="{width - 20}" y2="{top + chart_h}" class="chart-axis"/>'
        + "".join(bars)
        + "</svg>"
    )


def pie_path(cx: float, cy: float, radius: float, start_angle: float, end_angle: float) -> str:
    start = math.radians(start_angle)
    end = math.radians(end_angle)
    x1 = cx + radius * math.cos(start)
    y1 = cy + radius * math.sin(start)
    x2 = cx + radius * math.cos(end)
    y2 = cy + radius * math.sin(end)
    large = 1 if end_angle - start_angle > 180 else 0
    return f"M {cx:.1f} {cy:.1f} L {x1:.1f} {y1:.1f} A {radius:.1f} {radius:.1f} 0 {large} 1 {x2:.1f} {y2:.1f} Z"


def pie_chart(metrics: list[dict[str, Any]]) -> str:
    interaction_keys = {"likes", "favorites", "comments", "shares"}
    items = [item for item in metrics if item["key"] in interaction_keys and (item.get("value") or 0) > 0]
    total = sum(item["value"] or 0 for item in items)
    if total <= 0:
        return '<div class="empty-chart">暂无点赞、收藏、评论、分享数据</div>'
    cx = cy = 130
    radius = 105
    current = -90.0
    paths = []
    legend = []
    for index, item in enumerate(items):
        value = item["value"] or 0
        angle = 360 * value / total
        end = current + min(angle, 359.999)
        color = COLORS[index % len(COLORS)]
        paths.append(f'<path d="{pie_path(cx, cy, radius, current, end)}" fill="{color}"/>')
        percent = value / total * 100
        legend.append(
            f'<span><i style="background:{color}"></i>{escape(item["label"])} {percent:.1f}%</span>'
        )
        current += angle
    return (
        '<div class="pie-wrap">'
        '<svg class="chart pie" viewBox="0 0 260 260" role="img" aria-label="互动占比饼图">'
        + "".join(paths)
        + '<circle cx="130" cy="130" r="54" fill="#fffaf7"/>'
        + '<text x="130" y="126" text-anchor="middle" class="pie-center">互动</text>'
        + f'<text x="130" y="148" text-anchor="middle" class="pie-total">{escape(format_number(total))}</text>'
        + "</svg>"
        + f'<div class="legend">{"".join(legend)}</div>'
        + "</div>"
    )


def svg_lines(text: str, x: int, y: int, width: int = 10) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) > width * 2:
        clean = clean[: width * 2 - 1] + "…"
    chunks = [clean[i : i + width] for i in range(0, len(clean), width)] or ["未提供"]
    return "".join(
        f'<tspan x="{x}" dy="{0 if index == 0 else 17}">{escape(chunk)}</tspan>'
        for index, chunk in enumerate(chunks[:2])
    )


def flow_chart(note: dict[str, Any], metrics: list[dict[str, Any]], problems: list[dict[str, str]], experiments: list[dict[str, str]]) -> str:
    title = str(note.get("title") or "笔记内容")
    strongest_metric = next((item for item in metrics if item.get("value") is not None), {"label": "数据表现", "value": None})
    metric_text = f"{strongest_metric['label']} {format_number(strongest_metric.get('value'))}"
    problem = problems[0]["title"] if problems else "等待更多数据验证"
    experiment = experiments[0]["title"] if experiments else "下一篇实验待定"
    nodes = [
        ("输入内容", title, 40, 56, "#ff2442"),
        ("数据表现", metric_text, 270, 56, "#0f766e"),
        ("诊断原因", problem, 500, 56, "#f59e0b"),
        ("下一篇实验", experiment, 730, 56, "#7c3aed"),
    ]
    node_svg = []
    for heading, body, x, y, color in nodes:
        node_svg.append(
            f'<rect x="{x}" y="{y}" width="180" height="92" rx="8" fill="#fff" stroke="{color}" stroke-width="2"/>'
            f'<text x="{x + 18}" y="{y + 30}" class="flow-heading" fill="{color}">{escape(heading)}</text>'
            f'<text x="{x + 18}" y="{y + 58}" class="flow-body">{svg_lines(body, x + 18, y + 58, 11)}</text>'
        )
    arrows = []
    for x1, x2 in ((220, 270), (450, 500), (680, 730)):
        arrows.append(f'<line x1="{x1}" y1="102" x2="{x2 - 12}" y2="102" class="flow-line" marker-end="url(#arrow)"/>')
    return (
        '<svg class="flow-chart" viewBox="0 0 950 206" role="img" aria-label="连线图">'
        '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto">'
        '<path d="M0,0 L10,4 L0,8 Z" fill="#636363"/></marker></defs>'
        + "".join(arrows)
        + "".join(node_svg)
        + "</svg>"
    )


def list_cards(items: list[dict[str, str]], empty: str) -> str:
    if not items:
        return f'<p class="muted">{escape(empty)}</p>'
    return "".join(
        f'<article class="mini-card"><h4>{escape(item["title"])}</h4><p>{escape(item["body"])}</p></article>'
        for item in items
    )


def score_cards(scores: list[dict[str, Any]]) -> str:
    cards = []
    for item in scores:
        score = item.get("score")
        score_text = "数据不足" if score is None else f"{score:.0f}"
        cards.append(
            '<article class="score-card">'
            f'<div><strong>{escape(item["dimension"])}</strong><span>置信度：{escape(item["confidence"])}</span></div>'
            f'<b>{escape(score_text)}</b>'
            f'<p>{escape(item["evidence"])}</p>'
            "</article>"
        )
    return "".join(cards)


def render_html(data: dict[str, Any], source_dir: Path) -> str:
    note = data.get("note") if isinstance(data.get("note"), dict) else {}
    metrics = normalize_metrics(data.get("metrics"))
    scores = normalize_scores(data.get("scores"))
    total = average_score(scores)
    total_text = "数据不足" if total is None else f"{total:.0f}"
    tags = normalize_tags(note.get("tags") or note.get("标签"))
    images = normalize_images(note, source_dir)
    diagnosis = data.get("diagnosis") if isinstance(data.get("diagnosis"), dict) else {}
    problems = as_items(diagnosis.get("problems") or diagnosis.get("问题排序") or diagnosis.get("issues"))
    hypotheses = as_items(diagnosis.get("hypotheses") or diagnosis.get("原因假设") or diagnosis.get("reasons"))
    risks = as_items(diagnosis.get("risks") or diagnosis.get("风险边界") or diagnosis.get("risk"))
    experiments = as_items(data.get("experiments") or data.get("下一篇实验卡") or data.get("next_experiments"))
    image_html = ""
    for image in images:
        if image["src"]:
            image_html += (
                '<figure class="image-tile">'
                f'<img src="{escape(str(image["src"]))}" alt="{escape(str(image["caption"]))}">'
                f'<figcaption>{escape(str(image["caption"]))}</figcaption>'
                "</figure>"
            )
        else:
            image_html += (
                '<figure class="image-tile placeholder">'
                f'<div>{escape(str(image["status"]))}</div>'
                f'<figcaption>{escape(str(image["caption"]))}</figcaption>'
                "</figure>"
            )
    if not image_html:
        image_html = '<div class="image-empty">未提供图片，报告仅展示文字与数据复盘。</div>'

    css = """
* { box-sizing: border-box; }
body {
  margin: 0;
  color: #1f1f23;
  background: #fff7f2;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.page { max-width: 1180px; margin: 0 auto; padding: 32px 22px 56px; }
.hero {
  display: grid; grid-template-columns: minmax(0, 1fr) 190px; gap: 28px; align-items: center;
  padding: 30px; background: #ffffff; border: 1px solid #f0d7cf; border-radius: 8px;
  box-shadow: 0 18px 48px rgba(90, 45, 28, 0.10);
}
.eyebrow { color: #ff2442; font-weight: 700; letter-spacing: 0; margin: 0 0 10px; }
h1 { margin: 0; font-size: 34px; line-height: 1.18; letter-spacing: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; color: #616168; }
.meta span { padding: 7px 10px; background: #fff3ee; border-radius: 8px; }
.total-score {
  width: 170px; height: 170px; border-radius: 50%; display: grid; place-items: center;
  background: radial-gradient(circle at center, #fff 54%, transparent 55%), conic-gradient(#ff2442 0 70%, #0f766e 70% 88%, #f3c86d 88% 100%);
}
.total-score strong { display: block; font-size: 42px; line-height: 1; text-align: center; }
.total-score span { display: block; margin-top: 6px; font-size: 13px; color: #67676f; text-align: center; }
section { margin-top: 24px; padding: 24px; background: #ffffff; border: 1px solid #eddcd4; border-radius: 8px; }
h2 { margin: 0 0 18px; font-size: 22px; letter-spacing: 0; }
h3 { margin: 0 0 14px; font-size: 17px; letter-spacing: 0; }
.grid-2 { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr); gap: 22px; }
.gallery { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.image-tile { margin: 0; border: 1px solid #eee1da; border-radius: 8px; overflow: hidden; background: #fffaf7; }
.image-tile img { width: 100%; height: 220px; object-fit: cover; display: block; }
.image-tile figcaption { padding: 9px 10px; font-size: 13px; color: #666; }
.placeholder, .image-empty { min-height: 140px; display: grid; place-items: center; color: #777; padding: 18px; background: #fff4ed; border-radius: 8px; }
.note-body { line-height: 1.75; color: #33343a; white-space: normal; }
.tag { display: inline-block; margin: 0 8px 8px 0; padding: 7px 10px; color: #aa1d33; background: #fff0f3; border-radius: 8px; font-weight: 650; }
.muted { color: #83838b; }
.charts { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, 0.44fr); gap: 20px; align-items: center; }
.chart-card { padding: 18px; border: 1px solid #eee1da; border-radius: 8px; background: #fffdfa; overflow: auto; }
.chart { width: 100%; height: auto; display: block; }
.radar-grid { fill: none; stroke: #ead7cf; stroke-width: 1; }
.radar-axis, .chart-axis { stroke: #d8cbc4; stroke-width: 1; }
.radar-area { fill: rgba(255, 36, 66, 0.20); stroke: #ff2442; stroke-width: 3; }
.radar-label, .bar-label, .bar-value, .pie-center, .pie-total, .flow-body { fill: #33343a; font-size: 12px; }
.bar-value { font-weight: 700; }
.pie-wrap { display: grid; grid-template-columns: 260px 1fr; gap: 16px; align-items: center; }
.legend { display: grid; gap: 10px; font-size: 14px; }
.legend i { display: inline-block; width: 12px; height: 12px; margin-right: 8px; border-radius: 3px; vertical-align: -1px; }
.empty-chart { min-height: 220px; display: grid; place-items: center; color: #777; background: #fff4ed; border-radius: 8px; }
.score-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; }
.score-card, .mini-card { border: 1px solid #eee1da; background: #fffdfa; border-radius: 8px; padding: 16px; }
.score-card div { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
.score-card span { color: #777; font-size: 12px; }
.score-card b { display: block; margin: 12px 0 8px; color: #ff2442; font-size: 32px; }
.score-card p, .mini-card p { margin: 0; line-height: 1.65; color: #55565d; }
.mini-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
.mini-card h4 { margin: 0 0 8px; font-size: 15px; }
.flow-wrap { overflow-x: auto; }
.flow-chart { min-width: 900px; width: 100%; height: auto; display: block; }
.flow-line { stroke: #636363; stroke-width: 2; }
.flow-heading { font-size: 15px; font-weight: 800; }
.footer-note { margin-top: 18px; color: #777; font-size: 13px; line-height: 1.7; }
@media (max-width: 760px) {
  .hero, .grid-2, .charts, .pie-wrap { grid-template-columns: 1fr; }
  h1 { font-size: 26px; }
  .total-score { width: 140px; height: 140px; }
}
"""

    published_at = note.get("published_at") or note.get("发布时间") or "未提供发布时间"
    goal = note.get("goal") or note.get("目标") or "未提供目标"
    link = note.get("link") or note.get("链接") or ""
    profile_link = note.get("profile_link") or note.get("主页链接") or ""
    title = str(note.get("title") or note.get("标题") or "未命名笔记")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - 发布后复盘 HTML 看板</title>
  <style>{css}</style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <div>
        <p class="eyebrow">发布后复盘 HTML 看板</p>
        <h1>{escape(title)}</h1>
        <div class="meta">
          <span>发布时间：{escape(str(published_at))}</span>
          <span>目标：{escape(str(goal))}</span>
          <span>单篇链接：{escape(str(link or "未提供"))}</span>
          <span>主页链接：{escape(str(profile_link or "未提供"))}</span>
        </div>
      </div>
      <div class="total-score"><div><strong>{escape(total_text)}</strong><span>总分 / 100</span></div></div>
    </header>

    <section>
      <h2>用户输入内容</h2>
      <div class="grid-2">
        <div>
          <h3>图片与封面</h3>
          <div class="gallery">{image_html}</div>
        </div>
        <div>
          <h3>正文与标签</h3>
          <div class="note-body">{text_block(note.get("body") or note.get("正文"))}</div>
          <div style="margin-top:16px">{tag_html(tags)}</div>
        </div>
      </div>
    </section>

    <section>
      <h2>数据图表</h2>
      <div class="charts">
        <div class="chart-card">
          <h3>指标柱状图</h3>
          {bar_chart(metrics)}
        </div>
        <div class="chart-card">
          <h3>互动占比饼图</h3>
          {pie_chart(metrics)}
        </div>
      </div>
    </section>

    <section>
      <h2>六维评分</h2>
      <div class="charts">
        <div class="chart-card">
          <h3>六维雷达图</h3>
          {radar_chart(scores)}
        </div>
        <div class="score-grid">{score_cards(scores)}</div>
      </div>
    </section>

    <section>
      <h2>连线图</h2>
      <div class="flow-wrap">{flow_chart(note, metrics, problems, experiments)}</div>
    </section>

    <section>
      <h2>全链路诊断</h2>
      <div class="mini-grid">{list_cards(problems, "暂无问题排序，请补充更多表现数据。")}</div>
      <h3 style="margin-top:22px">原因假设</h3>
      <div class="mini-grid">{list_cards(hypotheses, "暂无原因假设。")}</div>
      <h3 style="margin-top:22px">风险边界</h3>
      <div class="mini-grid">{list_cards(risks, "暂无额外风险。")}</div>
    </section>

    <section>
      <h2>下一篇建议</h2>
      <div class="mini-grid">{list_cards(experiments, "暂无下一篇实验卡。")}</div>
      <p class="footer-note">本报告只基于已提供或公开可见数据生成。缺失字段未做推断，所有结论应理解为可能原因和下一轮实验假设。</p>
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成小红书发布后复盘 HTML 看板")
    parser.add_argument("--input", required=True, help="复盘 JSON 文件路径")
    parser.add_argument("--output", help="输出 HTML 文件路径")
    parser.add_argument("--output-dir", help="输出目录，默认 outputs/reports")
    parser.add_argument("--report-id", help="报告文件名 ID")
    args = parser.parse_args()

    try:
        input_path = Path(args.input).expanduser().resolve()
        data = load_json(input_path)
        output_path = resolve_output(args, data)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        html = render_html(data, input_path.parent)
        output_path.write_text(html, encoding="utf-8")
        try:
            display_path = str(output_path.relative_to(ROOT))
        except ValueError:
            display_path = str(output_path)
        emit({"status": "ok", "output_file": display_path})
    except ReportError as exc:
        emit({"status": "error", "message": str(exc)}, exit_code=1)


if __name__ == "__main__":
    main()
