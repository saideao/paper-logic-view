#!/usr/bin/env python3
"""把论文 PDF 和 logic.json 装进查看器模板，打包成单个 HTML。

用法：
    python3 pack_logic.py 论文.pdf logic.json -o 论文_逻辑图.html
    python3 pack_logic.py 论文.pdf logic.json --no-check   # 跳过校验（不推荐）

生成的页面只从 cdnjs 加载 PDF.js（版本写死），不请求别的地址，
可以双击打开，也可以直接当 claude.ai artifact 发布（≤16MB）。
"""
import argparse
import base64
import html
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TEMPLATE = HERE.parent / "templates" / "viewer.html"
LIMIT = 16 * 1024 * 1024
WARN = 12 * 1024 * 1024


def main():
    ap = argparse.ArgumentParser(description="打包成单个 HTML")
    ap.add_argument("pdf", type=pathlib.Path)
    ap.add_argument("logic", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path)
    ap.add_argument("--template", type=pathlib.Path, default=TEMPLATE)
    ap.add_argument("--no-check", action="store_true", help="跳过校验")
    a = ap.parse_args()
    for p in (a.pdf, a.logic, a.template):
        if not p.is_file():
            sys.exit(f"找不到文件：{p}")
    data = json.loads(a.logic.read_text(encoding="utf-8"))

    if not a.no_check:
        from check_logic import check
        rep, _ = check(a.pdf, data)
        if rep["errors"]:
            for e in rep["errors"]:
                print("✗", e, file=sys.stderr)
            sys.exit("有错误，先用 check_logic.py 查清楚再打包（或加 --no-check 强行打包，找不到的条目会列在'没定位上'）。")
        if rep["approx"]:
            print(f"提示：{len(rep['approx'])} 条是近似定位", file=sys.stderr)

    tpl = a.template.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    pdf_b64 = base64.b64encode(a.pdf.read_bytes()).decode("ascii")
    k1 = '<script type="application/json" id="logic-data">__LOGIC_DATA__</script>'
    k2 = '<script type="text/plain" id="pdf-data">__PDF_DATA__</script>'
    if k1 not in tpl or k2 not in tpl:
        sys.exit("模板里找不到数据占位，模板被改过了？")
    page = tpl.replace(k1, k1.replace("__LOGIC_DATA__", payload), 1)
    page = page.replace(k2, k2.replace("__PDF_DATA__", pdf_b64), 1)
    title = (data.get("paper") or {}).get("title")
    if title:
        page = re.sub(r"<title>.*?</title>", f"<title>{html.escape(title)} · 逻辑图</title>", page, count=1, flags=re.S)

    size = len(page.encode("utf-8"))
    if size > LIMIT:
        sys.exit(f"打包后 {size / 1e6:.1f} MB，超过 16 MB（artifact 上限）。PDF 本身大约要小于 11 MB，先压缩 PDF 再打包。")
    out = a.out or a.logic.with_name(a.pdf.stem + "_逻辑图.html")
    out.write_text(page, encoding="utf-8")
    if size > WARN:
        print(f"注意：{size / 1e6:.1f} MB，接近 16 MB 上限", file=sys.stderr)
    n = len(data.get("annotations", []))
    print(f"已生成 {out}（{n} 条标注，{len(data.get('links', []))} 条连线，{size / 1e6:.1f} MB）")


if __name__ == "__main__":
    main()
