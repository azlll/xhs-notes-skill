#!/usr/bin/env python3
"""调用 OpenAI-compatible Images API 生成图片。"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "image_model.json"
EXAMPLE_CONFIG = ROOT / "config" / "image_model.example.json"

ENV_MAP = {
    "provider": "XHS_IMAGE_PROVIDER",
    "base_url": "XHS_IMAGE_BASE_URL",
    "api_key": "XHS_IMAGE_API_KEY",
    "model": "XHS_IMAGE_MODEL",
    "size": "XHS_IMAGE_SIZE",
    "quality": "XHS_IMAGE_QUALITY",
    "timeout_seconds": "XHS_IMAGE_TIMEOUT_SECONDS",
    "response_format": "XHS_IMAGE_RESPONSE_FORMAT",
    "output_dir": "XHS_IMAGE_OUTPUT_DIR",
}


class ConfigError(Exception):
    """配置错误。"""


def emit(data: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON 格式错误：{path}: {exc}") from exc


def load_config(path: Path) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if path.exists():
        raw = load_json(path)
        if not isinstance(raw, dict):
            raise ConfigError("配置文件顶层必须是 JSON object")
        config.update(raw)
    elif EXAMPLE_CONFIG.exists():
        config["_missing_config"] = str(path)

    for key, env_name in ENV_MAP.items():
        value = os.environ.get(env_name)
        if value:
            config[key] = value

    if "timeout_seconds" in config:
        try:
            config["timeout_seconds"] = int(config["timeout_seconds"])
        except (TypeError, ValueError) as exc:
            raise ConfigError("timeout_seconds 必须是整数") from exc

    return config


def validate_config(config: dict[str, Any], *, dry_run: bool) -> None:
    missing = []
    for key in ("base_url", "model"):
        if not config.get(key):
            missing.append(key)
    if not dry_run and not config.get("api_key"):
        missing.append("api_key")
    if missing:
        target = config.get("_missing_config", str(DEFAULT_CONFIG))
        raise ConfigError(
            "缺少生图配置字段："
            + ", ".join(missing)
            + f"。请复制 {EXAMPLE_CONFIG.relative_to(ROOT)} 到 {Path(target).relative_to(ROOT) if Path(target).is_absolute() and ROOT in Path(target).parents else target} 并填写，或设置对应环境变量。"
        )


def normalize_endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/images/generations"):
        return value
    if value.endswith("/v1"):
        return f"{value}/images/generations"
    return f"{value}/v1/images/generations"


def load_prompts(path: Path) -> list[dict[str, Any]]:
    raw = load_json(path)
    if isinstance(raw, dict):
        raw_prompts = raw.get("prompts")
    else:
        raw_prompts = raw

    if not isinstance(raw_prompts, list) or not raw_prompts:
        raise ConfigError("prompts 文件必须包含非空数组，或包含 prompts 数组字段")

    prompts: list[dict[str, Any]] = []
    for index, item in enumerate(raw_prompts, start=1):
        if isinstance(item, str):
            prompt = item.strip()
            prompt_id = f"image-{index:02d}"
            prompt_item: dict[str, Any] = {"id": prompt_id, "prompt": prompt}
        elif isinstance(item, dict):
            prompt = str(item.get("prompt", "")).strip()
            prompt_id = str(item.get("id") or f"image-{index:02d}")
            prompt_item = dict(item)
            prompt_item["id"] = sanitize_id(prompt_id)
            prompt_item["prompt"] = prompt
        else:
            raise ConfigError(f"第 {index} 个 prompt 必须是字符串或 object")
        if not prompt:
            raise ConfigError(f"第 {index} 个 prompt 为空")
        prompts.append(prompt_item)
    return prompts


def sanitize_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned or "image"


def build_request_body(config: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": item.get("model") or config.get("model"),
        "prompt": item["prompt"],
        "n": int(item.get("n") or config.get("n") or 1),
        "size": item.get("size") or config.get("size") or "1024x1024",
    }

    quality = item.get("quality") or config.get("quality")
    if quality and quality != "default":
        body["quality"] = quality

    response_format = item.get("response_format") or config.get("response_format")
    if response_format:
        body["response_format"] = response_format

    style = item.get("style") or config.get("style")
    if style:
        body["style"] = style

    extra_body = config.get("extra_body")
    if isinstance(extra_body, dict):
        body.update(extra_body)
    item_extra_body = item.get("extra_body")
    if isinstance(item_extra_body, dict):
        body.update(item_extra_body)

    return body


def post_json(endpoint: str, api_key: str, body: dict[str, Any], timeout: int) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ConfigError(f"API 返回 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ConfigError(f"API 请求失败：{exc.reason}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError("API 返回内容不是合法 JSON") from exc
    if not isinstance(raw, dict):
        raise ConfigError("API 返回顶层不是 JSON object")
    return raw


def save_image_data(output_dir: Path, prompt_id: str, data: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    urls: list[str] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        if item.get("url"):
            urls.append(str(item["url"]))
        b64_value = item.get("b64_json") or item.get("image")
        if b64_value:
            try:
                image_bytes = base64.b64decode(str(b64_value))
            except Exception as exc:  # noqa: BLE001
                raise ConfigError(f"{prompt_id} 第 {index} 张图片 base64 解码失败") from exc
            filename = f"{sanitize_id(prompt_id)}-{index:02d}.png"
            target = output_dir / filename
            target.write_bytes(image_bytes)
            files.append(str(target.relative_to(ROOT)))
    return files, urls


def main() -> None:
    parser = argparse.ArgumentParser(description="生成小红书图文笔记图片")
    parser.add_argument("--prompts", required=True, help="prompts JSON 文件路径")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--output-dir", help="输出目录，默认读取配置或 outputs/images")
    parser.add_argument("--dry-run", action="store_true", help="只输出请求体，不发起网络请求")
    args = parser.parse_args()

    try:
        config = load_config(Path(args.config))
        prompts = load_prompts(Path(args.prompts))
        validate_config(config, dry_run=args.dry_run)
        endpoint = normalize_endpoint(str(config["base_url"]))
        timeout = int(config.get("timeout_seconds") or 120)
        output_dir = Path(args.output_dir or config.get("output_dir") or ROOT / "outputs" / "images")
        if not output_dir.is_absolute():
            output_dir = ROOT / output_dir

        request_bodies = [build_request_body(config, item) for item in prompts]
        if args.dry_run:
            emit(
                {
                    "status": "ok",
                    "mode": "dry-run",
                    "provider": config.get("provider", "openai-compatible"),
                    "endpoint": endpoint,
                    "requests": request_bodies,
                }
            )

        results = []
        for item, body in zip(prompts, request_bodies):
            raw = post_json(endpoint, str(config["api_key"]), body, timeout)
            data = raw.get("data")
            if not isinstance(data, list):
                raise ConfigError("API 返回缺少 data 数组")
            files, urls = save_image_data(output_dir, str(item["id"]), data)
            results.append(
                {
                    "id": item["id"],
                    "prompt": item["prompt"],
                    "saved_files": files,
                    "urls": urls,
                }
            )

        emit(
            {
                "status": "ok",
                "provider": config.get("provider", "openai-compatible"),
                "model": config.get("model"),
                "count": len(results),
                "output_dir": str(output_dir.relative_to(ROOT)),
                "results": results,
            }
        )
    except ConfigError as exc:
        emit(
            {
                "status": "error",
                "message": str(exc),
                "hint": "检查 config/image_model.json、环境变量和 prompts JSON。不要在对话或日志中暴露完整 API Key。",
            },
            exit_code=1,
        )


if __name__ == "__main__":
    main()

