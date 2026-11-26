#!/usr/bin/env python3
"""按页抽出 PDF 的文字，给模型读论文、逐字引用用。

用法：
    python3 pdf_text.py 论文.pdf              # 打印到屏幕
    python3 pdf_text.py 论文.pdf -o 论文.txt   # 写进文件

每页前面有一行"=== 第 N 页 ==="，N 就是 logic.json 里 page 要填的物理页码。
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from plv_common import NoExtractor, extract_pages  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="按页抽出 PDF 文字")
    ap.add_argument("pdf", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path)
    a = ap.parse_args()
    if not a.pdf.is_file():
        sys.exit(f"找不到文件：{a.pdf}")
    try:
        pages, tool = extract_pages(a.pdf)
    except NoExtractor as e:
        sys.exit(str(e))
    text = "".join(f"=== 第 {i} 页 ===\n{t.strip()}\n\n" for i, t in enumerate(pages, 1))
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"已写出 {a.out}：{len(pages)} 页，{len(text)} 字符（用 {tool} 抽取）", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
