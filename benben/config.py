"""项目级配置常量与初始化辅助函数。"""

import os
import textwrap

# 默认 Markdown 模板文件名，可根据需要在 temps 中新增不同方案
DEFAULT_MARKDOWN_TEMPLATE_FILENAME = "markdown_default.yaml"

# Markdown 预览默认样式配置
FALLBACK_MARKDOWN_TEMPLATE: dict[str, str] = {
    "css": textwrap.dedent(
        """
        :root {
          color-scheme: light;
        }
        .markdown-note {
          font-family: "Helvetica Neue", Arial, "PingFang SC", sans-serif;
          font-size: 16px;
          line-height: 1.65;
          color: #1f2933;
        }
        .markdown-note h1,
        .markdown-note h2,
        .markdown-note h3 {
          font-weight: 600;
          margin-top: 1.6em;
          margin-bottom: 0.6em;
          line-height: 1.3;
        }
        .markdown-note h1 {
          font-size: 2.1em;
        }
        .markdown-note h2 {
          font-size: 1.7em;
        }
        .markdown-note h3 {
          font-size: 1.35em;
        }
        .markdown-note p {
          margin-bottom: 0.9em;
        }
        .markdown-note ul,
        .markdown-note ol {
          padding-left: 1.4em;
          margin-bottom: 1em;
        }
        .markdown-note blockquote {
          border-left: 4px solid #8ea1c7;
          color: #4b5563;
          background: #f7f9fc;
          margin: 1.2em 0;
          padding: 0.8em 1.1em;
          border-radius: 0.25rem;
        }
        .markdown-note code {
          font-family: "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace;
          background: #f1f5f9;
          padding: 0.1em 0.35em;
          border-radius: 0.25rem;
          font-size: 0.95em;
        }
        .markdown-note pre code {
          display: block;
          padding: 0;
          background: transparent;
          font-size: 0.95em;
        }
        .markdown-note pre {
          background: #0f172a;
          color: #e2e8f0;
          padding: 1em;
          border-radius: 0.5rem;
          overflow-x: auto;
        }
        .markdown-note img {
          max-width: min(100%, 720px);
          height: auto;
          display: block;
          margin: 1.25rem auto;
          border-radius: 0.75rem;
          box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
          cursor: zoom-in;
          transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .markdown-note img:hover {
          transform: translateY(-2px) scale(1.01);
          box-shadow: 0 24px 55px rgba(15, 23, 42, 0.24);
        }
        .markdown-note img:focus {
          outline: 3px solid rgba(59, 130, 246, 0.45);
          outline-offset: 4px;
        }
        .markdown-note figure {
          margin: 1.5rem auto;
          text-align: center;
        }
        .markdown-note figcaption {
          margin-top: 0.75rem;
          font-size: 0.9rem;
          color: #6b7280;
        }
        .markdown-note .markdown-preview-table-wrapper {
          position: relative;
          margin: 1.25rem 0;
          border: 1px solid #c0ccf4;
          border-radius: 0.9rem;
          background: rgba(241, 244, 255, 0.94);
          overflow: auto;
          max-width: 100%;
          max-height: clamp(320px, 58vh, 640px);
          box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
          padding: 1.75rem 1rem 1.4rem;
        }
        .markdown-note .markdown-preview-table-wrapper table {
          width: 100%;
          min-width: 100%;
          border-collapse: collapse;
          background: rgba(235, 239, 255, 0.96);
          table-layout: auto;
        }
        .markdown-note .markdown-preview-table-wrapper caption {
          caption-side: top;
          text-align: left;
          font-weight: 600;
          margin-bottom: 0.75rem;
          color: #1f2937;
        }
        .markdown-note .markdown-preview-table-wrapper thead th {
          position: sticky;
          top: 0;
          z-index: 5;
          background: rgba(210, 219, 255, 0.98);
          color: #111827;
          box-shadow: inset 0 -1px 0 rgba(131, 146, 199, 0.45);
        }
        .markdown-note .markdown-preview-table-wrapper tbody tr:nth-child(odd) {
          background: rgba(206, 214, 255, 0.58);
        }
        .markdown-note .markdown-preview-table-wrapper th,
        .markdown-note .markdown-preview-table-wrapper td {
          border: 1px solid rgba(138, 151, 199, 0.45);
          padding: 0.6rem 0.75rem;
          text-align: left;
          vertical-align: middle;
          word-break: break-word;
          white-space: normal;
        }
        .markdown-note .markdown-table-expand-btn {
          position: absolute;
          top: 0.75rem;
          right: 0.75rem;
          z-index: 10;
          display: inline-flex;
          align-items: center;
          gap: 0.35rem;
          padding: 0.3rem 0.75rem;
          font-size: 0.8rem;
          font-weight: 600;
          background: rgba(99, 102, 241, 0.12);
          border: 1px solid rgba(99, 102, 241, 0.35);
          border-radius: 999px;
          color: #3730a3;
          cursor: pointer;
        }
        .markdown-note .markdown-table-expand-btn:hover,
        .markdown-note .markdown-table-expand-btn:focus {
          background: rgba(99, 102, 241, 0.22);
          border-color: rgba(67, 56, 202, 0.55);
          color: #1e1b4b;
          outline: none;
        }
        .markdown-note table {
          width: 100%;
          border-collapse: collapse;
          margin: 1.4em 0;
        }
        .markdown-note th,
        .markdown-note td {
          border: 1px solid #cbd5f5;
          padding: 0.65em 0.75em;
        }
        .markdown-note th {
          background: #e6ecfe;
          font-weight: 600;
        }
        .markdown-note hr {
          border: none;
          border-top: 1px solid #d8e3f8;
          margin: 2em 0;
        }
        .markdown-note .markdown-callout {
          position: relative;
          border-radius: 0.9rem;
          padding: 1.05rem 1.25rem;
          margin: 1.4rem 0;
          border: 1px solid rgba(99, 102, 241, 0.22);
          background: rgba(99, 102, 241, 0.06);
          box-shadow: 0 18px 42px rgba(15, 23, 42, 0.14);
        }
        .markdown-note .markdown-callout + .markdown-callout {
          margin-top: 1.15rem;
        }
        .markdown-note .markdown-callout-title {
          font-weight: 600;
          margin-bottom: 0.45rem;
          letter-spacing: 0.02em;
          color: #312e81;
        }
        .markdown-note .markdown-callout-body > :first-child {
          margin-top: 0;
        }
        .markdown-note .markdown-callout-body > :last-child {
          margin-bottom: 0;
        }
        .markdown-note .markdown-callout.info {
          border-color: rgba(59, 130, 246, 0.35);
          background: rgba(59, 130, 246, 0.1);
        }
        .markdown-note .markdown-callout.info .markdown-callout-title {
          color: #1d4ed8;
        }
        .markdown-note .markdown-callout.tip {
          border-color: rgba(16, 185, 129, 0.35);
          background: rgba(16, 185, 129, 0.1);
        }
        .markdown-note .markdown-callout.tip .markdown-callout-title {
          color: #047857;
        }
        .markdown-note .markdown-callout.warning {
          border-color: rgba(251, 191, 36, 0.55);
          background: rgba(251, 191, 36, 0.14);
        }
        .markdown-note .markdown-callout.warning .markdown-callout-title {
          color: #92400e;
        }
        body.theme-dark .markdown-note .markdown-callout {
          border-color: rgba(99, 102, 241, 0.35);
          background: rgba(15, 23, 42, 0.82);
          box-shadow: 0 24px 60px rgba(2, 6, 23, 0.55);
        }
        body.theme-dark .markdown-note .markdown-callout-title {
          color: #e0e7ff;
        }
        body.theme-dark .markdown-note .markdown-callout.info {
          border-color: rgba(96, 165, 250, 0.45);
          background: rgba(37, 99, 235, 0.24);
        }
        body.theme-dark .markdown-note .markdown-callout.tip {
          border-color: rgba(45, 212, 191, 0.45);
          background: rgba(16, 185, 129, 0.26);
        }
        body.theme-dark .markdown-note .markdown-callout.warning {
          border-color: rgba(251, 191, 36, 0.55);
          background: rgba(202, 138, 4, 0.32);
        }
        body.theme-dark .markdown-note .markdown-callout.warning .markdown-callout-title {
          color: #fde68a;
        }
        /* === 自建布局组件（与前端/导出保持一致） === */
        .markdown-note .markdown-img-grid {
          display: grid;
          gap: clamp(8px, 1vw, 14px);
          margin: 1.25rem 0;
          align-items: center;
        }
        .markdown-note .markdown-img-grid.two-col {
          grid-template-columns: repeat(2, minmax(0, 1fr));
          grid-auto-rows: minmax(180px, auto);
        }
        .markdown-note .markdown-img-grid.two-vertical {
          grid-template-columns: repeat(2, minmax(0, 1fr));
          grid-auto-rows: minmax(220px, 1fr);
        }
        .markdown-note .markdown-img-grid.four-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
          grid-auto-rows: minmax(180px, 1fr);
        }
        .markdown-note .markdown-img-grid.rail {
          display: grid;
          grid-auto-flow: column;
          grid-auto-columns: minmax(220px, 32vw);
          overflow-x: auto;
          gap: 12px;
          padding: 6px 4px;
          scroll-snap-type: x mandatory;
        }
        .markdown-note .markdown-img-grid img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          border-radius: 0.75rem;
          box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);
          scroll-snap-align: start;
        }
        .markdown-note .markdown-img-grid.four-grid img {
          aspect-ratio: 1 / 1;
        }
        .markdown-note .markdown-kpi {
          display: flex;
          gap: 14px;
          flex-wrap: wrap;
          margin: 1.1rem 0;
        }
        .markdown-note .markdown-kpi > * {
          flex: 1 1 180px;
          padding: 12px 14px;
          border-radius: 10px;
          background: #fff;
          box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
        }
        .markdown-note .markdown-cols {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
          gap: 16px;
          margin: 1.2rem 0;
        }
        .markdown-note .markdown-features {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 14px;
          margin: 1.2rem 0;
        }
        .markdown-note .markdown-cover {
          display: flex;
          align-items: center;
          justify-content: center;
          text-align: center;
          padding: 40px 18px;
          background: linear-gradient(135deg, rgba(99, 102, 241, 0.06), rgba(59, 130, 246, 0.08));
          border-radius: 16px;
        }
        .markdown-note .markdown-divider {
          text-align: center;
          padding: 14px 0;
        }
        .markdown-note .markdown-divider::before {
          content: "";
          display: block;
          height: 1px;
          background: rgba(31, 41, 55, 0.12);
          margin: 10px auto;
          max-width: 64%;
        }
        .markdown-note .markdown-banner {
          padding: 14px 16px;
          border-radius: 12px;
          background: linear-gradient(120deg, rgba(99, 102, 241, 0.14), rgba(37, 99, 235, 0.12));
          color: #111827;
          box-shadow: 0 14px 34px rgba(59, 130, 246, 0.18);
        }
        .markdown-note .markdown-notes {
          font-size: 0.95rem;
          color: #6b7280;
          font-style: italic;
          border-left: 3px solid rgba(0, 0, 0, 0.08);
          padding: 10px 12px;
          background: rgba(0, 0, 0, 0.02);
          border-radius: 0 10px 10px 0;
        }
        .markdown-note .markdown-code-split {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
          gap: 12px;
          align-items: start;
          margin: 1.2rem 0;
        }
        .markdown-note .markdown-qa {
          border: 1px solid rgba(17, 24, 39, 0.12);
          border-radius: 0.9rem;
          padding: 0.85rem 1rem;
          margin: 1.1rem 0;
          background: rgba(99, 102, 241, 0.05);
          box-shadow: 0 12px 28px rgba(15, 23, 42, 0.1);
        }
        .markdown-note .markdown-qa .markdown-qa-question,
        .markdown-note details.markdown-qa .markdown-qa-question {
          font-weight: 650;
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
        }
        .markdown-note .markdown-qa .markdown-qa-label {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 22px;
          height: 22px;
          margin-right: 8px;
          border-radius: 999px;
          background: rgba(99, 102, 241, 0.14);
          color: #1f2937;
          font-weight: 700;
          font-size: 0.85rem;
        }
        .markdown-note .markdown-qa .markdown-qa-answer > :first-child {
          margin-top: 0;
        }
        .markdown-note .markdown-qa .markdown-qa-answer > :last-child {
          margin-bottom: 0;
        }
        .markdown-note details.markdown-qa {
          border: 1px solid rgba(17, 24, 39, 0.12);
          border-radius: 0.9rem;
          padding: 0.65rem 0.9rem;
          margin: 1.1rem 0;
          background: rgba(99, 102, 241, 0.04);
          box-shadow: 0 12px 28px rgba(15, 23, 42, 0.1);
        }
        .markdown-note details.markdown-qa[open] {
          background: rgba(99, 102, 241, 0.07);
        }
        .markdown-note details.markdown-qa summary {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
          font-weight: 650;
          list-style: none;
        }
        .markdown-note details.markdown-qa summary::-webkit-details-marker {
          display: none;
        }
        .markdown-note details.markdown-qa .markdown-qa-toggle {
          margin-left: auto;
          font-size: 0.9rem;
          color: #4b5563;
        }
        .markdown-note details.markdown-qa .markdown-qa-answer {
          margin-top: 10px;
        }
        .markdown-note .markdown-media {
          margin: 1rem 0;
          border-radius: 0.9rem;
          background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(59, 130, 246, 0.06));
          padding: 0.85rem 1rem;
          box-shadow: 0 12px 30px rgba(15, 23, 42, 0.12);
        }
        .markdown-note .markdown-media audio,
        .markdown-note .markdown-media video {
          width: 100%;
          display: block;
          border-radius: 0.75rem;
          outline: none;
          background: #0b1224;
        }
        .markdown-note .markdown-media video {
          max-height: min(420px, 48vh);
          object-fit: contain;
        }
        .markdown-note .markdown-media .markdown-media-caption {
          margin-top: 0.6rem;
          font-size: 0.95rem;
          color: #4b5563;
        }
        """
    ).strip(),
    "wrapperClass": "markdown-note",
    "exportCss": "",
    "customHead": "",
    "customBody": "",
}

# OpenAI ChatCompletion / Embedding / TTS 相关配置（支持分用途 env）
OPENAI_API_BASE_URL = os.environ.get("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_CHAT_COMPLETIONS_MODEL = os.environ.get("LLM_CHAT_MODEL", os.environ.get("OPENAI_CHAT_MODEL", "gpt-5"))
OPENAI_CHAT_PATH = os.environ.get("LLM_CHAT_PATH", os.environ.get("OPENAI_CHAT_PATH", "/chat/completions"))
DEFAULT_EMBEDDING_MODEL = os.environ.get("LLM_EMBEDDING_MODEL", os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"))
DEFAULT_EMBEDDING_PATH = os.environ.get("LLM_EMBEDDING_PATH", "/embeddings")
DEFAULT_TTS_MODEL = os.environ.get("LLM_TTS_MODEL", os.environ.get("OPENAI_TTS_MODEL", "tts-1"))
DEFAULT_TTS_PATH = os.environ.get("LLM_TTS_PATH", "/audio/speech")
DEFAULT_CHAT_BASE_URL = os.environ.get("LLM_CHAT_BASE_URL", OPENAI_API_BASE_URL)
DEFAULT_EMBEDDING_BASE_URL = os.environ.get("LLM_EMBEDDING_BASE_URL", OPENAI_API_BASE_URL)
DEFAULT_TTS_BASE_URL = os.environ.get("LLM_TTS_BASE_URL", OPENAI_API_BASE_URL)

# ChatAnywhere ChatCompletion 相关配置（保持兼容但可被 LLM_* 覆盖）
CHATANYWHERE_API_BASE_URL = os.environ.get("CHAT_ANYWHERE_BASE_URL", "https://api.chatanywhere.tech/v1")
CHATANYWHERE_CHAT_PATH = os.environ.get("CHAT_ANYWHERE_CHAT_PATH", "/chat/completions")
CHATANYWHERE_DEFAULT_MODEL = os.environ.get("CHAT_ANYWHERE_MODEL", "gpt-5")
CHATANYWHERE_EMBEDDING_MODEL = os.environ.get("CHAT_ANYWHERE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
CHATANYWHERE_TTS_MODEL = os.environ.get("CHAT_ANYWHERE_TTS_MODEL", DEFAULT_TTS_MODEL)
CHATANYWHERE_EMBEDDING_PATH = os.environ.get("CHAT_ANYWHERE_EMBEDDING_PATH", DEFAULT_EMBEDDING_PATH)
CHATANYWHERE_TTS_PATH = os.environ.get("CHAT_ANYWHERE_TTS_PATH", DEFAULT_TTS_PATH)
CHATANYWHERE_EMBEDDING_BASE_URL = os.environ.get("CHAT_ANYWHERE_EMBEDDING_BASE_URL", CHATANYWHERE_API_BASE_URL)
CHATANYWHERE_TTS_BASE_URL = os.environ.get("CHAT_ANYWHERE_TTS_BASE_URL", CHATANYWHERE_API_BASE_URL)

MOCK_LLM_DEFAULT_MODEL = os.environ.get("MOCK_LLM_CHAT_MODEL", "gpt-5")

# 常见可用的 ChatCompletion/Embedding/TTS 模型清单，供前端下拉选择。
OPENAI_KNOWN_CHAT_MODELS: list[str] = [
    "gpt-5",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
    "o4-mini",
]

OPENAI_KNOWN_EMBEDDING_MODELS: list[str] = [
    "text-embedding-3-large",
    "text-embedding-3-small",
    "text-embedding-ada-002",
]

OPENAI_KNOWN_TTS_MODELS: list[str] = [
    "tts-1",
    "tts-1-hd",
]

CHATANYWHERE_KNOWN_CHAT_MODELS: list[str] = list(
    dict.fromkeys([CHATANYWHERE_DEFAULT_MODEL, *OPENAI_KNOWN_CHAT_MODELS])
)
CHATANYWHERE_KNOWN_EMBEDDING_MODELS: list[str] = list(
    dict.fromkeys([CHATANYWHERE_EMBEDDING_MODEL, *OPENAI_KNOWN_EMBEDDING_MODELS])
)
CHATANYWHERE_KNOWN_TTS_MODELS: list[str] = list(
    dict.fromkeys([CHATANYWHERE_TTS_MODEL, *OPENAI_KNOWN_TTS_MODELS])
)
MOCK_LLM_KNOWN_CHAT_MODELS: list[str] = list(dict.fromkeys([MOCK_LLM_DEFAULT_MODEL, *OPENAI_KNOWN_CHAT_MODELS]))
MOCK_LLM_KNOWN_EMBEDDING_MODELS: list[str] = list(
    dict.fromkeys(
        [
            os.environ.get("MOCK_LLM_EMBEDDING_MODEL", "text-embedding-3-large"),
            *OPENAI_KNOWN_EMBEDDING_MODELS,
        ]
    )
)
MOCK_LLM_KNOWN_TTS_MODELS: list[str] = list(
    dict.fromkeys(
        [
            os.environ.get("MOCK_LLM_TTS_MODEL", "tts-1"),
            *OPENAI_KNOWN_TTS_MODELS,
        ]
    )
)

# 通用 LLM 提供方注册表，便于统一管理聊天模型调用
LLM_PROVIDERS: dict[str, dict[str, object]] = {
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "base_url": DEFAULT_CHAT_BASE_URL,
        "chat_path": OPENAI_CHAT_PATH,
        "tts_path": DEFAULT_TTS_PATH,
        "embedding_path": DEFAULT_EMBEDDING_PATH,
        "embedding_base_url": DEFAULT_EMBEDDING_BASE_URL,
        "tts_base_url": DEFAULT_TTS_BASE_URL,
        "default_model": OPENAI_CHAT_COMPLETIONS_MODEL,
        "default_embedding_model": DEFAULT_EMBEDDING_MODEL,
        "default_tts_model": DEFAULT_TTS_MODEL,
        "models": OPENAI_KNOWN_CHAT_MODELS,
        "embedding_models": OPENAI_KNOWN_EMBEDDING_MODELS,
        "tts_models": OPENAI_KNOWN_TTS_MODELS,
        "api_key_env": "OPENAI_API_KEY",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "extra_headers": {},
        "timeout": 600,
    },
    "chatanywhere": {
        "id": "chatanywhere",
        "label": "ChatAnywhere",
        "base_url": CHATANYWHERE_API_BASE_URL,
        "chat_path": CHATANYWHERE_CHAT_PATH,
        "tts_path": CHATANYWHERE_TTS_PATH,
        "embedding_path": CHATANYWHERE_EMBEDDING_PATH,
        "embedding_base_url": CHATANYWHERE_EMBEDDING_BASE_URL,
        "tts_base_url": CHATANYWHERE_TTS_BASE_URL,
        "default_model": CHATANYWHERE_DEFAULT_MODEL,
        "default_embedding_model": CHATANYWHERE_EMBEDDING_MODEL,
        "default_tts_model": CHATANYWHERE_TTS_MODEL,
        "models": CHATANYWHERE_KNOWN_CHAT_MODELS,
        "embedding_models": CHATANYWHERE_KNOWN_EMBEDDING_MODELS,
        "tts_models": CHATANYWHERE_KNOWN_TTS_MODELS,
        "api_key_env": "CHAT_ANYWHERE_API_KEY",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "extra_headers": {},
        "timeout": 600,
    },
    # 兜底/占位 provider，避免前端下拉空列表（可改成你自己的代理）
    "mock-local": {
        "id": "mock-local",
        "label": "Mock Local",
        "base_url": os.environ.get("MOCK_LLM_BASE_URL", "http://localhost:8000/v1"),
        "chat_path": os.environ.get("MOCK_LLM_CHAT_PATH", "/chat/completions"),
        "embedding_path": os.environ.get("MOCK_LLM_EMBEDDING_PATH", "/embeddings"),
        "tts_path": os.environ.get("MOCK_LLM_TTS_PATH", "/audio/speech"),
        "embedding_base_url": os.environ.get("MOCK_LLM_EMBEDDING_BASE_URL", os.environ.get("MOCK_LLM_BASE_URL", "http://localhost:8000/v1")),
        "tts_base_url": os.environ.get("MOCK_LLM_TTS_BASE_URL", os.environ.get("MOCK_LLM_BASE_URL", "http://localhost:8000/v1")),
        "default_model": MOCK_LLM_DEFAULT_MODEL,
        "default_embedding_model": os.environ.get("MOCK_LLM_EMBEDDING_MODEL", "text-embedding-3-large"),
        "default_tts_model": os.environ.get("MOCK_LLM_TTS_MODEL", "tts-1"),
        "models": MOCK_LLM_KNOWN_CHAT_MODELS,
        "embedding_models": MOCK_LLM_KNOWN_EMBEDDING_MODELS,
        "tts_models": MOCK_LLM_KNOWN_TTS_MODELS,
        "api_key_env": os.environ.get("MOCK_LLM_API_KEY_ENV", "MOCK_LLM_API_KEY"),
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "extra_headers": {},
        "timeout": 600,
    },
}

_ENV_DEFAULT_PROVIDER = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
DEFAULT_LLM_PROVIDER = _ENV_DEFAULT_PROVIDER if _ENV_DEFAULT_PROVIDER in LLM_PROVIDERS else "openai"

# OpenAI 语音合成参数，可按需调整音色/格式/语速
OPENAI_TTS_MODEL = "tts-1"
OPENAI_TTS_VOICE = "alloy"
OPENAI_TTS_RESPONSE_FORMAT = "mp3"
OPENAI_TTS_SPEED = 1.0

# 不同优化场景对应的系统提示与用户模板
AI_PROMPTS = {
    "script": {
        "system": "你是一个讲稿写作专家，服从我的指示，返回优化后的讲稿文本。",
        "template": (
            "你是一个讲稿写作专家。选择合适的演讲风格，可以进行高级感的幽默和帮助演讲者学习英语。\n"
            "优化对应的讲稿，使其表达更清晰、逻辑更流畅、适合演讲，内容不要脱离主题。\n"
            "你需要根据我的 Markdown 内容生成讲稿，正文如下：\n{markdown}\n\n"
            "如果没有特别说明，无论原始内容是什么语言，默认输出语言是英文 en。\n\n"
            "原始讲稿如下：\n{script}\n\n"
            "如果原始讲稿有内容，判断是我的要求还是讲稿内容，如果是内容，请返回优化后的讲稿文本。\n"
            "讲稿不带 Markdown 标记，可以附上一些表情包以及演讲技巧提示。\n"
        ),
    },
    "note": {
        "system": "你是一个笔记写作专家，返回优化后的笔记（Markdown）。",
        "template": (
            "你是一个 Markdown 笔记/摘要写作专家。\n"
            "生成或优化一份适合阅读和记录的笔记（Markdown 格式），保留要点、关键结论和联系。\n"
            "原始笔记如下：\n{markdown}\n\n"
            "“ # ”后面是 Markdown 的注释，也是我给你的一些指示要求。\n"
            "输出内容的语言应该和我的笔记原始文本保持一致。\n"
            "Markdown 输出需使用下方组件库中已经定义的语法与组件（含 ::: 自建块与可用的 HTML 模板），不要引入组件库之外的自定义语法。\n"
            "组件库清单如下：\n{component_library}\n"
            "只要输出笔记内容，不要输出任何多余的内容。\n"
        ),
    },
}

AI_BIB_PROMPT = {
    "system": (
        "你是一名资深研究助理。"
        "接收任何网页链接或 DOI，输出一个 JSON 对象，总结该资源的关键信息。"
        "JSON 字段必须包含 label(50字以内记忆名), note(1-2句核心要点),"
        " id(推荐的引用键，仅含字母数字或-), link(首选规范化URL),"
        " metadata(对象，包含作者数组authors、年份year、来源venue、doi、type等可用信息)。"
        " 若是学术论文请返回 metadata.doi、metadata.authors(最多5位作者全名)、metadata.year、metadata.venue。"
        " 如能生成引用条目，可放在 bibtex 字段。"
        " 严格返回单个 JSON 对象，不要额外解释。"
    ),
    "user": (
        "请分析以下引用或网页，生成记忆名与重点摘要。"
        " 如果这是 DOI 论文，请尽可能补充论文的详细信息。\n"
        "输入: {ref}"
    ),
}

LEARNING_ASSISTANT_DEFAULT_PROMPTS = [
    {
        "id": "sentence_en",
        "name": "句子英语学习",
        "description": "翻译并润色句子，同时补充语法与文化背景知识。",
        "system": (
            "You are an experienced bilingual English-Chinese tutor. "
            "Explain grammar, nuance, and background in Chinese where appropriate, "
            "but keep important terminology bilingual. Provide clear, structured output in Markdown, "
            "and include math notation when useful."
        ),
        "template": (
            "学习目标：针对以下句子进行英语学习，需包含翻译、语法结构解析、表达优化建议、相关文化或专业知识补充。\n"
            "主句内容：\n{content}\n\n"
            "可参考的上下文：\n{context}\n\n"
            "请输出以下部分：\n"
            "1. **翻译**：给出地道的中英文互译。\n"
            "2. **语法与结构解析**：逐句拆解，指出核心语法点和常见错误。\n"
            "3. **表达优化**：提供多种更自然或更正式的替换表达。\n"
            "4. **知识扩展**：补充与句子相关的背景知识、使用场景或学术信息。\n"
            "5. **练习建议**：给出巩固学习的练习或记忆方法。\n"
        ),
    },
    {
        "id": "word_en",
        "name": "单词英语学习",
        "description": "学习单词，包含词源、近反义词、例句与常识补充。",
        "system": (
            "You are an etymology-focused English vocabulary coach. "
            "Explain words with roots, affixes, synonyms, antonyms, usage notes, and memorable examples. "
            "Return Markdown with sections and bullet lists when helpful."
        ),
        "template": (
            "目标：全面学习以下词汇或短语。\n"
            "待学习词汇：\n{content}\n\n"
            "上下文（可选）：\n{context}\n\n"
            "请输出：\n"
            "1. **基本含义**（中英文）。\n"
            "2. **词根词缀与来源**，若无则说明。\n"
            "3. **词性与常见搭配**，至少给出 3 个例句，并附简短中文解释。\n"
            "4. **近义词 / 反义词对比**，指出差别和适用场景。\n"
            "5. **拓展知识**：与该词相关的文化、学科、专业常识或记忆技巧。\n"
        ),
    },
    {
        "id": "concept_new",
        "name": "新的知识概念",
        "description": "理解第一次遇到的概念，进行系统化拆解。",
        "system": (
            "You are a subject-matter expert and teacher. "
            "Break down new concepts for a curious learner with structured explanations, analogies, and practice suggestions."
        ),
        "template": (
            "请帮助学习者理解以下全新概念：\n{content}\n\n"
            "上下文信息：\n{context}\n\n"
            "请输出：\n"
            "1. **概念定义**：给出通俗版与专业版定义。\n"
            "2. **核心组成/关键要素**：用分点或流程说明。\n"
            "3. **类比与图示思路**：给出帮助记忆的类比或图像化描述。\n"
            "4. **典型应用场景**：列举至少两个实际案例或问题。\n"
            "5. **延伸阅读与练习建议**：推荐进一步学习路径。\n"
        ),
    },
    {
        "id": "code_explain",
        "name": "代码学习解析",
        "description": "解析代码逻辑，拓展相关知识与实践建议。",
        "system": (
            "You are a pragmatic software mentor. "
            "Explain code line-by-line, summarize algorithms, discuss complexity, best practices, and potential pitfalls."
        ),
        "template": (
            "需要解析的代码或伪代码片段如下：\n{content}\n\n"
            "额外上下文（若有）：\n{context}\n\n"
            "请输出：\n"
            "1. **功能概述**：说明代码整体意图和输入输出。\n"
            "2. **详细解析**：按逻辑块或行解释关键语句、数据结构、算法思想。\n"
            "3. **复杂度与性能**：分析时间/空间复杂度，指出瓶颈。\n"
            "4. **相关知识拓展**：关联框架、语言特性、常见替代写法或高级用法。\n"
            "5. **实践建议**：给出测试、调试、优化或安全方面的注意事项。\n"
        ),
    },
    {
        "id": "code_optimize",
        "name": "代码优化实战",
        "description": "在保持语义一致的前提下提出性能、结构与安全优化建议。",
        "system": (
            "You are a senior software architect and performance engineer. "
            "Focus on practical refactoring suggestions, measurable improvements, and potential risks."
        ),
        "template": (
            "请在不改变功能的情况下优化下面的代码或伪代码：\n{content}\n\n"
            "可参考的上下文（需求、约束、技术栈等）：\n{context}\n\n"
            "请输出：\n"
            "1. **问题扫描**：指出原实现中的性能、可维护性、安全或可读性问题。\n"
            "2. **优化方案**：提供改进后的代码或伪代码片段，必要时分步骤解释。\n"
            "3. **效果评估**：说明预期的性能/复杂度变化，或其他可量化收益。\n"
            "4. **回归与风险**：列出需要注意的兼容性、测试要点与潜在副作用。\n"
            "5. **进一步提升**：给出可选的工程化建议，如监控、自动化、工具链优化等。\n"
        ),
    },
    {
        "id": "markdown_math_polish",
        "name": "Markdown 笔记优化（含公式）",
        "description": "润色含数学公式的 Markdown 笔记，强调结构与渲染质量。",
        "system": (
            "You are a technical writing coach specializing in scientific Markdown. "
            "Preserve mathematical meaning, improve structure, and ensure formulas render well in common Markdown engines."
        ),
        "template": (
            "请优化以下可能含数学、代码或化学内容的 Markdown 笔记：\n{content}\n\n"
            "补充上下文（可能为空）：\n{context}\n\n"
            "请完成：\n"
            "1. **结构梳理**：调整标题层级、列表、段落顺序，使逻辑清晰。\n"
            "2. **公式与符号**：统一使用 `$...$` 或 `$$...$$`，排查未闭合/格式错误的表达式，并适当添加注释。\n"
            "3. **表达优化**：润色语言，使表述准确、紧凑，必要时补充定义或说明。\n"
            "4. **语法检查**：Markdown 语法是否足够简单，方便渲染。\n"
            "5. **垃圾清理**：直接返回优化之后的笔记就好，不要生成多余内容。\n"
        ),
    },
    {
        "id": "chem_pdf_cleanup",
        "name": "化学论文 PDF 清洗排版",
        "description": "清洗化学论文 OCR/复制文本，修复格式与上下标，不增不减内容。",
        "system": (
            "You are a meticulous copyeditor for chemistry papers. "
            "Tidy noisy OCR/PDF-copied text without adding or removing facts. "
            "Preserve original languages (Chinese/English or mixed), scientific notation, and chemical meaning exactly. "
            "Use Markdown-friendly formatting, fix subscripts/superscripts and Greek letters, and strip obvious noise like page numbers or stray citation markers."
        ),
        "template": (
            "任务：对从化学论文 PDF 中复制/识别的原文做纯粹的内容清洗与重新排版，保证信息不增不减、不改动含义。\n"
            "原始文本：\n{content}\n\n"
            "上下文（可选，不一定有）：\n{context}\n\n"
            "请严格遵循：\n"
            "- 仅整理排版与格式，不改写或摘要，不补充缺失信息。\n"
            "- 合并被硬换行分割的句子或段落，保持原有段落逻辑；删除各种引用标识、页码、页眉/页脚、残缺引用编号、脚注提示等明显噪声。\n"
            "- 修复上下标、离子电荷、化学式与数学符号，可用常见记法（如 H2O、Na+、alpha），包裹采用美元符号$\n"
            "- 保留原有的中英文混排与符号；遇到无法确定的字符，用原样保留并可用 [?] 标记。\n"
            "输出：仅给出清洗排版后的正文（Markdown），不要额外解释或代码块标记。\n"
        ),
    },
    {
        "id": "ledger_insight",
        "name": "记账洞察助手",
        "description": "分析记账 Markdown，输出现金流洞察、风险提醒与行动建议。",
        "system": (
            "You are a trusted personal finance copilot. "
            "Summarize cash flow, spot anomalies, surface risks, and recommend actionable optimizations "
            "while keeping tone supportive and data-driven."
        ),
        "template": (
            "以下是我记录的记账 Markdown 内容，包含表格、列表或备注：\n{content}\n\n"
            "补充背景（预算目标、特殊事件等，可为空）：\n{context}\n\n"
            "请以个人财务助理的身份完成：\n"
            "1. **数据概览**：汇总总收入、总支出与净现金流，若数据缺失请说明假设。\n"
            "2. **类别洞察**：按类别/账户列出 2-3 个金额占比最高或变化异常的项目，解释原因。\n"
            "3. **风险与提醒**：指出潜在的现金流压力、重复订阅、过度消费或账务记录缺口。\n"
            "4. **优化建议**：给出具体的预算调整、消费替代、储蓄或投资建议，并说明预期影响。\n"
            "5. **下一步行动**：以待办清单形式输出 2-3 条可执行任务（含负责账户或时间节点）。\n"
        ),
    },
]

COMPONENT_LIBRARY = {
    "markdown": [
        {
            "group": "现成的模板",
            "items": [
                {
                    "name": "Blog Front Matter",
                    "code": "---\ncover: https://example.com/cover.jpg\ndate: \"2025-01-01\"\nstatus: draft\nsummary: |\n  在这里撰写文章摘要，支持多行描述。\ntags:\n  - 标签一\n  - 标签二\ntitle: \"文章标题\"\ncategories:\n  - 默认分类\nslug: my-blog-post\n---\n\n# 主标题\n\n正文从这里开始……\n",
                },
                {
                    "name": "日记模板",
                    "code": "---\ndate: \"2025-01-01\"\nmood: 😊\nweather: 晴\nkeywords:\n  - 生活\n  - 感悟\n---\n\n## 今日亮点\n- \n\n## 遇到的挑战\n- \n\n## 学到的事情\n- \n\n## 明日计划\n- \n",
                },
                {
                    "name": "记账模板",
                    "code": (
                        "---\n"
                        "date: \"2025-01-01\"\n"
                        "account_book: \"默认账本\"\n"
                        "currency: CNY\n"
                        "mood: 😊\n"
                        "focus: \"本周消费反思\"\n"
                        "tags:\n"
                        "  - 日常\n"
                        "  - 消费记录\n"
                        "---\n"
                        "\n"
                        "## 今日概览\n"
                        "- **总收入**：￥0.00\n"
                        "- **总支出**：￥0.00\n"
                        "- **净现金流**：`= 收入合计 - 支出合计`\n"
                        "- **预算偏差**：`= 今日实际 - 预算`\n"
                        "- **备注/情绪**：\n"
                        "\n"
                        "## 收支明细\n"
                        "| 时间 | 类别 | 子类 | 账户 | 描述 | 收入 | 支出 |\n"
                        "| ---- | ---- | ---- | ---- | ---- | ---- | ---- |\n"
                        "| 08:30 | 工作 | 工资 | 工资账户 | 1 月薪资 | 500.00 | 0.00 |\n"
                        "| 12:10 | 生活 | 午餐 | 数字钱包 | 商务午餐 | 0.00 | 38.00 |\n"
                        "\n"
                        "## 固定支出 / 订阅检查\n"
                        "- [ ] 项目 / 金额 / 到期时间\n"
                        "\n"
                        "## 预算与目标\n"
                        "- 本周目标：\n"
                        "- 进展点评：\n"
                        "\n"
                        "## 财务反思\n"
                        "- 今日洞察：\n"
                        "- 明日行动：\n"
                    ),
                },
                {
                    "name": "会议笔记模板",
                    "code": (
                        "---\n"
                        "meeting: \n"
                        "type: \n"
                        "date: \"\"\n"
                        "time: \"\"\n"
                        "location: \n"
                        "facilitator: \n"
                        "attendees:\n"
                        "  \n"
                        "  \n"
                        "objective: |\n"
                        "  \n"
                        "context: \"\"\n"
                        "---\n"
                        "\n"
                    ),
                },
                {
                    "name": "课堂/读书笔记模板",
                    "code": (
                        "---\n"
                        "topic: 课程/书籍名称\n"
                        "date: \"2025-01-01\"\n"
                        "tags:\n"
                        "  - 知识管理\n"
                        "  - 专业技能\n"
                        "---\n"
                        "\n"
                        "## 章节脉络\n"
                        "| 章节 | 核心命题 | 证据/案例 |\n"
                        "| ---- | -------- | --------- |\n"
                        "| 第 1 章 | | |\n"
                        "\n"
                        "## 核心概念拆解\n"
                        "- 概念：定义 / 关键公式 / 适用场景\n"
                        "- 概念：\n"
                        "\n"
                        "## 重点摘录\n"
                        "> 原文节选（引用 + 页码或时间戳）\n"
                        ">\n"
                        "> 自己的理解：\n"
                        "\n"
                        "## 思考与疑问\n"
                        "- 现有认知冲突：\n"
                        "- 待进一步求证的问题：\n"
                        "\n"
                        "## 应用与行动\n"
                        "- 场景假设：\n"
                        "- 行动实验：\n"
                        "- 复盘指标：\n"
                    ),
                },
                {
                    "name": "日程规划安排模板",
                    "code": (
                        "---\n"
                        "date: \"2025-01-01\"\n"
                        "week: \"Week 01\"\n"
                        "focus_mission: \"当天最高优先级任务\"\n"
                        "energy_curve:\n"
                        "  morning: 高\n"
                        "  afternoon: 中\n"
                        "  evening: 低\n"
                        "habits:\n"
                        "  - 运动\n"
                        "  - 阅读\n"
                        "---\n"
                        "\n"
                        "## 今日三大目标\n"
                        "1. \n"
                        "2. \n"
                        "3. \n"
                        "\n"
                        "## 时间区块\n"
                        "| 时间 | 事项 | 预期成果 | 提醒 |\n"
                        "| ---- | ---- | -------- | ---- |\n"
                        "| 08:30-10:00 | 深度工作 | 模块交付 | 关闭通知 |\n"
                        "\n"
                        "## 优先级清单\n"
                        "- P0：\n"
                        "- P1：\n"
                        "- P2：\n"
                        "\n"
                        "## 日终复盘\n"
                        "- 完成度：\n"
                        "- 情绪/能量观察：\n"
                        "- 明日微调：\n"
                    ),
                },
                {
                    "name": "活动组织模板",
                    "code": (
                        "---\n"
                        "event_name: 春季客户见面会\n"
                        "theme: \"以客户成功为中心\"\n"
                        "date_range: \"2025-03-10 ~ 2025-03-12\"\n"
                        "location: 上海会议中心\n"
                        "## 关键里程碑\n"
                        "| 截止时间 | 事项 | 负责人 | 状态 |\n"
                        "| -------- | ---- | ------ | ---- |\n"
                        "| 02-15 | 场地确认 | 王五 | 进行中 |\n"
                        "\n"
                        "## 资源与分工\n"
                        "- 策划：\n"
                        "- 运营：\n"
                        "- 物料：\n"
                        "- 技术支持：\n"
                        "\n"
                        "## 活动当日日程\n"
                        "| 时间 | 环节 | 负责人 | 备注 |\n"
                        "| ---- | ---- | ------ | ---- |\n"
                        "| 09:00 | 签到 | 前台组 | 准备礼品 |\n"
                        "\n"
                        "## 复盘要点\n"
                        "- 成果指标：到场人数 / NPS / 成交\n"
                        "- 学习与改进：\n"
                    ),
                },
            ],
        },
        {
            "group": "md基础简单语法",
            "items": [
                {"name": "二级标题", "code": "## 小节标题\n\n这里是内容简介。"},
                {"name": "加粗", "code": "**加粗文本**"},
                {"name": "斜体", "code": "*斜体文本*"},
                {"name": "划线", "code": "～划线文本～"},
                {
                    "name": "任务清单",
                    "code": "- [ ] 待办事项一\n- [x] 已完成事项",
                },
                {
                    "name": "引用块",
                    "code": "> 引用内容，可用于强调某句文字。",
                },
                {
                    "name": "分割线",
                    "code": "---\n",
                },
            ],
        },
        {
            "group": "补充特殊卡片",
            "items": [
                {
                    "name": "指标卡（KPI）（自建）",
                    "code": ":::kpi\n- **指标一**: 95%\n- **指标二**: 120\n- **指标三**: 完成\n:::\n",
                },
                {
                    "name": "封面卡（自建）",
                    "code": ":::cover\n# 演示标题\n副标题或作者 / 日期\n:::\n",
                },
                {
                    "name": "横幅卡片（自建）",
                    "code": ":::banner\n**要点**：在这里写一段醒目的提示文本。\n:::\n",
                },
                {
                    "name": "备注卡片（仅显示在编辑器，导出为小字）（自建）",
                    "code": ":::notes\n讲者备注：仅供备忘，不作为正文展示。\n:::\n",
                },
                {
                    "name": "代码解析卡片（自建）",
                    "code": ":::code-split\n```python\nprint('示例')\n```\n\n说明：在右侧写解释文本。\n:::\n",
                },
                {
                    "name": "问题卡片（展开显示答案）（自建）",
                    "code": ":::qa 这里是问题？\n这里写展开即见的答案或提示。\n:::\n",
                },
                {
                    "name": "答案卡片（点击才会显示的答案）（自建）",
                    "code": ":::qa 这里是问题？ | collapse\n这里写默认隐藏、点击展开的答案。\n:::\n",
                },
            ],
        },
        {
            "group": "补充布局优化",
            "items": [
                {
                    "name": "左右两栏布局（自建）",
                    "code": ":::cols\n左侧内容\n\n右侧内容\n:::\n",
                },
                {
                    "name": "三栏特性（自建）",
                    "code": ":::features\n- 特性一\n- 特性二\n- 特性三\n:::\n",
                },
            ],
        },
        {
            "group": "列表与表格",
            "items": [
                {
                    "name": "嵌套列表",
                    "code": "- 一级要点\n  - 二级要点\n    - 三级要点",
                },
                {
                    "name": "有序列表",
                    "code": "1. 第一要点\n1. 第二要点\n1. 第三要点",
                },
                {
                    "name": "简单表格（markdown 表格）",
                    "code": "| 项目 | 指标 | 说明 |\n| ---- | ---- | ---- |\n| A    | 95   | 描述A |\n| B    | 88   | 描述B |",
                },
            ],
        },
        {
            "group": "补充辅助块",
            "items": [
                {
                    "name": "代码块",
                    "code": "```python\nprint('Hello World')\n```",
                },
                {
                    "name": "提示块",
                    "code": ":::tip\n关键提示写在这里。\n:::\n",
                },
                {
                    "name": "警告块",
                    "code": ":::warning\n需要注意的内容。\n:::\n",
                },
                {
                    "name": "信息块（自建）",
                    "code": ":::info\n标题\n\n说明内容。\n:::\n",
                },
            ],
        },
        {
            "group": "媒体文件（Markdown）",
            "items": [
                {
                    "name": "插入图片",
                    "code": "![图片说明](path/to/image.png)",
                },
                {
                    "name": "插入视频（自建语法）",
                    "code": ":::video https://example.com/video.mp4\n可选：这里写视频说明。\n:::\n",
                },
                {
                    "name": "插入音频（自建语法）",
                    "code": ":::audio https://example.com/audio.mp3\n可选：这里写音频说明。\n:::\n",
                },
                {
                    "name": "嵌入链接",
                    "code": "[相关链接](https://example.com)",
                },
                {
                    "name": "左右两列图片（自建）",
                    "code": ":::img-2\n![](图片1地址)\n\n![](图片2地址)\n:::\n",
                },
                {
                    "name": "上下两列图片（自建）",
                    "code": ":::img-2v\n![](图片1地址)\n\n![](图片2地址)\n:::\n",
                },
                {
                    "name": "田字四图（自建）",
                    "code": ":::img-4\n![](图片1地址)\n![](图片2地址)\n\n![](图片3地址)\n![](图片4地址)\n:::\n",
                },
                {
                    "name": "滚动画廊（自建）",
                    "code": ":::img-scroll\n![](图片1地址)\n![](图片2地址)\n![](图片3地址)\n![](图片4地址)\n:::\n",
                },
            ],
        },
        {
            "group": "HTML 直接插入",
            "items": [
                {
                    "name": "两列对比表格",
                    "code": "<table>\n  <tr>\n    <th>优势</th>\n    <th>劣势</th>\n  </tr>\n  <tr>\n    <td>内容 A</td>\n    <td>内容 B</td>\n  </tr>\n</table>\n",
                },
                {
                    "name": "插入视频",
                    "code": "<video controls width=\"640\">\n  <source src=\"path/to/video.mp4\" type=\"video/mp4\">\n  您的浏览器不支持 HTML5 视频。\n</video>\n",
                },
                {
                    "name": "插入音频",
                    "code": "<audio controls>\n  <source src=\"path/to/audio.mp3\" type=\"audio/mpeg\">\n  您的浏览器不支持音频播放。\n</audio>\n",
                },
                {
                    "name": "折叠区块（details/summary）",
                    "code": "<details>\n  <summary>点击展开/收起</summary>\n  <p>这里放置可折叠的详细说明。</p>\n</details>\n",
                },
                {
                    "name": "提示条（alert）",
                    "code": "<div class=\"alert alert-warning\" role=\"alert\">\n  <strong>提示：</strong> 这里是强调的说明或风险提醒。\n</div>\n",
                },
                {
                    "name": "卡片容器",
                    "code": "<div class=\"card\" style=\"max-width:640px;\">\n  <div class=\"card-body\">\n    <h5 class=\"card-title\">卡片标题</h5>\n    <p class=\"card-text\">简短内容描述，支持<b>加粗</b>与链接。</p>\n    <a href=\"#\" class=\"btn btn-primary\">操作按钮</a>\n  </div>\n</div>\n",
                },
                {
                    "name": "按钮组",
                    "code": "<div class=\"btn-group\" role=\"group\" aria-label=\"操作\">\n  <button type=\"button\" class=\"btn btn-outline-primary\">操作一</button>\n  <button type=\"button\" class=\"btn btn-outline-secondary\">操作二</button>\n  <button type=\"button\" class=\"btn btn-outline-success\">操作三</button>\n</div>\n",
                },
                {
                    "name": "嵌入 iframe",
                    "code": "<div style=\"position:relative;padding-top:56.25%;\">\n  <iframe src=\"https://example.com\" title=\"嵌入页面\"\n    style=\"position:absolute;top:0;left:0;width:100%;height:100%;border:0;\"\n    allowfullscreen loading=\"lazy\"></iframe>\n</div>\n",
                },
            ],
        },
    ],
}

_ui_skin = (os.environ.get("BENBEN_UI_SKIN") or "default").strip().lower()
if _ui_skin not in {"default", "pastel", "paper", "ocean", "forest", "sunset", "slate"}:
    _ui_skin = "default"

_ui_tier = (os.environ.get("BENBEN_UI_TIER") or "standard").strip().lower()
if _ui_tier not in {"compact", "standard", "relaxed"}:
    _ui_tier = "standard"

_ui_pane_ratio = (os.environ.get("BENBEN_UI_PANE_RATIO") or "balanced").strip().lower()
if _ui_pane_ratio not in {"no-script", "editor-wide", "balanced", "preview-wide", "equal"}:
    _ui_pane_ratio = "balanced"

_ui_pane_layout = (os.environ.get("BENBEN_UI_PANE_LAYOUT") or "default").strip().lower()
if _ui_pane_layout not in {"default", "editor-only", "preview-only"}:
    _ui_pane_layout = "default"

_ui_color_mode = (os.environ.get("BENBEN_COLOR_MODE") or "light").strip().lower()
if _ui_color_mode not in {"light", "dark"}:
    _ui_color_mode = "light"

_navbar_style = (os.environ.get("BENBEN_NAVBAR_STYLE") or "uniform").strip().lower()
if _navbar_style not in {"uniform", "palette"}:
    _navbar_style = "uniform"

_navbar_variant = (os.environ.get("BENBEN_NAVBAR_VARIANT") or "outline").strip().lower()
if _navbar_variant not in {"outline", "solid"}:
    _navbar_variant = "outline"

_navbar_palette_env = os.environ.get("BENBEN_NAVBAR_PALETTE") or "primary,success,warning,danger,info"
_navbar_palette = [c.strip().lower() for c in _navbar_palette_env.split(",") if c.strip()] or ["primary"]

UI_THEME = {
    "color_mode": _ui_color_mode,  # light | dark
    "skin": _ui_skin,
    "tier": _ui_tier,
    "fontSize": _ui_tier,
    "pane_ratio": _ui_pane_ratio,
    "paneRatio": _ui_pane_ratio,
    "pane_layout": _ui_pane_layout,
    "paneLayout": _ui_pane_layout,
    "navbar_buttons": {
        "preset": (os.environ.get("BENBEN_NAVBAR_PRESET") or "modern").strip().lower(),
        "style": _navbar_style,  # uniform | palette
        "variant": _navbar_variant,  # outline | solid
        "color": (os.environ.get("BENBEN_NAVBAR_COLOR") or "auto").strip(),
        "palette": _navbar_palette,
    },
}


def template_library_root(app: object | None = None) -> str:
    """确定可复用 Markdown 模板所在目录。"""

    if app is not None:
        # 在应用上下文内优先读取配置值
        root = getattr(app, "config", {}).get("TEMPLATE_LIBRARY")  # type: ignore[arg-type]
        if root:
            return root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "temps"))


def init_app_config(app) -> None:
    """根据应用根目录初始化项目与模板文件夹。"""

    projects_root = os.path.join(app.root_path, "projects")
    app.config.setdefault("PROJECTS_ROOT", projects_root)

    # 预先加载 OSS 配置，允许通过环境变量覆盖
    app.config.setdefault("ALIYUN_OSS_ENDPOINT", os.environ.get("ALIYUN_OSS_ENDPOINT"))
    app.config.setdefault("ALIYUN_OSS_ACCESS_KEY_ID", os.environ.get("ALIYUN_OSS_ACCESS_KEY_ID"))
    app.config.setdefault("ALIYUN_OSS_ACCESS_KEY_SECRET", os.environ.get("ALIYUN_OSS_ACCESS_KEY_SECRET"))
    app.config.setdefault("ALIYUN_OSS_BUCKET", os.environ.get("ALIYUN_OSS_BUCKET"))
    app.config.setdefault("ALIYUN_OSS_PREFIX", os.environ.get("ALIYUN_OSS_PREFIX"))
    app.config.setdefault("ALIYUN_OSS_PUBLIC_BASE_URL", os.environ.get("ALIYUN_OSS_PUBLIC_BASE_URL"))

    template_root = template_library_root(app)
    app.config.setdefault("TEMPLATE_LIBRARY", template_root)
    os.makedirs(template_root, exist_ok=True)


__all__ = [
    "DEFAULT_MARKDOWN_TEMPLATE_FILENAME",
    "FALLBACK_MARKDOWN_TEMPLATE",
    "OPENAI_CHAT_COMPLETIONS_MODEL",
    "OPENAI_API_BASE_URL",
    "OPENAI_CHAT_PATH",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_PATH",
    "DEFAULT_TTS_MODEL",
    "DEFAULT_TTS_PATH",
    "CHATANYWHERE_EMBEDDING_MODEL",
    "CHATANYWHERE_TTS_MODEL",
    "CHATANYWHERE_EMBEDDING_PATH",
    "CHATANYWHERE_TTS_PATH",
    "CHATANYWHERE_API_BASE_URL",
    "CHATANYWHERE_CHAT_PATH",
    "CHATANYWHERE_DEFAULT_MODEL",
    "LLM_PROVIDERS",
    "DEFAULT_LLM_PROVIDER",
    "OPENAI_TTS_MODEL",
    "OPENAI_TTS_VOICE",
    "OPENAI_TTS_RESPONSE_FORMAT",
    "OPENAI_TTS_SPEED",
    "AI_PROMPTS",
    "AI_BIB_PROMPT",
    "LEARNING_ASSISTANT_DEFAULT_PROMPTS",
    "COMPONENT_LIBRARY",
    "UI_THEME",
    "init_app_config",
    "template_library_root",
]
