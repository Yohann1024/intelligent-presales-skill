#!/usr/bin/env python3
"""
知识库入库脚本 — 将历史标书文件清洗、分段、向量化后存入 ChromaDB

支持格式：.docx, .pdf, .txt, .md, .png, .jpg, .jpeg, .bmp, .tiff
用法：
    python ingest.py /path/to/bid/documents
    python ingest.py /path/to/bid/documents --reset  # 清空重建
"""

import os
import sys
import json
import hashlib
import argparse
import re
from pathlib import Path
from typing import Optional

import requests
import chromadb
import pdfplumber
import fitz  # PyMuPDF — PDF 页面渲染为图片
from PIL import Image
import io

# python-docx 的包名是 docx
from docx import Document as DocxDocument

# OCR 引擎（基于 PaddleOCR 模型，轻量 ONNX 推理）
_ocr_engine = None

def get_ocr_engine():
    """延迟加载 OCR 引擎（首次调用时初始化，约 2-3 秒）"""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
        print("  🔤 OCR 引擎已加载")
    return _ocr_engine

# ============================================================
# 配置
# ============================================================

OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "bge-m3"
CHUNK_SIZE = 800       # 每段大约 800 字
CHUNK_OVERLAP = 100    # 段落重叠 100 字
BATCH_SIZE = 32        # 每批向量化的段落数

SKILL_DIR = Path(__file__).resolve().parent.parent
KB_DIR = SKILL_DIR / "knowledge_base"
VECTORDB_DIR = KB_DIR / "vectordb"
DOCS_DIR = KB_DIR / "documents"
METADATA_FILE = KB_DIR / "metadata.json"

SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}

# 扫描件判定阈值：每页文字少于此字数视为扫描页
SCAN_PAGE_TEXT_THRESHOLD = 50

# ============================================================
# 文件解析
# ============================================================

def parse_docx(file_path: Path) -> str:
    """解析 Word 文档，保留章节结构"""
    doc = DocxDocument(str(file_path))
    parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # 识别标题层级
        if para.style and para.style.name.startswith("Heading"):
            level = para.style.name.replace("Heading ", "").replace("Heading", "1")
            try:
                level = int(level)
            except ValueError:
                level = 1
            parts.append(f"\n{'#' * level} {text}\n")
        else:
            parts.append(text)
    return "\n".join(parts)


def ocr_image(image) -> str:
    """
    对图片执行 OCR 识别
    image: PIL.Image 对象，或图片文件路径
    """
    ocr = get_ocr_engine()
    if isinstance(image, (str, Path)):
        result, _ = ocr(str(image))
    else:
        # PIL Image → bytes
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        result, _ = ocr(buf.getvalue())

    if not result:
        return ""
    # result 格式: [[box, text, confidence], ...]
    lines = [item[1] for item in result]
    return "\n".join(lines)


def parse_image(file_path: Path) -> str:
    """解析图片文件（OCR）"""
    print(f"    🔤 OCR 识别中: {file_path.name}")
    text = ocr_image(file_path)
    if not text.strip():
        print(f"    ⚠️  OCR 未识别到文字")
        return ""
    char_count = len(text)
    print(f"    ✓  识别到 {char_count} 个字符")
    return text


def parse_pdf(file_path: Path) -> str:
    """
    解析 PDF 文件：
    - 文本型 PDF：直接提取文字
    - 扫描型 PDF：渲染为图片后 OCR
    - 混合型 PDF：逐页判断，自动切换
    """
    parts = []
    text_pages = 0
    ocr_pages = 0

    # 先用 pdfplumber 尝试提取文本
    with pdfplumber.open(str(file_path)) as pdf:
        page_texts = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            page_texts.append((i, text.strip()))

    # 再用 PyMuPDF 对扫描页做 OCR
    pdf_doc = fitz.open(str(file_path))

    for i, text in page_texts:
        if len(text) >= SCAN_PAGE_TEXT_THRESHOLD:
            # 文本型页面，直接用
            parts.append(f"[第{i+1}页]\n{text}")
            text_pages += 1
        else:
            # 扫描型页面，渲染为图片再 OCR
            try:
                page = pdf_doc[i]
                # 渲染为 2x 分辨率图片
                mat = fitz.Matrix(2, 2)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text = ocr_image(img)
                if ocr_text.strip():
                    parts.append(f"[第{i+1}页 OCR]\n{ocr_text}")
                    ocr_pages += 1
            except Exception as e:
                print(f"    ⚠️  第{i+1}页 OCR 失败: {e}")

    pdf_doc.close()

    if ocr_pages > 0:
        print(f"    📊 文本页: {text_pages}, OCR页: {ocr_pages}")

    return "\n\n".join(parts)


def parse_text(file_path: Path) -> str:
    """解析纯文本/Markdown 文件"""
    return file_path.read_text(encoding="utf-8")


def parse_file(file_path: Path) -> Optional[str]:
    """根据文件类型自动选择解析器"""
    ext = file_path.suffix.lower()
    try:
        if ext == ".docx":
            return parse_docx(file_path)
        elif ext == ".pdf":
            return parse_pdf(file_path)
        elif ext in (".txt", ".md"):
            return parse_text(file_path)
        elif ext in IMAGE_EXTENSIONS:
            return parse_image(file_path)
        else:
            print(f"  ⚠️  不支持的格式: {ext}，跳过 {file_path.name}")
            return None
    except Exception as e:
        print(f"  ❌ 解析失败: {file_path.name} — {e}")
        return None


# ============================================================
# 文本分段
# ============================================================

def smart_chunk(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    智能分段：
    1. 优先按标题分段
    2. 段落过长则按句子切分
    3. 段落间保留重叠
    """
    # 先按标题拆分大段
    sections = re.split(r'\n(?=#{1,4}\s)', text)

    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 提取段落标题
        title_match = re.match(r'^(#{1,4})\s+(.+)', section)
        section_title = title_match.group(2).strip() if title_match else ""

        # 如果段落不超过 chunk_size，整段作为一个 chunk
        if len(section) <= chunk_size:
            chunks.append({
                "text": section,
                "section": section_title,
            })
            continue

        # 段落过长，按句子切分
        sentences = re.split(r'(?<=[。！？\.\!\?])', section)
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(current_chunk) + len(sentence) <= chunk_size:
                current_chunk += sentence
            else:
                if current_chunk:
                    chunks.append({
                        "text": current_chunk,
                        "section": section_title,
                    })
                    # 保留重叠部分
                    if overlap > 0 and len(current_chunk) > overlap:
                        current_chunk = current_chunk[-overlap:] + sentence
                    else:
                        current_chunk = sentence
                else:
                    # 单个句子就超长，强制加入
                    chunks.append({
                        "text": sentence,
                        "section": section_title,
                    })
                    current_chunk = ""

        if current_chunk:
            chunks.append({
                "text": current_chunk,
                "section": section_title,
            })

    return chunks


# ============================================================
# 向量化
# ============================================================

def embed_texts(texts: list[str]) -> list[list[float]]:
    """调用 Ollama bge-m3 生成向量"""
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": EMBED_MODEL,
            "input": texts
        }, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"]
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接 Ollama，请确保 Ollama 正在运行（运行 ollama serve）")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 向量化失败: {e}")
        sys.exit(1)


# ============================================================
# 自动打标签
# ============================================================

# 标签关键词映射
TAG_KEYWORDS = {
    "架构设计": ["架构", "微服务", "SOA", "分层", "中台"],
    "安全方案": ["安全", "等保", "加密", "防护", "漏洞", "密码", "认证", "审计"],
    "数据库": ["数据库", "MySQL", "Oracle", "PostgreSQL", "Redis", "MongoDB"],
    "云计算": ["云计算", "云平台", "IaaS", "PaaS", "SaaS", "容器", "K8s", "Docker"],
    "网络方案": ["网络", "防火墙", "VPN", "负载均衡", "带宽", "交换机"],
    "实施方案": ["实施", "部署", "里程碑", "验收", "交付", "上线"],
    "运维保障": ["运维", "监控", "告警", "应急", "巡检", "备份"],
    "培训方案": ["培训", "教学", "操作手册", "使用指南"],
    "项目管理": ["项目管理", "进度", "风险", "质量", "沟通"],
    "人工智能": ["AI", "人工智能", "机器学习", "深度学习", "大模型", "NLP"],
    "大数据": ["大数据", "Hadoop", "Spark", "数据仓库", "数据治理", "ETL"],
    "政务信息化": ["政务", "电子政务", "一网通办", "数字政府"],
    "智慧城市": ["智慧城市", "城市大脑", "IoT", "物联网"],
    "教育信息化": ["教育", "校园", "教学", "学生", "教师"],
    "医疗信息化": ["医疗", "医院", "HIS", "电子病历", "PACS"],
}


def auto_tag(text: str) -> list[str]:
    """基于关键词自动打标签"""
    tags = []
    for tag, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                tags.append(tag)
                break
    return tags


def detect_project_type(text: str) -> str:
    """检测项目类型"""
    type_keywords = {
        "政务信息化": ["政务", "电子政务", "政府", "数字政府", "一网通办"],
        "智慧城市": ["智慧城市", "城市大脑", "智慧交通", "智慧社区"],
        "教育信息化": ["教育", "校园", "教学平台", "在线学习"],
        "医疗信息化": ["医疗", "医院", "HIS", "电子病历", "健康"],
        "公安/军队": ["公安", "军队", "部队", "武警", "消防"],
        "金融科技": ["银行", "金融", "保险", "证券", "支付"],
        "企业信息化": ["ERP", "OA", "CRM", "企业", "办公"],
        "通用IT项目": [],
    }
    for ptype, keywords in type_keywords.items():
        for kw in keywords:
            if kw in text:
                return ptype
    return "通用IT项目"


# ============================================================
# 主流程
# ============================================================

def file_hash(file_path: Path) -> str:
    """计算文件 MD5，用于去重"""
    return hashlib.md5(file_path.read_bytes()).hexdigest()


def load_metadata() -> dict:
    """加载已处理文件的元数据"""
    if METADATA_FILE.exists():
        return json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    return {"files": {}}


def save_metadata(metadata: dict):
    """保存元数据"""
    METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def scan_files(source_dir: Path) -> list[Path]:
    """扫描目录下所有支持的文件"""
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(source_dir.rglob(f"*{ext}"))
    return sorted(files)


def ingest(source_dir: Path, reset: bool = False):
    """主入库流程"""
    print(f"\n📂 扫描目录: {source_dir}")

    # 确保目录存在
    VECTORDB_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # 初始化 ChromaDB
    client = chromadb.PersistentClient(path=str(VECTORDB_DIR))

    if reset:
        print("🗑️  清空并重建知识库...")
        try:
            client.delete_collection("bid_documents")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name="bid_documents",
        metadata={"description": "历史投标文件知识库"}
    )

    # 加载元数据
    metadata = load_metadata() if not reset else {"files": {}}

    # 扫描文件
    files = scan_files(source_dir)
    print(f"📄 发现 {len(files)} 个文件\n")

    if not files:
        print("⚠️  未发现支持的文件（.docx, .pdf, .txt, .md, .png, .jpg, .jpeg, .bmp, .tiff）")
        return

    total_chunks = 0
    processed_files = 0
    skipped_files = 0

    for file_path in files:
        fhash = file_hash(file_path)

        # 跳过已处理的文件
        if fhash in metadata.get("files", {}):
            print(f"  ⏩ 已入库，跳过: {file_path.name}")
            skipped_files += 1
            continue

        print(f"  📖 处理中: {file_path.name}")

        # 1. 解析文件
        content = parse_file(file_path)
        if not content:
            continue

        # 2. 保存清洗后的文档
        clean_name = file_path.stem + ".md"
        clean_path = DOCS_DIR / clean_name
        clean_path.write_text(content, encoding="utf-8")

        # 3. 智能分段
        chunks = smart_chunk(content)
        if not chunks:
            print(f"    ⚠️  无有效内容段落")
            continue

        # 4. 检测项目类型
        project_type = detect_project_type(content[:3000])

        # 5. 批量向量化 + 入库
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            texts = [c["text"] for c in batch]

            # 向量化
            embeddings = embed_texts(texts)

            # 准备 ChromaDB 数据
            ids = [f"{fhash}_{i+j}" for j in range(len(batch))]
            documents = texts
            metadatas = []
            for j, chunk in enumerate(batch):
                tags = auto_tag(chunk["text"])
                metadatas.append({
                    "source_file": file_path.name,
                    "section": chunk["section"],
                    "tags": ",".join(tags) if tags else "",
                    "project_type": project_type,
                    "chunk_index": i + j,
                    "word_count": len(chunk["text"]),
                })

            # 写入 ChromaDB
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )

        # 记录元数据
        metadata["files"][fhash] = {
            "filename": file_path.name,
            "path": str(file_path),
            "chunks": len(chunks),
            "project_type": project_type,
        }

        total_chunks += len(chunks)
        processed_files += 1
        print(f"    ✅ {len(chunks)} 个段落已入库")

    # 保存元数据
    save_metadata(metadata)

    # 统计
    print(f"\n{'='*50}")
    print(f"✅ 入库完成!")
    print(f"   新处理文件: {processed_files}")
    print(f"   跳过文件:   {skipped_files}")
    print(f"   新增段落:   {total_chunks}")
    print(f"   知识库总量: {collection.count()} 条")
    print(f"   向量数据库: {VECTORDB_DIR}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="历史标书入库工具")
    parser.add_argument("source_dir", help="标书文件目录路径")
    parser.add_argument("--reset", action="store_true", help="清空知识库重新入库")

    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    if not source_dir.is_dir():
        print(f"❌ 目录不存在: {source_dir}")
        sys.exit(1)

    ingest(source_dir, reset=args.reset)


if __name__ == "__main__":
    main()
