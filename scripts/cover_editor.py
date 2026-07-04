#!/usr/bin/env python3
"""本地小红书封面编辑器。"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "cover_editor"
DEFAULT_CANVAS = {"width": 1080, "height": 1440, "background": "#f7f7f5"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


class EditorError(Exception):
    """编辑器请求错误。"""


def safe_name(value: str, default: str = "untitled") -> str:
    """Return a filesystem-safe name without allowing path traversal."""
    text = urllib.parse.unquote(str(value or "")).strip()
    text = Path(text).name
    cleaned = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", text).strip("-._")
    return cleaned or default


def safe_asset_name(value: str, default: str = "asset") -> str:
    raw = urllib.parse.unquote(str(value or "")).strip()
    if "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise EditorError("素材文件名不安全")
    return safe_name(raw, default)


def ensure_dirs(output_dir: Path) -> None:
    for child in ("projects", "exports", "assets"):
        (output_dir / child).mkdir(parents=True, exist_ok=True)


def decode_data_url(value: str, *, expected_prefix: str | None = None) -> tuple[str, bytes]:
    match = re.fullmatch(r"data:([^;,]+);base64,(.+)", str(value or ""), re.S)
    if not match:
        raise EditorError("data_url 格式错误")
    mime = match.group(1).lower()
    if expected_prefix and not mime.startswith(expected_prefix):
        raise EditorError(f"data_url 必须是 {expected_prefix} 类型")
    try:
        return mime, base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise EditorError("base64 数据无效") from exc


def extension_for_mime(mime: str) -> str:
    if mime == "image/jpeg":
        return ".jpg"
    guess = mimetypes.guess_extension(mime) or ".bin"
    return ".jpg" if guess == ".jpe" else guess


def template_layer(layer_id: str, layer_type: str, **kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": layer_id,
        "type": layer_type,
        "name": kwargs.pop("name", layer_id),
        "x": kwargs.pop("x", 0),
        "y": kwargs.pop("y", 0),
        "w": kwargs.pop("w", 200),
        "h": kwargs.pop("h", 120),
        "opacity": kwargs.pop("opacity", 1),
        "locked": kwargs.pop("locked", False),
    }
    base.update(kwargs)
    return base


def built_in_templates() -> list[dict[str, Any]]:
    card = {"fill": "#ffffff", "stroke": "#eadcdf", "radius": 42, "shadow": True}
    red = "#ff2442"
    dark = "#252326"
    muted = "#6b6668"

    return [
        {
            "id": "redskill-cover",
            "name": "REDSkill 封面",
            "canvas": {"width": 1080, "height": 1440, "background": "#2d2929"},
            "layers": [
                template_layer("headline", "text", text="手机也能装", x=82, y=110, w=920, h=160, fontSize=96, fontWeight=900, color="#ffffff", align="left", lineHeight=1.05),
                template_layer("redskill", "text", text="REDSkill", x=82, y=280, w=920, h=180, fontSize=144, fontWeight=900, color=red, align="left", lineHeight=1),
                template_layer("sub", "text", text="不用电脑 | 任选一个 Agent | 先试试 xhs-notes-skill", x=86, y=492, w=900, h=70, fontSize=36, fontWeight=700, color="#ffffff", align="left", lineHeight=1.2),
                template_layer("phone", "rect", x=270, y=700, w=540, h=560, fill="#171416", stroke="#50484a", radius=64, shadow=True),
                template_layer("phone-card", "rect", x=340, y=850, w=400, h=250, fill="#221f21", stroke=red, radius=36, shadow=True),
                template_layer("phone-title", "text", text="REDSkill", x=380, y=910, w=320, h=72, fontSize=62, fontWeight=900, color=red, align="center"),
                template_layer("phone-skill", "text", text="xhs-notes-skill", x=375, y=1025, w=330, h=54, fontSize=38, fontWeight=800, color="#ffffff", align="center"),
            ],
        },
        {
            "id": "flow-steps",
            "name": "安装路径图",
            "canvas": dict(DEFAULT_CANVAS),
            "layers": [
                template_layer("title", "text", text="REDSkill 怎么开始", x=92, y=90, w=896, h=92, fontSize=72, fontWeight=900, color=dark, align="center"),
                *[
                    template_layer(f"step-{i}", "rect", x=210, y=230 + (i - 1) * 175, w=660, h=112, **card)
                    for i in range(1, 6)
                ],
                *[
                    template_layer(f"step-text-{i}", "text", text=text, x=245, y=258 + (i - 1) * 175, w=590, h=56, fontSize=36, fontWeight=800, color=dark, align="center")
                    for i, text in enumerate(["看到 Skill", "点 REDSkill 组件", "复制口令", "放进手机 Agent", "开始用"], start=1)
                ],
                *[
                    template_layer(f"arrow-{i}", "text", text="v", x=510, y=350 + (i - 1) * 175, w=60, h=50, fontSize=42, fontWeight=900, color=red, align="center")
                    for i in range(1, 5)
                ],
            ],
        },
        {
            "id": "entry-example",
            "name": "入口示例图",
            "canvas": dict(DEFAULT_CANVAS),
            "layers": [
                template_layer("title", "text", text="重点不是推荐哪个 Agent", x=88, y=105, w=904, h=92, fontSize=68, fontWeight=900, color=dark, align="center"),
                template_layer("sub", "text", text="它们只是手机端入口示例", x=140, y=210, w=800, h=55, fontSize=36, fontWeight=700, color=muted, align="center"),
                template_layer("app-1", "rect", x=90, y=390, w=270, h=150, **card),
                template_layer("app-2", "rect", x=405, y=390, w=270, h=150, **card),
                template_layer("app-3", "rect", x=720, y=390, w=270, h=150, **card),
                template_layer("app-t1", "text", text="入口 A", x=115, y=435, w=220, h=52, fontSize=36, fontWeight=800, color=dark, align="center"),
                template_layer("app-t2", "text", text="入口 B", x=430, y=435, w=220, h=52, fontSize=36, fontWeight=800, color=dark, align="center"),
                template_layer("app-t3", "text", text="入口 C", x=745, y=435, w=220, h=52, fontSize=36, fontWeight=800, color=dark, align="center"),
                template_layer("target", "rect", x=200, y=720, w=680, h=250, fill="#fff5f6", stroke=red, radius=44, shadow=True),
                template_layer("target-t1", "text", text="REDSkill", x=250, y=765, w=580, h=72, fontSize=62, fontWeight=900, color=red, align="center"),
                template_layer("target-t2", "text", text="xhs-notes-skill", x=250, y=855, w=580, h=58, fontSize=42, fontWeight=900, color=dark, align="center"),
            ],
        },
        {
            "id": "function-grid",
            "name": "功能页",
            "canvas": dict(DEFAULT_CANVAS),
            "layers": [
                template_layer("title", "text", text="xhs-notes-skill 能做什么", x=80, y=95, w=920, h=86, fontSize=66, fontWeight=900, color=dark, align="center"),
                template_layer("subtitle", "text", text="小红书创作和复盘助手", x=170, y=205, w=740, h=54, fontSize=36, fontWeight=800, color=dark, align="center"),
                template_layer("brand", "rect", x=190, y=322, w=700, h=140, fill="#fffaf9", stroke=red, radius=32, shadow=True),
                template_layer("brand-text", "text", text="xhs-notes-skill", x=245, y=365, w=590, h=64, fontSize=54, fontWeight=900, color=red, align="center"),
                *[
                    template_layer(f"card-{i}", "rect", x=x, y=y, w=400, h=210, **card)
                    for i, (x, y) in enumerate([(90, 545), (590, 545), (90, 805), (590, 805)], start=1)
                ],
                template_layer("card-5", "rect", x=90, y=1070, w=900, h=210, **card),
                *[
                    template_layer(f"feature-{i}", "text", text=title, x=x, y=y, w=w, h=56, fontSize=48, fontWeight=900, color=dark, align="center")
                    for i, (title, x, y, w) in enumerate([
                        ("选题", 130, 600, 320), ("标题", 630, 600, 320), ("正文", 130, 860, 320), ("标签", 630, 860, 320), ("复盘", 260, 1130, 560)
                    ], start=1)
                ],
                *[
                    template_layer(f"feature-note-{i}", "text", text=note, x=x, y=y, w=w, h=42, fontSize=30, fontWeight=700, color=muted, align="center")
                    for i, (note, x, y, w) in enumerate([
                        ("确定方向", 130, 680, 320), ("提升点击", 630, 680, 320), ("结构清楚", 130, 940, 320), ("搜索匹配", 630, 940, 320), ("数据诊断", 260, 1210, 560)
                    ], start=1)
                ],
            ],
        },
        {
            "id": "audience-grid",
            "name": "适合人群页",
            "canvas": dict(DEFAULT_CANVAS),
            "layers": [
                template_layer("title", "text", text="适合谁？", x=100, y=98, w=880, h=100, fontSize=92, fontWeight=900, color=dark, align="center"),
                template_layer("subtitle", "text", text="从具体场景开始用 Skill", x=145, y=232, w=790, h=52, fontSize=38, fontWeight=800, color=dark, align="center"),
                *[
                    template_layer(f"aud-card-{i}", "rect", x=x, y=y, w=410, h=260, **card)
                    for i, (x, y) in enumerate([(80, 365), (590, 365), (80, 690), (590, 690)], start=1)
                ],
                *[
                    template_layer(f"aud-title-{i}", "text", text=title, x=x, y=y, w=330, h=54, fontSize=42, fontWeight=900, color=dark, align="center")
                    for i, (title, x, y) in enumerate([
                        ("小红书新手", 120, 468), ("内容创作者", 630, 468), ("运营 / 自媒体", 120, 793), ("AI 工具玩家", 630, 793)
                    ], start=1)
                ],
                *[
                    template_layer(f"aud-note-{i}", "text", text=note, x=x, y=y, w=330, h=42, fontSize=30, fontWeight=700, color=muted, align="center")
                    for i, (note, x, y) in enumerate([
                        ("不知道怎么写", 120, 540), ("想固定流程", 630, 540), ("要选题和复盘", 120, 865), ("想试 REDSkill", 630, 865)
                    ], start=1)
                ],
                template_layer("callout", "rect", x=140, y=1088, w=800, h=110, fill="#fff2f4", stroke=red, radius=55, shadow=False),
                template_layer("callout-text", "text", text="不用一上来折腾复杂配置", x=180, y=1117, w=720, h=52, fontSize=40, fontWeight=900, color=red, align="center"),
            ],
        },
        {
            "id": "vote-card",
            "name": "评论投票页",
            "canvas": dict(DEFAULT_CANVAS),
            "layers": [
                template_layer("title", "text", text="下一篇你想看？", x=100, y=105, w=880, h=90, fontSize=76, fontWeight=900, color=dark, align="center"),
                *[
                    template_layer(f"vote-{i}", "rect", x=135, y=y, w=810, h=138, fill="#ffffff", stroke=red, radius=34, shadow=True)
                    for i, y in enumerate([310, 510, 710], start=1)
                ],
                template_layer("vote-a", "text", text="A. 手机端安装步骤", x=185, y=352, w=710, h=52, fontSize=40, fontWeight=900, color=dark, align="center"),
                template_layer("vote-b", "text", text="B. 用它写一篇笔记", x=185, y=552, w=710, h=52, fontSize=40, fontWeight=900, color=dark, align="center"),
                template_layer("vote-c", "text", text="C. 用它复盘一篇笔记", x=185, y=752, w=710, h=52, fontSize=40, fontWeight=900, color=dark, align="center"),
                template_layer("footer", "text", text="评论区选 A / B / C 就行", x=150, y=1010, w=780, h=58, fontSize=42, fontWeight=900, color=red, align="center"),
            ],
        },
    ]


BUILTIN_TEMPLATES = built_in_templates()


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>小红书封面编辑器</title>
  <style>
    :root {
      --red: #ff2442;
      --ink: #252326;
      --muted: #746f72;
      --line: #eadfe2;
      --paper: #f7f7f5;
      --panel: #fffdfb;
      --soft: #fff3f5;
      --shadow: 0 18px 50px rgba(28, 20, 24, .11);
      font-family: "HarmonyOS Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        linear-gradient(rgba(255,255,255,.74), rgba(255,255,255,.74)),
        radial-gradient(circle at 15% 12%, rgba(255,36,66,.12), transparent 32%),
        radial-gradient(circle at 82% 0%, rgba(255,36,66,.10), transparent 30%),
        #f4f1ef;
    }
    button, input, select, textarea { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 10px;
      padding: 8px 12px;
      cursor: pointer;
    }
    button:hover { border-color: var(--red); color: var(--red); }
    button.primary { background: var(--red); border-color: var(--red); color: #fff; }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 10px;
      background: #fff;
      color: var(--ink);
    }
    textarea { min-height: 88px; resize: vertical; }
    #cover-editor-app { min-height: 100vh; display: flex; flex-direction: column; }
    .topbar {
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 18px;
      background: rgba(255,253,251,.92);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(14px);
      position: sticky;
      top: 0;
      z-index: 20;
    }
    .brand { display: flex; align-items: baseline; gap: 10px; font-weight: 900; letter-spacing: .02em; }
    .brand span { color: var(--red); }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .workspace {
      flex: 1;
      display: grid;
      grid-template-columns: 280px minmax(420px, 1fr) 310px;
      gap: 14px;
      padding: 14px;
      overflow: hidden;
    }
    .panel {
      background: rgba(255,253,251,.94);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      overflow: hidden;
      min-height: 0;
    }
    .panel h2 {
      margin: 0;
      padding: 15px 16px 8px;
      font-size: 16px;
      letter-spacing: .04em;
    }
    .panel-body { padding: 12px 14px 16px; overflow: auto; max-height: calc(100vh - 110px); }
    .template-card, .layer-row {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      background: #fff;
      margin-bottom: 10px;
    }
    .template-card { cursor: pointer; }
    .template-card:hover { border-color: var(--red); background: var(--soft); }
    .template-name { font-weight: 900; margin-bottom: 4px; }
    .template-meta { font-size: 12px; color: var(--muted); }
    .layer-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; cursor: pointer; }
    .layer-row.active { border-color: var(--red); background: var(--soft); }
    .layer-title { min-width: 0; font-weight: 800; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .layer-type { color: var(--muted); font-size: 12px; }
    .stage {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,.58);
      display: grid;
      place-items: center;
      overflow: auto;
      min-height: 0;
      position: relative;
    }
    .canvas-wrap {
      margin: 22px;
      padding: 18px;
      background: #fff;
      border-radius: 18px;
      box-shadow: 0 24px 80px rgba(28, 20, 24, .18);
    }
    canvas {
      width: min(58vw, 540px);
      aspect-ratio: 1080 / 1440;
      display: block;
      background: #fff;
      cursor: default;
    }
    .drop-hint {
      position: absolute;
      left: 50%;
      bottom: 20px;
      transform: translateX(-50%);
      background: rgba(37,35,38,.78);
      color: #fff;
      padding: 9px 12px;
      border-radius: 999px;
      font-size: 13px;
      pointer-events: none;
    }
    .field { margin-bottom: 12px; }
    .field label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; font-weight: 800; }
    .inline { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .button-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }
    .status {
      min-height: 22px;
      font-size: 13px;
      color: var(--muted);
      padding: 0 4px 8px;
      line-height: 1.5;
    }
    .empty { color: var(--muted); font-size: 13px; line-height: 1.6; padding: 10px; }
    @media (max-width: 1080px) {
      .workspace { grid-template-columns: 1fr; overflow: auto; }
      .panel-body { max-height: none; }
      canvas { width: min(86vw, 540px); }
    }
  </style>
</head>
<body>
<div id="cover-editor-app">
  <header class="topbar">
    <div class="brand">XHS <span>Cover Editor</span></div>
    <div class="toolbar">
      <input id="projectName" value="untitled" style="width:150px" aria-label="项目名称">
      <button id="newBtn">新建</button>
      <select id="projectSelect" style="width:150px" aria-label="打开项目"></select>
      <button id="openBtn">打开</button>
      <button id="saveBtn" class="primary">保存</button>
      <button id="saveAsBtn">另存为</button>
      <button id="exportBtn">导出 PNG</button>
    </div>
  </header>
  <main class="workspace">
    <aside class="panel">
      <h2>模板素材库</h2>
      <div class="panel-body">
        <div id="templateList"></div>
        <h2 style="padding-left:0">图层</h2>
        <div class="button-grid">
          <button id="addTextBtn">文字</button>
          <button id="addRectBtn">矩形</button>
          <button id="addEllipseBtn">圆形</button>
          <button id="uploadBtn">图片</button>
        </div>
        <input id="fileInput" type="file" accept="image/*" hidden multiple>
        <div id="layerList"></div>
      </div>
    </aside>
    <section class="stage" id="dropZone">
      <div class="canvas-wrap">
        <canvas id="canvas" width="1080" height="1440"></canvas>
      </div>
      <div class="drop-hint">把 PNG/JPG/WebP 拖进来即可成为图片图层</div>
    </section>
    <aside class="panel">
      <h2>属性</h2>
      <div class="panel-body">
        <div class="status" id="status"></div>
        <div class="button-grid">
          <button id="bringForwardBtn">上移</button>
          <button id="sendBackwardBtn">下移</button>
          <button id="bringTopBtn">置顶</button>
          <button id="sendBottomBtn">置底</button>
          <button id="lockBtn">锁定/解锁</button>
          <button id="deleteBtn">删除</button>
        </div>
        <div id="properties"></div>
      </div>
    </aside>
  </main>
</div>
<script>
const BUILTIN_TEMPLATES = __TEMPLATES__;
const DEFAULT_PROJECT = __DEFAULT_PROJECT__;
let project = clone(DEFAULT_PROJECT);
let selectedId = null;
let dirty = false;
let drag = null;
const imageCache = new Map();

const el = id => document.getElementById(id);
const canvas = el('canvas');
const ctx = canvas.getContext('2d');

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function uid(prefix) { return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`; }
function selectedLayer() { return project.layers.find(layer => layer.id === selectedId) || null; }
function setStatus(text) { el('status').textContent = text || ''; }
function markDirty(options = {}) {
  dirty = true;
  if (options.canvasOnly) renderCanvas();
  else render();
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
}
function canvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height };
}
function applyCanvas() {
  canvas.width = project.canvas.width;
  canvas.height = project.canvas.height;
  canvas.style.aspectRatio = `${project.canvas.width} / ${project.canvas.height}`;
}
function drawRoundRect(c, x, y, w, h, r) {
  const radius = Math.min(r || 0, w / 2, h / 2);
  c.beginPath();
  c.moveTo(x + radius, y);
  c.arcTo(x + w, y, x + w, y + h, radius);
  c.arcTo(x + w, y + h, x, y + h, radius);
  c.arcTo(x, y + h, x, y, radius);
  c.arcTo(x, y, x + w, y, radius);
  c.closePath();
}
function wrappedLines(c, text, maxWidth) {
  const raw = String(text || '').split('\n');
  const lines = [];
  raw.forEach(part => {
    let current = '';
    Array.from(part).forEach(ch => {
      const next = current + ch;
      if (c.measureText(next).width > maxWidth && current) {
        lines.push(current);
        current = ch;
      } else {
        current = next;
      }
    });
    lines.push(current);
  });
  return lines;
}
function drawText(layer) {
  ctx.save();
  ctx.globalAlpha = layer.opacity ?? 1;
  const weight = layer.fontWeight || 700;
  const size = layer.fontSize || 48;
  const family = layer.fontFamily || '"HarmonyOS Sans SC", "Microsoft YaHei", sans-serif';
  ctx.font = `${weight} ${size}px ${family}`;
  ctx.fillStyle = layer.color || '#252326';
  ctx.textAlign = layer.align || 'left';
  ctx.textBaseline = 'top';
  const lineHeight = size * (layer.lineHeight || 1.18);
  const lines = wrappedLines(ctx, layer.text || '', layer.w || 400);
  const startX = layer.align === 'center' ? layer.x + layer.w / 2 : layer.align === 'right' ? layer.x + layer.w : layer.x;
  lines.forEach((line, index) => ctx.fillText(line, startX, layer.y + index * lineHeight));
  ctx.restore();
}
function getImage(src) {
  if (!src) return null;
  if (imageCache.has(src)) return imageCache.get(src);
  const img = new Image();
  img.onload = () => renderCanvas();
  img.src = src;
  imageCache.set(src, img);
  return img;
}
function renderLayer(layer) {
  ctx.save();
  ctx.globalAlpha = layer.opacity ?? 1;
  if (layer.shadow) {
    ctx.shadowColor = 'rgba(28,20,24,.12)';
    ctx.shadowBlur = 28;
    ctx.shadowOffsetY = 12;
  }
  if (layer.type === 'rect') {
    drawRoundRect(ctx, layer.x, layer.y, layer.w, layer.h, layer.radius || 0);
    ctx.fillStyle = layer.fill || '#fff';
    ctx.fill();
    if (layer.stroke) {
      ctx.strokeStyle = layer.stroke;
      ctx.lineWidth = layer.strokeWidth || 2;
      ctx.stroke();
    }
  } else if (layer.type === 'ellipse') {
    ctx.beginPath();
    ctx.ellipse(layer.x + layer.w / 2, layer.y + layer.h / 2, Math.abs(layer.w / 2), Math.abs(layer.h / 2), 0, 0, Math.PI * 2);
    ctx.fillStyle = layer.fill || '#fff';
    ctx.fill();
    if (layer.stroke) {
      ctx.strokeStyle = layer.stroke;
      ctx.lineWidth = layer.strokeWidth || 2;
      ctx.stroke();
    }
  } else if (layer.type === 'image') {
    const img = getImage(layer.src);
    if (img && img.complete && img.naturalWidth) ctx.drawImage(img, layer.x, layer.y, layer.w, layer.h);
  } else if (layer.type === 'text') {
    ctx.restore();
    drawText(layer);
    ctx.save();
  }
  ctx.restore();
}
function renderSelection(layer) {
  if (!layer) return;
  ctx.save();
  ctx.strokeStyle = '#ff2442';
  ctx.lineWidth = 3;
  ctx.setLineDash([10, 6]);
  ctx.strokeRect(layer.x, layer.y, layer.w, layer.h);
  ctx.setLineDash([]);
  ctx.fillStyle = '#ff2442';
  ctx.fillRect(layer.x + layer.w - 13, layer.y + layer.h - 13, 26, 26);
  ctx.restore();
}
function renderCanvas() {
  applyCanvas();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = project.canvas.background || '#f7f7f5';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  project.layers.forEach(renderLayer);
  renderSelection(selectedLayer());
}
function render() {
  renderCanvas();
  renderLayers();
  renderProperties();
}
function hitTest(point) {
  for (let i = project.layers.length - 1; i >= 0; i--) {
    const layer = project.layers[i];
    if (layer.locked) continue;
    if (point.x >= layer.x && point.x <= layer.x + layer.w && point.y >= layer.y && point.y <= layer.y + layer.h) return layer;
  }
  return null;
}
function isResizeHandle(point, layer) {
  return layer && point.x >= layer.x + layer.w - 30 && point.y >= layer.y + layer.h - 30;
}
function renderTemplates() {
  el('templateList').innerHTML = BUILTIN_TEMPLATES.map(t => `
    <div class="template-card" data-template="${escapeHtml(t.id)}">
      <div class="template-name">${escapeHtml(t.name)}</div>
      <div class="template-meta">${t.canvas.width} x ${t.canvas.height} · 可编辑图层</div>
    </div>`).join('');
  document.querySelectorAll('[data-template]').forEach(node => node.addEventListener('click', () => {
    if (dirty && !confirm('当前项目还没保存，确定替换为模板吗？')) return;
    const template = BUILTIN_TEMPLATES.find(item => item.id === node.dataset.template);
    project = { canvas: clone(template.canvas), layers: clone(template.layers), meta: { name: template.id, template: template.id, updated_at: new Date().toISOString() } };
    selectedId = project.layers[project.layers.length - 1]?.id || null;
    el('projectName').value = template.id;
    dirty = true;
    render();
  }));
}
function renderLayers() {
  const list = el('layerList');
  if (!project.layers.length) {
    list.innerHTML = '<div class="empty">还没有图层。可以添加文字、图形，或拖入图片素材。</div>';
    return;
  }
  list.innerHTML = project.layers.slice().reverse().map(layer => `
    <div class="layer-row ${layer.id === selectedId ? 'active' : ''}" data-layer="${layer.id}">
      <div>
        <div class="layer-title">${escapeHtml(layer.name || layer.id)}</div>
        <div class="layer-type">${escapeHtml(layer.type)}${layer.locked ? ' · 已锁定' : ''}</div>
      </div>
      <span>${layer.opacity ?? 1}</span>
    </div>`).join('');
  document.querySelectorAll('[data-layer]').forEach(node => node.addEventListener('click', () => {
    selectedId = node.dataset.layer;
    render();
  }));
}
function inputField(label, key, value, type='text') {
  return `<div class="field"><label>${label}</label><input data-prop="${key}" type="${type}" value="${escapeHtml(value ?? '')}"></div>`;
}
function renderProperties() {
  const layer = selectedLayer();
  const box = el('properties');
  if (!layer) {
    box.innerHTML = `<div class="field"><label>画布背景</label><input data-canvas="background" type="color" value="${project.canvas.background || '#f7f7f5'}"></div><div class="empty">请选择一个图层来编辑属性。</div>`;
    bindPropertyInputs();
    return;
  }
  let html = `
    ${inputField('名称', 'name', layer.name)}
    <div class="inline">${inputField('X', 'x', Math.round(layer.x), 'number')}${inputField('Y', 'y', Math.round(layer.y), 'number')}</div>
    <div class="inline">${inputField('宽度', 'w', Math.round(layer.w), 'number')}${inputField('高度', 'h', Math.round(layer.h), 'number')}</div>
    ${inputField('透明度', 'opacity', layer.opacity ?? 1, 'number')}`;
  if (layer.type === 'text') {
    html += `<div class="field"><label>文字内容</label><textarea data-prop="text">${escapeHtml(layer.text || '')}</textarea></div>
      <div class="inline">${inputField('字号', 'fontSize', layer.fontSize || 48, 'number')}${inputField('行高', 'lineHeight', layer.lineHeight || 1.18, 'number')}</div>
      <div class="inline">${inputField('字重', 'fontWeight', layer.fontWeight || 800, 'number')}${inputField('文字颜色', 'color', layer.color || '#252326', 'color')}</div>
      <div class="field"><label>对齐</label><select data-prop="align">
        <option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option>
      </select></div>`;
  } else if (layer.type === 'rect' || layer.type === 'ellipse') {
    html += `<div class="inline">${inputField('填充', 'fill', layer.fill || '#ffffff', 'color')}${inputField('描边', 'stroke', layer.stroke || '#eadfe2', 'color')}</div>`;
    if (layer.type === 'rect') html += inputField('圆角', 'radius', layer.radius || 0, 'number');
  } else if (layer.type === 'image') {
    html += inputField('图片地址', 'src', layer.src || '');
  }
  box.innerHTML = html;
  if (layer.type === 'text') box.querySelector('[data-prop="align"]').value = layer.align || 'left';
  bindPropertyInputs();
}
function coerceValue(input) {
  if (input.type === 'number') return Number(input.value);
  return input.value;
}
function bindPropertyInputs() {
  document.querySelectorAll('[data-prop]').forEach(input => input.addEventListener('input', () => {
    const layer = selectedLayer();
    if (!layer) return;
    layer[input.dataset.prop] = coerceValue(input);
    dirty = true;
    renderCanvas();
    renderLayers();
  }));
  document.querySelectorAll('[data-canvas]').forEach(input => input.addEventListener('input', () => {
    project.canvas[input.dataset.canvas] = input.value;
    markDirty({ canvasOnly: true });
  }));
}
function addLayer(layer) {
  project.layers.push(layer);
  selectedId = layer.id;
  markDirty();
}
function moveSelected(delta) {
  const index = project.layers.findIndex(layer => layer.id === selectedId);
  if (index < 0) return;
  const next = Math.max(0, Math.min(project.layers.length - 1, index + delta));
  const [layer] = project.layers.splice(index, 1);
  project.layers.splice(next, 0, layer);
  markDirty();
}
async function apiJson(url, payload) {
  const response = await fetch(url, { method: payload === undefined ? 'GET' : 'POST', headers: payload === undefined ? {} : { 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload) });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { message: text }; }
  if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
  return data;
}
async function refreshProjects() {
  try {
    const data = await apiJson('/api/projects');
    el('projectSelect').innerHTML = '<option value="">选择项目</option>' + data.projects.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
  } catch (error) { setStatus(error.message); }
}
async function saveProject(name) {
  project.meta = { ...(project.meta || {}), name, updated_at: new Date().toISOString() };
  await apiJson(`/api/projects/${encodeURIComponent(name)}`, project);
  dirty = false;
  setStatus(`已保存项目：${name}`);
  await refreshProjects();
}
async function uploadFile(file) {
  const reader = new FileReader();
  const dataUrl = await new Promise((resolve, reject) => {
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  const result = await apiJson('/api/assets', { filename: file.name, mime: file.type, data_url: dataUrl });
  addLayer({ id: uid('image'), type: 'image', name: file.name, x: 160, y: 220, w: 520, h: 520, opacity: 1, src: result.url });
  setStatus(`已加载素材：${result.filename}`);
}
function bindEvents() {
  el('newBtn').onclick = () => {
    if (dirty && !confirm('当前项目还没保存，确定新建吗？')) return;
    project = clone(DEFAULT_PROJECT);
    selectedId = null;
    el('projectName').value = 'untitled';
    dirty = false;
    render();
  };
  el('openBtn').onclick = async () => {
    const name = el('projectSelect').value;
    if (!name) return;
    if (dirty && !confirm('当前项目还没保存，确定打开其他项目吗？')) return;
    project = await apiJson(`/api/projects/${encodeURIComponent(name)}`);
    selectedId = project.layers?.[project.layers.length - 1]?.id || null;
    el('projectName').value = name.replace(/\.json$/, '');
    dirty = false;
    render();
  };
  el('saveBtn').onclick = () => saveProject(el('projectName').value || 'untitled').catch(err => setStatus(err.message));
  el('saveAsBtn').onclick = () => {
    const name = prompt('另存为项目名', el('projectName').value || 'untitled');
    if (name) { el('projectName').value = name; saveProject(name).catch(err => setStatus(err.message)); }
  };
  el('exportBtn').onclick = async () => {
    try {
      const name = el('projectName').value || 'untitled';
      const dataUrl = canvas.toDataURL('image/png');
      const result = await apiJson(`/api/export/${encodeURIComponent(name)}`, { data_url: dataUrl });
      setStatus(`已导出：${result.path}`);
    } catch (error) { setStatus(error.message); }
  };
  el('addTextBtn').onclick = () => addLayer({ id: uid('text'), type: 'text', name: '文字', text: '双击右侧修改文字', x: 110, y: 140, w: 760, h: 80, fontSize: 56, fontWeight: 900, color: '#252326', align: 'left', lineHeight: 1.18, opacity: 1 });
  el('addRectBtn').onclick = () => addLayer({ id: uid('rect'), type: 'rect', name: '矩形卡片', x: 140, y: 260, w: 520, h: 220, fill: '#ffffff', stroke: '#eadfe2', radius: 32, shadow: true, opacity: 1 });
  el('addEllipseBtn').onclick = () => addLayer({ id: uid('ellipse'), type: 'ellipse', name: '圆形', x: 240, y: 300, w: 220, h: 220, fill: '#fff2f4', stroke: '#ff2442', opacity: 1 });
  el('uploadBtn').onclick = () => el('fileInput').click();
  el('fileInput').onchange = event => [...event.target.files].forEach(file => uploadFile(file).catch(err => setStatus(err.message)));
  el('bringForwardBtn').onclick = () => moveSelected(1);
  el('sendBackwardBtn').onclick = () => moveSelected(-1);
  el('bringTopBtn').onclick = () => { const i = project.layers.findIndex(l => l.id === selectedId); if (i >= 0) { project.layers.push(project.layers.splice(i, 1)[0]); markDirty(); } };
  el('sendBottomBtn').onclick = () => { const i = project.layers.findIndex(l => l.id === selectedId); if (i >= 0) { project.layers.unshift(project.layers.splice(i, 1)[0]); markDirty(); } };
  el('deleteBtn').onclick = () => { project.layers = project.layers.filter(l => l.id !== selectedId); selectedId = null; markDirty(); };
  el('lockBtn').onclick = () => { const layer = selectedLayer(); if (layer) { layer.locked = !layer.locked; markDirty(); } };
  canvas.addEventListener('mousedown', event => {
    const point = canvasPoint(event);
    const layer = hitTest(point);
    selectedId = layer?.id || null;
    if (layer) {
      drag = { mode: isResizeHandle(point, layer) ? 'resize' : 'move', start: point, x: layer.x, y: layer.y, w: layer.w, h: layer.h };
    }
    render();
  });
  window.addEventListener('mousemove', event => {
    if (!drag || !selectedId) return;
    const layer = selectedLayer();
    const point = canvasPoint(event);
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    if (drag.mode === 'resize') {
      layer.w = Math.max(24, drag.w + dx);
      layer.h = Math.max(24, drag.h + dy);
    } else {
      layer.x = drag.x + dx;
      layer.y = drag.y + dy;
    }
    dirty = true;
    renderCanvas();
  });
  window.addEventListener('mouseup', () => {
    if (drag) renderProperties();
    drag = null;
  });
  const dropZone = el('dropZone');
  dropZone.addEventListener('dragover', event => { event.preventDefault(); });
  dropZone.addEventListener('drop', event => {
    event.preventDefault();
    [...event.dataTransfer.files].filter(file => file.type.startsWith('image/')).forEach(file => uploadFile(file).catch(err => setStatus(err.message)));
  });
}
renderTemplates();
bindEvents();
refreshProjects();
render();
</script>
</body>
</html>
"""


def render_html() -> str:
    default_project = {
        "canvas": dict(DEFAULT_CANVAS),
        "layers": [],
        "meta": {"name": "untitled", "created_at": datetime.now().isoformat(timespec="seconds")},
    }
    return (
        HTML_TEMPLATE.replace("__TEMPLATES__", json.dumps(BUILTIN_TEMPLATES, ensure_ascii=False))
        .replace("__DEFAULT_PROJECT__", json.dumps(default_project, ensure_ascii=False))
    )


class CoverEditorHandler(BaseHTTPRequestHandler):
    server_version = "CoverEditor/1.0"

    @property
    def output_dir(self) -> Path:
        return self.server.output_dir  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[cover-editor] " + format % args + "\n")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise EditorError("JSON 格式错误") from exc
        if not isinstance(data, dict):
            raise EditorError("请求体必须是 JSON object")
        return data

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: dict[str, Any], status: int = 200) -> None:
        self.send_bytes(status, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"status": "error", "message": message}, status)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self.send_bytes(200, render_html().encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/projects":
                projects = sorted(item.name for item in (self.output_dir / "projects").glob("*.json"))
                self.send_json({"status": "ok", "projects": projects})
            elif path.startswith("/api/projects/"):
                name = safe_name(path.removeprefix("/api/projects/"))
                project_path = self.output_dir / "projects" / f"{Path(name).stem}.json"
                if not project_path.exists():
                    self.send_error_json(404, "项目不存在")
                else:
                    self.send_bytes(200, project_path.read_bytes(), "application/json; charset=utf-8")
            elif path.startswith("/assets/"):
                filename = safe_name(path.removeprefix("/assets/"))
                asset_path = self.output_dir / "assets" / filename
                if not asset_path.exists():
                    self.send_error_json(404, "素材不存在")
                else:
                    mime = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
                    self.send_bytes(200, asset_path.read_bytes(), mime)
            else:
                self.send_error_json(404, "路径不存在")
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self.send_error_json(500, str(exc))

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/projects/"):
                payload = self.read_json()
                name = safe_name(path.removeprefix("/api/projects/"))
                project_path = self.output_dir / "projects" / f"{Path(name).stem}.json"
                project_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                self.send_json({"status": "ok", "path": str(project_path)})
            elif path.startswith("/api/export/"):
                payload = self.read_json()
                name = safe_name(path.removeprefix("/api/export/"))
                mime, image_bytes = decode_data_url(str(payload.get("data_url") or ""), expected_prefix="image/png")
                if mime != "image/png":
                    raise EditorError("导出只支持 PNG")
                if not image_bytes.startswith(PNG_SIGNATURE):
                    raise EditorError("导出数据不是有效 PNG")
                export_path = self.output_dir / "exports" / f"{Path(name).stem}.png"
                export_path.write_bytes(image_bytes)
                self.send_json({"status": "ok", "path": str(export_path)})
            elif path == "/api/assets":
                payload = self.read_json()
                declared_mime = str(payload.get("mime") or "").lower()
                if declared_mime and not declared_mime.startswith("image/"):
                    raise EditorError("只支持图片素材（PNG/JPG/WebP/GIF）")
                data_mime, image_bytes = decode_data_url(str(payload.get("data_url") or ""), expected_prefix="image/")
                mime = data_mime
                if mime not in ALLOWED_IMAGE_MIMES:
                    raise EditorError("只支持图片素材（PNG/JPG/WebP/GIF）")
                filename = safe_asset_name(str(payload.get("filename") or f"asset{extension_for_mime(mime)}"), "asset")
                stem = Path(filename).stem or "asset"
                suffix = extension_for_mime(mime)
                final_name = safe_name(f"{stem}-{int(time.time() * 1000)}{suffix}", "asset.png")
                asset_path = self.output_dir / "assets" / final_name
                asset_path.write_bytes(image_bytes)
                self.send_json({"status": "ok", "filename": final_name, "url": f"/assets/{urllib.parse.quote(final_name)}"})
            else:
                self.send_error_json(404, "路径不存在")
        except EditorError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self.send_error_json(500, str(exc))


def create_server(host: str, port: int, output_dir: Path) -> ThreadingHTTPServer:
    output_dir = output_dir.expanduser().resolve()
    ensure_dirs(output_dir)
    server = ThreadingHTTPServer((host, port), CoverEditorHandler)
    server.output_dir = output_dir  # type: ignore[attr-defined]
    return server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="打开本地小红书封面编辑器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录，默认 outputs/cover_editor")
    parser.add_argument("--no-open", action="store_true", help="只启动服务，不自动打开浏览器")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    server = create_server(args.host, args.port, Path(args.output_dir))
    url = f"http://{server.server_address[0]}:{server.server_address[1]}/"
    print(json.dumps({"status": "ok", "url": url, "output_dir": str(server.output_dir)}, ensure_ascii=False, indent=2))
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止封面编辑器")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
