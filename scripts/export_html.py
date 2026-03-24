#!/usr/bin/env python3
"""
将 Markdown 方案文件导出为带样式的 HTML（支持表格和 Mermaid 图表）

用法：
    python export_html.py /path/to/方案.md
    python export_html.py /path/to/方案.md -o output.html
"""

import re
import sys
import argparse
from pathlib import Path

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad: true, theme: 'default'}});</script>
<style>
  body {{
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 40px 30px;
    color: #1a1a1a;
    line-height: 1.8;
    font-size: 15px;
  }}
  h1 {{ font-size: 28px; border-bottom: 3px solid #2563eb; padding-bottom: 10px; color: #1e3a5f; }}
  h2 {{ font-size: 22px; color: #2563eb; margin-top: 35px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }}
  h3 {{ font-size: 18px; color: #374151; }}
  h4 {{ font-size: 16px; color: #4b5563; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 14px;
  }}
  th {{
    background: #2563eb;
    color: white;
    padding: 10px 14px;
    text-align: left;
    font-weight: 600;
  }}
  td {{
    padding: 9px 14px;
    border-bottom: 1px solid #e5e7eb;
  }}
  tr:nth-child(even) {{ background: #f8fafc; }}
  tr:hover {{ background: #eff6ff; }}
  code {{
    background: #f1f5f9;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
    color: #e11d48;
  }}
  pre {{
    background: #1e293b;
    color: #e2e8f0;
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.5;
  }}
  pre code {{
    background: none;
    color: inherit;
    padding: 0;
  }}
  blockquote {{
    border-left: 4px solid #2563eb;
    margin: 16px 0;
    padding: 12px 20px;
    background: #eff6ff;
    border-radius: 0 8px 8px 0;
  }}
  blockquote.warning {{
    border-left-color: #f59e0b;
    background: #fffbeb;
  }}
  blockquote.important {{
    border-left-color: #7c3aed;
    background: #f5f3ff;
  }}
  blockquote.caution {{
    border-left-color: #ef4444;
    background: #fef2f2;
  }}
  blockquote.tip {{
    border-left-color: #10b981;
    background: #ecfdf5;
  }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 30px 0; }}
  .mermaid {{ text-align: center; margin: 20px 0; }}
  ul, ol {{ padding-left: 24px; }}
  li {{ margin: 4px 0; }}
  strong {{ color: #1e3a5f; }}

  @media print {{
    body {{ padding: 20px; font-size: 12px; }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 18px; page-break-before: auto; }}
    table {{ font-size: 11px; }}
    pre {{ font-size: 11px; }}
    .mermaid {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>
{content}
</body>
</html>"""


def md_to_html(md_text: str) -> str:
    """简易 Markdown → HTML 转换"""
    lines = md_text.split('\n')
    html_parts = []
    in_code = False
    in_table = False
    in_list = False
    code_lang = ""
    code_content = []
    table_rows = []
    list_items = []
    list_type = "ul"

    i = 0
    while i < len(lines):
        line = lines[i]

        # 代码块
        if line.strip().startswith('```'):
            if not in_code:
                in_code = True
                code_lang = line.strip()[3:].strip()
                code_content = []
            else:
                if code_lang == 'mermaid':
                    html_parts.append(f'<div class="mermaid">\n{"chr(10)".join(code_content)}\n</div>')
                else:
                    escaped = '\n'.join(code_content).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html_parts.append(f'<pre><code>{escaped}</code></pre>')
                in_code = False
                code_lang = ""
            i += 1
            continue

        if in_code:
            code_content.append(line)
            i += 1
            continue

        # 关闭列表
        if in_list and not (line.strip().startswith('- ') or line.strip().startswith('* ') or re.match(r'^\d+\.\s', line.strip())):
            tag = list_type
            items_html = ''.join(f'<li>{item}</li>' for item in list_items)
            html_parts.append(f'<{tag}>{items_html}</{tag}>')
            in_list = False
            list_items = []

        # 关闭表格
        if in_table and not line.strip().startswith('|'):
            header = table_rows[0]
            body = table_rows[2:] if len(table_rows) > 2 else []
            thead = '<tr>' + ''.join(f'<th>{c.strip()}</th>' for c in header.strip('|').split('|')) + '</tr>'
            tbody = ''
            for row in body:
                cells = row.strip('|').split('|')
                tbody += '<tr>' + ''.join(f'<td>{inline_format(c.strip())}</td>' for c in cells) + '</tr>'
            html_parts.append(f'<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>')
            in_table = False
            table_rows = []

        # 空行
        if not line.strip():
            i += 1
            continue

        # 表格
        if line.strip().startswith('|'):
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(line)
            i += 1
            continue

        # 列表
        if line.strip().startswith('- ') or line.strip().startswith('* '):
            if not in_list:
                in_list = True
                list_type = "ul"
                list_items = []
            list_items.append(inline_format(line.strip()[2:]))
            i += 1
            continue

        if re.match(r'^\d+\.\s', line.strip()):
            if not in_list:
                in_list = True
                list_type = "ol"
                list_items = []
            list_items.append(inline_format(re.sub(r'^\d+\.\s', '', line.strip())))
            i += 1
            continue

        # 标题
        heading = re.match(r'^(#{1,6})\s+(.+)', line)
        if heading:
            level = len(heading.group(1))
            text = inline_format(heading.group(2))
            html_parts.append(f'<h{level}>{text}</h{level}>')
            i += 1
            continue

        # 水平线
        if re.match(r'^---+$', line.strip()):
            html_parts.append('<hr>')
            i += 1
            continue

        # 引用块 (GitHub alerts)
        if line.strip().startswith('>'):
            quote_lines = []
            alert_type = ""
            while i < len(lines) and lines[i].strip().startswith('>'):
                content = lines[i].strip()[1:].strip()
                alert_match = re.match(r'\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', content)
                if alert_match:
                    alert_type = alert_match.group(1).lower()
                else:
                    quote_lines.append(content)
                i += 1
            cls = f' class="{alert_type}"' if alert_type else ''
            html_parts.append(f'<blockquote{cls}>{"<br>".join(inline_format(l) for l in quote_lines if l)}</blockquote>')
            continue

        # 普通段落
        html_parts.append(f'<p>{inline_format(line)}</p>')
        i += 1

    # 关闭未结束的列表/表格
    if in_list:
        items_html = ''.join(f'<li>{item}</li>' for item in list_items)
        html_parts.append(f'<{list_type}>{items_html}</{list_type}>')
    if in_table and table_rows:
        header = table_rows[0]
        body = table_rows[2:] if len(table_rows) > 2 else []
        thead = '<tr>' + ''.join(f'<th>{c.strip()}</th>' for c in header.strip('|').split('|')) + '</tr>'
        tbody = ''
        for row in body:
            cells = row.strip('|').split('|')
            tbody += '<tr>' + ''.join(f'<td>{inline_format(c.strip())}</td>' for c in cells) + '</tr>'
        html_parts.append(f'<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>')

    return '\n'.join(html_parts)


def inline_format(text: str) -> str:
    """行内格式：粗体、斜体、行内代码、链接"""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    return text


def main():
    parser = argparse.ArgumentParser(description="Markdown → HTML 导出")
    parser.add_argument("input", help="输入 Markdown 文件路径")
    parser.add_argument("-o", "--output", help="输出 HTML 文件路径")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"❌ 文件不存在: {input_path}")
        sys.exit(1)

    md_text = input_path.read_text(encoding="utf-8")

    # 去掉 YAML frontmatter
    md_text = re.sub(r'^---\n.*?\n---\n', '', md_text, flags=re.DOTALL)

    # 提取标题
    title_match = re.search(r'^#\s+(.+)', md_text, re.MULTILINE)
    title = title_match.group(1) if title_match else input_path.stem

    # 转换
    content = md_to_html(md_text)
    html = HTML_TEMPLATE.format(title=title, content=content)

    # 输出
    output_path = Path(args.output) if args.output else input_path.with_suffix('.html')
    output_path.write_text(html, encoding="utf-8")
    print(f"✅ 已导出: {output_path}")


if __name__ == "__main__":
    main()
