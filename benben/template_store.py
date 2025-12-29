"""用于从磁盘加载公用 LaTeX / Markdown 模板的工具函数。"""

import os
import re
from functools import lru_cache

import yaml
from flask import current_app

from .config import (
    DEFAULT_MARKDOWN_TEMPLATE_FILENAME,
    DEFAULT_TEMPLATE_FILENAME,
    FALLBACK_MARKDOWN_TEMPLATE,
    FALLBACK_TEMPLATE,
    template_library_root,
)


def _template_root() -> str:
    """返回模板资源所在的目录，优先读取应用配置。"""

    try:
        # Flask 配置在应用上下文存在时优先被使用
        return current_app.config["TEMPLATE_LIBRARY"]  # type: ignore[index]
    except (KeyError, RuntimeError):
        # 若无应用上下文则退回包内 temps 目录
        return template_library_root()


def _template_path(name: str = DEFAULT_TEMPLATE_FILENAME) -> str:
    """拼接模板文件完整路径。"""

    return os.path.join(_template_root(), name)


def _safe_strip(value: str | None) -> str:
    return (value or "").replace("\r\n", "\n").strip()


_COMPILE_DIRECTIVE_RE = re.compile(r"^compile\s*:\s*(.+)$", re.IGNORECASE)


def _split_compile_steps(raw: str) -> list[str]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return []
    if ";" in cleaned:
        parts = [part.strip() for part in cleaned.split(";")]
    elif "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",")]
    else:
        parts = cleaned.split()
    return [part.lower() for part in parts if part]


def _normalize_compile_steps(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        steps: list[str] = []
        for item in value:
            steps.extend(_normalize_compile_steps(item))
        return steps
    if isinstance(value, str):
        return _split_compile_steps(value)
    cleaned = str(value).strip()
    return _split_compile_steps(cleaned)


def _extract_compile_steps(raw_text: str) -> list[str]:
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("#"):
            break
        comment = stripped.lstrip("#").strip()
        if not comment:
            continue
        match = _COMPILE_DIRECTIVE_RE.match(comment)
        if match:
            return _split_compile_steps(match.group(1))
    return []


@lru_cache(maxsize=8)
def load_template(name: str = DEFAULT_TEMPLATE_FILENAME) -> dict[str, str]:
    """从 YAML 载入模板结构；缺失时回退到默认值。

    使用 ``@lru_cache`` 可以缓存最近读取的模板，避免频繁 I/O。
    ``maxsize=8`` 表示最多缓存 8 个模板文件，命中后直接返回内存数据。
    """

    path = _template_path(name)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                raw_text = handle.read()
                data = yaml.safe_load(raw_text) or {}
                compile_steps = _extract_compile_steps(raw_text)
                if not compile_steps and isinstance(data, dict):
                    compile_steps = _normalize_compile_steps(data.get("compile"))
                payload = {
                    "header": _safe_strip(str(data.get("header") or FALLBACK_TEMPLATE["header"])),
                    "beforePages": _safe_strip(str(data.get("beforePages") or FALLBACK_TEMPLATE["beforePages"]))
                    or FALLBACK_TEMPLATE["beforePages"],
                    "footer": _safe_strip(str(data.get("footer") or FALLBACK_TEMPLATE["footer"]))
                    or FALLBACK_TEMPLATE["footer"],
                }
                if compile_steps:
                    payload["compile"] = compile_steps
                return payload
    except Exception as exc:  # pragma: no cover - defensive fallback
        # 出现读取异常时打印提示并退回默认模板
        print(f"加载模板失败 {path}: {exc}")
    return dict(FALLBACK_TEMPLATE)


def get_default_template() -> dict[str, str]:
    """返回默认模板结构，供创建新项目时引用。"""

    return load_template(DEFAULT_TEMPLATE_FILENAME)


@lru_cache(maxsize=8)
def load_markdown_template(name: str = DEFAULT_MARKDOWN_TEMPLATE_FILENAME) -> dict[str, str]:
    """从 YAML 载入 Markdown 样式配置，缺失时使用兜底样式。"""

    path = _template_path(name)
    fallback_css = FALLBACK_MARKDOWN_TEMPLATE.get("css", "")
    fallback_wrapper = FALLBACK_MARKDOWN_TEMPLATE.get("wrapperClass", "")
    fallback_head = FALLBACK_MARKDOWN_TEMPLATE.get("customHead", "")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
                if isinstance(data, dict):
                    css = _safe_strip(str(data.get("css") or fallback_css)) or fallback_css
                    wrapper = str(data.get("wrapperClass") or fallback_wrapper).strip()
                    custom_head = _safe_strip(str(data.get("customHead") or fallback_head))
                    return {
                        "css": css,
                        "wrapperClass": wrapper,
                        "customHead": custom_head,
                    }
    except Exception as exc:  # pragma: no cover - defensive log
        print(f"加载模板失败 {path}: {exc}")
    return {
        "css": fallback_css,
        "wrapperClass": fallback_wrapper,
        "customHead": fallback_head,
    }


def get_default_markdown_template() -> dict[str, str]:
    """返回默认 Markdown 样式配置。"""

    return load_markdown_template(DEFAULT_MARKDOWN_TEMPLATE_FILENAME)


def get_default_header() -> str:
    """获取默认模板中的 header 段落。"""

    return get_default_template()["header"]


def refresh_template_cache() -> None:
    """清空 LRU 缓存，编辑模板文件后调用即可强制重新加载。"""

    load_template.cache_clear()  # type: ignore[attr-defined]


def list_templates() -> dict[str, list[dict[str, str]]]:
    """列出可用模板文件，按类型区分。"""

    root = template_library_root()
    latex_templates: list[dict[str, str]] = []
    markdown_templates: list[dict[str, str]] = []
    if os.path.isdir(root):
        for fname in sorted(os.listdir(root)):
            if not fname.lower().endswith((".yaml", ".yml")):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    raw = yaml.safe_load(handle) or {}
            except Exception as exc:  # pragma: no cover - log and skip
                print(f"读取模板失败 {path}: {exc}")
                continue

            if isinstance(raw, dict):
                template_type = str(raw.get("type") or "").strip().lower()
            else:
                template_type = ""

            if not template_type:
                if isinstance(raw, dict) and ("css" in raw or "wrapperClass" in raw):
                    template_type = "markdown"
                else:
                    template_type = "latex"

            if template_type == "markdown":
                data = load_markdown_template(fname)
                data.update({
                    "name": fname,
                    "type": "markdown",
                })
                markdown_templates.append(data)
            else:
                data = load_template(fname)
                entry = {
                    "name": fname,
                    "type": "latex",
                    "header": data.get("header", ""),
                    "beforePages": data.get("beforePages", ""),
                    "footer": data.get("footer", ""),
                }
                if "compile" in data:
                    entry["compile"] = data.get("compile")
                latex_templates.append(entry)

    return {
        "latex": latex_templates,
        "markdown": markdown_templates,
    }


__all__ = [
    "get_default_template",
    "get_default_markdown_template",
    "get_default_header",
    "load_template",
    "load_markdown_template",
    "refresh_template_cache",
    "list_templates",
]
