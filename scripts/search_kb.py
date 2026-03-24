#!/usr/bin/env python3
"""
知识库检索脚本 — 从 ChromaDB 中检索与查询最相关的历史标书内容

用法：
    python search_kb.py --query "系统架构设计要求微服务" --top_k 5
    python search_kb.py --query "安全等保三级" --tag "安全方案"
    python search_kb.py --stats  # 查看知识库统计
"""

import os
import sys
import json
import argparse
from pathlib import Path

import requests
import chromadb

# ============================================================
# 配置
# ============================================================

OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "bge-m3"

SKILL_DIR = Path(__file__).resolve().parent.parent
KB_DIR = SKILL_DIR / "knowledge_base"
VECTORDB_DIR = KB_DIR / "vectordb"
METADATA_FILE = KB_DIR / "metadata.json"


# ============================================================
# 向量化
# ============================================================

def embed_query(text: str) -> list[float]:
    """将查询文本向量化"""
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": EMBED_MODEL,
            "input": [text]
        }, timeout=60)
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接 Ollama，请确保 Ollama 正在运行")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 向量化失败: {e}")
        sys.exit(1)


# ============================================================
# 检索
# ============================================================

def search(query: str, top_k: int = 5, tag_filter: str = None, project_type: str = None) -> list[dict]:
    """
    检索知识库

    Args:
        query: 检索查询文本
        top_k: 返回最相关的 K 条结果
        tag_filter: 按标签过滤（可选）
        project_type: 按项目类型过滤（可选）

    Returns:
        匹配结果列表
    """
    if not VECTORDB_DIR.exists():
        print("❌ 知识库不存在，请先运行 ingest.py 入库")
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(VECTORDB_DIR))

    try:
        collection = client.get_collection("bid_documents")
    except Exception:
        print("❌ 知识库集合不存在，请先运行 ingest.py 入库")
        sys.exit(1)

    if collection.count() == 0:
        print("⚠️  知识库为空，请先运行 ingest.py 入库")
        return []

    # 构建过滤条件
    where_filter = None
    conditions = []

    if tag_filter:
        conditions.append({"tags": {"$contains": tag_filter}})
    if project_type:
        conditions.append({"project_type": project_type})

    if len(conditions) == 1:
        where_filter = conditions[0]
    elif len(conditions) > 1:
        where_filter = {"$and": conditions}

    # 向量化查询
    query_embedding = embed_query(query)

    # 检索
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    # 整理结果
    matches = []
    if results and results["documents"] and results["documents"][0]:
        for i in range(len(results["documents"][0])):
            distance = results["distances"][0][i]
            # ChromaDB 返回的是 L2 距离，转换为相似度分数
            similarity = 1 / (1 + distance)

            matches.append({
                "content": results["documents"][0][i],
                "similarity": round(similarity, 4),
                "source_file": results["metadatas"][0][i].get("source_file", ""),
                "section": results["metadatas"][0][i].get("section", ""),
                "tags": results["metadatas"][0][i].get("tags", ""),
                "project_type": results["metadatas"][0][i].get("project_type", ""),
            })

    return matches


def get_stats() -> dict:
    """获取知识库统计信息"""
    if not VECTORDB_DIR.exists():
        return {"status": "知识库不存在"}

    client = chromadb.PersistentClient(path=str(VECTORDB_DIR))
    try:
        collection = client.get_collection("bid_documents")
    except Exception:
        return {"status": "知识库集合不存在"}

    # 加载元数据
    metadata = {}
    if METADATA_FILE.exists():
        metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))

    files_info = metadata.get("files", {})
    project_types = {}
    for fhash, info in files_info.items():
        pt = info.get("project_type", "未知")
        project_types[pt] = project_types.get(pt, 0) + 1

    return {
        "total_chunks": collection.count(),
        "total_files": len(files_info),
        "project_types": project_types,
        "files": [
            {"filename": info["filename"], "chunks": info["chunks"], "type": info["project_type"]}
            for info in files_info.values()
        ]
    }


# ============================================================
# 输出格式化
# ============================================================

def format_results(matches: list[dict], query: str) -> str:
    """格式化检索结果，可直接供 LLM 使用"""
    if not matches:
        return f"未找到与 \"{query}\" 相关的历史内容。"

    output_parts = [f"## 知识库检索结果\n\n查询: \"{query}\"\n匹配数量: {len(matches)}\n"]

    for i, match in enumerate(matches, 1):
        output_parts.append(f"""
---
### 结果 {i}（相似度: {match['similarity']:.1%}）

- **来源**: {match['source_file']}
- **章节**: {match['section'] or '（无）'}
- **标签**: {match['tags'] or '（无）'}
- **项目类型**: {match['project_type']}

**内容**:
{match['content'][:1000]}{'...' if len(match['content']) > 1000 else ''}
""")

    return "\n".join(output_parts)


def format_json(matches: list[dict]) -> str:
    """JSON 格式输出"""
    return json.dumps(matches, ensure_ascii=False, indent=2)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="知识库检索工具")
    parser.add_argument("--query", "-q", help="检索查询文本")
    parser.add_argument("--top_k", "-k", type=int, default=5, help="返回结果数量（默认5）")
    parser.add_argument("--tag", "-t", help="按标签过滤")
    parser.add_argument("--project_type", "-p", help="按项目类型过滤")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--stats", action="store_true", help="查看知识库统计")

    args = parser.parse_args()

    if args.stats:
        stats = get_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    if not args.query:
        parser.error("请提供 --query 或 --stats 参数")

    # 执行检索
    matches = search(
        query=args.query,
        top_k=args.top_k,
        tag_filter=args.tag,
        project_type=args.project_type,
    )

    # 输出结果
    if args.json:
        print(format_json(matches))
    else:
        print(format_results(matches, args.query))


if __name__ == "__main__":
    main()
