# Benben

Benben 是一个 **Markdown 驱动** 的演示/笔记工作台：后端基于 Flask，前端使用单页 `editor.html` 集成 CodeMirror 与 Markdown 渲染，适合做分享稿、课程笔记、读书摘要与项目备忘。  
一个 `.benben` 文件就是完整工作区（页面、模板、附件、资源、学习记录等全部封装在 SQLite 中），支持本地与 OSS 远程工作区。

---

## 快速开始

1. **环境**：建议 Python 3.11+。
2. **安装依赖**：

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install .
```

3. **配置 `.env`（可选）**：

```ini
FLASK_DEBUG=1
OPENAI_API_KEY=sk-xxxx

# 远程工作区（OSS）
ALIYUN_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
ALIYUN_OSS_ACCESS_KEY_ID=xxx
ALIYUN_OSS_ACCESS_KEY_SECRET=xxx
ALIYUN_OSS_BUCKET=benben
ALIYUN_OSS_PREFIX=workspaces
```

4. **启动**：

```bash
flask --app benben run
```

生产部署示例：

```bash
gunicorn -w 4 -b 0.0.0.0:5555 benben:app
```

---

## 目录结构

```
Benben/
├─ benben/
│  ├─ __init__.py        # Flask 工厂 & .env 加载
│  ├─ package.py         # `.benben` SQLite 容器读写
│  ├─ workspace.py       # 运行时工作区注册/切换
│  ├─ views.py           # API + 导出/渲染逻辑
│  ├─ templates/
│  │   └─ editor.html    # 唯一前端页面（含 JS/CSS）
│  └─ ...
├─ temps/                # Markdown 模板（YAML）
│  └─ attachments_seed/  # 预置附件
├─ README.md
└─ pyproject.toml
```

---

## 工作区与数据

- **工作区**：每个 `.benben` 是一个 SQLite 数据库文件。  
  WAL 文件（`.benben-wal` / `.benben-shm`）是正常产物，连接关闭或 checkpoint 后会自动清理。
- **核心表**：
  - `meta`：项目基础信息与时间戳
  - `pages` / `page_markdown` / `page_notes`：页面结构与正文/讲稿
  - `attachments` / `resource_files`：附件与资源
  - `templates`：保存到项目内的模板
  - `learning_prompts` / `learning_records`：学习助手与记录
  - `settings`：全局设置

---

## 编辑与预览

- **Markdown 单一编辑模式**：实时预览、滚动同步。
- **内置 Markdown 特性**：表格、任务清单、脚注、删除线、内联 HTML。
- **讲稿 & TTS**：每页讲稿可独立导出音频。

---

## 自定义 Markdown 语法（Benben 扩展）

Benben 内置多种自定义块语法（通过 container 插件实现），你需要在模板 CSS 中为这些类名提供样式：

### Callout（提示框）

```md
:::info 标题
这里是内容
:::
```

输出结构：  
`.markdown-callout.info` + `.markdown-callout-title` + `.markdown-callout-body`

支持 `:::info` / `:::tip` / `:::warning`。

### Q&A（可折叠）

```md
:::qa 这里是问题？ | collapse
这里写默认隐藏、点击展开的答案。
:::
```

输出结构：  
`details.markdown-qa.collapsed`（折叠）或 `div.markdown-qa`（不折叠）  
内部包含：`.markdown-qa-label` / `.markdown-qa-question` / `.markdown-qa-toggle` / `.markdown-qa-answer`

### 图片网格

```md
:::img-2
![](a.png)
![](b.png)
:::
```

支持容器：
- `:::img-2` → `.markdown-img-grid.two-col`
- `:::img-2v` → `.markdown-img-grid.two-vertical`
- `:::img-4` → `.markdown-img-grid.four-grid`
- `:::img-scroll` → `.markdown-img-grid.rail`

### 媒体块

```md
:::audio path/to/audio.mp3
:::

:::video path/to/video.mp4
:::
```

输出结构：`.markdown-media.audio` / `.markdown-media.video`  
内部包含 `audio`/`video` 与 `.markdown-media-caption`。

### 视觉块容器（仅包裹内容）

```md
:::kpi
这里是指标卡
:::
```

可用容器：
`:::kpi`、`:::cols`、`:::features`、`:::cover`、`:::divider`、`:::banner`、`:::notes`、`:::code-split`  
分别对应：
`.markdown-kpi` / `.markdown-cols` / `.markdown-features` / `.markdown-cover` / `.markdown-divider` /
`.markdown-banner` / `.markdown-notes` / `.markdown-code-split`

### 内联语法

```
==highlight==
??blur??
```

输出结构：  
`<mark class="markdown-highlight">`  
`<span class="markdown-blur" tabindex="0">`

> 建议给 `.markdown-blur` 设置 `filter: blur(...)`，并在 `:hover` 或 `:focus` 时恢复清晰。

---

## 模板系统（temps）说明书

### 1) 模板位置与加载规则

- **模板库目录**：`temps/`  
  默认模板：`temps/markdown_default.yaml`
- **命名规则**：任意 `*.yaml` 文件都会被识别为可选模板。
- **缓存**：模板读取有 LRU 缓存，直接改动文件后需要 **重启服务** 才能刷新。

### 2) YAML 字段说明

```yaml
type: markdown
css: |
  # 预览样式（也会注入导出 HTML）
wrapperClass: markdown-note
exportCss: |
  # 仅用于 HTML 导出（body/容器基础样式）
customHead: |
  <!-- 仅用于 HTML 导出：字体/额外样式/第三方库 -->
customBody: |
  <script>
  // 仅用于 HTML 导出：交互脚本
  </script>
```

字段含义：
- `css`：编辑器预览样式（同时会被注入导出 HTML）。  
- `wrapperClass`：Markdown 渲染根容器 class（预览与导出都会加上）。  
- `exportCss`：导出 HTML 专用 CSS（推荐写 `body.markdown-export` 和 `.markdown-export-content` 的基础布局）。  
- `customHead`：导出 HTML 的 `<head>` 额外内容（字体/外部样式）。  
- `customBody`：导出 HTML 的 `<body>` 尾部脚本（交互/目录/复制等）。

### 3) 导出 HTML 结构（CSS 必须覆盖）

导出 HTML 的外层结构固定如下：

- `body`：`class="markdown-export theme-light|theme-dark"` 且带 `data-theme`  
- 内容容器：  
  `div.markdown-preview-content.markdown-export-content.{wrapperClass}`

因此导出 CSS 至少覆盖：
- `body.markdown-export`：页面底色、字体、排版
- `.markdown-export-content`：内容容器宽度/间距/阴影
- `.markdown-preview-image`：导出时所有图片都会自动加此 class

### 4) CSS 清单（建议完整覆盖）

基础元素（Markdown 原生）：
- `h1..h4`, `p`, `a`, `ul/ol`, `blockquote`, `code`, `pre`, `table`, `hr`, `img`, `figure`, `figcaption`
- 代码块高亮：`pre.hljs`、`code.hljs`（导出时自动添加）

Benben 自建语法类：
- `.markdown-callout`, `.markdown-callout-title`, `.markdown-callout-body`
- `.markdown-qa`, `.markdown-qa-label`, `.markdown-qa-question`, `.markdown-qa-toggle`, `.markdown-qa-answer`
- `.markdown-img-grid` + `two-col`/`two-vertical`/`four-grid`/`rail`
- `.markdown-media` + `audio`/`video` + `.markdown-media-caption`
- `.markdown-kpi`, `.markdown-cols`, `.markdown-features`, `.markdown-cover`, `.markdown-divider`, `.markdown-banner`, `.markdown-notes`, `.markdown-code-split`
- `.markdown-highlight`, `.markdown-blur`

### 5) JS 清单（customBody）

`customBody` 会在导出 HTML 中执行，可实现以下功能：

- **目录/锚点跳转**：扫描 `h1..h3` 生成目录并写入 DOM  
- **标题锚点复制**：为标题生成 ID 与复制按钮  
- **阅读进度条**：滚动进度条  
- **Back to Top**：返回顶部  
- **图片灯箱**：点击图片全屏预览  
- **代码复制按钮**：在 `pre` 内插入按钮  
- **阅读聚焦/宽屏切换**：切换容器宽度

推荐入口：

```js
const root = document.querySelector('.markdown-export-content');
```

### 6) 内置模板清单（带 JS 交互）

- `markdown_default.yaml`：滚动进度条 + 代码复制
- `markdown_minimal.yaml`：专注/宽屏切换 + 标题锚点复制
- `markdown_classic.yaml`：返回顶部按钮
- `markdown_contrast.yaml`：当前标题提示条
- `markdown_album.yaml`：图片灯箱
- `markdown_cyber.yaml`：扫描线 + 标题脉冲

### 7) 新增模板流程

1. 在 `temps/` 新增 YAML 文件。  
2. 填入 `css` / `wrapperClass` / `exportCss` / `customHead` / `customBody`。  
3. 重启服务后，模板会出现在“外观配置/模板选择”里。

---

## 导出说明书

### Markdown 导出

- **当前页**：导出 Markdown 并打包附件  
- **全部页**：合并全部笔记导出  
- **当前页及相关页**：从当前页开始，解析其内部链接并递归收集关联页面（自动去重、避免循环）

Markdown 导出会生成：
- 一个 `.md` 文件
- 同包内的附件文件（自动打包为 zip）

### HTML 导出

- HTML 为单文件输出，图片/视频/音频会 **转为 base64** 内嵌。
- 导出样式严格使用 **当前模板** 的 `exportCss + css + customHead + customBody`。

### 相关页解析规则（链接格式）

系统会解析 Markdown 中的链接（或 HTML 的 `href`/`src`）并识别页面索引或 pageId。

可识别示例：

```
[link](page-3)
[link](p3)
[link](3)
[link](?page=3)
[link](?pageIndex=3)
[link](pageId:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)
[link](pageId-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)
```

---

## AI 助理 & RAG

- **索引范围**：仅索引当前已解锁 `.benben` 的 Markdown 笔记。  
- **默认向量化**：OpenAI `text-embedding-3-large`。  
- **可配置项**：`LLM_BASE_URL`、`LLM_EMBEDDING_PATH`、`LLM_EMBEDDING_MODEL`、`LLM_PROVIDER`、`LLM_CHAT_PATH`、`LLM_MODEL`。

---

## 常用命令

| 命令 | 说明 |
| ---- | ---- |
| `pip install .` | 安装依赖 |
| `flask --app benben run` | 开发模式启动 |
| `gunicorn benben:app` | 生产部署示例 |
| `python -m compileall benben` | 语法检查 |

---

## 常见问题

**Q: 模板改完不生效？**  
A: 模板读取有缓存，需重启服务。

**Q: HTML 导出样式为什么不对？**  
A: 导出只读取模板里的 `exportCss` / `customHead` / `customBody`，请确保这些字段完整。

---

欢迎提交 Issue 或 PR 讨论新特性与 AI 工作流。
