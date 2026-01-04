"""封装 Flask 路由的蓝图，提供前端交互所需的全部接口。"""

import base64
import copy
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import parse_qsl, urlparse, unquote

import requests
import yaml
from flask import Blueprint, after_this_request, current_app, jsonify, render_template, request, send_file, url_for
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from contextlib import contextmanager
from werkzeug.utils import secure_filename

from .oss_client import (
    delete_file as oss_delete_file,
    upload_bytes as oss_upload_bytes,
    is_configured as oss_is_configured,
    get_settings as oss_get_settings,
    build_public_url as oss_build_public_url,
)
from .config import (
    AI_BIB_PROMPT,
    AI_PROMPTS,
    COMPONENT_LIBRARY,
    DEFAULT_EMBEDDING_MODEL,
    LEARNING_ASSISTANT_DEFAULT_PROMPTS,
    UI_THEME,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_RESPONSE_FORMAT,
    OPENAI_TTS_SPEED,
    OPENAI_TTS_VOICE,
)
from .template_store import get_default_markdown_template, list_templates
from .responses import api_error, api_success
from .llm import (
    build_chat_headers,
    get_default_llm_state,
    list_llm_providers,
    resolve_llm_config,
)
from .package import AssetRecord, BenbenPackage, WorkspaceVersionConflict
from .workspace import (
    WorkspaceHandle,
    WorkspaceLockedError,
    WorkspaceNotFoundError,
    clear_workspace_password,
    close_workspace,
    create_local_workspace,
    create_remote_workspace,
    discover_local_workspaces,
    get_workspace,
    get_workspace_package,
    WorkspaceArchiveNotFoundError,
    list_remote_workspaces,
    list_workspace_archives,
    create_workspace_archive,
    delete_workspace_archive,
    restore_workspace_archive,
    workspace_archive_dir,
    list_workspaces,
    open_local_workspace,
    open_remote_workspace,
    portable_workspace_context,
    set_workspace_password,
    sync_remote_workspace,
    unlock_workspace,
    record_workspace_save,
    run_local_maintenance,
)
from .rag import RagUnavailableError, ensure_markdown_index, search_markdown

bp = Blueprint("benben", __name__)

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent


_DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", flags=re.IGNORECASE)

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_HTML_SRC_RE = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
_HTML_HREF_RE = re.compile(r'\bhref=["\']([^"\']+)["\']', re.IGNORECASE)
_INTERNAL_LINK_SCHEMES_RE = re.compile(r"^(?:https?:|mailto:|tel:|ftp:|file:|data:|//)", re.IGNORECASE)

_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp', '.heic', '.heif'}

_RAG_CHUNK_SIZE = 900
_RAG_CHUNK_OVERLAP = 180
_RAG_TOP_K = 5

_ASSISTANT_SYSTEM_PROMPT = (
    "You are a concise, detail-oriented private assistant for my Benben workspace. "
    "Prefer answers grounded in the provided Markdown snippets. "
    "If context is missing or insufficient, be explicit that you are replying without RAG and avoid fabricating workspace details."
)


def _build_markdown_callout_renderer(name: str):
    """Return a renderer that wraps :::callouts with semantic containers."""

    def _render(tokens, idx, _options, _env):
        if tokens[idx].nesting == 1:
            info = tokens[idx].info.strip()
            title_text = info[len(name):].strip()
            parts = [f'<div class="markdown-callout {name}">']
            if title_text:
                parts.append(f'<div class="markdown-callout-title">{escapeHtml(title_text)}</div>')
            parts.append('<div class="markdown-callout-body">')
            return "".join(parts)
        return "</div></div>\n"

    return _render


def _build_markdown_inline_span_rule(marker: str, token_type: str):
    marker_len = len(marker)

    def _rule(state, silent):
        pos = state.pos
        if state.src[pos : pos + marker_len] != marker:
            return False
        start = pos + marker_len
        if start >= state.posMax:
            return False
        end = state.src.find(marker, start)
        if end == -1:
            return False
        content = state.src[start:end]
        if not content or not content.strip():
            return False
        if "\n" in content or "\r" in content:
            return False
        if not silent:
            token = state.push(token_type, "", 0)
            token.markup = marker
            token.content = content
            token.children = []
            state.md.inline.parse(content, state.md, state.env, token.children)
        state.pos = end + marker_len
        return True

    return _rule


def _render_markdown_inline(tag: str, attrs: str):
    def _render(self, tokens, idx, options, env):
        token = tokens[idx]
        children = token.children or []
        inner = self.renderInline(children, options, env) if children else escapeHtml(token.content or "")
        return f"<{tag}{attrs}>{inner}</{tag}>"

    return _render


def _register_markdown_inline_extras(md: MarkdownIt) -> None:
    md.inline.ruler.before(
        "emphasis",
        "markdown_highlight",
        _build_markdown_inline_span_rule("==", "markdown_highlight"),
    )
    md.inline.ruler.before(
        "emphasis",
        "markdown_blur",
        _build_markdown_inline_span_rule("??", "markdown_blur"),
    )
    md.renderer.rules["markdown_highlight"] = _render_markdown_inline(
        "mark",
        ' class="markdown-highlight"',
    )
    md.renderer.rules["markdown_blur"] = _render_markdown_inline(
        "span",
        ' class="markdown-blur" tabindex="0"',
    )


_MARKDOWN_RENDERER = (
    MarkdownIt("commonmark", {"html": True, "linkify": True, "typographer": True})
    .enable("table")
    .enable("strikethrough")
    .use(tasklists_plugin, enabled=True, label=True)
    .use(footnote_plugin)
    .use(_register_markdown_inline_extras)
)
for _callout_name in ("info", "tip", "warning"):
    _MARKDOWN_RENDERER.use(
        container_plugin,
        _callout_name,
        render=_build_markdown_callout_renderer(_callout_name),
    )


def _parse_qa_info(info: str) -> tuple[str, bool]:
    """Extract question text and collapsed flag from :::qa info."""

    raw = (info or "").strip()
    if raw.lower().startswith("qa"):
        raw = raw[2:].strip()
    collapsed = bool(re.search(r"\b(collapse|fold|hide)\b", raw, re.IGNORECASE))
    question_part = raw
    if "|" in raw:
        question_part, _, _options = raw.partition("|")
    elif collapsed:
        question_part = re.sub(r"\b(collapse|fold|hide)\b", "", raw, flags=re.IGNORECASE)
    question = question_part.strip()
    return question, collapsed


def _build_markdown_qa_renderer():
    """Render :::qa Question | collapse blocks into Q/A cards."""

    def _render(tokens, idx, _options, _env):
        info = tokens[idx].info if hasattr(tokens[idx], "info") else ""
        question, collapsed = _parse_qa_info(info)
        question_html = escapeHtml(question or "问题")
        if tokens[idx].nesting == 1:
            if collapsed:
                return (
                    '<details class="markdown-qa collapsed">'
                    '<summary><span class="markdown-qa-label">Q</span>'
                    f'<span class="markdown-qa-question">{question_html}</span>'
                    '<span class="markdown-qa-toggle">查看答案</span></summary>'
                    '<div class="markdown-qa-answer">'
                )
            return (
                '<div class="markdown-qa">'
                '<div class="markdown-qa-question">'
                f'<span class="markdown-qa-label">Q</span><span class="markdown-qa-question-text">{question_html}</span>'
                "</div>"
                '<div class="markdown-qa-answer">'
            )
        return "</div></details>\n" if collapsed else "</div></div>\n"

    return _render


# 渲染图片网格的容器渲染器：用于处理 :::img-2 / :::img-2v / :::img-4
def _build_image_grid_renderer(layout: str):
    """Return a renderer that wraps a container into an image grid wrapper.

    layout: one of 'two-col', 'two-vertical', 'four-grid'
    Usage in Markdown:
      :::img-2
      ![](a)
      ![](b)
      :::

      :::img-2v
      ![](a)
      ![](b)
      :::

      :::img-4
      ![](a)
      ![](b)
      ![](c)
      ![](d)
      :::
    """

    def _render(tokens, idx, _options, _env):
        if tokens[idx].nesting == 1:
            return f'<div class="markdown-img-grid {layout}">'
        return "</div>\n"

    return _render


def _build_media_renderer(kind: str):
    """Render :::audio / :::video blocks into semantic figure + media tag."""

    def _render(tokens, idx, _options, _env):
        if tokens[idx].nesting == 1:
            info = tokens[idx].info.strip()
            src = info[len(kind) :].strip()
            tag = "video" if kind == "video" else "audio"
            attrs = ' controls preload="metadata"'
            if tag == "video":
                attrs += ' playsinline'
            media_tag = (
                f'<{tag} src="{escapeHtml(src)}"{attrs}></{tag}>'
                if src
                else f"<{tag}{attrs}></{tag}>"
            )
            return f'<figure class="markdown-media {kind}">{media_tag}<div class="markdown-media-caption">'
        return "</div></figure>\n"

    return _render


# 注册三个图片网格容器
_MARKDOWN_RENDERER.use(container_plugin, "img-2", render=_build_image_grid_renderer("two-col"))
_MARKDOWN_RENDERER.use(container_plugin, "img-2v", render=_build_image_grid_renderer("two-vertical"))
_MARKDOWN_RENDERER.use(container_plugin, "img-4", render=_build_image_grid_renderer("four-grid"))
_MARKDOWN_RENDERER.use(container_plugin, "img-scroll", render=_build_image_grid_renderer("rail"))
_MARKDOWN_RENDERER.use(container_plugin, "qa", render=_build_markdown_qa_renderer())

# 媒体容器：提供 ::audio / :::video 语法
_MARKDOWN_RENDERER.use(container_plugin, "audio", render=_build_media_renderer("audio"))
_MARKDOWN_RENDERER.use(container_plugin, "video", render=_build_media_renderer("video"))

# 通用展示块容器渲染器（自建语法）
def _build_simple_block_renderer(css_class: str):
    def _render(tokens, idx, _options, _env):
        if tokens[idx].nesting == 1:
            return f'<div class="{css_class}">'
        return "</div>\n"

    return _render

# 注册若干展示相关自建容器（仅包裹内容，样式由 CSS 控制）
_MARKDOWN_RENDERER.use(container_plugin, "kpi", render=_build_simple_block_renderer("markdown-kpi"))
_MARKDOWN_RENDERER.use(container_plugin, "cols", render=_build_simple_block_renderer("markdown-cols"))
_MARKDOWN_RENDERER.use(container_plugin, "features", render=_build_simple_block_renderer("markdown-features"))
_MARKDOWN_RENDERER.use(container_plugin, "cover", render=_build_simple_block_renderer("markdown-cover"))
_MARKDOWN_RENDERER.use(container_plugin, "divider", render=_build_simple_block_renderer("markdown-divider"))
_MARKDOWN_RENDERER.use(container_plugin, "banner", render=_build_simple_block_renderer("markdown-banner"))
_MARKDOWN_RENDERER.use(container_plugin, "notes", render=_build_simple_block_renderer("markdown-notes"))
_MARKDOWN_RENDERER.use(container_plugin, "code-split", render=_build_simple_block_renderer("markdown-code-split"))
def _resolve_cache_env_seconds(env_name: str, default: int, minimum: int) -> int:
    """Parse an environment override for cache timing, clamping to sane bounds."""

    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _env_flag_enabled(name: str) -> bool:
    """Return True when the named environment flag is set to a truthy value."""

    raw_value = os.environ.get(name, "")
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


_WORKSPACE_CACHE_ROOT = Path(tempfile.gettempdir()) / "benben_workspace_cache"
_WORKSPACE_CACHE_TTL_SECONDS = _resolve_cache_env_seconds("BENBEN_CACHE_TTL_SECONDS", 3 * 24 * 3600, 3600)
_WORKSPACE_CACHE_SWEEP_INTERVAL_SECONDS = _resolve_cache_env_seconds("BENBEN_CACHE_SWEEP_INTERVAL", 3600, 300)
_WORKSPACE_CACHE_CLEANER_LOCK = threading.Lock()
_WORKSPACE_CACHE_CLEANER_STARTED = False
_WORKSPACE_CACHE_CLEANUP_DISABLED = _env_flag_enabled("BENBEN_DISABLE_WORKSPACE_CACHE_CLEANUP")


def _remove_stale_cache_entry(path: Path, cutoff_ts: float) -> None:
    """Best-effort removal of expired cache files/directories."""

    try:
        if path.is_dir():
            try:
                children = list(path.iterdir())
            except OSError:
                children = []
            for child in children:
                _remove_stale_cache_entry(child, cutoff_ts)
            try:
                next(path.iterdir())
                has_children = True
            except StopIteration:
                has_children = False
            except OSError:
                has_children = False
            if not has_children:
                try:
                    path.rmdir()
                except OSError:
                    pass
                return
            try:
                mtime = path.stat().st_mtime
            except OSError:
                return
            if mtime < cutoff_ts:
                shutil.rmtree(path, ignore_errors=True)
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime < cutoff_ts:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def _sweep_workspace_cache_once() -> None:
    """Remove leftover cache artifacts older than the configured TTL."""

    if not _WORKSPACE_CACHE_ROOT.exists():
        return
    cutoff_ts = time.time() - _WORKSPACE_CACHE_TTL_SECONDS
    if cutoff_ts <= 0:
        return
    try:
        entries = list(_WORKSPACE_CACHE_ROOT.iterdir())
    except OSError:
        return
    for entry in entries:
        _remove_stale_cache_entry(entry, cutoff_ts)


def _workspace_cache_cleaner_loop() -> None:
    """Background worker that periodically sweeps the workspace cache."""

    while True:
        try:
            _sweep_workspace_cache_once()
        except Exception as exc:
            print(f"[benben] workspace cache cleanup error: {exc}")
        time.sleep(_WORKSPACE_CACHE_SWEEP_INTERVAL_SECONDS)


def _start_workspace_cache_cleaner() -> None:
    """Launch the cache cleaner thread once per process."""

    global _WORKSPACE_CACHE_CLEANER_STARTED
    if _WORKSPACE_CACHE_CLEANUP_DISABLED:
        return

    with _WORKSPACE_CACHE_CLEANER_LOCK:
        if _WORKSPACE_CACHE_CLEANER_STARTED:
            return

        thread = threading.Thread(
            target=_workspace_cache_cleaner_loop,
            name="workspace-cache-cleaner",
            daemon=True,
        )
        thread.start()
        _WORKSPACE_CACHE_CLEANER_STARTED = True


_start_workspace_cache_cleaner()


def _workspace_id_from_request() -> Optional[str]:
    workspace_id = request.args.get("workspace")
    if workspace_id:
        return workspace_id
    try:
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            workspace_id = payload.get("workspace")
            if workspace_id:
                return workspace_id
    except Exception:
        pass
    try:
        form_workspace = request.form.get("workspace")
        if form_workspace:
            return form_workspace
    except Exception:
        pass
    return None


def _load_workspace_handle() -> Optional[dict]:
    workspace_id = _workspace_id_from_request()
    if not workspace_id:
        return None
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return None
    return handle.to_dict()


def _require_workspace_package() -> BenbenPackage | None:
    workspace_id = _workspace_id_from_request()
    if not workspace_id:
        return None
    try:
        return get_workspace_package(workspace_id)
    except WorkspaceNotFoundError:
        return None


def _resolve_workspace_context() -> tuple[Optional[str], Optional[BenbenPackage], bool]:
    workspace_id = _workspace_id_from_request()
    if not workspace_id:
        return None, None, False
    try:
        package = get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return workspace_id, None, True
    except WorkspaceNotFoundError:
        return workspace_id, None, False
    return workspace_id, package, False


def _require_workspace_package_response() -> tuple[Optional[str], Optional[BenbenPackage], Optional[Any]]:
    """Ensure the current request is bound to a workspace."""

    workspace_id, package, locked = _resolve_workspace_context()
    if not workspace_id:
        return None, None, api_error("请先选择工作区", 400)
    if locked:
        return workspace_id, None, _workspace_locked_response()
    if package is None:
        return None, None, api_error("workspace 未找到", 404)
    return workspace_id, package, None


def _workspace_locked_response(message: Optional[str] = None):
    payload = {
        "success": False,
        "error": message or "workspace 已加密，请先解锁",
        "locked": True,
    }
    return jsonify(payload), 423


def _require_workspace_project_response() -> tuple[Optional[str], Optional[BenbenPackage], Optional[dict], Optional[Any]]:
    """Ensure the current request has a workspace and return its exported project."""

    workspace_id, package, error = _require_workspace_package_response()
    if error:
        return None, None, None, error
    project = package.export_project()
    if not isinstance(project, dict):
        project = {}
    return workspace_id, package, project, None


def _workspace_asset_url(workspace_id: str, asset: AssetRecord, filename: Optional[str] = None) -> str:
    download_name = filename or asset.name or f"{asset.asset_id}.bin"
    safe_name = secure_filename(download_name) or download_name or asset.asset_id
    return url_for(
        "benben.download_workspace_asset",
        workspace_id=workspace_id,
        scope=asset.scope,
        asset_id=asset.asset_id,
        filename=safe_name,
    )


def _workspace_asset_payload(workspace_id: str, asset: AssetRecord, package: BenbenPackage, handle: Optional[WorkspaceHandle] = None) -> dict[str, object]:
    target_handle = handle
    if target_handle is None:
        try:
            target_handle = get_workspace(workspace_id)
        except Exception:
            target_handle = None
    is_cloud = getattr(target_handle, "mode", "") == "cloud"
    meta = asset.metadata if isinstance(asset.metadata, dict) else {}
    has_local_flag = meta.get("hasLocal")
    if has_local_flag is None:
        has_local_flag = bool(asset.size)
    has_local = bool(has_local_flag)
    url = _workspace_asset_url(workspace_id, asset) if has_local else None
    oss_meta = _asset_oss_info(asset)
    oss_url = oss_meta.get("url") if isinstance(oss_meta, dict) else None
    stub_url = _stub_oss_url(workspace_id, package, asset) if not oss_url else None
    preferred = oss_url or stub_url or url
    missing = not has_local and not oss_url
    return {
        "name": asset.name,
        "path": asset.name,
        "preferredUrl": preferred,
        "localUrl": url,
        "ossUrl": oss_url,
        "assetId": asset.asset_id,
        "size": asset.size,
        "metadata": asset.metadata,
        "local": has_local,
        "remote": bool(oss_url),
        "location": "missing" if missing else ("oss" if oss_url and not has_local else "workspace" if has_local else "mixed"),
        "missing": missing,
    }


def _workspace_project_label(package: BenbenPackage, project: Optional[dict] = None) -> str:
    if isinstance(project, dict):
        name = project.get("project")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return package.path.stem


def _asset_oss_info(asset: AssetRecord) -> Optional[dict]:
    payload = getattr(asset, "metadata", {}) or {}
    info = payload.get("oss") if isinstance(payload, dict) else None
    if isinstance(info, dict):
        return info
    return None


def _workspace_project_meta(package: BenbenPackage) -> dict:
    meta = package.get_meta_value("project", {})
    if isinstance(meta, dict):
        return meta
    return {}


def _workspace_oss_context(workspace_id: str, package: BenbenPackage) -> Optional[dict[str, Any]]:
    if not oss_is_configured():
        return None
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        handle = None
    project_meta = _workspace_project_meta(package)
    raw_name = str(project_meta.get("name") or "").strip() or package.path.stem
    slug = secure_filename(raw_name) or package.path.stem
    return {
        "project": raw_name,
        "slug": slug,
        "meta": project_meta,
        "handle": handle,
    }


def _parse_storage_choice() -> tuple[Optional[bool], Optional[bool]]:
    """Return (store_local, store_oss); None indicates auto/default."""

    storage = None
    try:
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            storage = payload.get("storage")
    except Exception:
        pass
    if storage is None:
        storage = request.form.get("storage") or request.args.get("storage")
    if storage is None:
        return None, None
    normalized = str(storage).strip().lower()
    if normalized in {"oss", "remote", "cloud"}:
        return False, True
    if normalized in {"local", "workspace"}:
        return True, False
    if normalized in {"both", "all"}:
        return True, True
    return None, None


def _default_storage(workspace_id: Optional[str]) -> tuple[bool, bool]:
    if not workspace_id:
        return True, False
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return True, False
    is_cloud = getattr(handle, "mode", "") == "cloud"
    return (False, True) if is_cloud else (True, False)


def _normalize_storage_choice(workspace_id: Optional[str], store_local: Optional[bool], store_oss: Optional[bool]) -> tuple[bool, bool]:
    """Enforce sensible storage defaults per workspace mode.

    Local workspace: always keep local copy (store_local=True), OSS optional.
    Cloud workspace: default store_local=False, store_oss=True.
    """

    default_local, default_oss = _default_storage(workspace_id)
    try:
        handle = get_workspace(workspace_id) if workspace_id else None
    except WorkspaceNotFoundError:
        handle = None
    is_cloud = getattr(handle, "mode", "") == "cloud"

    local = default_local if store_local is None else store_local
    oss = default_oss if store_oss is None else store_oss

    if not is_cloud:
        # 本地工作区强制保留本地文件，允许额外上传 OSS
        local = True
    else:
        # 云工作区默认不保留本地，可按需打开
        if store_local is None:
            local = default_local
    if not local and not oss:
        # 至少保留一份，避免数据丢失
        local = True
    return bool(local), bool(oss)


def _oss_category_for_scope(scope: str) -> Optional[str]:
    # 新策略：OSS 目录不再区分 attachment/resource，统一放在项目目录下
    return None


def _stub_oss_url(workspace_id: str, package: BenbenPackage, asset: AssetRecord) -> Optional[str]:
    """Return a synthetic OSS URL for link insertion even when not uploaded."""

    ctx = _workspace_oss_context(workspace_id, package)
    if not ctx:
        return None
    try:
        settings = oss_get_settings()
    except Exception:
        return None
    if not settings:
        return None
    key_segments = []
    prefix = settings.prefix.strip("/")
    if prefix:
        key_segments.append(prefix)
    slug = ctx.get("slug") or package.path.stem
    if slug:
        key_segments.append(slug)
    category = _oss_category_for_scope(asset.scope)
    if category:
        key_segments.append(category)
    name = (asset.name or "").lstrip("/")
    if name:
        key_segments.append(name)
    key = "/".join(filter(None, key_segments))
    if not key:
        return None
    return oss_build_public_url(settings, key) if hasattr(settings, "bucket_name") else None


def _mark_local_flag(asset: AssetRecord, enabled: bool) -> None:
    if not asset or not isinstance(asset.metadata, dict):
        return
    asset.metadata["hasLocal"] = bool(enabled)


def _update_asset_local_flag(package: BenbenPackage, asset: AssetRecord, enabled: bool) -> None:
    _mark_local_flag(asset, enabled)
    package.update_asset_metadata(asset.asset_id, asset.metadata, replace=True)


def _clear_asset_local_data(
    package: BenbenPackage,
    asset: AssetRecord,
    handle: Optional[WorkspaceHandle] = None,
    workspace_id: Optional[str] = None,
) -> None:
    """Remove local payload to shrink .benben when cloud workspace explicitly关闭本地存储。"""

    if not asset:
        return
    target_handle = handle
    if target_handle is None and workspace_id:
        try:
            target_handle = get_workspace(workspace_id)
        except Exception:
            target_handle = None
    if not target_handle or getattr(target_handle, "mode", "") != "cloud":
        # 仅确认是云端时才移除本地数据，避免误删本地工作区文件
        return
    _mark_local_flag(asset, False)
    package.update_asset_metadata(asset.asset_id, asset.metadata, replace=True)
    table = package._asset_table_for_scope(asset.scope)  # type: ignore[attr-defined]
    with package._lock:  # type: ignore[attr-defined]
        package.conn.execute(f"UPDATE {table} SET data = ? WHERE id = ?", (b"", asset.asset_id))  # type: ignore[attr-defined]
        package.conn.commit()
    asset.data = b""


def _sync_cloud_workspace_state(workspace_id: str, handle: Optional[WorkspaceHandle] = None) -> bool:
    """Best-effort sync for cloud workspaces after mutating package state."""

    if not workspace_id:
        return False
    target_handle = handle
    if target_handle is None:
        try:
            target_handle = get_workspace(workspace_id)
        except WorkspaceNotFoundError:
            return False
        except Exception as exc:  # pragma: no cover - defensive guard
            current_app.logger.warning("同步云端工作区失败（获取句柄）：%s", exc)
            return False
    if getattr(target_handle, "mode", None) != "cloud":
        return False
    try:
        sync_remote_workspace(target_handle)
        return True
    except Exception as exc:  # pragma: no cover - network/filesystem dependent
        current_app.logger.warning("同步云端工作区失败：%s", exc)
        return False


def _oss_sync_asset(
    workspace_id: str,
    package: BenbenPackage,
    asset: AssetRecord,
    *,
    data: Optional[bytes] = None,
    context: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    ctx = context if context is not None else _workspace_oss_context(workspace_id, package)
    if not ctx or not asset:
        return None
    payload = data
    if payload is None:
        reloaded = package.get_asset(asset.asset_id, include_data=True)
        if not reloaded or reloaded.data is None:
            return None
        payload = reloaded.data
        asset = reloaded
    checksum = hashlib.md5(payload).hexdigest()
    existing = _asset_oss_info(asset)
    if existing and existing.get("md5") == checksum and existing.get("fileName") == asset.name:
        return existing
    category = _oss_category_for_scope(asset.scope)
    try:
        uploaded = oss_upload_bytes(ctx["slug"], asset.name, payload, category=category)
    except Exception as exc:  # pragma: no cover - network errors
        current_app.logger.warning("OSS 上传失败：%s", exc)
        return None
    if not uploaded:
        return None
    oss_meta = {
        "url": uploaded.get("url"),
        "key": uploaded.get("key"),
        "etag": uploaded.get("etag"),
        "bucket": uploaded.get("bucket"),
        "uploadedAt": time.time(),
        "md5": checksum,
        "size": len(payload),
        "category": category,
        "fileName": asset.name,
    }
    package.update_asset_metadata(asset.asset_id, {"oss": oss_meta})
    asset.metadata["oss"] = oss_meta
    return oss_meta


def _oss_delete_asset(
    workspace_id: str,
    package: BenbenPackage,
    *,
    asset: Optional[AssetRecord] = None,
    name: Optional[str] = None,
    scope: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> bool:
    ctx = context if context is not None else _workspace_oss_context(workspace_id, package)
    if not ctx:
        return False
    target_name = name or (asset.name if asset else None)
    target_scope = scope or (asset.scope if asset else None)
    if not target_name or not target_scope:
        return False
    category = _oss_category_for_scope(target_scope)
    try:
        oss_delete_file(ctx["slug"], target_name, category=category)
    except Exception as exc:  # pragma: no cover - network errors
        current_app.logger.warning("OSS 删除失败：%s", exc)
        return False
    if asset:
        package.update_asset_metadata(asset.asset_id, {"oss": None})
    return True


def _workspace_asset_rel_path(asset: AssetRecord) -> str:
    cleaned = str(asset.name or "").strip().replace("\\", "/")
    cleaned = re.sub(r"/+", "/", cleaned)
    cleaned = cleaned.lstrip("./")
    parts: list[str] = []
    for segment in cleaned.split("/"):
        sanitized = secure_filename(segment)
        if sanitized:
            parts.append(sanitized)
    if not parts:
        fallback = secure_filename(asset.asset_id) or f"{asset.scope}_{asset.asset_id}"
        parts = [fallback]
    return os.path.join(*parts)


def _write_workspace_asset(asset: AssetRecord, dest_root: Path) -> Path | None:
    if asset.data is None:
        return
    rel_path = _workspace_asset_rel_path(asset)
    target = dest_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(asset.data)
    return target


def _iter_workspace_asset_bytes(package: BenbenPackage, scope: str):
    for asset in package.list_assets(scope, include_data=True):
        if asset.data is None:
            continue
        yield _workspace_asset_rel_path(asset), asset.data


def _create_workspace_snapshot(package: BenbenPackage, safe_name: str) -> tuple[Path, Path]:
    """Copy the current workspace into a temporary `.benben` for download."""

    sanitized = secure_filename(safe_name or "") or "workspace"
    temp_dir = Path(tempfile.mkdtemp(prefix="benben_export_bundle_"))
    snapshot_path = temp_dir / f"{sanitized}.benben"
    try:
        package.snapshot_to(snapshot_path)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return snapshot_path, temp_dir


@contextmanager
def _workspace_runtime_dirs(package: BenbenPackage):
    base_dir = Path(tempfile.mkdtemp(prefix="benben_workspace_export_"))
    attachments_dir = base_dir / "attachments"
    resources_dir = base_dir / "resources"
    build_dir = base_dir / "build"
    audio_dir = build_dir / "audio"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    attachment_map: dict[str, str] = {}
    for asset in package.list_assets("attachment", include_data=True):
        rel_path = _workspace_asset_rel_path(asset)
        target = _write_workspace_asset(asset, attachments_dir)
        if target:
            # 为本地优先渲染保留 assetId 与文件名的映射
            attachment_map[asset.asset_id] = str(target)
            if asset.name:
                attachment_map[asset.name] = str(target)
                base = os.path.basename(asset.name)
                if base and base != asset.name:
                    attachment_map.setdefault(base, str(target))
    for asset in package.list_assets("resource", include_data=True):
        _write_workspace_asset(asset, resources_dir)

    try:
        yield {
            "base": str(base_dir),
            "attachments": str(attachments_dir),
            "resources": str(resources_dir),
            "build": str(build_dir),
            "audio": str(audio_dir),
            "attachment_map": attachment_map,
        }
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def _workspace_cache_dir(workspace_id: str) -> Path:
    safe_id = secure_filename(workspace_id) or workspace_id
    cache_base = _WORKSPACE_CACHE_ROOT / safe_id
    cache_base.mkdir(parents=True, exist_ok=True)
    return cache_base


def _safe_path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    try:
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
    except Exception:
        return total
    return total


def _asset_metadata_from_upload(file_storage, data: bytes) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "size": len(data),
        "uploadedAt": time.time(),
    }
    if getattr(file_storage, "filename", None):
        metadata["originalName"] = file_storage.filename
    return metadata


def _sanitize_attachment_name(raw: Optional[str], prefix: str = "file") -> str:
    candidate = secure_filename(raw or "") or ""
    if candidate:
        return candidate
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@bp.route("/attachments/storage", methods=["POST"])
def update_attachment_storage():
    """调整单个附件的存储策略（本地 / OSS / 同时）。"""

    data = request.get_json(silent=True) or request.form or {}
    name = (data.get("name") or data.get("path") or "").strip()
    if not name:
        return api_error("name required", 400)

    workspace_id, package, error = _require_workspace_package_response()
    if error:
        return error

    store_local, store_oss = _parse_storage_choice()
    store_local, store_oss = _normalize_storage_choice(workspace_id, store_local, store_oss)

    try:
        handle = get_workspace(workspace_id)
    except Exception:
        handle = None

    asset = package.find_asset_by_name("attachment", name, include_data=True)
    if not asset:
        return api_error("附件不存在", 404)

    url = _workspace_asset_url(workspace_id, asset)
    oss_context = _workspace_oss_context(workspace_id, package) if store_oss else None
    oss_meta = None
    if store_oss and asset.data:
        oss_meta = _oss_sync_asset(workspace_id, package, asset, data=asset.data, context=oss_context)
    elif not store_oss:
        _oss_delete_asset(workspace_id, package, asset=asset, context=_workspace_oss_context(workspace_id, package))
    if store_local:
        _update_asset_local_flag(package, asset, True)
    else:
        if store_oss and oss_meta:
            _clear_asset_local_data(package, asset, handle=handle, workspace_id=workspace_id)
        else:
            # 远程未成功，保留本地数据以免丢失
            _update_asset_local_flag(package, asset, True)
            store_local = True
    oss_url = oss_meta.get("url") if isinstance(oss_meta, dict) else None
    stub_url = _stub_oss_url(workspace_id, package, asset) if not oss_url else None

    context_handle = oss_context.get("handle") if isinstance(oss_context, dict) else None
    _sync_cloud_workspace_state(workspace_id, handle=context_handle)

    preferred = oss_url or stub_url or (url if store_local else None)
    return api_success(
        {
            "name": asset.name,
            "assetId": asset.asset_id,
            "local": store_local,
            "oss": store_oss,
            "localUrl": url if store_local else None,
            "ossUrl": oss_url,
            "preferredUrl": preferred,
        }
    )


@bp.route("/resources/storage", methods=["POST"])
def update_resource_storage():
    """调整单个资源的存储策略（本地 / OSS / 同时）。"""

    data = request.get_json(silent=True) or request.form or {}
    name = (data.get("name") or data.get("path") or "").strip()
    if not name:
        return api_error("name required", 400)

    workspace_id, package, error = _require_workspace_package_response()
    if error:
        return error

    store_local, store_oss = _parse_storage_choice()
    store_local, store_oss = _normalize_storage_choice(workspace_id, store_local, store_oss)

    try:
        handle = get_workspace(workspace_id)
    except Exception:
        handle = None

    asset = package.find_asset_by_name("resource", name, include_data=True)
    if not asset:
        return api_error("资源不存在", 404)

    url = _workspace_asset_url(workspace_id, asset, filename=os.path.basename(name))
    oss_context = _workspace_oss_context(workspace_id, package) if store_oss else None
    oss_meta = None
    if store_oss and asset.data:
        oss_meta = _oss_sync_asset(workspace_id, package, asset, data=asset.data, context=oss_context)
    elif not store_oss:
        _oss_delete_asset(workspace_id, package, asset=asset, context=_workspace_oss_context(workspace_id, package))
    if store_local:
        _update_asset_local_flag(package, asset, True)
    else:
        if store_oss and oss_meta:
            _clear_asset_local_data(package, asset, handle=handle, workspace_id=workspace_id)
        else:
            _update_asset_local_flag(package, asset, True)
            store_local = True
    oss_url = oss_meta.get("url") if isinstance(oss_meta, dict) else None
    stub_url = _stub_oss_url(workspace_id, package, asset) if not oss_url else None

    context_handle = oss_context.get("handle") if isinstance(oss_context, dict) else None
    _sync_cloud_workspace_state(workspace_id, handle=context_handle)

    preferred = oss_url or stub_url or (url if store_local else None)
    return api_success(
        {
            "name": asset.name,
            "path": asset.name,
            "assetId": asset.asset_id,
            "local": store_local,
            "oss": store_oss,
            "localUrl": url if store_local else None,
            "ossUrl": oss_url,
            "preferredUrl": preferred,
        }
    )


@bp.route("/attachments/upload", methods=["POST"])
def upload_attachment():
    """上传附件文件并回传可引用链接。"""

    files = request.files.getlist("files[]") or request.files.getlist("files")
    if not files and "file" in request.files:
        files = [request.files["file"]]
    if not files:
        return api_error("No file part", 400)

    workspace_id, package, error = _require_workspace_package_response()
    if error:
        return error

    paths_hint = request.form.getlist("paths[]") or request.form.getlist("paths") or []

    store_local, store_oss = _parse_storage_choice()
    store_local, store_oss = _normalize_storage_choice(workspace_id, store_local, store_oss)

    try:
        handle = get_workspace(workspace_id)
    except Exception:
        handle = None
    uploads: list[dict[str, object]] = []
    oss_context = _workspace_oss_context(workspace_id, package) if store_oss else None
    for idx, file_storage in enumerate(files):
        if not file_storage or not file_storage.filename:
            continue
        local_pref = store_local
        data = file_storage.read()
        if not data:
            continue
        raw_path = paths_hint[idx] if idx < len(paths_hint) else file_storage.filename
        parts = [secure_filename(p) for p in str(raw_path or file_storage.filename).split("/") if secure_filename(p)]
        filename = "/".join(parts) if parts else _sanitize_attachment_name(file_storage.filename, prefix=f"file{idx+1}")
        mime = file_storage.mimetype or mimetypes.guess_type(filename)[0]
        metadata = _asset_metadata_from_upload(file_storage, data)
        metadata["hasLocal"] = bool(local_pref)
        stored_data = data  # 保留数据，待远程成功后再按需清理
        asset = package.save_or_replace_asset(
            name=filename,
            scope="attachment",
            data=stored_data,
            mime=mime,
            metadata=metadata,
        )
        oss_meta = _oss_sync_asset(workspace_id, package, asset, data=data, context=oss_context) if oss_context else None
        oss_url = oss_meta.get("url") if isinstance(oss_meta, dict) else None
        stub_url = _stub_oss_url(workspace_id, package, asset) if not oss_url else None
        if not local_pref and oss_meta:
            _clear_asset_local_data(package, asset, handle=handle, workspace_id=workspace_id)
        else:
            _update_asset_local_flag(package, asset, True)
            if not local_pref and not oss_meta:
                local_pref = True
        url = _workspace_asset_url(workspace_id, asset)
        preferred = oss_url or stub_url or url
        markdown_ref = f"![{asset.asset_id}]({preferred})" if preferred else None
        uploads.append(
            {
                "name": asset.name,
                "filename": asset.name,
                "localUrl": url if local_pref else None,
                "preferredUrl": preferred,
                "url": preferred,
                "ossUrl": oss_url,
                "assetId": asset.asset_id,
                "size": asset.size,
                "metadata": asset.metadata,
                "markdown": markdown_ref,
            }
        )
    if not uploads:
        return api_error("No valid files", 400)
    primary = uploads[0]
    payload = {
        "attachments": uploads,
        "filename": primary.get("filename"),
        "name": primary.get("name"),
        "localUrl": primary.get("localUrl"),
        "url": primary.get("preferredUrl"),
        "preferredUrl": primary.get("preferredUrl"),
        "ossUrl": primary.get("ossUrl"),
    }
    if primary.get("markdown"):
        payload["markdown"] = primary["markdown"]
    context_handle = oss_context.get("handle") if isinstance(oss_context, dict) else None
    _sync_cloud_workspace_state(workspace_id, handle=context_handle)
    return api_success(payload)


def _safe_join(base: str, relative: str) -> Optional[str]:
    """Safely join a relative path to a base directory."""

    if not relative:
        return None
    normalized_base = os.path.abspath(base)
    candidate = os.path.abspath(os.path.join(base, relative))
    try:
        common = os.path.commonpath([normalized_base, candidate])
    except ValueError:
        return None
    if common != normalized_base:
        return None
    return candidate


def _resolve_local_asset_path(
    src: str,
    project_name: str,
    attachments_folder: str,
    resources_folder: str,
) -> Optional[str]:
    """Resolve a local image URL to an absolute filesystem path."""

    if not src:
        return None
    cleaned = unquote(str(src).strip())
    if not cleaned:
        return None
    cleaned = cleaned.split("#", 1)[0].split("?", 1)[0]
    parsed = urlparse(cleaned)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    path = parsed.path or cleaned
    trimmed = path.lstrip("/")
    project_prefix = f"projects/{project_name}/"
    if trimmed.startswith(project_prefix):
        trimmed = trimmed[len(project_prefix) :]
    trimmed = trimmed.lstrip("/")
    if trimmed.startswith("uploads/"):
        rel = trimmed[len("uploads/") :]
        return _safe_join(attachments_folder, rel)
    if trimmed.startswith("resources/"):
        rel = trimmed[len("resources/") :]
        return _safe_join(resources_folder, rel)
    candidate = _safe_join(attachments_folder, trimmed)
    if candidate and os.path.exists(candidate):
        return candidate


def _extract_llm_preference(payload: Optional[dict], project: Optional[dict], usage: str) -> tuple[Optional[str], Optional[str]]:
    provider_override = None
    model_override = None
    if isinstance(payload, dict):
        llm_payload = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
        if usage == "embedding":
            provider_override = llm_payload.get("embedding", {}).get("provider") if isinstance(llm_payload.get("embedding"), dict) else None
            model_override = llm_payload.get("embedding", {}).get("model") if isinstance(llm_payload.get("embedding"), dict) else None
            provider_override = provider_override or payload.get("llmEmbeddingProvider")
            model_override = model_override or payload.get("llmEmbeddingModel") or payload.get("embeddingModel") or payload.get("embedding_model")
        elif usage == "tts":
            provider_override = llm_payload.get("tts", {}).get("provider") if isinstance(llm_payload.get("tts"), dict) else None
            model_override = llm_payload.get("tts", {}).get("model") if isinstance(llm_payload.get("tts"), dict) else None
            provider_override = provider_override or payload.get("llmTtsProvider")
            model_override = model_override or payload.get("llmTtsModel") or payload.get("ttsModel") or payload.get("tts_model")
        else:
            provider_override = llm_payload.get("chat", {}).get("provider") if isinstance(llm_payload.get("chat"), dict) else None
            model_override = llm_payload.get("chat", {}).get("model") if isinstance(llm_payload.get("chat"), dict) else None
            provider_override = provider_override or payload.get("llmProvider") or payload.get("llm_provider")
            model_override = model_override or payload.get("llmModel") or payload.get("llm_model")
    if provider_override:
        provider_override = str(provider_override).strip()
    if model_override:
        model_override = str(model_override).strip()
    return provider_override or None, model_override or None


def _resolve_llm_for_request(payload: Optional[dict] = None, project: Optional[dict] = None, usage: str = "chat") -> tuple[dict, dict]:
    """组合请求体与项目配置，解析出最终的 LLM 配置与请求头（按用途区分）。"""

    provider_override, model_override = _extract_llm_preference(payload, project, usage)
    config = resolve_llm_config(
        provider_id=provider_override,
        project=project,
        model=model_override if usage == "chat" else None,
        embedding_model=model_override if usage == "embedding" else None,
        tts_model=model_override if usage == "tts" else None,
        usage=usage,
    )
    headers = build_chat_headers(config)
    return config, headers


def _llm_missing_key_error(config: dict) -> str:
    """生成缺少 API Key 时的错误提示。"""

    env_name = str(config.get("api_key_env") or "LLM_API_KEY")
    provider_label = str(config.get("label") or config.get("id") or "LLM")
    return f"未设置{env_name}环境变量（{provider_label}）"


def _llm_provider_label(config: dict) -> str:
    """提取 provider 的友好名称。"""

    return str(config.get("label") or config.get("id") or "LLM")


def _resolve_llm_timeout(config: dict, fallback: int) -> int:
    """根据 provider 配置与默认值确定请求超时时间。"""

    timeout_value = config.get("timeout")
    try:
        resolved = int(timeout_value)
    except (TypeError, ValueError):
        resolved = fallback
    if resolved <= 0:
        return fallback
    return resolved


def _resolve_embedding_model(payload: Optional[dict], llm_config: dict) -> str:
    """Pick an embedding model from request, provider, or defaults."""

    if isinstance(payload, dict):
        candidate = payload.get("embeddingModel") or payload.get("embedding_model")
        if candidate:
            trimmed = str(candidate).strip()
            if trimmed:
                return trimmed
    if llm_config.get("embedding_model"):
        candidate = str(llm_config["embedding_model"]).strip()
        if candidate:
            return candidate
    if llm_config.get("default_embedding_model"):
        candidate = str(llm_config["default_embedding_model"]).strip()
        if candidate:
            return candidate
    return DEFAULT_EMBEDDING_MODEL


def _resolve_tts_model(payload: Optional[dict], llm_config: dict, default: str = "tts-1") -> str:
    """Pick a TTS model from request, provider, or defaults."""

    if isinstance(payload, dict):
        candidate = payload.get("ttsModel") or payload.get("tts_model")
        if candidate:
            trimmed = str(candidate).strip()
            if trimmed:
                return trimmed
    for key in ("tts_model", "default_tts_model"):
        if llm_config.get(key):
            trimmed = str(llm_config[key]).strip()
            if trimmed:
                return trimmed
    return default


def _format_assistant_user_message(message: str, contexts: list[dict]) -> str:
    """Build user message with optional RAG context list."""

    context_lines: list[str] = []
    for ctx in contexts:
        text = _truncate_text(ctx.get("text") or "", 1200)
        label = ctx.get("label") or f"Page {int(ctx.get('pageIdx') or 0) + 1}"
        page_idx = ctx.get("pageIdx")
        page_tag = f"(第 {int(page_idx) + 1} 页)" if isinstance(page_idx, int) else ""
        context_lines.append(f"[{ctx.get('rank', '?')}] {label} {page_tag}\n{text}")
    context_block = "\n\n".join(context_lines)
    if context_block:
        return (
            "以下是我工作区中最相关的 Markdown 片段（按相关度排序）。"
            "回答时优先引用它们，若仍不足以回答，请说明缺少上下文后再补充推理。\n\n"
            f"{context_block}\n\n用户问题：\n{message}"
        )
    return (
        "未检索到可用的工作区上下文。请直接回答用户问题，但不要捏造具体的工作区内容。\n\n"
        f"用户问题：\n{message}"
    )


def _build_rag_contexts(
    query: str,
    workspace_id: str,
    package: BenbenPackage,
    llm_config: dict,
    headers: dict,
    embedding_model: str,
    top_k: int,
    *,
    page_id_filter: str | None = None,
    page_idx_filter: int | None = None,
) -> tuple[list[dict], bool]:
    allowed_pages = None
    if page_id_filter:
        normalized = page_id_filter.strip()
        if normalized:
            allowed_pages = {normalized}

    cache_dir = _workspace_cache_dir(workspace_id) / "rag"
    cache_dir.mkdir(parents=True, exist_ok=True)
    index, manifest, rebuilt = ensure_markdown_index(
        workspace_id,
        package,
        llm_config,
        headers,
        cache_dir,
        embedding_model=embedding_model,
        chunk_size=_RAG_CHUNK_SIZE,
        overlap=_RAG_CHUNK_OVERLAP,
    )
    contexts = search_markdown(
        query,
        index,
        manifest,
        llm_config,
        headers,
        package=package,
        embedding_model=embedding_model,
        top_k=top_k,
        allowed_page_ids=allowed_pages,
    )
    if page_id_filter or page_idx_filter is not None:
        filtered: list[dict] = []
        normalized_id = (page_id_filter or "").strip()
        for ctx in contexts:
            if normalized_id and ctx.get("pageId") != normalized_id:
                continue
            if page_idx_filter is not None and ctx.get("pageIdx") != page_idx_filter:
                continue
            filtered.append(ctx)
        contexts = filtered
    return contexts, rebuilt


def _iter_component_items(library: dict, mode: str):
    """Yield component library items for prompt/validation."""

    groups = library.get(mode, [])
    if not isinstance(groups, list):
        return
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("group") or "").strip()
        items = group.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            code = item.get("code")
            if code is None:
                code = ""
            yield group_name, name, str(code).strip()


def _format_component_library_for_prompt(mode: str) -> str:
    """Format component library as a strict whitelist for LLM prompts."""

    lines: list[str] = []
    current_group = None
    for group_name, name, code in _iter_component_items(COMPONENT_LIBRARY, mode):
        if group_name and group_name != current_group:
            lines.append(f"[{group_name}]")
            current_group = group_name
        if name:
            lines.append(f"- {name}")
        if code:
            lines.append(code)
    return "\n".join(lines).strip()


def _component_library_prompt_text(mode: str) -> str:
    text = _format_component_library_for_prompt(mode)
    return text if text else "无"


@bp.route("/llm/test", methods=["POST"])
def llm_connectivity_test():
    """向选定的能力（chat/embedding/tts）发送最短请求，验证接口可用性。"""

    data = request.get_json(silent=True) or {}
    usage = str(data.get("type") or "chat").strip().lower()
    if usage not in {"chat", "embedding", "tts"}:
        usage = "chat"

    _, _, project, error = _require_workspace_project_response()
    if error:
        return error
    llm_config, headers = _resolve_llm_for_request(data, project=project, usage=usage)
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)

    started = time.perf_counter()
    if usage == "embedding":
        model_name = llm_config.get("embedding_model")
        if not model_name:
            return api_error("未配置可用的 embedding 模型", 500)
        try:
            resp = requests.post(
                llm_config["embedding_endpoint"],
                headers=headers,
                json={"model": model_name, "input": ["ping"]},
                timeout=_resolve_llm_timeout(llm_config, 15),
            )
        except Exception as exc:  # pragma: no cover
            return api_error(str(exc), 500)
        latency_ms = (time.perf_counter() - started) * 1000.0
        if resp.status_code != 200:
            return api_error(f"{_llm_provider_label(llm_config)} Embedding API错误: {resp.text}", 500)
        return api_success({"result": {"latencyMs": latency_ms, "preview": "ok"}})

    if usage == "tts":
        model_name = llm_config.get("tts_model") or OPENAI_TTS_MODEL
        try:
            resp = requests.post(
                llm_config.get("tts_endpoint") or llm_config.get("endpoint"),
                headers=headers,
                json={
                    "model": model_name,
                    "input": "ping",
                    "voice": llm_config.get("tts_voice") or OPENAI_TTS_VOICE,
                    "response_format": llm_config.get("tts_response_format") or OPENAI_TTS_RESPONSE_FORMAT,
                    "speed": llm_config.get("tts_speed") or OPENAI_TTS_SPEED,
                },
                timeout=_resolve_llm_timeout(llm_config, 15),
            )
        except Exception as exc:  # pragma: no cover
            return api_error(str(exc), 500)
        latency_ms = (time.perf_counter() - started) * 1000.0
        if resp.status_code != 200:
            return api_error(f"{_llm_provider_label(llm_config)} TTS API错误: {resp.text}", 500)
        return api_success({"result": {"latencyMs": latency_ms, "preview": "ok"}})

    # chat
    model_name = llm_config.get("model")
    if not model_name:
        return api_error("未配置可用的聊天模型", 500)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a connectivity probe. Reply concisely."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 2,
        "temperature": 0,
    }
    try:
        resp = requests.post(
            llm_config["endpoint"],
            headers=headers,
            json=payload,
            timeout=_resolve_llm_timeout(llm_config, 15),
        )
    except Exception as exc:  # pragma: no cover - network errors
        return api_error(str(exc), 500)
    latency_ms = (time.perf_counter() - started) * 1000.0

    if resp.status_code != 200:
        return api_error(f"{_llm_provider_label(llm_config)} API错误: {resp.text}", 500)

    preview = ""
    try:
        parsed = resp.json()
        preview = parsed.get("choices", [{}])[0].get("message", {}).get("content", "")  # type: ignore[index]
    except (ValueError, TypeError, IndexError, KeyError):
        preview = resp.text
    preview = _truncate_text(preview or "", 120)
    return api_success({
        "result": {
            "latencyMs": latency_ms,
            "preview": preview,
        }
    })


@bp.route("/ai_optimize", methods=["POST"])
def ai_optimize():
    """调用 LLM 优化 Markdown 笔记或讲稿。"""

    data = request.get_json(silent=True) or {}
    _, _, project, error = _require_workspace_project_response()
    if error:
        return error

    opt_type = str(data.get("type") or "note").strip().lower()
    markdown_text = str(data.get("markdown") or data.get("content") or "")
    script_text = str(data.get("script") or "")

    llm_config, headers = _resolve_llm_for_request(data, project=project, usage="chat")
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)
    model_name = llm_config.get("model")
    if not model_name:
        return api_error("未配置可用的聊天模型", 500)

    if opt_type not in AI_PROMPTS:
        opt_type = "note"

    component_library_text = ""
    if opt_type == "script":
        prompt_template = AI_PROMPTS["script"]["template"]
        system_text = AI_PROMPTS["script"]["system"]
        user_prompt = prompt_template.format(markdown=markdown_text, script=script_text)
    else:
        prompt_template = AI_PROMPTS["note"]["template"]
        system_text = AI_PROMPTS["note"]["system"]
        component_library_text = _component_library_prompt_text("markdown")
        user_prompt = prompt_template.format(
            markdown=markdown_text,
            component_library=component_library_text,
        )

    try:
        resp = requests.post(
            llm_config["endpoint"],
            headers=headers,
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
            },
            timeout=_resolve_llm_timeout(llm_config, 60),
        )
    except Exception as exc:  # pragma: no cover - network errors
        return api_error(str(exc), 500)

    if resp.status_code != 200:
        return api_error(f"{_llm_provider_label(llm_config)} API错误: {resp.text}", 500)

    try:
        result = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as exc:  # pragma: no cover
        return api_error(f"解析 LLM 响应失败: {exc}", 500)

    return api_success({"result": result})


@bp.route("/ai_bib", methods=["POST"])
def ai_bib():
    """调用 LLM 基于 DOI/链接生成参考条目。"""

    data = request.get_json(silent=True) or {}
    ref = str(data.get("ref") or "").strip()
    if not ref:
        return api_error("参考链接输入为空", 400)

    _, _, project, error = _require_workspace_project_response()
    if error:
        return error

    llm_config, headers = _resolve_llm_for_request(data, project=project, usage="chat")
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)
    model_name = llm_config.get("model")
    if not model_name:
        return api_error("未配置可用的聊天模型", 500)

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": AI_BIB_PROMPT["system"]},
            {"role": "user", "content": AI_BIB_PROMPT["user"].format(ref=ref)},
        ],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(
            llm_config["endpoint"],
            headers=headers,
            json=payload,
            timeout=_resolve_llm_timeout(llm_config, 60),
        )
    except Exception as exc:  # pragma: no cover - network errors
        return api_error(str(exc), 500)

    if resp.status_code != 200:
        return api_error(f"{_llm_provider_label(llm_config)} API错误: {resp.text}", 500)

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as exc:  # pragma: no cover
        return api_error(f"解析 LLM 响应失败: {exc}", 500)

    entry = _extract_json_object(content)
    if entry:
        return api_success({"entry": entry})
    return api_success({"bib": content.strip()})


@bp.route("/assistant/query", methods=["POST"])
def assistant_query():
    """AI 助理：可选 RAG（当前工作区 Markdown）。"""

    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or data.get("prompt") or "").strip()
    if not message:
        return api_error("消息不能为空", 400)

    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error
    llm_config, headers = _resolve_llm_for_request(data, project=project, usage="chat")
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)
    model_name = llm_config.get("model")
    if not model_name:
        return api_error("未配置可用的聊天模型", 500)

    top_k = _RAG_TOP_K
    top_k_raw = data.get("topK") or data.get("k")
    if top_k_raw is not None:
        try:
            top_k_val = int(top_k_raw)
            top_k = max(1, min(top_k_val, 12))
        except (TypeError, ValueError):
            pass

    embedding_config, embedding_headers = _resolve_llm_for_request(data, project=project, usage="embedding")
    embedding_model = _resolve_embedding_model(data, embedding_config)
    use_rag_flag = _parse_bool_flag(data.get("useRag"))
    use_rag = True if use_rag_flag is None else bool(use_rag_flag)
    page_only_flag = _parse_bool_flag(
        data.get("ragPageOnly") or data.get("currentPageOnly") or data.get("pageOnly") or data.get("ragCurrentPage")
    )
    page_only = bool(page_only_flag)
    page_id_filter = str(data.get("pageId") or data.get("page_id") or data.get("ragPageId") or "").strip()
    page_idx_raw = data.get("pageIndex") if "pageIndex" in data else data.get("pageIdx")
    page_idx_filter = None
    if page_idx_raw is not None:
        try:
            page_idx_filter = int(page_idx_raw)
        except (TypeError, ValueError):
            page_idx_filter = None
    page_scope_warning = None
    if page_only and not page_id_filter and page_idx_filter is None:
        page_scope_warning = "未提供当前页信息，已回退为全局检索。"
        page_only = False

    contexts: list[dict] = []
    rag_rebuilt = False
    rag_used = False
    rag_notice = None
    rag_scope = "off"

    if use_rag:
        rag_scope = "page" if page_only else "all"
        try:
            contexts, rag_rebuilt = _build_rag_contexts(
                message,
                workspace_id,
                package,
                embedding_config,
                embedding_headers,
                embedding_model,
                top_k,
                page_id_filter=page_id_filter if page_only else None,
                page_idx_filter=page_idx_filter if page_only else None,
            )
            rag_used = bool(contexts)
            if not contexts:
                scope_hint = "（仅当前页）" if page_only else ""
                rag_notice = f"未命中相关 Markdown 片段{scope_hint}，已直接与 LLM 对话。"
            if page_scope_warning:
                rag_notice = f"{page_scope_warning} {rag_notice}" if rag_notice else page_scope_warning
        except RagUnavailableError as exc:
            rag_notice = str(exc)
            use_rag = False
            rag_scope = "off"
        except Exception as exc:  # pragma: no cover - network/faiss errors
            return api_error(f"RAG 查询失败: {exc}", 500)
    elif page_scope_warning:
        rag_notice = page_scope_warning

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _ASSISTANT_SYSTEM_PROMPT},
            {"role": "user", "content": _format_assistant_user_message(message, contexts if use_rag else [])},
        ],
        "temperature": 0.35,
    }
    try:
        resp = requests.post(
            llm_config["endpoint"],
            headers=headers,
            json=payload,
            timeout=_resolve_llm_timeout(llm_config, 60),
        )
    except Exception as exc:  # pragma: no cover
        return api_error(str(exc), 500)

    if resp.status_code != 200:
        return api_error(f"{_llm_provider_label(llm_config)} API错误: {resp.text}", 500)

    try:
        result = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as exc:  # pragma: no cover
        return api_error(f"解析 LLM 响应失败: {exc}", 500)

    return api_success(
        {
            "result": result,
            "contexts": contexts if use_rag else [],
            "ragUsed": use_rag and rag_used,
            "ragNotice": rag_notice,
            "ragRebuilt": rag_rebuilt,
            "llmModel": model_name,
            "embeddingModel": embedding_model,
            "ragScope": rag_scope,
            "ragPageOnly": rag_scope == "page",
        }
    )


def _list_workspace_learning_prompts(package: BenbenPackage) -> tuple[list[dict], dict[str, dict], set[str]]:
    stored = package.list_learning_prompts()
    custom: list[dict] = []
    overrides: dict[str, dict] = {}
    removed: set[str] = set()
    for entry in stored:
        prompt_id = entry.get("id")
        if not isinstance(prompt_id, str) or not prompt_id.strip():
            continue
        prompt_id = prompt_id.strip()
        entry["id"] = prompt_id
        entry.setdefault("source", "custom")
        if entry.get("removed"):
            removed.add(prompt_id)
            continue
        if entry["source"] == "override":
            overrides[prompt_id] = entry
        else:
            custom.append(entry)
    return custom, overrides, removed


def _list_workspace_learning_records(package: BenbenPackage) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in package.list_learning_records():
        key = row.get("input") or ""
        if not key:
            continue
        group = grouped.setdefault(
            key,
            {
                "input": key,
                "entries": [],
            },
        )
        context = row.get("context")
        if context:
            group["context"] = context
        entry = {
            "id": row.get("id") or uuid.uuid4().hex,
            "promptId": row.get("promptId") or row.get("prompt_id"),
            "promptName": row.get("promptName") or row.get("prompt_name"),
            "output": row.get("output") or "",
        }
        if row.get("savedAt"):
            entry["savedAt"] = row["savedAt"]
        if row.get("method"):
            entry["method"] = row["method"]
        if row.get("category"):
            entry["category"] = row["category"]
        entry["favorite"] = bool(row.get("favorite"))
        if row.get("review") is not None:
            entry["review"] = row.get("review")
        group["entries"].append(entry)
    return list(grouped.values())


def _merge_learning_prompts(package: BenbenPackage) -> tuple[list[dict], dict]:
    custom_prompts, overrides, removed = _list_workspace_learning_prompts(package)
    combined: list[dict] = []
    for default_prompt in LEARNING_ASSISTANT_DEFAULT_PROMPTS:
        prompt_id = default_prompt["id"]
        if prompt_id in removed:
            continue
        prompt = copy.deepcopy(default_prompt)
        override = overrides.get(prompt_id)
        if override:
            for key in ("name", "description", "template", "system"):
                if override.get(key):
                    prompt[key] = override[key]
        prompt["source"] = "default"
        prompt["allowDelete"] = True
        combined.append(prompt)

    for custom_prompt in custom_prompts:
        prompt = copy.deepcopy(custom_prompt)
        prompt["source"] = custom_prompt.get("source") or "custom"
        prompt["allowDelete"] = True
        combined.append(prompt)

    combined.sort(key=lambda item: (0 if item.get("source") == "default" else 1, item.get("name", "")))
    prompts_meta = {
        "custom": custom_prompts,
        "overrides": list(overrides.values()),
        "removed": sorted(removed),
    }
    return combined, prompts_meta


def _export_learning_payload(package: BenbenPackage) -> dict:
    prompts_meta = _merge_learning_prompts(package)[1]
    records = _list_workspace_learning_records(package)
    return {
        "prompts": prompts_meta,
        "records": records,
    }


def _load_image_bytes(
    src: str,
    project_name: str,
    attachments_folder: str,
    resources_folder: str,
    attachment_map: Optional[dict[str, str]] = None,
    asset_hint: Optional[str] = None,
) -> tuple[Optional[bytes], Optional[str]]:
    """Fetch image content and detect its MIME type."""

    if (not src or src.startswith("data:")) and not asset_hint:
        return None, None
    cleaned = (src or "").strip()
    alt_key = (asset_hint or "").strip()
    local_candidates: list[str] = []
    if alt_key:
        if attachment_map:
            for key in {alt_key, os.path.basename(alt_key)}:
                candidate = attachment_map.get(key) if isinstance(attachment_map, dict) else None
                if candidate:
                    local_candidates.append(candidate)
        trimmed_alt = alt_key.split("#", 1)[0].split("?", 1)[0].lstrip("/")
        if attachments_folder:
            candidate = _safe_join(attachments_folder, trimmed_alt)
            if candidate:
                local_candidates.append(candidate)
        if resources_folder:
            candidate = _safe_join(resources_folder, trimmed_alt)
            if candidate:
                local_candidates.append(candidate)

    for candidate in local_candidates:
        if candidate and os.path.exists(candidate):
            try:
                with open(candidate, "rb") as fh:
                    content = fh.read()
            except OSError:
                continue
            mime_type = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
            return content, mime_type

    parsed = urlparse(cleaned)
    local_path = _resolve_local_asset_path(cleaned, project_name, attachments_folder, resources_folder)
    if local_path and os.path.exists(local_path):
        try:
            with open(local_path, "rb") as fh:
                content = fh.read()
        except OSError:
            return None, None
        mime_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        return content, mime_type
    if parsed.scheme in {"http", "https"}:
        try:
            response = requests.get(cleaned, timeout=10)
            response.raise_for_status()
        except Exception:
            return None, None
        mime_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip() or None
        return response.content, mime_type
    return None, None


def _enhance_markdown_soup(
    html: str,
    project_name: str,
    attachments_folder: str,
    resources_folder: str,
    attachment_map: Optional[dict[str, str]] = None,
) -> BeautifulSoup:
    """Apply export-specific enhancements to rendered Markdown HTML."""

    soup = BeautifulSoup(html, "html.parser")

    def _inline_media_attr(tag, attr: str, hint: Optional[str] = None) -> None:
        src = tag.get(attr) or ""
        content, mime_type = _load_image_bytes(
            src,
            project_name,
            attachments_folder,
            resources_folder,
            attachment_map=attachment_map,
            asset_hint=hint,
        )
        if content and mime_type:
            encoded = base64.b64encode(content).decode("ascii")
            tag[attr] = f"data:{mime_type};base64,{encoded}"
            if tag.name == "source" and not tag.get("type"):
                tag["type"] = mime_type

    for pre in soup.find_all("pre"):
        code_block = pre.find("code", recursive=False)
        if not code_block:
            continue
        code_classes = list(code_block.get("class") or [])
        if "hljs" not in code_classes:
            code_classes.append("hljs")
        code_block["class"] = code_classes
        pre_classes = list(pre.get("class") or [])
        if "hljs" not in pre_classes:
            pre_classes.append("hljs")
        pre["class"] = pre_classes

    for img in soup.find_all("img"):
        src = img.get("src") or ""
        _inline_media_attr(img, "src", hint=img.get("alt") or src)
        classes = set(img.get("class") or [])
        classes.add("markdown-preview-image")
        img["class"] = list(classes)
        if not img.has_attr("loading"):
            img["loading"] = "lazy"
        if not img.has_attr("decoding"):
            img["decoding"] = "async"

    for media in soup.find_all(["video", "audio"]):
        if media.get("src"):
            _inline_media_attr(media, "src", hint=media.get("src"))
        if media.name == "video" and media.get("poster"):
            _inline_media_attr(media, "poster", hint=media.get("poster"))
        for source in media.find_all("source"):
            if source.get("src"):
                _inline_media_attr(source, "src", hint=source.get("src"))

    return soup


def _build_markdown_export_html(
    markdown_text: str,
    template: dict,
    project_name: str,
    attachments_folder: str,
    resources_folder: str,
    attachment_map: Optional[dict[str, str]] = None,
) -> str:
    """Render Markdown text and wrap it with styling suitable for export."""

    rendered_html = _MARKDOWN_RENDERER.render(markdown_text or "")
    soup = _enhance_markdown_soup(
        rendered_html,
        project_name,
        attachments_folder,
        resources_folder,
        attachment_map=attachment_map,
    )
    body_html = "".join(str(child) for child in soup.contents)

    wrapper_classes = ["markdown-preview-content", "markdown-export-content"]
    wrapper_extra = str(template.get("wrapperClass") or "").strip()
    if wrapper_extra:
        wrapper_classes.extend(wrapper_extra.split())
    wrapper_class_attr = " ".join(dict.fromkeys(wrapper_classes))

    css = str(template.get("css") or "")
    export_css = str(template.get("exportCss") or "")
    custom_head = str(template.get("customHead") or "")
    custom_body = str(template.get("customBody") or "")

    css_blocks = []
    if export_css.strip():
        css_blocks.append(export_css)
    if css.strip():
        css_blocks.append(css)
    style_block = ""
    if css_blocks:
        style_block = "<style>\n" + "\n".join(css_blocks) + "\n  </style>"

    color_mode = "light"
    if isinstance(UI_THEME, dict):
        color_mode = str(UI_THEME.get("color_mode", "light") or "light").lower()
        if color_mode not in {"light", "dark"}:
            color_mode = "light"

    body_classes = ["markdown-export", f"theme-{color_mode}"]
    body_attr = f'class="{" ".join(body_classes)}" data-theme="{color_mode}"'

    document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Markdown 预览导出</title>
  {style_block}
  {custom_head}
</head>
<body {body_attr}>
  <div class="{wrapper_class_attr}">
{body_html}
  </div>
  {custom_body}
  </body>
</html>
"""
    return document


def _resolve_export_asset_target(
    target: str,
    project_name: str,
    attachments_folder: str,
    resources_folder: str,
    attachment_map: Optional[dict[str, str]] = None,
) -> tuple[str, str] | None:
    """Resolve an asset reference to (source_path, bundled_relative_path)."""

    cleaned = _normalize_link_target(target)
    if not cleaned:
        return None

    def _within(base: str, candidate: str) -> bool:
        if not base:
            return False
        try:
            return os.path.commonpath([os.path.abspath(base), os.path.abspath(candidate)]) == os.path.abspath(base)
        except Exception:
            return False

    source_path = _resolve_local_asset_path(cleaned, project_name, attachments_folder, resources_folder)
    scope = None
    if source_path and _within(attachments_folder, source_path):
        scope = "attachments"
    elif source_path and _within(resources_folder, source_path):
        scope = "resources"
    elif attachment_map:
        candidate = attachment_map.get(cleaned) or attachment_map.get(os.path.basename(cleaned))
        if candidate and os.path.exists(candidate):
            source_path = candidate
            scope = "attachments"

    if not source_path or not scope or not os.path.exists(source_path):
        return None
    base_dir = attachments_folder if scope == "attachments" else resources_folder
    try:
        rel_part = os.path.relpath(source_path, base_dir)
    except Exception:
        rel_part = os.path.basename(source_path)
    rel_path = os.path.join(scope, rel_part).replace("\\", "/")
    return source_path, rel_path


def _rewrite_markdown_for_export(
    markdown_text: str,
    project_name: str,
    attachments_folder: str,
    resources_folder: str,
    attachment_map: Optional[dict[str, str]] = None,
) -> tuple[str, dict[str, str]]:
    """Rewrite Markdown links to bundled asset paths and collect copy targets."""

    assets: dict[str, str] = {}

    def _register(target: str) -> Optional[str]:
        resolved = _resolve_export_asset_target(
            target,
            project_name,
            attachments_folder,
            resources_folder,
            attachment_map=attachment_map,
        )
        if not resolved:
            return None
        src_path, rel_path = resolved
        assets.setdefault(rel_path, src_path)
        return rel_path

    def _rewrite_markdown_link(match: re.Match[str]) -> str:
        target = match.group(1)
        new_target = _register(target)
        if not new_target:
            return match.group(0)
        return match.group(0).replace(target, new_target, 1)

    def _rewrite_html_src(match: re.Match[str]) -> str:
        target = match.group(1)
        new_target = _register(target)
        if not new_target:
            return match.group(0)
        return match.group(0).replace(target, new_target, 1)

    rewritten = _MARKDOWN_LINK_RE.sub(_rewrite_markdown_link, markdown_text)
    rewritten = _HTML_SRC_RE.sub(_rewrite_html_src, rewritten)
    rewritten = _HTML_HREF_RE.sub(_rewrite_html_src, rewritten)
    return rewritten, assets


def _build_markdown_bundle(
    markdown_text: str,
    export_filename: str,
    project_name: str,
    attachments_folder: str,
    resources_folder: str,
    attachment_map: Optional[dict[str, str]] = None,
) -> tuple[Path, Path]:
    """Write Markdown plus referenced assets into a temporary bundle and zip it."""

    safe_name = secure_filename(export_filename) or export_filename or "notes.md"
    rewritten_md, assets = _rewrite_markdown_for_export(
        markdown_text,
        project_name,
        attachments_folder,
        resources_folder,
        attachment_map=attachment_map,
    )
    bundle_dir = Path(tempfile.mkdtemp(prefix="benben_md_export_"))
    bundle_dir.mkdir(parents=True, exist_ok=True)
    md_path = bundle_dir / safe_name
    md_path.write_text(rewritten_md, encoding="utf-8")

    for rel_path, src_path in assets.items():
        dest = bundle_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src_path, dest)
        except Exception:
            continue

    archive_path = Path(shutil.make_archive(str(bundle_dir), "zip", bundle_dir))
    return archive_path, bundle_dir


def _collect_bib_entries_for_export(project: dict) -> list[str]:
    """Extract citation entries from project-level与页面引用。"""

    entries: list[str] = []

    def _add_entry(candidate: Optional[str]) -> None:
        if not candidate:
            return
        text = str(candidate).strip()
        if text:
            entries.append(text)

    pages = project.get("pages", []) if isinstance(project, dict) else []
    for page in pages if isinstance(pages, list) else []:
        for entry in page.get("bib", []) or []:
            if isinstance(entry, dict):
                _add_entry(entry.get("bibtex") or entry.get("entry"))
            else:
                _add_entry(entry)

    for entry in project.get("bib", []) or []:
        if isinstance(entry, dict):
            _add_entry(entry.get("bibtex") or entry.get("entry"))
        else:
            _add_entry(entry)

    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return deduped



def _resolve_markdown_template(project: Optional[dict]) -> dict:
    """Return the effective Markdown export template for a project."""

    default_template = get_default_markdown_template()
    template: dict[str, str] = {
        "css": default_template.get("css", ""),
        "wrapperClass": default_template.get("wrapperClass", ""),
        "exportCss": default_template.get("exportCss", ""),
    }
    default_head = default_template.get("customHead")
    if isinstance(default_head, str) and default_head.strip():
        template["customHead"] = default_head
    default_body = default_template.get("customBody")
    if isinstance(default_body, str) and default_body.strip():
        template["customBody"] = default_body

    raw_template = project.get("markdownTemplate") if isinstance(project, dict) else None
    raw_has_export = False
    if isinstance(raw_template, dict):
        raw_has_export = any(key in raw_template for key in ("exportCss", "customHead", "customBody"))
        css_value = raw_template.get("css")
        if isinstance(css_value, str):
            template["css"] = css_value
        wrapper_value = raw_template.get("wrapperClass")
        if isinstance(wrapper_value, str):
            template["wrapperClass"] = wrapper_value
        export_css_value = raw_template.get("exportCss")
        if isinstance(export_css_value, str):
            template["exportCss"] = export_css_value
        head_value = raw_template.get("customHead")
        if isinstance(head_value, str) and head_value.strip():
            template["customHead"] = head_value
        elif not head_value:
            template.pop("customHead", None)
        body_value = raw_template.get("customBody")
        if isinstance(body_value, str) and body_value.strip():
            template["customBody"] = body_value
        elif not body_value:
            template.pop("customBody", None)

        if not raw_has_export:
            matched = _find_matching_markdown_template(template)
            if matched:
                matched_export = matched.get("exportCss")
                if isinstance(matched_export, str):
                    template["exportCss"] = matched_export
                matched_head = matched.get("customHead")
                if isinstance(matched_head, str) and matched_head.strip():
                    template["customHead"] = matched_head
                matched_body = matched.get("customBody")
                if isinstance(matched_body, str) and matched_body.strip():
                    template["customBody"] = matched_body
            else:
                template["exportCss"] = ""
                template.pop("customHead", None)
                template.pop("customBody", None)

    return template


def _normalize_css_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").strip()


def _find_matching_markdown_template(template: dict) -> Optional[dict]:
    """Match a template by css + wrapper class against library templates."""

    css = _normalize_css_text(template.get("css"))
    wrapper = str(template.get("wrapperClass") or "").strip()
    try:
        library = list_templates().get("markdown", [])
    except Exception:
        return None
    for candidate in library:
        if not isinstance(candidate, dict):
            continue
        if _normalize_css_text(candidate.get("css")) != css:
            continue
        if str(candidate.get("wrapperClass") or "").strip() != wrapper:
            continue
        return candidate
    return None


def _normalize_link_target(value: object) -> str:
    """Clean up a link or path and return a comparable string."""

    if value is None:
        return ""
    cleaned = str(value).strip()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("\\", "/")
    cleaned = cleaned.split("?", 1)[0]
    cleaned = cleaned.split("#", 1)[0]
    return cleaned.strip()


def _safe_unquote(value: str) -> str:
    try:
        return unquote(value)
    except Exception:
        return value


def _build_page_id_index(pages: list) -> dict[str, int]:
    """Build a lowercase pageId -> index lookup table."""

    mapping: dict[str, int] = {}
    for idx, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        for key in ("pageId", "id"):
            raw = page.get(key)
            if isinstance(raw, str) and raw.strip():
                mapping[raw.strip().lower()] = idx
    return mapping


def _parse_markdown_internal_link(href: object) -> tuple[Optional[int], Optional[str]]:
    """Parse a Markdown/HTML link target and extract page index or page ID."""

    if href is None:
        return None, None
    trimmed = str(href).strip()
    if not trimmed:
        return None, None
    if _INTERNAL_LINK_SCHEMES_RE.match(trimmed):
        return None, None
    if trimmed.startswith("#"):
        return None, None

    working = trimmed
    if working.startswith("./"):
        working = working[2:]
    working = working.lstrip("/")

    if "#" in working:
        working = working.split("#", 1)[0]

    if not working:
        return None, None

    working = _safe_unquote(working)
    if working.startswith("?"):
        working = working[1:]
    if working.lower().endswith(".md"):
        working = working[:-3]

    page_index: Optional[int] = None
    page_id: Optional[str] = None

    if "=" in working:
        params: dict[str, str] = {}
        for key, value in parse_qsl(working, keep_blank_values=True):
            if key:
                params[key.lower()] = value

        def _get_param(*keys: str) -> Optional[str]:
            for key in keys:
                if key in params:
                    return params[key]
            return None

        page_param = _get_param("page", "p")
        if page_param is not None:
            try:
                page_index = int(page_param) - 1
            except (TypeError, ValueError):
                page_index = None
        page_index_param = _get_param("pageindex", "page_idx", "index")
        if page_index_param is not None:
            try:
                page_index = int(page_index_param) - 1
            except (TypeError, ValueError):
                page_index = None
        page_id_param = _get_param("pageid", "page_id", "pid", "id")
        if page_id_param is not None:
            trimmed_pid = str(page_id_param).strip()
            if trimmed_pid:
                page_id = trimmed_pid

    if page_index is None and not page_id:
        match = re.match(r"^(?:page[-_]?|p)(\d+)$", working, flags=re.IGNORECASE)
        if match:
            page_index = int(match.group(1)) - 1
        else:
            match = re.match(r"^(\d+)$", working)
            if match:
                page_index = int(match.group(1)) - 1
            else:
                match = re.match(r"^page(?:Id)?[-_:]?([0-9a-f]{32})$", working, flags=re.IGNORECASE)
                if match:
                    page_id = match.group(1)
                else:
                    match = re.match(r"^page(?:Id)?[-_:]?(.+)$", working, flags=re.IGNORECASE)
                    if match:
                        candidate = match.group(1).strip()
                        if candidate:
                            page_id = candidate
                    else:
                        match = re.match(r"^([0-9a-f]{32})$", working, flags=re.IGNORECASE)
                        if match:
                            page_id = match.group(1)

    if page_index is not None and page_index < 0:
        page_index = None

    return page_index, page_id


def _resolve_markdown_target_page_index(
    target: tuple[Optional[int], Optional[str]],
    page_id_index: dict[str, int],
    total_pages: int,
) -> Optional[int]:
    page_index, page_id = target
    if page_index is not None and 0 <= page_index < total_pages:
        return page_index
    if page_id:
        normalized = str(page_id).strip().lower()
        return page_id_index.get(normalized)
    return None


def _collect_markdown_link_targets(
    markdown_text: str,
    source_index: int,
    page_id_index: dict[str, int],
    total_pages: int,
) -> list[int]:
    """Return ordered page indices referenced by Markdown content."""

    if not markdown_text or not markdown_text.strip():
        return []

    targets: list[int] = []
    seen: set[int] = set()

    def _handle_target(raw: object) -> None:
        target = _parse_markdown_internal_link(raw)
        target_idx = _resolve_markdown_target_page_index(target, page_id_index, total_pages)
        if target_idx is None or target_idx == source_index:
            return
        if target_idx in seen:
            return
        seen.add(target_idx)
        targets.append(target_idx)

    for match in _MARKDOWN_LINK_RE.finditer(markdown_text):
        _handle_target(match.group(1))
    for match in _HTML_SRC_RE.finditer(markdown_text):
        _handle_target(match.group(1))
    for match in _HTML_HREF_RE.finditer(markdown_text):
        _handle_target(match.group(1))

    return targets


def _normalize_resource_path(value: str) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip().replace("\\", "/")
    cleaned = re.sub(r"/+", "/", cleaned)
    cleaned = cleaned.lstrip("/")
    if cleaned in {"", ".", ".."}:
        return ""
    parts: list[str] = []
    for segment in cleaned.split("/"):
        if segment in {"", ".", ".."}:
            continue
        sanitized = secure_filename(segment)
        if not sanitized:
            continue
        parts.append(sanitized)
    return "/".join(parts)


def _collect_resource_usage(project: dict) -> dict[str, dict[str, object]]:
    """Map resource filenames to page/global references."""


    usage: dict[str, dict[str, object]] = {}
    pages = project.get("pages", [])
    if isinstance(pages, list):
        for idx, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            for res_name in page.get("resources", []) or []:
                if not isinstance(res_name, str):
                    continue
                normalized = _normalize_resource_path(res_name)
                if not normalized:
                    continue
                entry = usage.setdefault(normalized, {"pages": set(), "global": False})
                entry["pages"].add(idx)
    global_resources = project.get("resources", [])
    if isinstance(global_resources, list):
        for res_name in global_resources:
            if not isinstance(res_name, str):
                continue
            normalized = _normalize_resource_path(res_name)
            if not normalized:
                continue
            entry = usage.setdefault(normalized, {"pages": set(), "global": False})
            entry["global"] = True
    return usage


def _collect_attachment_references(project: dict) -> dict[str, list[str]]:
    """Scan project content and gather attachment usage contexts."""

    usage: dict[str, set[str]] = {}

    def _register(raw: object, context: str):
        cleaned = _normalize_link_target(raw)
        if not cleaned:
            return
        base = os.path.basename(cleaned)
        if not base:
            return
        usage.setdefault(base, set()).add(context)

    def _scan_text(text: object, context: str):
        if text is None:
            return
        content = str(text)
        if not content:
            return
        for match in _MARKDOWN_LINK_RE.finditer(content):
            _register(match.group(1), context)
        for match in _HTML_SRC_RE.finditer(content):
            _register(match.group(1), context)
        for match in _HTML_HREF_RE.finditer(content):
            _register(match.group(1), context)

    pages = project.get("pages", [])
    if isinstance(pages, list):
        for idx, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            _scan_text(page.get("notes", ""), f"第{idx + 1}页笔记")
            _scan_text(page.get("script", ""), f"第{idx + 1}页讲稿")
            for entry in page.get("bib", []) or []:
                if isinstance(entry, dict):
                    _scan_text(entry.get("entry", ""), f"第{idx + 1}页参考链接")
                else:
                    _scan_text(entry, f"第{idx + 1}页参考链接")

    md_template = project.get("markdownTemplate", {})
    if isinstance(md_template, dict):
        _scan_text(md_template.get("css"), "Markdown 模板 CSS")
        _scan_text(md_template.get("wrapperClass"), "Markdown 模板 wrapperClass")
        _scan_text(md_template.get("customHead"), "Markdown 模板自定义头部")
        _scan_text(md_template.get("exportCss"), "Markdown 模板导出 CSS")
        _scan_text(md_template.get("customBody"), "Markdown 模板自定义脚本")

    global_bib = project.get("bib", [])
    if isinstance(global_bib, list):
        for idx, entry in enumerate(global_bib):
            if isinstance(entry, dict):
                _scan_text(entry.get("entry", ""), f"全局参考链接 {idx + 1}")
            else:
                _scan_text(entry, f"全局参考链接 {idx + 1}")

    return {name: sorted(contexts) for name, contexts in usage.items()}




_DEFAULT_LEARNING_SYSTEM_MESSAGE = (
    "You are a knowledgeable bilingual tutor. "
    "Provide thorough, structured explanations in Markdown. "
    "Use math notation when appropriate, and include actionable study advice."
)


def _truncate_text(value: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    snippet = text[:limit].rstrip()
    return f"{snippet}\n\n…（内容较长，已截断）"


def _find_learning_prompt(prompts: list[dict], prompt_id: str) -> Optional[dict]:
    for prompt in prompts:
        if prompt.get("id") == prompt_id:
            return prompt
    return None


def _format_learning_user_message(template: str, content: str, context: str) -> str:
    base_template = template or "{content}\n\n上下文：\n{context}"
    safe_context = context or "（无额外上下文）"
    try:
        return base_template.format(content=content, context=safe_context)
    except (KeyError, IndexError, ValueError):
        # 容忍模板里出现未转义的花括号（如化学式 H_{2}O），回退到简单替换。
        fallback = base_template.replace("{content}", content).replace("{context}", safe_context)
        if fallback == base_template:
            fallback = f"{base_template}\n\n---\n{content}\n\n上下文：\n{safe_context}"
        return fallback


def _normalize_temp_prompt_template(template: str) -> str:
    """确保临时提示词里能带上学习内容和上下文占位符。"""

    cleaned = (template or "").strip()
    if not cleaned:
        return ""
    has_content = "{content}" in cleaned
    has_context = "{context}" in cleaned
    if has_content and has_context:
        return cleaned
    suffix_parts: list[str] = []
    if not has_content:
        suffix_parts.append("学习内容：\n{content}")
    if not has_context:
        suffix_parts.append("上下文：\n{context}")
    if suffix_parts:
        suffix = "\n\n".join(suffix_parts)
        cleaned = f"{cleaned}\n\n{suffix}"
    return cleaned


def _extract_json_object(text: str) -> dict:
    """尽量从模型输出中解析出 JSON 对象。"""

    if not text:
        return {}

    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        snippet = match.group(0)
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_reference_link(ref: str, link: Optional[str], doi: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """返回规范化后的链接和 DOI。"""

    found_doi = doi
    if not found_doi:
        match = _DOI_PATTERN.search(ref)
        if match:
            found_doi = match.group(0).strip().rstrip('.')

    normalized_link = link.strip() if link else ""
    if not normalized_link and _DOI_PATTERN.match(ref):
        normalized_link = f"https://doi.org/{ref.strip()}"
    if not normalized_link and ref.lower().startswith("http"):
        normalized_link = ref
    if not normalized_link and found_doi:
        normalized_link = f"https://doi.org/{found_doi}"

    return normalized_link or None, found_doi


_SEARCH_FIELD_LABELS = {
    "notes": "Markdown 正文",
    "script": "讲稿",
}


# 继续为蓝图注册后续路由。注意不要在此重新实例化蓝图，否则前面注册的路由会丢失。
@bp.route("/learn/config", methods=["GET"])
def learn_config():
    _, package, _, error = _require_workspace_project_response()
    if error:
        return error
    prompts, _ = _merge_learning_prompts(package)
    return api_success({"prompts": prompts})


@bp.route("/learn/prompts", methods=["POST"])
def learn_create_prompt():
    data = request.json or {}
    name = str(data.get("name") or "").strip()
    template = str(data.get("template") or "").strip()
    if not name or not template:
        return api_error("name 和 template 必填", 400)
    description = str(data.get("description") or "").strip()
    system_text = str(data.get("system") or "").strip()

    _, package, _, error = _require_workspace_project_response()
    if error:
        return error

    prompt_id = f"custom_{uuid.uuid4().hex[:12]}"
    entry = {
        "id": prompt_id,
        "name": name,
        "template": template,
        "description": description,
        "system": system_text,
        "source": "custom",
    }
    package.save_learning_prompt_entry(entry, removed=False)
    prompts, _ = _merge_learning_prompts(package)
    return api_success({"prompts": prompts, "createdId": prompt_id})


@bp.route("/learn/prompts/<prompt_id>", methods=["PUT"])
def learn_update_prompt(prompt_id: str):
    data = request.json or {}
    prompt_id = str(prompt_id or "").strip()
    if not prompt_id:
        return api_error("prompt_id 无效", 400)

    _, package, _, error = _require_workspace_project_response()
    if error:
        return error

    custom_prompts, overrides, _ = _list_workspace_learning_prompts(package)
    target = None
    for item in custom_prompts:
        if item.get("id") == prompt_id:
            target = item
            break
    if not target:
        target = overrides.get(prompt_id)
    source = "custom" if target and target.get("source") == "custom" else "override"
    updated = dict(target or {"id": prompt_id, "source": source})
    if data.get("name"):
        updated["name"] = str(data["name"]).strip()
    if data.get("template"):
        template_value = str(data["template"]).strip()
        if not template_value:
            return api_error("template 不能为空", 400)
        updated["template"] = template_value
    if "description" in data:
        desc_val = str(data.get("description") or "").strip()
        if desc_val:
            updated["description"] = desc_val
        else:
            updated.pop("description", None)
    if "system" in data:
        sys_val = str(data.get("system") or "").strip()
        if sys_val:
            updated["system"] = sys_val
        else:
            updated.pop("system", None)
    package.save_learning_prompt_entry(updated, removed=False)
    prompts, _ = _merge_learning_prompts(package)
    return api_success({"prompts": prompts})


@bp.route("/learn/prompts/<prompt_id>", methods=["DELETE"])
def learn_delete_prompt(prompt_id: str):
    prompt_id = str(prompt_id or "").strip()
    if not prompt_id:
        return api_error("prompt_id 无效", 400)

    _, package, _, error = _require_workspace_project_response()
    if error:
        return error

    custom_prompts, overrides, _ = _list_workspace_learning_prompts(package)
    is_custom = any(item.get("id") == prompt_id and item.get("source") == "custom" for item in custom_prompts)
    if is_custom:
        package.delete_learning_prompt_entry(prompt_id)
    else:
        package.mark_learning_prompt_removed(prompt_id, True)
    prompts, _ = _merge_learning_prompts(package)
    return api_success({"prompts": prompts})


@bp.route("/learn/query", methods=["POST"])
def learn_query():
    data = request.json or {}
    content = str(data.get("content") or "").strip()
    if not content:
        return api_error("学习内容不能为空", 400)
    context = str(data.get("context") or "").strip()
    prompt_id = str(data.get("promptId") or "").strip()
    prompt_name = str(data.get("promptName") or "").strip()
    temp_template_raw = str(data.get("tempPromptTemplate") or data.get("tempPrompt") or "").strip()
    temp_prompt_name = str(data.get("tempPromptName") or "").strip()
    temp_system_prompt = str(data.get("tempSystemPrompt") or "").strip()

    _, package, project_for_llm, error = _require_workspace_project_response()
    if error:
        return error
    prompts, _ = _merge_learning_prompts(package)

    template = (
        "以下是需要学习或解析的内容，请用结构化 Markdown 给出详细讲解与建议：\n"
        "{content}\n\n上下文信息：\n{context}"
    )
    system_text = _DEFAULT_LEARNING_SYSTEM_MESSAGE

    if temp_template_raw:
        prompt_id = "__temp__"
        template = _normalize_temp_prompt_template(temp_template_raw)
        prompt_name = temp_prompt_name or prompt_name or _truncate_text(temp_template_raw, 36) or "临时提示词"
        if temp_system_prompt:
            system_text = temp_system_prompt
    elif prompt_id and prompt_id not in {"__raw__", "__temp__"}:
        prompt = _find_learning_prompt(prompts, prompt_id)
        if not prompt:
            return api_error("提示词不存在", 404)
        prompt_name = prompt.get("name", prompt_id)
        system_text = prompt.get("system") or system_text
        template = prompt.get("template") or template
    else:
        prompt_id = "__temp__"
        if not prompt_name:
            prompt_name = temp_prompt_name or "临时提示词"

    truncated_content = _truncate_text(content, 4000)
    truncated_context = _truncate_text(context, 3000) or "（无额外上下文）"
    user_prompt = _format_learning_user_message(template, truncated_content, truncated_context)

    llm_config, headers = _resolve_llm_for_request(data, project=project_for_llm, usage="chat")
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)
    model_name = llm_config.get("model")
    if not model_name:
        return api_error("未配置可用的聊天模型", 500)

    try:
        resp = requests.post(
            llm_config["endpoint"],
            headers=headers,
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.4,
            },
            timeout=_resolve_llm_timeout(llm_config, 60),
        )
    except Exception as exc:  # pragma: no cover
        return api_error(str(exc), 500)

    if resp.status_code != 200:
        provider_label = llm_config.get("label") or llm_config.get("id") or "LLM"
        return api_error(f"{provider_label} API错误: {resp.text}", 500)

    try:
        result = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:  # pragma: no cover
        return api_error(f"解析 OpenAI 响应失败: {exc}", 500)

    return api_success({
        "result": result,
        "promptId": prompt_id,
        "promptName": prompt_name,
    })


@bp.route("/learn/record", methods=["POST"])
def learn_record():
    data = request.json or {}
    content = str(data.get("content") or "").strip()
    output = str(data.get("output") or "").strip()
    if not content or not output:
        return api_error("content 和 output 必填", 400)

    prompt_name = str(data.get("promptName") or "").strip() or "临时提示词"
    prompt_id = str(data.get("promptId") or "").strip()
    context = str(data.get("context") or "").strip()
    method = str(data.get("method") or data.get("learningMethod") or "").strip()
    category = str(data.get("category") or data.get("classification") or "").strip()
    favorite_raw = data.get("favorite")
    review_payload = data.get("review")
    if isinstance(favorite_raw, str):
        favorite = favorite_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        favorite = bool(favorite_raw)

    _, package, _, error = _require_workspace_project_response()
    if error:
        return error

    existing_records = package.list_learning_records()
    target_id = None
    for record in existing_records:
        if record.get("input") != content:
            continue
        record_prompt_id = str(record.get("promptId") or "").strip()
        record_prompt_name = str(record.get("promptName") or "").strip()
        if (prompt_id and record_prompt_id == prompt_id) or (not prompt_id and record_prompt_name == prompt_name):
            target_id = record.get("id")
            break

    saved = package.save_learning_record_entry(
        {
            "id": target_id,
            "input": content,
            "context": context or None,
            "promptId": prompt_id,
            "promptName": prompt_name,
            "output": output,
            "method": method,
            "category": category,
            "favorite": favorite,
            "savedAt": time.time(),
            "review": review_payload if isinstance(review_payload, dict) else None,
        }
    )
    return api_success({"savedAt": saved.get("savedAt"), "recordId": saved.get("id")})


def _parse_bool_flag(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, str):
        val = value.strip().lower()
        if val in {"", "auto"}:
            return None
        return val in {"1", "true", "yes", "on"}
    return bool(value)


@bp.route("/learn/records", methods=["GET"])
def learn_list_records():
    _, package, _, error = _require_workspace_project_response()
    if error:
        return error
    category_filter = str(request.args.get("category") or "").strip()
    category_query = str(request.args.get("categoryQuery") or "").strip().lower()
    query = str(request.args.get("q") or "").strip().lower()
    favorite_flag = _parse_bool_flag(request.args.get("favorite"))
    records = package.list_learning_records()
    collected_categories: set[str] = set()
    filtered: list[dict] = []
    for rec in records:
        category = (rec.get("category") or "").strip()
        if category:
            collected_categories.add(category)
        if category_filter and category != category_filter:
            continue
        if category_query and category_query not in category.lower():
            continue
        if favorite_flag is not None and bool(rec.get("favorite")) != favorite_flag:
            continue
        if query:
            combined = " ".join(
                str(part or "")
                for part in (
                    rec.get("input"),
                    rec.get("context"),
                    rec.get("output"),
                    rec.get("promptName"),
                    rec.get("method"),
                    rec.get("category"),
                )
            ).lower()
            if query not in combined:
                continue
        filtered.append(rec)
    return api_success(
        {
            "records": filtered,
            "categories": sorted(collected_categories),
        }
    )


@bp.route("/learn/records/<record_id>", methods=["PATCH", "DELETE"])
def learn_update_or_delete_record(record_id: str):
    record_id = str(record_id or "").strip()
    if not record_id:
        return api_error("record_id 无效", 400)
    _, package, _, error = _require_workspace_project_response()
    if error:
        return error
    if request.method == "DELETE":
        deleted = package.delete_learning_record_entry(record_id)
        if not deleted:
            return api_error("记录不存在", 404)
        return api_success({})
    data = request.json or {}
    payload: dict[str, Any] = {}
    if "favorite" in data:
        flag = _parse_bool_flag(data.get("favorite"))
        if flag is not None:
            payload["favorite"] = flag
    if "method" in data:
        payload["method"] = data.get("method")
    if "category" in data:
        payload["category"] = data.get("category")
    if "input" in data:
        payload["input"] = data.get("input")
    if "context" in data:
        payload["context"] = data.get("context")
    if "output" in data:
        payload["output"] = data.get("output")
    review_payload = data.get("review")
    review_note = data.get("reviewNote")
    review_effect = data.get("reviewEffect")
    if review_payload is not None or review_note is not None or review_effect is not None:
        base_review: dict[str, Any] = {}
        if isinstance(review_payload, dict):
            base_review = dict(review_payload)
        else:
            existing = package.get_learning_record_entry(record_id)
            if existing and isinstance(existing.get("review"), dict):
                base_review = dict(existing["review"])
        if review_note is not None:
            base_review["note"] = str(review_note or "").strip()
        if review_effect is not None:
            try:
                base_review["effect"] = int(review_effect)
            except (TypeError, ValueError):
                base_review["effect"] = review_effect
        payload["review"] = base_review
    if not payload:
        return api_error("没有可更新的字段", 400)
    updated = package.update_learning_record_entry(record_id, payload)
    if not updated:
        return api_error("记录不存在", 404)
    return api_success({"record": updated})


@bp.route("/export_learn_project", methods=["GET"])
def export_learning_records():
    """导出学习助手的记录/配置文件（YAML，仅作备份）。"""

    _, package, project, error = _require_workspace_project_response()
    if error:
        return error
    payload = _export_learning_payload(package)
    yaml_payload = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    download_name = f"{_workspace_project_label(package, project)}_learning_records.yaml"
    return send_file(
        io.BytesIO(yaml_payload.encode("utf-8")),
        mimetype="application/x-yaml",
        as_attachment=True,
        download_name=download_name,
    )


@bp.route("/export_project_bundle", methods=["GET"])
def export_project_bundle():
    """导出当前工作区的 `.benben` 文件。"""

    _, package, project, error = _require_workspace_project_response()
    if error:
        return error
    include_code = bool(_parse_bool_flag(request.args.get("include_code")))
    if include_code:
        return api_error("工作区便携包功能已下线，仅支持导出 .benben 工作区", 410)
    project_label = _workspace_project_label(package, project)
    safe_label = secure_filename(project_label) or "workspace"
    try:
        snapshot_path, temp_dir = _create_workspace_snapshot(package, safe_label)
    except Exception as exc:
        return api_error(f"导出失败：{exc}", 500)

    @after_this_request
    def _cleanup(response):
        shutil.rmtree(temp_dir, ignore_errors=True)
        return response

    download_name = f"{safe_label}.benben"
    mimetype = "application/octet-stream"
    file_path = snapshot_path

    return send_file(
        str(file_path),
        mimetype=mimetype,
        as_attachment=True,
        download_name=download_name,
    )


@bp.route("/workspaces", methods=["GET"])
def api_list_workspaces():
    return jsonify({"workspaces": list_workspaces()})


@bp.route("/workspaces/discover", methods=["GET"])
def api_discover_local_workspaces():
    limit_param = request.args.get("limit")
    limit = 200
    if limit_param:
        try:
            limit_value = int(limit_param)
            limit = max(10, min(limit_value, 1000))
        except ValueError:
            pass
    try:
        payload = discover_local_workspaces(None, recursive=True, limit=limit)
    except Exception as exc:
        return api_error(str(exc), 400)
    return jsonify(payload)


@bp.route("/workspaces/open", methods=["POST"])
def api_open_workspace():
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return api_error("path 必填", 400)
    try:
        handle = open_local_workspace(path)
    except FileNotFoundError:
        return api_error("文件不存在", 404)
    except Exception as exc:
        return api_error(str(exc), 500)
    return api_success({"workspace": handle.workspace_id, "info": handle.to_dict()})


@bp.route("/workspaces/create", methods=["POST"])
def api_create_workspace():
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return api_error("path 必填", 400)
    project_name = (data.get("name") or "").strip() or Path(path).stem
    try:
        handle = create_local_workspace(path, project_name)
    except Exception as exc:
        return api_error(str(exc), 500)
    return api_success({"workspace": handle.workspace_id, "info": handle.to_dict()})


@bp.route("/workspaces/<workspace_id>", methods=["DELETE"])
def api_close_workspace(workspace_id: str):
    close_workspace(workspace_id)
    return api_success({"workspace": workspace_id})


@bp.route("/workspaces/<workspace_id>/project", methods=["GET"])
def api_workspace_project(workspace_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        package = get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    payload = package.export_project()
    if not isinstance(payload, dict):
        payload = {}
    pages_mode = request.args.get("pages", "").strip().lower()
    if pages_mode == "meta":
        payload["pages"] = package.list_page_meta()
    elif pages_mode in {"none", "meta_only", "metaonly"}:
        payload["pages"] = []
    payload["locked"] = handle.locked
    payload["unlocked"] = handle.unlocked
    return jsonify(payload)


@bp.route("/workspaces/<workspace_id>/project/meta", methods=["GET"])
def api_workspace_project_meta(workspace_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        package = get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    meta = package.get_project_meta()
    meta["locked"] = handle.locked
    meta["unlocked"] = handle.unlocked
    return jsonify(meta)


@bp.route("/workspaces/<workspace_id>/health", methods=["GET"])
def api_workspace_health(workspace_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        package = get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    db_path = Path(handle.local_path or package.path)
    wal_path = Path(f"{db_path}-wal")
    shm_path = Path(f"{db_path}-shm")
    cache_dir = _workspace_cache_dir(workspace_id)
    payload = {
        "dbSize": _safe_path_size(db_path),
        "walSize": _safe_path_size(wal_path),
        "shmSize": _safe_path_size(shm_path),
        "attachments": len(package.list_assets("attachment", include_data=False)),
        "resources": len(package.list_assets("resource", include_data=False)),
        "cacheSize": _dir_size(cache_dir),
        "updatedAt": package.get_project_meta().get("updatedAt"),
        "locked": handle.locked,
        "unlocked": handle.unlocked,
    }
    return api_success(payload)


@bp.route("/workspaces/<workspace_id>/checkpoint", methods=["POST"])
def api_workspace_checkpoint(workspace_id: str):
    payload = request.get_json(silent=True) or {}
    probe_payload = payload.get("probe") if isinstance(payload, dict) else None
    if probe_payload is None and isinstance(payload, dict):
        probe_payload = {
            "pageId": payload.get("pageId") or payload.get("page_id"),
            "expectedUpdatedAt": payload.get("expectedUpdatedAt")
            or payload.get("projectUpdatedAt")
            or payload.get("updatedAt"),
        }
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    if handle.locked and not handle.unlocked:
        return _workspace_locked_response()
    package = handle.package
    try:
        checkpoint = package.checkpoint_and_verify(probe_payload if isinstance(probe_payload, dict) else None)
    except Exception as exc:
        return api_error(str(exc), 500)
    checkpoint["workspace"] = workspace_id
    checkpoint["mode"] = handle.mode
    checkpoint["locked"] = handle.locked
    checkpoint["unlocked"] = handle.unlocked
    return api_success({"checkpoint": checkpoint})


@bp.route("/workspaces/<workspace_id>/pages/meta", methods=["GET"])
def api_workspace_pages_meta(workspace_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        package = get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    entries = package.list_page_meta()
    meta = package.get_project_meta()
    meta["locked"] = handle.locked
    meta["unlocked"] = handle.unlocked
    return api_success({"pages": entries, "project": meta})


@bp.route("/workspaces/<workspace_id>/pages/<page_id>", methods=["GET"])
def api_workspace_page_detail(workspace_id: str, page_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        package = get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    payload = package.get_page_payload(page_id)
    if payload is None:
        return api_error("页面不存在", 404)
    meta = package.get_project_meta()
    meta["locked"] = handle.locked
    meta["unlocked"] = handle.unlocked
    return api_success({"page": payload, "updatedAt": meta.get("updatedAt")})


@bp.route("/workspaces/<workspace_id>/project", methods=["POST"])
def api_workspace_project_save(workspace_id: str):
    data = request.get_json(silent=True) or {}
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    if handle.locked and not handle.unlocked:
        return _workspace_locked_response()
    package = handle.package
    try:
        updated = package.save_project(data)
    except WorkspaceVersionConflict as exc:
        return api_error(str(exc), 409)
    except Exception as exc:
        return api_error(str(exc), 500)
    record_workspace_save(handle)
    if handle.mode == "cloud":
        try:
            sync_remote_workspace(handle)
            updated["remoteSynced"] = True
        except Exception as exc:
            updated["remoteSynced"] = False
            updated["remoteSyncError"] = str(exc)
    updated["locked"] = handle.locked
    updated["unlocked"] = handle.unlocked
    return api_success(updated)


@bp.route("/workspaces/<workspace_id>/pages/<page_id>", methods=["PATCH"])
def api_workspace_page_patch(workspace_id: str, page_id: str):
    data = request.get_json(silent=True) or {}
    data["pageId"] = page_id
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    if handle.locked and not handle.unlocked:
        return _workspace_locked_response()
    package = handle.package
    expected_ts = data.get("clientUpdatedAt") or data.get("expectedUpdatedAt")
    expected_value: float | None
    try:
        expected_value = float(expected_ts) if expected_ts is not None else None
    except (TypeError, ValueError):
        expected_value = None
    try:
        page_payload = package.save_page(data, expected_ts=expected_value)
    except WorkspaceVersionConflict as exc:
        return api_error(str(exc), 409)
    except KeyError:
        return api_error("页面不存在", 404)
    except Exception as exc:
        return api_error(str(exc), 500)
    record_workspace_save(handle)
    meta = package.get_project_meta()
    meta["locked"] = handle.locked
    meta["unlocked"] = handle.unlocked
    return api_success({"page": page_payload, "updatedAt": meta.get("updatedAt")})


@bp.route("/workspaces/<workspace_id>/archives", methods=["GET"])
def api_list_workspace_archives(workspace_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    archives = list_workspace_archives(handle)
    return jsonify(
        {
            "archives": archives,
            "archiveRoot": str(workspace_archive_dir(handle)),
            "workspace": handle.to_dict(),
        }
    )


@bp.route("/workspaces/<workspace_id>/archives", methods=["POST"])
def api_create_workspace_archive(workspace_id: str):
    payload = request.get_json(silent=True) or {}
    note = (payload.get("note") or payload.get("label") or "").strip()
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    try:
        record = create_workspace_archive(handle, note=note)
    except Exception as exc:
        return api_error(f"创建存档失败：{exc}", 500)
    return api_success(
        {
            "archive": record,
            "archiveRoot": str(workspace_archive_dir(handle)),
        }
    )


@bp.route("/workspaces/<workspace_id>/archives/<archive_id>", methods=["DELETE"])
def api_delete_workspace_archive(workspace_id: str, archive_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    try:
        delete_workspace_archive(handle, archive_id)
    except WorkspaceArchiveNotFoundError:
        return api_error("存档未找到", 404)
    except Exception as exc:
        return api_error(f"删除存档失败：{exc}", 500)
    return api_success({"archive": archive_id})


@bp.route("/workspaces/<workspace_id>/archives/<archive_id>/restore", methods=["POST"])
def api_restore_workspace_archive(workspace_id: str, archive_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    try:
        record = restore_workspace_archive(handle, archive_id)
    except WorkspaceArchiveNotFoundError:
        return api_error("存档未找到", 404)
    except Exception as exc:
        return api_error(f"恢复存档失败：{exc}", 500)
    return api_success(
        {
            "archive": record,
            "workspace": handle.to_dict(),
        }
    )


@bp.route("/workspaces/<workspace_id>/archives/<archive_id>/download", methods=["GET"])
def download_workspace_archive(workspace_id: str, archive_id: str):
    try:
        handle = get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    try:
        get_workspace_package(workspace_id)
    except WorkspaceLockedError:
        return _workspace_locked_response()
    archives = list_workspace_archives(handle)
    target = next((item for item in archives if item.get("id") == archive_id), None)
    if not target:
        return api_error("存档未找到", 404)
    archive_path = target.get("path") or ""
    if not archive_path or not Path(archive_path).exists():
        return api_error("存档文件缺失", 404)
    download_name = Path(target.get("filename") or archive_path).name
    return send_file(
        str(archive_path),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=download_name,
    )


@bp.route("/workspaces/<workspace_id>/password", methods=["POST"])
def api_workspace_password(workspace_id: str):
    data = request.get_json(silent=True) or {}
    new_password = (data.get("newPassword") or "").strip()
    current_password = (data.get("currentPassword") or "").strip() or None
    clear_flag = bool(data.get("clear"))
    try:
        if clear_flag:
            handle = clear_workspace_password(workspace_id, current_password=current_password)
            action = "cleared"
        else:
            if not new_password:
                return api_error("新密码不能为空", 400)
            handle = set_workspace_password(
                workspace_id,
                new_password,
                current_password=current_password,
            )
            action = "set"
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    except PermissionError as exc:
        return api_error(str(exc), 403)
    except ValueError as exc:
        return api_error(str(exc), 400)
    return api_success(
        {
            "workspace": workspace_id,
            "locked": handle.locked,
            "unlocked": handle.unlocked,
            "action": action,
        }
    )


@bp.route("/workspaces/<workspace_id>/unlock", methods=["POST"])
def api_workspace_unlock(workspace_id: str):
    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    try:
        handle = unlock_workspace(workspace_id, password)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    except ValueError as exc:
        return api_error(str(exc), 400)
    except PermissionError as exc:
        return api_error(str(exc), 403)
    return api_success(
        {
            "workspace": workspace_id,
            "locked": handle.locked,
            "unlocked": handle.unlocked,
        }
    )


@bp.route("/workspaces/<workspace_id>/assets/<scope>/<asset_id>/<path:filename>")
def download_workspace_asset(workspace_id: str, scope: str, asset_id: str, filename: str):
    try:
        package = get_workspace_package(workspace_id)
    except WorkspaceNotFoundError:
        return api_error("workspace 未找到", 404)
    asset = package.get_asset(asset_id, include_data=True)
    if not asset or asset.scope != scope or asset.data is None:
        return api_error("附件不存在", 404)
    mimetype = asset.mime or mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
    return send_file(
        io.BytesIO(asset.data),
        mimetype=mimetype,
        as_attachment=False,
        download_name=asset.name or filename,
    )


@bp.route("/workspaces/remote", methods=["GET"])
def api_list_remote_workspaces():
    if not oss_is_configured():
        return jsonify({"workspaces": [], "directories": [], "dir": "", "ossConfigured": False})
    try:
        payload = list_remote_workspaces()
    except Exception as exc:
        return api_error(str(exc), 500)
    payload = dict(payload or {})
    payload["ossConfigured"] = True
    return jsonify(payload)


@bp.route("/workspaces/remote/open", methods=["POST"])
def api_open_remote_workspace():
    if not oss_is_configured():
        return api_error("OSS 未配置", 400)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or data.get("key") or "").strip()
    if not name:
        return api_error("name 必填", 400)
    try:
        handle = open_remote_workspace(name)
    except FileNotFoundError:
        return api_error("远程工作区不存在", 404)
    except Exception as exc:
        return api_error(str(exc), 500)
    return api_success({"workspace": handle.workspace_id, "info": handle.to_dict()})


@bp.route("/workspaces/remote/create", methods=["POST"])
def api_create_remote_workspace():
    if not oss_is_configured():
        return api_error("OSS 未配置", 400)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    display_name = (data.get("displayName") or "").strip() or None
    if not name:
        return api_error("name 必填", 400)
    try:
        handle = create_remote_workspace(name, display_name)
    except FileExistsError:
        return api_error("远程工作区已存在", 409)
    except Exception as exc:
        return api_error(str(exc), 500)
    return api_success({"workspace": handle.workspace_id, "info": handle.to_dict()})

_LOCKED_ERROR = '项目已加密，请先解锁'


def _clean_text_for_excerpt(text: str) -> str:
    """粗略去除 Markdown 标记，生成更易读的摘要。"""

    if not text:
        return ""
    cleaned = re.sub(r"\[[^\]]*]\([^)]+\)", " ", text)
    cleaned = re.sub(r"`{1,3}[^`]*`{1,3}", " ", cleaned)
    cleaned = re.sub(r"[*_#>-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _build_excerpt(text: str, start: int, match_len: int, radius: int = 60) -> str:
    """根据命中位置构建简短摘要。"""

    if not text:
        return ""
    start = max(start, 0)
    if match_len <= 0:
        match_len = 1
    end = min(len(text), start + match_len)
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].replace('\n', ' ')
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if left > 0:
        snippet = '…' + snippet
    if right < len(text):
        snippet += '…'
    return snippet


def _extract_page_label(idx: int, page: dict) -> str:
    """尽量提取页面标题用于搜索结果展示。"""

    if not isinstance(page, dict):
        return f"第 {idx + 1} 页"

    notes = page.get("notes") or ""
    script = page.get("script") or ""

    note_title = re.search(r"^\s*#+\s+(.+)$", notes, flags=re.MULTILINE)
    if note_title and note_title.group(1).strip():
        return _clean_text_for_excerpt(note_title.group(1).strip()) or f"第 {idx + 1} 页"

    for raw in (notes, script):
        cleaned = _clean_text_for_excerpt(raw)
        if cleaned:
            return cleaned[:40]

    return f"第 {idx + 1} 页"


def _collect_notes_markdown_for_pages(pages: list, indices: list[int]) -> tuple[str, list[int]]:
    """Merge selected page notes into one Markdown document."""

    sections: list[str] = []
    included_pages: list[int] = []

    for idx in indices:
        if idx < 0 or idx >= len(pages):
            continue
        page = pages[idx]
        if isinstance(page, dict):
            notes_raw = page.get("notes", "") or ""
        else:  # pragma: no cover - defensive fallback for unexpected payloads
            notes_raw = str(page or "")

        normalized = str(notes_raw or "")
        if not normalized.strip():
            continue

        title = _extract_page_label(idx, page if isinstance(page, dict) else {})
        clean_title = re.sub(r"[\r\n]+", " ", title).strip()
        default_title = f"第 {idx + 1} 页"
        if clean_title == default_title:
            clean_title = ""

        if clean_title:
            sections.append(f"## {clean_title}\n\n{normalized.strip()}")
        else:
            sections.append(normalized.strip())
        included_pages.append(idx + 1)

    merged = "\n\n---\n\n".join(sections)
    return merged, included_pages


def _collect_related_page_indices(project: Optional[dict], start_idx: int) -> list[int]:
    """Return breadth-first related page indices from a start page."""

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not isinstance(pages, list) or not pages:
        return []
    if start_idx < 0 or start_idx >= len(pages):
        return []

    page_id_index = _build_page_id_index(pages)
    visited: set[int] = set()
    order: list[int] = []
    queue: deque[int] = deque([start_idx])

    while queue:
        idx = queue.popleft()
        if idx in visited:
            continue
        if idx < 0 or idx >= len(pages):
            continue
        visited.add(idx)
        order.append(idx)
        page = pages[idx]
        notes = page.get("notes", "") if isinstance(page, dict) else str(page or "")
        targets = _collect_markdown_link_targets(notes, idx, page_id_index, len(pages))
        for target_idx in targets:
            if target_idx not in visited:
                queue.append(target_idx)

    return order


def _collect_project_notes_markdown(project: Optional[dict]) -> tuple[str, list[int]]:
    """Merge all page notes into one Markdown document."""

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not isinstance(pages, list):
        pages = []
    indices = list(range(len(pages)))
    return _collect_notes_markdown_for_pages(pages, indices)


def _get_page_id_by_index(project: dict, page_idx: int) -> tuple[str | None, list[dict] | list]:
    """Return page_id and pages list for a given index."""

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not isinstance(pages, list):
        pages = []
    if page_idx < 0 or page_idx >= len(pages):
        return None, pages
    page = pages[page_idx]
    if isinstance(page, dict):
        pid = str(page.get("pageId") or page.get("id") or "").strip()
        return pid or None, pages
    return None, pages


def _request_tts_audio_bytes(
    normalized: str,
    llm_config: dict,
    headers: dict,
    tts_model: str,
):
    """调用 TTS API，将文本转换为语音字节。"""

    api_key = llm_config.get("api_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "未设置可用的 TTS API Key", 500

    endpoint = llm_config.get("tts_endpoint") or "https://api.openai.com/v1/audio/speech"
    request_headers = dict(headers or {})
    request_headers["Content-Type"] = "application/json"
    payload = {
        "model": tts_model or OPENAI_TTS_MODEL,
        "input": normalized,
        "voice": llm_config.get("tts_voice") or OPENAI_TTS_VOICE,
        "response_format": llm_config.get("tts_response_format") or OPENAI_TTS_RESPONSE_FORMAT,
        "speed": llm_config.get("tts_speed") or OPENAI_TTS_SPEED,
    }
    try:
        resp = requests.post(endpoint, headers=request_headers, json=payload, timeout=_resolve_llm_timeout(llm_config, 120))
    except Exception as exc:  # pragma: no cover - 网络错误
        return None, str(exc), 500

    if resp.status_code == 200:
        return resp.content, None, 200

    status = resp.status_code if resp.status_code >= 400 else 500
    provider_label = _llm_provider_label(llm_config)
    return None, f"{provider_label} TTS错误: {resp.text}", status


def _export_tts_audio_file(
    text: str,
    audio_folder: str,
    base_name: str,
    download_name: str,
    empty_error: str,
    llm_config: dict,
    headers: dict,
    tts_model: str,
):
    """将讲稿文本转换为语音文件并返回下载响应。"""

    normalized = str(text or "")
    if not normalized.strip():
        return jsonify({"success": False, "error": empty_error}), 400

    os.makedirs(audio_folder, exist_ok=True)
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    audio_path = os.path.join(audio_folder, f"{base_name}.mp3")
    hash_path = os.path.join(audio_folder, f"{base_name}.hash")

    if os.path.exists(audio_path) and os.path.exists(hash_path):
        try:
            with open(hash_path, "r", encoding="utf-8") as hf:
                if hf.read().strip() == content_hash:
                    return send_file(
                        audio_path,
                        mimetype="audio/mpeg",
                        as_attachment=True,
                        download_name=download_name,
                    )
        except Exception:
            pass

    audio_bytes, error_message, status_code = _request_tts_audio_bytes(normalized, llm_config, headers, tts_model)
    if not audio_bytes:
        return jsonify({"success": False, "error": error_message}), status_code

    try:
        with open(audio_path, "wb") as af:
            af.write(audio_bytes)
        with open(hash_path, "w", encoding="utf-8") as hf:
            hf.write(content_hash)
    except Exception as exc:
        print(f"写入音频失败: {exc}")

    return send_file(
        audio_path,
        mimetype="audio/mpeg",
        as_attachment=True,
        download_name=download_name,
    )


def _collect_search_matches(pages, query: str, limit: int = 50):
    """在项目页内检索关键词，返回按命中次数排序的结果。"""

    matches = []
    if not query:
        return matches

    lowered_query = query.lower()
    tokens = [token.lower() for token in re.split(r"\s+", query) if token.strip()]

    for idx, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        for field, label in _SEARCH_FIELD_LABELS.items():
            raw = page.get(field)
            if not raw:
                continue
            text = str(raw)
            lowered_text = text.lower()

            positions = []
            if lowered_query:
                start = 0
                while True:
                    found = lowered_text.find(lowered_query, start)
                    if found == -1:
                        break
                    positions.append(found)
                    increment = len(lowered_query) or 1
                    start = found + increment

            if not positions and tokens:
                if all(token in lowered_text for token in tokens):
                    first_token = tokens[0]
                    pos = lowered_text.find(first_token)
                    if pos != -1:
                        positions.append(pos)

            if not positions:
                continue

            page_label = _extract_page_label(idx, page)
            excerpt_source = _build_excerpt(text, positions[0], len(query))
            excerpt = _clean_text_for_excerpt(excerpt_source) or excerpt_source

            matches.append({
                "pageIndex": idx,
                "pageId": page.get("pageId"),
                "pageLabel": page_label,
                "field": field,
                "fieldLabel": label,
                "matchCount": len(positions),
                "excerpt": excerpt,
                "position": positions[0],
                "matchLength": max(len(query), 1),
            })

    matches.sort(key=lambda item: (-item["matchCount"], item["pageIndex"]))
    return matches[:limit]


@bp.route("/search", methods=["POST"])
def search_project():
    """检索当前工作区项目内容，返回命中摘要。"""

    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query") or payload.get("q") or "").strip()
    try:
        limit = int(payload.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    workspace_id, _, project, error = _require_workspace_project_response()
    if error:
        return error

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not isinstance(pages, list):
        pages = []

    matches = _collect_search_matches(pages, query, limit=limit)
    return api_success(
        {
            "workspace": workspace_id,
            "query": query,
            "matches": matches,
            "pageCount": len(pages),
        }
    )


@bp.route("/")
def index():
    """渲染主编辑器页面，提供初始 UI。"""

    portable_context = portable_workspace_context()
    return render_template(
        "editor.html",
        component_library=COMPONENT_LIBRARY,
        ui_theme=UI_THEME,
        llm_providers=list_llm_providers(),
        llm_default_state=get_default_llm_state(),
        default_workspace=portable_context.get("workspace"),
        portable_workspace_error=portable_context.get("error"),
    )


@bp.route("/export_audio", methods=["GET"])
def export_audio():
    """合并所有讲稿并调用 OpenAI TTS 生成整段音频。"""
    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error
    pages = project.get("pages", []) if isinstance(project, dict) else []
    scripts = [str(p.get("script", "")) for p in pages if isinstance(p, dict)]
    merged = "\n\n".join([n.strip() for n in scripts if n and n.strip()])
    audio_folder = _workspace_cache_dir(workspace_id) / "audio"
    llm_config, headers = _resolve_llm_for_request({}, project=project, usage="tts")
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)
    tts_model = _resolve_tts_model({}, llm_config, OPENAI_TTS_MODEL)
    return _export_tts_audio_file(
        merged,
        str(audio_folder),
        'all_notes',
        'all_notes.mp3',
        '没有可用的笔记内容',
        llm_config,
        headers,
        tts_model,
    )


@bp.route("/export_page_audio", methods=["GET"])
def export_page_audio():
    """为当前页讲稿生成语音并返回音频文件。"""
    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error

    page_number = request.args.get("page", type=int)
    if page_number is None:
        return jsonify({"success": False, "error": "缺少页码参数"}), 400

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not pages:
        return jsonify({"success": False, "error": "项目内没有幻灯片页"}), 404

    page_idx = page_number - 1
    if page_idx < 0 or page_idx >= len(pages):
        return jsonify({"success": False, "error": "指定页不存在"}), 404

    page = pages[page_idx]
    script = ""
    if isinstance(page, dict):
        script = str(page.get("script", ""))
    else:
        script = str(page)

    audio_folder = _workspace_cache_dir(workspace_id) / 'audio'
    base_name = f'page_{page_idx + 1}_script'
    download_name = f'{base_name}.mp3'
    llm_config, headers = _resolve_llm_for_request({}, project=project, usage="tts")
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)
    tts_model = _resolve_tts_model({}, llm_config, OPENAI_TTS_MODEL)
    return _export_tts_audio_file(
        script,
        str(audio_folder),
        base_name,
        download_name,
        '当前页没有讲稿内容',
        llm_config,
        headers,
        tts_model,
    )


@bp.route("/tts", methods=["POST"])
def generate_tts_preview():
    """根据传入文本生成实时语音预览，返回 Base64 音频。"""

    payload = request.get_json(silent=True) or {}
    raw_text = payload.get("text")
    normalized = str(raw_text or "")
    if not normalized.strip():
        return jsonify({"success": False, "error": "文本内容不能为空"}), 400

    workspace_id, package, locked = _resolve_workspace_context()
    if locked:
        return _workspace_locked_response()
    project = None
    if package:
        project = package.export_project()
    workspace_label = workspace_id or "global_preview"
    audio_folder = _workspace_cache_dir(workspace_label) / "audio"
    audio_folder.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    audio_path = audio_folder / f"tts_preview_{content_hash}.mp3"

    if audio_path.exists():
        try:
            audio_bytes = audio_path.read_bytes()
            encoded = base64.b64encode(audio_bytes).decode("ascii")
            return jsonify({"success": True, "audio": encoded})
        except Exception:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass

    llm_config, headers = _resolve_llm_for_request(payload, project=project, usage="tts")
    if not llm_config.get("api_key"):
        return api_error(_llm_missing_key_error(llm_config), 500)
    tts_model = _resolve_tts_model(payload, llm_config, OPENAI_TTS_MODEL)
    audio_bytes, error_message, status_code = _request_tts_audio_bytes(normalized, llm_config, headers, tts_model)
    if not audio_bytes:
        return jsonify({"success": False, "error": error_message}), status_code

    try:
        audio_path.write_bytes(audio_bytes)
    except Exception as exc:
        print(f"缓存TTS音频失败: {exc}")

    encoded = base64.b64encode(audio_bytes).decode("ascii")
    return jsonify({"success": True, "audio": encoded})


@bp.route("/recording/<int:page>", methods=["GET", "POST", "DELETE"])
def page_recording(page: int):
    """读写指定页的录播音频。"""

    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error

    page_idx = max(page - 1, 0)
    page_id, pages = _get_page_id_by_index(project, page_idx)
    if not pages or page_idx >= len(pages):
        return jsonify({"success": False, "error": "指定页不存在"}), 404
    if not page_id:
        return jsonify({"success": False, "error": "页缺少 pageId"}), 400

    if request.method == "GET":
        found = package.get_page_recording(page_id)
        if not found:
            return jsonify({"success": False, "error": "当前页没有录播"}), 404
        mime, data, _updated = found
        return send_file(
            io.BytesIO(data),
            mimetype=mime or "audio/webm",
            as_attachment=False,
            download_name=f"page_{page}_recording.webm",
        )

    if request.method == "DELETE":
        package.delete_page_recording(page_id)
        return jsonify({"success": True})

    # POST: 保存录音
    data_bytes: bytes | None = None
    mime = request.headers.get("Content-Type", "audio/webm")
    if request.files:
        file = request.files.get("audio") or next(iter(request.files.values()), None)
        if file:
            data_bytes = file.read()
            mime = file.mimetype or mime
    if data_bytes is None:
        raw = request.get_data()
        data_bytes = raw if raw else None
    if not data_bytes:
        return jsonify({"success": False, "error": "没有收到录音数据"}), 400

    package.save_page_recording(page_id, mime or "audio/webm", data_bytes)
    return jsonify({"success": True})


@bp.route("/add_page", methods=["POST"])
def add_page():
    """在指定位置插入一页默认 Markdown 内容。"""

    payload = request.get_json(silent=True) or {}
    idx_param = payload.get("idx")
    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error
    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not isinstance(pages, list):
        pages = []
    try:
        idx = int(idx_param if idx_param is not None else len(pages))
    except (TypeError, ValueError):
        idx = len(pages)
    idx = max(0, min(idx, len(pages)))
    new_page = {
        "notes": "# 新页面\n\n在这里写 Markdown 内容。",
        "script": "",
        "bib": [],
        "resources": [],
        "pageId": f"page_{uuid.uuid4().hex[:8]}",
    }
    pages.insert(idx, new_page)
    package.save_pages(pages)
    return jsonify({"success": True, "pages": pages})


@bp.route("/export_page_notes", methods=["GET"])
def export_page_notes():
    """导出当前页的 Markdown 笔记。"""

    page_param = request.args.get("page", type=int)
    page_idx = max((page_param or 1) - 1, 0)

    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not pages or page_idx >= len(pages):
        return jsonify({"success": False, "error": "指定页不存在"}), 404

    page = pages[page_idx]
    notes = ""
    if isinstance(page, dict):
        notes = page.get("notes", "") or ""
    else:  # pragma: no cover - 容错兜底
        notes = str(page or "")

    if not notes.strip():
        return jsonify({"success": False, "error": "当前页没有笔记可导出"}), 400

    raw_flag = _parse_bool_flag(request.args.get("raw") or request.args.get("plain"))
    bundle_flag = _parse_bool_flag(request.args.get("bundle"))
    use_bundle = True
    if raw_flag is True or bundle_flag is False:
        use_bundle = False

    if not use_bundle:
        buffer = io.BytesIO(notes.encode("utf-8"))
        download_name = f"page_{page_idx + 1}_notes.md"
        return send_file(
            buffer,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=download_name,
        )

    project_name = _workspace_project_label(package, project)
    safe_project = secure_filename(project_name) or project_name or "project"
    md_name = f"page_{page_idx + 1}_notes.md"
    with _workspace_runtime_dirs(package) as paths:
        archive_path, bundle_dir = _build_markdown_bundle(
            notes,
            md_name,
            project_name,
            paths["attachments"],
            paths["resources"],
            attachment_map=paths.get("attachment_map"),
        )

    @after_this_request
    def _cleanup_bundle(response):
        try:
            shutil.rmtree(bundle_dir, ignore_errors=True)
        finally:
            try:
                os.remove(archive_path)
            except Exception:
                pass
        return response

    download_name = f"{safe_project}_page_{page_idx + 1}_notes_bundle.zip"
    return send_file(
        str(archive_path),
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )


@bp.route("/export_page_markdown_html", methods=["GET"])
def export_page_markdown_html():
    """导出当前页 Markdown 渲染后的 HTML（内联媒体）。"""

    page_param = request.args.get("page", type=int)
    page_idx = max((page_param or 1) - 1, 0)
    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not pages or page_idx >= len(pages):
        return jsonify({"success": False, "error": "指定页不存在"}), 404

    page = pages[page_idx]
    notes = ""
    if isinstance(page, dict):
        notes = page.get("notes", "") or ""
    else:  # pragma: no cover - 容错兜底
        notes = str(page or "")

    if not notes.strip():
        return jsonify({"success": False, "error": "当前页没有笔记可导出"}), 400

    template = _resolve_markdown_template(project)
    with _workspace_runtime_dirs(package) as paths:
        project_name = _workspace_project_label(package, project)
        html_output = _build_markdown_export_html(
            notes,
            template,
            project_name,
            paths["attachments"],
            paths["resources"],
            attachment_map=paths.get("attachment_map"),
        )

    buffer = io.BytesIO(html_output.encode("utf-8"))
    download_name = f"page_{page_idx + 1}_notes.html"
    return send_file(
        buffer,
        mimetype="text/html",
        as_attachment=True,
        download_name=download_name,
    )


@bp.route("/export_page_related_notes", methods=["GET"])
def export_page_related_notes():
    """导出当前页及相关页的 Markdown 笔记。"""

    page_param = request.args.get("page", type=int)
    page_idx = max((page_param or 1) - 1, 0)

    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not pages or page_idx >= len(pages):
        return jsonify({"success": False, "error": "指定页不存在"}), 404

    related_indices = _collect_related_page_indices(project, page_idx)
    merged_markdown, _included_pages = _collect_notes_markdown_for_pages(pages, related_indices)
    if not merged_markdown.strip():
        return jsonify({"success": False, "error": "当前页及相关页没有笔记可导出"}), 400

    raw_flag = _parse_bool_flag(request.args.get("raw") or request.args.get("plain"))
    bundle_flag = _parse_bool_flag(request.args.get("bundle"))
    use_bundle = True
    if raw_flag is True or bundle_flag is False:
        use_bundle = False

    if not use_bundle:
        buffer = io.BytesIO(merged_markdown.encode("utf-8"))
        download_name = f"page_{page_idx + 1}_related_notes.md"
        return send_file(
            buffer,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=download_name,
        )

    project_name = _workspace_project_label(package, project)
    safe_project = secure_filename(project_name) or project_name or "project"
    md_name = f"page_{page_idx + 1}_related_notes.md"
    with _workspace_runtime_dirs(package) as paths:
        archive_path, bundle_dir = _build_markdown_bundle(
            merged_markdown,
            md_name,
            project_name,
            paths["attachments"],
            paths["resources"],
            attachment_map=paths.get("attachment_map"),
        )

    @after_this_request
    def _cleanup_bundle(response):
        try:
            shutil.rmtree(bundle_dir, ignore_errors=True)
        finally:
            try:
                os.remove(archive_path)
            except Exception:
                pass
        return response

    download_name = f"{safe_project}_page_{page_idx + 1}_related_notes_bundle.zip"
    return send_file(
        str(archive_path),
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )


@bp.route("/export_page_related_notes_html", methods=["GET"])
def export_page_related_notes_html():
    """导出当前页及相关页的 Markdown 渲染 HTML（内联媒体）。"""

    page_param = request.args.get("page", type=int)
    page_idx = max((page_param or 1) - 1, 0)
    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error

    pages = project.get("pages", []) if isinstance(project, dict) else []
    if not pages or page_idx >= len(pages):
        return jsonify({"success": False, "error": "指定页不存在"}), 404

    related_indices = _collect_related_page_indices(project, page_idx)
    merged_markdown, _included_pages = _collect_notes_markdown_for_pages(pages, related_indices)
    if not merged_markdown.strip():
        return jsonify({"success": False, "error": "当前页及相关页没有笔记可导出"}), 400

    template = _resolve_markdown_template(project)
    with _workspace_runtime_dirs(package) as paths:
        project_name = _workspace_project_label(package, project)
        html_output = _build_markdown_export_html(
            merged_markdown,
            template,
            project_name,
            paths["attachments"],
            paths["resources"],
            attachment_map=paths.get("attachment_map"),
        )

    download_name = f"page_{page_idx + 1}_related_notes.html"
    return send_file(
        io.BytesIO(html_output.encode("utf-8")),
        mimetype="text/html",
        as_attachment=True,
        download_name=download_name,
    )


@bp.route("/export_notes", methods=["GET"])
def export_notes():
    """导出全部页面的 Markdown 笔记。"""

    _, package, project, error = _require_workspace_project_response()
    if error:
        return error

    merged_markdown, _included_pages = _collect_project_notes_markdown(project)
    if not merged_markdown.strip():
        return jsonify({"success": False, "error": "项目中没有可导出的笔记"}), 400

    raw_flag = _parse_bool_flag(request.args.get("raw") or request.args.get("plain"))
    bundle_flag = _parse_bool_flag(request.args.get("bundle"))
    use_bundle = True
    if raw_flag is True or bundle_flag is False:
        use_bundle = False

    project_label = _workspace_project_label(package, project)
    safe_label = secure_filename(project_label) or project_label or "notes"
    download_name = f"{safe_label}_notes.md"

    if not use_bundle:
        buffer = io.BytesIO(merged_markdown.encode("utf-8"))
        return send_file(
            buffer,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=download_name,
        )

    with _workspace_runtime_dirs(package) as paths:
        archive_path, bundle_dir = _build_markdown_bundle(
            merged_markdown,
            download_name,
            project_label,
            paths["attachments"],
            paths["resources"],
            attachment_map=paths.get("attachment_map"),
        )

    @after_this_request
    def _cleanup_bundle(response):
        try:
            shutil.rmtree(bundle_dir, ignore_errors=True)
        finally:
            try:
                os.remove(archive_path)
            except Exception:
                pass
        return response

    bundle_name = f"{safe_label}_notes_bundle.zip"
    return send_file(
        str(archive_path),
        mimetype="application/zip",
        as_attachment=True,
        download_name=bundle_name,
    )


@bp.route("/export_notes_html", methods=["GET"])
def export_notes_html():
    """导出全部页面的 Markdown 渲染 HTML（合并，内联媒体）。"""

    _, package, project, error = _require_workspace_project_response()
    if error:
        return error

    merged_markdown, _included_pages = _collect_project_notes_markdown(project)
    if not merged_markdown.strip():
        return jsonify({"success": False, "error": "项目中没有可导出的笔记"}), 400

    template = _resolve_markdown_template(project)
    with _workspace_runtime_dirs(package) as paths:
        project_name = _workspace_project_label(package, project)
        html_output = _build_markdown_export_html(
            merged_markdown,
            template,
            project_name,
            paths["attachments"],
            paths["resources"],
            attachment_map=paths.get("attachment_map"),
        )

    safe_label = secure_filename(project_name) or project_name or "notes"
    download_name = f"{safe_label}_notes.html"
    return send_file(
        io.BytesIO(html_output.encode("utf-8")),
        mimetype="text/html",
        as_attachment=True,
        download_name=download_name,
    )



@bp.route("/attachments/list")
def list_attachments():
    """返回项目附件清单及访问链接。"""

    workspace_id, package, locked = _resolve_workspace_context()
    if not workspace_id:
        return api_error("请先选择工作区后再管理附件", 400)
    if locked:
        return _workspace_locked_response()
    if not package:
        return api_error("workspace 未找到", 404)
    project_data = package.export_project()
    attachment_refs = _collect_attachment_references(project_data or {})
    assets = package.list_assets("attachment", include_data=False)
    files: list[dict[str, object]] = []
    oss_context = _workspace_oss_context(workspace_id, package)
    oss_configured = oss_is_configured()
    try:
        handle = get_workspace(workspace_id)
    except Exception:
        handle = None
    for asset in assets:
        payload = _workspace_asset_payload(workspace_id, asset, package, handle=handle)
        name = asset.name
        refs = attachment_refs.get(name, [])
        payload.update(
            {
                "refCount": len(refs),
                "references": refs,
            }
        )
        files.append(payload)
    unused = [item["name"] for item in files if item.get("refCount", 0) == 0]
    return api_success(
        {
            "files": files,
            "ossConfigured": oss_configured,
            "localPath": None,
            "workspace": workspace_id,
            "unused": unused,
        }
    )


@bp.route("/attachments/delete", methods=["POST"])
def delete_attachment():
    """验证路径后删除附件文件。"""

    data = request.get_json(silent=True) or request.form or {}
    rel = data.get('path') or data.get('name') or request.args.get('path')
    if not rel:
        return api_error('path required', 400)
    if '..' in rel or rel.startswith('/') or rel.startswith('\\'):
        return api_error('invalid path', 400)
    workspace_id, package, locked = _resolve_workspace_context()
    if not workspace_id:
        return api_error("请先选择工作区后再删除附件", 400)
    if locked:
        return _workspace_locked_response()
    if not package:
        return api_error("workspace 未找到", 404)
    project = package.export_project()
    attachment_name = os.path.basename(rel)
    refs_map = _collect_attachment_references(project or {})
    contexts = refs_map.get(attachment_name, [])
    if contexts:
        preview = contexts[:5]
        detail = '，'.join(preview)
        if len(contexts) > len(preview):
            detail += '，等'
        return api_error(f'附件仍被引用，涉及：{detail}', 409)
    asset = package.find_asset_by_name("attachment", attachment_name, include_data=False)
    if not asset:
        return api_error('file not found', 404)
    oss_context = _workspace_oss_context(workspace_id, package)
    remote_removed = _oss_delete_asset(
        workspace_id,
        package,
        asset=asset,
        context=oss_context,
    )
    package.delete_asset(asset.asset_id)
    context_handle = oss_context.get("handle") if isinstance(oss_context, dict) else None
    _sync_cloud_workspace_state(workspace_id, handle=context_handle)
    return api_success({"localRemoved": True, "remoteRemoved": remote_removed})


@bp.route("/attachments/rename", methods=["POST"])
def rename_attachment():
    """Rename an attachment locally and propagate to OSS if enabled."""

    data = request.get_json(silent=True) or request.form or {}
    old_name = data.get('oldName') or data.get('from') or data.get('old')
    new_name = data.get('newName') or data.get('to') or data.get('name')
    if not old_name or not new_name:
        return api_error('oldName and newName required', 400)
    if any(sep in old_name for sep in ('..', '/', '\\')):
        return api_error('invalid oldName', 400)

    new_name_sanitized = secure_filename(new_name)
    if not new_name_sanitized:
        return api_error('invalid newName', 400)
    workspace_id, package, error = _require_workspace_package_response()
    if error:
        return error
    asset = package.find_asset_by_name("attachment", old_name, include_data=False)
    if not asset:
        return api_error('file not found', 404)
    if asset.name == new_name_sanitized:
        url = _workspace_asset_url(workspace_id, asset)
        return api_success(
            {
                "name": asset.name,
                "localUrl": url,
                "ossStatus": None,
            }
        )
    existing = package.find_asset_by_name("attachment", new_name_sanitized, include_data=False)
    if existing:
        return api_error('target filename already exists', 409)
    oss_context = _workspace_oss_context(workspace_id, package)
    previous_name = asset.name
    updated = package.rename_asset(asset.asset_id, new_name_sanitized)
    if not updated:
        return api_error('file not found', 404)
    url = _workspace_asset_url(workspace_id, updated)
    oss_status: Optional[dict[str, object]] = None
    if oss_context:
        oss_status = {}
        removed = _oss_delete_asset(
            workspace_id,
            package,
            asset=asset,
            name=previous_name,
            scope="attachment",
            context=oss_context,
        )
        if not removed:
            oss_status["delete_error"] = "未能移除旧的 OSS 对象"
        fresh = package.get_asset(updated.asset_id, include_data=True) or updated
        oss_meta = _oss_sync_asset(
            workspace_id,
            package,
            fresh,
            context=oss_context,
        )
        if not oss_meta:
            oss_status["error"] = "OSS 上传失败"
        else:
            oss_status["uploaded"] = True
            oss_status["ossUrl"] = oss_meta.get("url")
        if not oss_status:
            oss_status = None
    payload = {
        "name": updated.name,
        "localUrl": url,
        "ossStatus": oss_status,
    }
    context_handle = oss_context.get("handle") if isinstance(oss_context, dict) else None
    _sync_cloud_workspace_state(workspace_id, handle=context_handle)
    return api_success(payload)

@bp.route("/upload_resource", methods=["POST"])
def upload_resource():
    """上传资源文件，可按需挂载到指定页面或全局。"""

    files = request.files.getlist('files[]') or request.files.getlist('files')
    if not files and 'file' in request.files:
        files = [request.files['file']]
    if not files:
        return jsonify({'success': False, 'error': 'No file part'}), 400

    scope_param = (request.form.get('scope') or request.args.get('scope') or '').strip().lower()
    page_raw = request.form.get('page') or request.args.get('page')
    try:
        requested_page_idx = int(page_raw) if page_raw is not None else None
    except Exception:
        requested_page_idx = None
    effective_scope = 'page' if scope_param == 'page' and requested_page_idx is not None else 'global'

    paths_hint = request.form.getlist('paths[]') or request.form.getlist('paths') or []

    workspace_id, package, project, error = _require_workspace_project_response()
    if error:
        return error
    pages = project.get('pages') if isinstance(project.get('pages'), list) else []
    store_local, store_oss = _parse_storage_choice()
    store_local, store_oss = _normalize_storage_choice(workspace_id, store_local, store_oss)
    try:
        handle = get_workspace(workspace_id)
    except Exception:
        handle = None
    oss_context = _workspace_oss_context(workspace_id, package) if store_oss else None

    def _ensure_page_resources(idx: int) -> list[str]:
        if not isinstance(pages, list) or not (0 <= idx < len(pages)) or not isinstance(pages[idx], dict):
            return []
        res_list = pages[idx].setdefault('resources', [])
        if not isinstance(res_list, list):
            res_list = pages[idx]['resources'] = []
        return res_list

    global_resources = project.get('resources', [])
    if not isinstance(global_resources, list):
        global_resources = []

    uploads: list[dict[str, object]] = []
    for idx, file_storage in enumerate(files):
        if not file_storage or file_storage.filename == '':
            continue
        local_pref = store_local
        raw_path = paths_hint[idx] if idx < len(paths_hint) else file_storage.filename
        normalized_hint = _normalize_resource_path(raw_path or file_storage.filename)
        if not normalized_hint:
            fallback_name = secure_filename(file_storage.filename or f'file_{idx}')
            normalized_hint = fallback_name or f'file_{idx}'
        parts = [secure_filename(part) for part in normalized_hint.split('/') if secure_filename(part)]
        if not parts:
            fallback = secure_filename(file_storage.filename or f'file_{idx}')
            if not fallback:
                continue
            parts = [fallback]
        rel_path = '/'.join(parts)
        data = file_storage.read()
        if not data:
            continue
        mime = file_storage.mimetype or mimetypes.guess_type(rel_path)[0]
        metadata = _asset_metadata_from_upload(file_storage, data)
        metadata["hasLocal"] = bool(local_pref)
        stored_data = data  # 保留数据，远程成功后再清理
        asset = package.save_or_replace_asset(
            name=rel_path,
            scope='resource',
            data=stored_data,
            mime=mime,
            metadata=metadata,
        )
        oss_meta = _oss_sync_asset(workspace_id, package, asset, data=data, context=oss_context) if oss_context else None
        if not local_pref and oss_meta:
            _clear_asset_local_data(package, asset, handle=handle, workspace_id=workspace_id)
        else:
            _update_asset_local_flag(package, asset, True)
            if not local_pref and not oss_meta:
                local_pref = True
        scope_for_file = effective_scope
        page_idx = requested_page_idx if scope_for_file == 'page' else None
        if scope_for_file == 'page' and page_idx is not None:
            res_list = _ensure_page_resources(page_idx)
            if rel_path not in res_list:
                res_list.append(rel_path)
        else:
            scope_for_file = 'global'
            if rel_path not in global_resources:
                global_resources.append(rel_path)
        url = _workspace_asset_url(workspace_id, asset, filename=os.path.basename(rel_path))
        oss_meta = _oss_sync_asset(workspace_id, package, asset, data=data, context=oss_context) if oss_context else None
        oss_url = oss_meta.get('url') if isinstance(oss_meta, dict) else None
        stub_url = _stub_oss_url(workspace_id, package, asset) if not oss_url else None
        preferred = oss_url or stub_url or url
        uploads.append(
            {
                'path': rel_path,
                'name': os.path.basename(rel_path),
                'scope': scope_for_file,
                'page': page_idx,
                'localUrl': url,
                'ossUrl': oss_url,
                'url': preferred,
            }
        )
    if not uploads:
        return jsonify({'success': False, 'error': 'No valid files'}), 400
    saved_project = package.save_project(
        {
            'pages': pages,
            'resources': global_resources,
        }
    )
    context_handle = oss_context.get("handle") if isinstance(oss_context, dict) else None
    _sync_cloud_workspace_state(workspace_id, handle=context_handle)
    return api_success(
        {
            'files': uploads,
            'scope': effective_scope,
            'page': requested_page_idx,
            'updatedAt': saved_project.get('updatedAt') if isinstance(saved_project, dict) else None,
        }
    )

@bp.route('/projects/<project_name>/resources/<path:filename>')
def project_resources(project_name: str, filename: str):
    """RESTful 访问指定项目资源文件。"""

    return api_error("资源访问接口已迁移到工作区模式", 410)


@bp.route('/resources/<path:filename>')
def serve_resource(filename):
    """兼容旧接口，通过查询参数解析项目名。"""

    return api_error("资源访问接口已迁移到工作区模式", 410)


@bp.route('/resources/rename', methods=['POST'])
def rename_resource():
    """重命名资源文件并同步更新引用及 OSS。"""

    data = request.get_json(silent=True) or request.form or {}
    raw_old = (
        data.get('oldPath')
        or data.get('oldName')
        or data.get('from')
        or data.get('old')
        or ''
    )
    raw_new = (
        data.get('newPath')
        or data.get('newName')
        or data.get('to')
        or data.get('name')
        or ''
    )
    old_value = str(raw_old).strip()
    new_value = str(raw_new).strip()
    if not old_value or not new_value:
        return api_error('oldPath and newPath required', 400)

    workspace_id = _workspace_id_from_request()
    if workspace_id:
        try:
            package = get_workspace_package(workspace_id)
        except WorkspaceNotFoundError:
            return api_error("workspace 未找到", 404)
        project = package.export_project()
        normalized_old = _normalize_resource_path(old_value)
        if not normalized_old:
            sanitized = secure_filename(old_value)
            if not sanitized:
                return api_error('invalid oldPath', 400)
            normalized_old = sanitized
        normalized_new = _normalize_resource_path(new_value)
        if not normalized_new:
            sanitized_new = secure_filename(new_value)
            if not sanitized_new:
                return api_error('invalid newPath', 400)
            parent_rel = os.path.dirname(normalized_old)
            normalized_new = '/'.join(filter(None, [parent_rel, sanitized_new]))
        asset = package.find_asset_by_name("resource", normalized_old, include_data=False)
        if not asset:
            return api_error('file not found', 404)
        existing = package.find_asset_by_name("resource", normalized_new, include_data=False)
        if existing:
            return api_error('target filename already exists', 409)

        def _rewrite_entries(container: list[str] | None) -> list[str] | None:
            if not isinstance(container, list):
                return container
            updated: list[str] = []
            for entry in container:
                if not isinstance(entry, str):
                    updated.append(entry)
                    continue
                normalized_entry = _normalize_resource_path(entry)
                if normalized_entry in {normalized_old, os.path.basename(normalized_old)}:
                    updated.append(normalized_new)
                else:
                    updated.append(entry)
            seen: set[str] = set()
            deduped: list[str] = []
            for item in updated:
                if isinstance(item, str):
                    marker = _normalize_resource_path(item) or item
                    if marker in seen:
                        continue
                    seen.add(marker)
                deduped.append(item)
            return deduped

        global_resources = project.get('resources')
        if isinstance(global_resources, list):
            project['resources'] = _rewrite_entries(global_resources)  # type: ignore[assignment]
        pages = project.get('pages')
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, dict) and isinstance(page.get('resources'), list):
                    page['resources'] = _rewrite_entries(page['resources'])  # type: ignore[assignment]

        oss_context = _workspace_oss_context(workspace_id, package)
        previous_name = asset.name
        updated_asset = package.rename_asset(asset.asset_id, normalized_new)
        saved_project = package.save_project(
            {
                'pages': project.get('pages', []),
                'resources': project.get('resources', []),
            }
        )
        url = _workspace_asset_url(workspace_id, updated_asset or asset, filename=os.path.basename(normalized_new))
        oss_status: Optional[dict[str, object]] = None
        if oss_context:
            oss_status = {}
            removed = _oss_delete_asset(
                workspace_id,
                package,
                asset=asset,
                name=previous_name,
                scope="resource",
                context=oss_context,
            )
            if not removed:
                oss_status["delete_error"] = "未能移除旧的 OSS 对象"
            fresh = package.get_asset((updated_asset or asset).asset_id, include_data=True) or updated_asset or asset
            oss_meta = _oss_sync_asset(
                workspace_id,
                package,
                fresh,
                context=oss_context,
            )
            if not oss_meta:
                oss_status["error"] = "OSS 上传失败"
            else:
                oss_status["uploaded"] = True
                oss_status["ossUrl"] = oss_meta.get("url")
            if not oss_status:
                oss_status = None
        payload = {
            'name': os.path.basename(normalized_new),
            'path': normalized_new,
            'localUrl': url,
            'ossStatus': oss_status,
            'updatedAt': saved_project.get('updatedAt') if isinstance(saved_project, dict) else None,
        }
        context_handle = oss_context.get("handle") if isinstance(oss_context, dict) else None
        _sync_cloud_workspace_state(workspace_id, handle=context_handle)
        return api_success(payload)

    return api_error('请先选择工作区后再重命名资源', 400)


@bp.route('/resources/delete', methods=['POST'])
def delete_resource():
    """删除资源文件并清理项目中的引用。"""

    data = request.get_json(silent=True) or request.form or {}
    raw = data.get('name') or data.get('path') or request.args.get('name') or request.args.get('path')
    if not raw:
        return api_error('name required', 400)
    raw = str(raw).strip()
    if not raw:
        return api_error('name required', 400)
    raw = raw.split('?', 1)[0]
    raw = raw.split('#', 1)[0]
    relative = raw.lstrip('/')
    if '..' in relative:
        return api_error('invalid name', 400)
    name = os.path.basename(relative)
    if not name or name in ('.', '..') or '/' in name or '\\' in name:
        return api_error('invalid name', 400)

    scope = str(data.get('scope') or '').strip().lower()
    page_idx_raw = data.get('page')
    try:
        page_idx = int(page_idx_raw) if page_idx_raw is not None else None
    except (TypeError, ValueError):
        page_idx = None
    workspace_id = _workspace_id_from_request()
    if workspace_id:
        try:
            package = get_workspace_package(workspace_id)
        except WorkspaceNotFoundError:
            return api_error("workspace 未找到", 404)
        project = package.export_project()
        normalized_name = _normalize_resource_path(relative) or secure_filename(relative)
        if not normalized_name:
            return api_error('invalid name', 400)
        base_name = os.path.basename(normalized_name)
        pages_removed: list[int] = []
        global_removed = False

        def matches_entry(entry: object) -> bool:
            if not isinstance(entry, str):
                return False
            candidate = _normalize_resource_path(entry) or entry
            return candidate in {normalized_name, base_name}

        if scope == 'page':
            if page_idx is None:
                return api_error('page required for scope=page', 400)
            pages = project.get('pages', [])
            if not isinstance(pages, list) or not (0 <= page_idx < len(pages)):
                return api_error('page out of range', 404)
            page_obj = pages[page_idx]
            if not isinstance(page_obj, dict):
                return api_error('page data invalid', 500)
            resources = page_obj.get('resources', [])
            if not isinstance(resources, list) or not any(matches_entry(r) for r in resources):
                return api_error('resource not associated with page', 404)
            page_obj['resources'] = [r for r in resources if not matches_entry(r)]
            pages_removed.append(page_idx)
        elif scope == 'global':
            resources = project.get('resources', [])
            if not isinstance(resources, list) or not any(matches_entry(r) for r in resources):
                return api_error('resource not in global scope', 404)
            project['resources'] = [r for r in resources if not matches_entry(r)]
            global_removed = True
        else:
            resources = project.get('resources', [])
            if isinstance(resources, list) and any(matches_entry(r) for r in resources):
                project['resources'] = [r for r in resources if not matches_entry(r)]
                global_removed = True
            pages = project.get('pages', [])
            if isinstance(pages, list):
                for idx, page in enumerate(pages):
                    if not isinstance(page, dict):
                        continue
                    res_list = page.get('resources', [])
                    if not isinstance(res_list, list) or not any(matches_entry(r) for r in res_list):
                        continue
                    page['resources'] = [r for r in res_list if not matches_entry(r)]
                    pages_removed.append(idx)

        saved_project = package.save_project(
            {
                'pages': project.get('pages', []),
                'resources': project.get('resources', []),
            }
        )
        updated_at = saved_project.get('updatedAt') if isinstance(saved_project, dict) else None
        usage_after = _collect_resource_usage(project)
        remaining = usage_after.get(normalized_name) or usage_after.get(base_name)
        payload = {
            'name': normalized_name,
            'scope': scope or 'all',
            'globalRemoved': global_removed,
            'pagesRemoved': [idx + 1 for idx in pages_removed],
            'updatedAt': updated_at,
        }
        payload['remoteRemoved'] = False
        if remaining:
            payload['fileRemoved'] = False
            payload['stillReferenced'] = {
                'pages': sorted(idx + 1 for idx in remaining['pages']),
                'global': bool(remaining['global']),
                'refCount': len(remaining['pages']) + (1 if remaining['global'] else 0),
            }
            _sync_cloud_workspace_state(workspace_id)
            return api_success(payload)
        asset = package.find_asset_by_name("resource", normalized_name, include_data=False)
        if not asset and base_name != normalized_name:
            asset = package.find_asset_by_name("resource", base_name, include_data=False)
        if asset:
            oss_context = _workspace_oss_context(workspace_id, package)
            payload['remoteRemoved'] = _oss_delete_asset(
                workspace_id,
                package,
                asset=asset,
                context=oss_context,
            )
            package.delete_asset(asset.asset_id)
            payload['fileRemoved'] = True
        else:
            payload['fileRemoved'] = False
        _sync_cloud_workspace_state(workspace_id)
        return api_success(payload)

    return api_error('请先选择工作区后再删除资源', 400)

@bp.route('/resources/list')
def list_resources():
    """列出全局或指定页面的资源，并标记文件是否存在。"""

    workspace_id = _workspace_id_from_request()
    page = request.args.get('page')
    try:
        page_idx = int(page) if page is not None else None
    except Exception:
        page_idx = None
    if workspace_id:
        try:
            package = get_workspace_package(workspace_id)
        except WorkspaceNotFoundError:
            return api_error("workspace 未找到", 404)
        project = package.export_project()
        names: list[str] = []
        page_id = None
        pages = project.get('pages', [])
        oss_context = _workspace_oss_context(workspace_id, package)
        oss_configured = oss_is_configured()
        if page_idx is not None and isinstance(pages, list) and 0 <= page_idx < len(pages):
            page_obj = pages[page_idx]
            if isinstance(page_obj, dict):
                res_list = page_obj.get('resources', [])
                if isinstance(res_list, list):
                    names = [str(name) for name in res_list if isinstance(name, str)]
                page_id = page_obj.get('pageId')
        else:
            res_list = project.get('resources', [])
            if isinstance(res_list, list):
                names = [str(name) for name in res_list if isinstance(name, str)]
        usage_map = _collect_resource_usage(project)
        assets = {asset.name: asset for asset in package.list_assets("resource", include_data=False)}
        files: list[dict[str, object]] = []
        for name in names:
            normalized = _normalize_resource_path(name) or secure_filename(name) or name
            base = os.path.basename(normalized)
            asset = assets.get(normalized) or assets.get(base)
            if asset:
                payload = _workspace_asset_payload(workspace_id, asset, package)
            else:
                payload = {
                    'name': base or normalized,
                    'path': normalized,
                    'preferredUrl': None,
                    'localUrl': None,
                    'ossUrl': None,
                    'assetId': None,
                    'size': 0,
                    'metadata': {},
                    'local': False,
                    'remote': False,
                    'location': 'missing',
                    'missing': True,
                }
            usage_entry = usage_map.get(normalized) or usage_map.get(base) or {'pages': set(), 'global': False}
            pages_used = usage_entry['pages'] if isinstance(usage_entry.get('pages'), set) else set()
            payload.update(
                {
                    'url': payload.get('preferredUrl'),
                    'exists': bool(payload.get('localUrl')),
                    'refCount': len(pages_used) + (1 if usage_entry.get('global') else 0),
                    'usedOnPages': sorted(idx + 1 for idx in pages_used),
                    'usedGlobally': bool(usage_entry.get('global')),
                    'otherPages': sorted(idx + 1 for idx in pages_used if page_idx is not None and idx != page_idx),
                }
            )
            files.append(payload)
        payload = {
            'files': files,
            'ossConfigured': oss_configured,
            'workspace': workspace_id,
        }
        if page_id:
            payload['pageId'] = str(page_id)
        return api_success(payload)

    return api_error('请先选择工作区后再查看资源列表', 400)


@bp.route('/templates/list', methods=['GET'])
def templates_list():
    """返回可用模板列表，供前端选择。"""

    try:
        return api_success({'templates': list_templates()})
    except Exception as exc:
        return api_error(str(exc), 500)
