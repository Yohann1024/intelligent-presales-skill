#!/usr/bin/env python3
"""
环境检查与初始化脚本 — 首次使用前自动检测并引导安装所有依赖

用法：
    python setup.py          # 检查环境
    python setup.py --fix    # 自动修复缺失的依赖
"""

import subprocess
import sys
import shutil
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REQUIREMENTS = SKILL_DIR / "requirements.txt"

# ANSI 颜色
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg):
    print(f"  {GREEN}✅ {msg}{RESET}")


def fail(msg):
    print(f"  {RED}❌ {msg}{RESET}")


def warn(msg):
    print(f"  {YELLOW}⚠️  {msg}{RESET}")


def header(msg):
    print(f"\n{BOLD}{'='*50}")
    print(f"  {msg}")
    print(f"{'='*50}{RESET}\n")


def check_python():
    """检查 Python 版本"""
    v = sys.version_info
    if v.major == 3 and v.minor >= 9:
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    else:
        fail(f"Python {v.major}.{v.minor} — 需要 Python 3.9+")
        return False


def check_ollama():
    """检查 Ollama 是否安装且运行"""
    # 检查安装
    if not shutil.which("ollama"):
        fail("Ollama 未安装")
        print(f"    安装方法:")
        print(f"      macOS:  brew install ollama")
        print(f"      Linux:  curl -fsSL https://ollama.com/install.sh | sh")
        return False

    # 检查版本
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
        version = result.stdout.strip()
        ok(f"Ollama 已安装 ({version})")
    except Exception:
        ok("Ollama 已安装")

    # 检查是否运行
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            ok("Ollama 服务运行中")
            return True
        else:
            warn("Ollama 已安装但服务未启动，请运行: ollama serve")
            return False
    except Exception:
        warn("Ollama 已安装但服务未启动，请运行: ollama serve")
        return False


def check_bge_m3():
    """检查 bge-m3 模型是否已拉取"""
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            if any("bge-m3" in name for name in model_names):
                ok("bge-m3 Embedding 模型已就绪")
                return True
            else:
                fail("bge-m3 模型未下载")
                print(f"    下载命令: ollama pull bge-m3")
                return False
    except Exception:
        warn("无法检查模型状态（Ollama 未运行）")
        return False


def check_python_packages():
    """检查 Python 依赖包"""
    packages = {
        "chromadb": "chromadb",
        "docx": "python-docx",
        "pdfplumber": "pdfplumber",
        "requests": "requests",
        "rapidocr_onnxruntime": "rapidocr-onnxruntime",
        "fitz": "PyMuPDF",
        "PIL": "Pillow",
    }
    all_ok = True
    missing = []

    for import_name, pip_name in packages.items():
        try:
            __import__(import_name)
            ok(f"{pip_name}")
        except ImportError:
            fail(f"{pip_name} 未安装")
            missing.append(pip_name)
            all_ok = False

    if missing:
        print(f"\n    安装命令: pip install {' '.join(missing)}")
        print(f"    或: pip install -r {REQUIREMENTS}")

    return all_ok


def check_knowledge_base():
    """检查知识库状态"""
    vectordb_dir = SKILL_DIR / "knowledge_base" / "vectordb"
    metadata_file = SKILL_DIR / "knowledge_base" / "metadata.json"

    if not vectordb_dir.exists() or not metadata_file.exists():
        warn("知识库为空 — 尚未导入任何历史标书")
        print(f"    入库命令: python scripts/ingest.py /path/to/你的标书目录")
        return False

    import json
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        file_count = len(metadata.get("files", {}))
        total_chunks = sum(f.get("chunks", 0) for f in metadata["files"].values())
        ok(f"知识库已有 {file_count} 个文件，{total_chunks} 个段落")
        return True
    except Exception:
        warn("知识库元数据损坏")
        return False


def auto_fix():
    """自动修复缺失的依赖"""
    header("自动修复")

    # 1. 安装 Python 包
    print("📦 安装 Python 依赖...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)

    # 2. 拉取 bge-m3
    if shutil.which("ollama"):
        print("\n📥 拉取 bge-m3 模型...")
        subprocess.run(["ollama", "pull", "bge-m3"], check=True)

    print(f"\n{GREEN}✅ 自动修复完成！请重新运行 python setup.py 检查。{RESET}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="智能售前 Skill 环境检查")
    parser.add_argument("--fix", action="store_true", help="自动修复缺失的依赖")
    args = parser.parse_args()

    if args.fix:
        auto_fix()
        return

    header("智能售前 Skill — 环境检查")

    results = {}

    print("📋 1. Python 环境")
    results["python"] = check_python()

    print("\n📋 2. Ollama 推理引擎")
    results["ollama"] = check_ollama()

    print("\n📋 3. Embedding 模型")
    results["model"] = check_bge_m3()

    print("\n📋 4. Python 依赖包")
    results["packages"] = check_python_packages()

    print("\n📋 5. 知识库状态")
    results["kb"] = check_knowledge_base()

    # 汇总
    header("检查结果")

    all_passed = all(results.values())
    if all_passed:
        print(f"{GREEN}🎉 所有检查通过！可以开始使用。{RESET}")
        print(f"\n  使用方式: 在 Claude Code 中直接说")
        print(f'  👉 "请帮我根据这份招标文件写投标方案"')
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"{YELLOW}部分检查未通过: {', '.join(failed)}{RESET}")
        print(f"\n  自动修复: python scripts/setup.py --fix")
        if not results.get("kb"):
            print(f"  导入标书: python scripts/ingest.py /path/to/标书目录")


if __name__ == "__main__":
    main()
