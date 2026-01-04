"""用于从磁盘加载 Markdown 模板的工具函数。"""

import os
from functools import lru_cache

import yaml
from flask import current_app

from .config import (
    DEFAULT_MARKDOWN_TEMPLATE_FILENAME,
    FALLBACK_MARKDOWN_TEMPLATE,
    template_library_root,
)


def _template_root() -> str:
    """返回模板资源所在的目录，优先读取应用配置。"""

    try:
        return current_app.config["TEMPLATE_LIBRARY"]  # type: ignore[index]
    except (KeyError, RuntimeError):
        return template_library_root()


def _template_path(name: str = DEFAULT_MARKDOWN_TEMPLATE_FILENAME) -> str:
    """拼接模板文件完整路径。"""

    return os.path.join(_template_root(), name)


def _safe_strip(value: str | None) -> str:
    return (value or "").replace("\r\n", "\n").strip()


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


def refresh_template_cache() -> None:
    """清空 LRU 缓存，编辑模板文件后调用即可强制重新加载。"""

    load_markdown_template.cache_clear()  # type: ignore[attr-defined]


def list_templates() -> dict[str, list[dict[str, str]]]:
    """列出可用 Markdown 模板文件。"""

    root = template_library_root()
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

            if isinstance(raw, dict) and ("css" in raw or "wrapperClass" in raw or "customHead" in raw):
                data = load_markdown_template(fname)
                data.update({
                    "name": fname,
                    "type": "markdown",
                })
                markdown_templates.append(data)

    return {"markdown": markdown_templates}


__all__ = [
    "get_default_markdown_template",
    "load_markdown_template",
    "refresh_template_cache",
    "list_templates",
]
