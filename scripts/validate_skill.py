#!/usr/bin/env python3
"""校验 xhs-notes-skill 项目结构。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "LICENSE",
    ".gitignore",
    "config/image_model.example.json",
    "scripts/generate_images.py",
    "scripts/generate_review_report.py",
    "scripts/validate_skill.py",
    "references/title_formulas.md",
    "references/content_templates.md",
    "references/tags_strategy.md",
    "references/hooks_library.md",
    "references/trend_keywords.md",
    "references/meme_sentence_patterns.md",
    "references/trend_update_rules.md",
    "references/dynamic_clarification.md",
    "references/topic_selection.md",
    "references/live_formula_refresh.md",
    "references/image_understanding_prompt.md",
    "references/fallback_outputs.md",
    "references/post_publish_review.md",
    "references/risk_checklist.md",
    "references/prompts/composition.md",
    "references/prompts/style_presets.md",
    "references/prompts/color_palettes.md",
    "examples/case_food_tutorial.md",
    "examples/case_fashion_match.md",
    "examples/case_home_good.md",
    "examples/case_knowledge_card.md",
    "tests/test_skill_project.py",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        fail("SKILL.md 缺少 YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        fail("SKILL.md frontmatter 未正确闭合")
    raw = text[4:end]
    body = text[end + 5 :]
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            fail(f"frontmatter 行格式错误：{line}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data, body


def check_frontmatter() -> str:
    skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    data, body = parse_frontmatter(skill_text)
    name = data.get("name", "")
    description = data.get("description", "")
    if name != ROOT.name:
        fail(f"name 必须等于父目录名：{ROOT.name}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        fail("name 只能包含小写字母、数字和单个短横线")
    if len(name) > 64:
        fail("name 超过 64 字符")
    if not description:
        fail("description 不能为空")
    if len(description) > 1024:
        fail("description 超过 1024 字符")
    if not body.strip():
        fail("SKILL.md 正文不能为空")
    return body


def check_required_files() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        fail("缺少文件：" + ", ".join(missing))


def check_skill_links(body: str) -> None:
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", body)
    missing: list[str] = []
    for link in links:
        if re.match(r"^[a-z]+://", link) or link.startswith("#"):
            continue
        clean = link.split("#", 1)[0]
        if clean and not (ROOT / clean).exists():
            missing.append(clean)
    if missing:
        fail("SKILL.md 引用路径不存在：" + ", ".join(sorted(set(missing))))


def check_config_template() -> None:
    path = ROOT / "config" / "image_model.example.json"
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    required = ["provider", "base_url", "api_key", "model", "size", "quality", "timeout_seconds"]
    missing = [key for key in required if key not in data]
    if missing:
        fail("配置模板缺少字段：" + ", ".join(missing))


def check_gitignore() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for needle in ("config/image_model.json", "outputs/"):
        if needle not in text:
            fail(f".gitignore 缺少 {needle}")


def main() -> None:
    check_required_files()
    body = check_frontmatter()
    check_skill_links(body)
    check_config_template()
    check_gitignore()
    print("OK: xhs-notes-skill 项目校验通过")


if __name__ == "__main__":
    main()
