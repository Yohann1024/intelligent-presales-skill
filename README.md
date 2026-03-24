# 智能售前 Skill

**解析招标文件，检索历史标书知识库，AI 辅助生成投标内容。**

适用于 Claude Code / Open Claw 等支持 Skills 的 AI 编程助手。

## 功能特点

- 📄 **招标文件深度解析** — 自动提取项目信息、技术要求、评分标准
- 🔍 **知识库语义检索** — 基于向量相似度匹配历史标书的相关内容
- ✍️ **原创内容生成** — 结合历史经验 + AI 思考，撰写全新的投标内容（非复制粘贴）
- 🏷️ **自动标签分类** — 按技术领域、行业类型自动标注，精准检索
- 🔒 **全本地运行** — Ollama + ChromaDB，数据不出本地，适合涉密项目

## 快速开始

### 1. 环境准备

```bash
# 安装 Ollama（如已安装可跳过）
brew install ollama        # macOS
# curl -fsSL https://ollama.com/install.sh | sh  # Linux

# 拉取 Embedding 模型
ollama pull bge-m3

# 安装 Python 依赖
pip install -r requirements.txt
```

### 2. 导入历史标书

将历史投标文件（.docx / .pdf / .txt / .md）放入一个文件夹，执行入库：

```bash
python scripts/ingest.py /path/to/你的标书目录
```

支持增量入库，已处理过的文件会自动跳过。如需重建：

```bash
python scripts/ingest.py /path/to/你的标书目录 --reset
```

### 3. 验证检索

```bash
# 语义检索
python scripts/search_kb.py --query "系统安全等保要求" --top_k 5

# 按标签过滤
python scripts/search_kb.py --query "架构设计" --tag "微服务"

# 查看知识库统计
python scripts/search_kb.py --stats
```

### 4. 在 AI 助手中使用

将本 Skill 目录放到你的 AI 编码助手的 Skills 目录下，然后在对话中直接说：

> 请帮我根据这份招标文件写投标方案

AI 助手会自动调用 Skill，执行解析 → 检索 → 生成的完整流程。

## 目录结构

```
intelligent-presales/
├── SKILL.md                     # Skill 核心指令
├── README.md                    # 本文件
├── requirements.txt             # Python 依赖
├── scripts/
│   ├── ingest.py                # 数据入库脚本
│   └── search_kb.py             # 知识库检索脚本
├── knowledge_base/              # 知识库数据（自动生成）
│   ├── vectordb/                # ChromaDB 向量数据
│   ├── documents/               # 清洗后的结构化文档
│   └── metadata.json            # 文件索引
└── resources/
    └── prompt_templates/        # 提示词模板（可扩展）
```

## 支持的文件格式

| 格式 | 说明 |
|---|---|
| `.docx` | Word 文档，自动识别标题层级 |
| `.pdf` | PDF 文件，支持文本提取 |
| `.txt` `.md` | 纯文本 / Markdown |

> 📌 扫描件 PDF 和图片格式需要 OCR 支持，后续版本将集成 PaddleOCR。

## 技术栈

| 组件 | 选型 | 说明 |
|---|---|---|
| Embedding 模型 | bge-m3（智源 BAAI） | 国产开源，中文语义理解强 |
| 推理引擎 | Ollama | 本地运行，免费 |
| 向量数据库 | ChromaDB | 轻量嵌入式，纯 Python |
| 文档解析 | python-docx + pdfplumber | 开源工具 |

## License

MIT
