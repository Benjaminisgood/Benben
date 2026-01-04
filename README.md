# Benben

Benben 是一个 **Markdown 驱动** 的演示/笔记工作台：后端基于 Flask，前端使用单页 `editor.html` 整合 CodeMirror、Markdown 渲染与 Bootstrap 交互，并接入主流 LLM、TTS 能力。适合做分享稿、课程笔记、读书摘要与项目备忘。

最新版本已将所有“项目”存储迁移为 **`.benben` SQLite 容器工作区**。一个 `.benben` 文件就是完整项目（页面、模板、附件、资源、学习记录等都封装进去），支持本地与远程（OSS）双工作区。

> 若你看到 `demo.benben-wal` / `demo.benben-shm`，这是 SQLite WAL 模式的正常产物，连接关闭或执行 checkpoint 后会自动清理。

---

## 核心特性

- **Markdown 单一编辑模式**：一份正文 + 实时预览，支持表格、任务清单、代码高亮与自定义 Markdown 组件。
- **滚动同步**：编辑器与预览区同步滚动，减少定位成本。
- **讲稿与 TTS**：每页独立讲稿，支持导出当前页或全局 MP3。
- **AI 工作流**：
  - 笔记优化、讲稿优化；
  - “AI 学习”支持后台运行与结果归档；
  - “AI 复习”可按分类/收藏/关键词检索历史记录。
- **AI 助理（可选 RAG）**：可检索当前工作区 Markdown 笔记生成上下文，不上传附件。
- **模板体系**：内置 Markdown CSS 模板库，支持自定义样式与预览容器 class。
- **工作区安全**：每个 `.benben` 可设置访问密码。
- **附件与资源管理**：附件、资源可按页面/项目管理，支持引用统计与清理。
- **关系图谱**：基于 Markdown 内部跳转生成页面关系图。

---

## 目录与组件概览

```
Benben/
├─ benben/
│  ├─ __init__.py        # Flask 工厂 & .env 加载
│  ├─ package.py         # `.benben` SQLite 容器读写
│  ├─ workspace.py       # 运行时工作区注册/切换
│  ├─ views.py           # Flask 蓝图（API + 模板渲染）
│  ├─ templates/
│  │   └─ editor.html    # 唯一的前端页面，内含所有 JS/CSS
│  └─ ...
├─ temps/                # Markdown 模板（YAML）
├─ README.md
└─ pyproject.toml
```

### 额外资源 & 清理脚本
- `node_modules/` & `package(-lock).json`：前端调试依赖，运行 `npm install` 后生成。如不需要，可用 `scripts/clean_workspace.py --include-node` 移除。
- `.pytest_cache/`、`__pycache__/`、`build/`、`benben.egg-info/` 等目录仅由测试/打包流程生成，Benben 启动时会自动清理（设置 `BENBEN_DISABLE_AUTO_CLEAN=1` 可关闭），也可手动执行 `scripts/clean_workspace.py`。

---

## 环境准备

1. **Python**：建议 Python 3.11+。
2. **虚拟环境与依赖**：

   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install --upgrade pip
   pip install .
   ```

3. **配置环境变量**：在仓库根目录放置 `.env`（Flask 启动时自动加载），示例：

   ```ini
   FLASK_DEBUG=1
   OPENAI_API_KEY=sk-xxxx

   # OSS/远程工作区
   ALIYUN_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
   ALIYUN_OSS_ACCESS_KEY_ID=xxx
   ALIYUN_OSS_ACCESS_KEY_SECRET=xxx
   ALIYUN_OSS_BUCKET=benben
   ALIYUN_OSS_PREFIX=workspaces
   ```

---

## 运行

```bash
flask --app benben run    # http://localhost:5000
```

生产环境：

```bash
gunicorn -w 4 -b 0.0.0.0:5555 benben:app
```

---

## 工作区使用指南

1. **打开工作区菜单**：导航栏左上角显示当前工作区名。
   - `📁 打开本地工作区`：列出项目根目录下的 `.benben` 文件。
   - `☁️ 打开远程工作区`：列出 OSS 上的 `.benben` 包。

2. **本地工作区**：
   - 自动扫描项目根目录的 `.benben` 文件；
   - 新建时会自动追加 `.benben` 后缀。

3. **远程工作区（OSS）**：
   - 需在 `.env` 配置 OSS 相关变量；
   - 支持创建、打开与同步。

4. **WAL 文件提示**：`xxx.benben-wal` 与 `xxx.benben-shm` 为正常写前日志文件，推荐保留。

---

## `.benben` 架构简述

- SQLite 数据库关键表：
  - `meta`：项目基础信息与时间戳；
  - `pages`：页顺序与更新时间；
  - `page_markdown`：Markdown 正文；
  - `page_notes`：讲稿（脚本）；
  - `page_recordings`：录播/音频信息；
  - `page_resources` / `page_references`：页面级资源与引用；
  - `project_resources` / `project_references`：项目级资源与引用；
  - `attachments` / `resource_files`：附件与静态资源；
  - `templates`：模板；
  - `learning_prompts` / `learning_records`：学习助手提示词与记录；
  - `settings`：全局设置。
- `benben/package.py` 封装所有读写逻辑，前端只需调用 `/workspaces/<id>/project`。

### 附件与图片
- 附件统一存储于 SQLite `attachments` 表；
- 渲染/导出时会展开到临时目录，避免重复上传。

---

## AI 助理 & RAG

- **范围与缓存**：仅索引当前已解锁 `.benben` 的 Markdown 笔记，索引与向量存放本机临时目录。
- **默认向量化**：使用当前 LLM 提供方的 embedding 接口（默认 OpenAI `text-embedding-3-large`）。
- **自定义**：可通过环境变量覆写 `LLM_BASE_URL`、`LLM_EMBEDDING_PATH`、`LLM_EMBEDDING_MODEL`、`LLM_PROVIDER`、`LLM_CHAT_PATH`、`LLM_MODEL` 等。
- **前端开关**：导航栏 “AI助理” -> 勾/不勾 “使用 RAG”。

---

## 常用命令

| 命令 | 说明 |
| ---- | ---- |
| `pip install .` | 安装依赖 |
| `flask --app benben run` | 开发模式启动 |
| `gunicorn benben:app` | 生产部署示例 |
| `python -m compileall benben` | 语法检查 |

---

## 贡献指南

1. Fork & 新建分支。
2. 提交前运行 `python -m compileall benben`。
3. 如需变更 `.benben` 数据结构，请在 PR 描述说明。

欢迎提交 Issue 或 PR 讨论新特性与 AI 工作流。


继续执行下面没有完成的指令：

“”“
现在在导出里新增导出当前页及相关页，也是分为md和html两种。
当前页和相关页的意思是，以当前页为起点，连同当前页所引用的页及引用页中的引用页等等不断类推下去，类似于这页后面所有的分支页走到头的所有页一并写入导出为一个md或者html文件，注意避免循环重复。
其中html的图片等媒体是base64嵌入一个html文件中，md的则是一个md连同媒体附件文件一起打包。
并且优化现在所有导出为html的，当前样式模板中似乎只写了css，我请你把现在补充加css和js等的逻辑改为这些也全部放进样式模版文件中去，然后导出时我当前用的什么样式（模版），就导出为什么样子。相当于每个模版就是一种html册，我可以把一份内容导出渲染为各种各样、不同交互的分享版本。
”“”


优化管理链接的提示词，输入可能为一段描述、可能为多个链接、可能为任何可能包含链接信息的内容，不再是原来的bib了，让ai正确识别出来。

现在的展示不要直接全屏，而是进入网页全屏模式，浏览器全屏需要我自己点击全屏才对。

现在附件管理弹窗中附件未被引用的提示框的css颜色是固定的与可调整的主题色不适配，改为也跟随主题色变动。

现在只有markdown模式了，所以config里面
COMPONENT_LIBRARY = {
    "markdown": [
不需要多余的“  "markdown": [  ”吧。其他的一些多余的markdown的强调似乎也不需要了，可以适当简化优化。

