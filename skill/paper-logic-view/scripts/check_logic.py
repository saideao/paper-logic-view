#!/usr/bin/env python3
"""校验 logic.json：结构对不对、原文引用能不能在 PDF 里找到，再预算一遍检查规则。

用法：
    python3 check_logic.py 论文.pdf logic.json
    python3 check_logic.py 论文.pdf logic.json --json   # 输出机器可读的结果

✗ 错误：必须改（引用找不到、id 重复、连线指向不存在的标注……），退出码 1。
~ 近似定位 / ! 提醒：建议改，不影响打包。
最后列出 A 档（"空转"除外，它要在页面上按版面算）和 B 档的问题，供你转告用户。
"""
import argparse
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from plv_common import Locator, NoExtractor, extract_pages, rules, validate  # noqa: E402


def check(pdf, data, jump_pages=3, jump_gap=0):
    errors, warns = validate(data)
    report = {"errors": errors, "warnings": warns, "approx": [], "unlocated": [], "rules": [], "extractor": None}
    try:
        pages, tool = extract_pages(pdf)
        report["extractor"] = tool
    except NoExtractor as e:
        report["warnings"].append(str(e) + "。这次跳过了引用检查，打开页面后看'没定位上'一组。")
        pages = None
    anns = [a for a in data.get("annotations", []) if isinstance(a, dict) and a.get("id")]
    pos, pages_of = {}, {}
    if pages is not None:
        loc = Locator(pages)
        for a in anns:
            if a.get("implicit") or not a.get("quote"):
                continue
            r = loc.locate(a["quote"], a.get("page"))
            if not r["found"]:
                report["unlocated"].append(a["id"])
                errors.append(f"标注 {a['id']}（第 {a.get('page')} 页）：{r['reason']}。引用：{a['quote'][:100]}")
                continue
            pos[a["id"]], pages_of[a["id"]] = r["pos"], r["page"]
            if r["approx"]:
                report["approx"].append(a["id"])
                warns.append(f"~ 标注 {a['id']}：近似定位（第 {r['page']} 页），引用和原文有出入，最好改成逐字一致")
            elif a.get("page") and r["page"] != a["page"]:
                warns.append(f"标注 {a['id']}：page 写的是 {a['page']}，实际在第 {r['page']} 页")
        for a in anns:
            if a.get("implicit") and a.get("anchor") in pos:
                pos[a["id"]] = pos[a["anchor"]] - 0.5
                pages_of[a["id"]] = pages_of[a["anchor"]]
    order = sorted(pos, key=pos.get)
    ranks = {k: i for i, k in enumerate(order)}
    report["rules"] = rules(data, ranks, pages_of, jump_pages, jump_gap)
    return report, len(pages) if pages is not None else None


def main():
    ap = argparse.ArgumentParser(description="校验 paper-logic-view 的标注数据")
    ap.add_argument("pdf", type=pathlib.Path)
    ap.add_argument("logic", type=pathlib.Path)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--jump-pages", type=int, default=3, help="理由在前、结论在后，跨几页以上算隔太远")
    ap.add_argument("--jump-gap", type=int, default=0, help="中间夹几条标注以上算隔太远；0 表示不看")
    a = ap.parse_args()
    for p in (a.pdf, a.logic):
        if not p.is_file():
            sys.exit(f"找不到文件：{p}")
    try:
        data = json.loads(a.logic.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"✗ {a.logic} 不是合法 JSON：{e}")
    rep, npages = check(a.pdf, data, a.jump_pages, a.jump_gap)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        sys.exit(1 if rep["errors"] else 0)

    anns = [x for x in data.get("annotations", []) if isinstance(x, dict)]
    types = Counter(x.get("type") for x in anns)
    print(f"PDF {npages if npages else '?'} 页（文字用 {rep['extractor'] or '—'} 抽取）；"
          f"标注 {len(anns)} 条，连线 {len(data.get('links', []))} 条；"
          + "、".join(f"{k} {v}" for k, v in types.most_common()))
    for e in rep["errors"]:
        print("✗", e)
    for w in rep["warnings"]:
        print(w if w.startswith("~") else "! " + w)
    located = len([x for x in anns if not x.get("implicit")]) - len(rep["unlocated"])
    print(f"\n定位：{located} 条找到（其中近似 {len(rep['approx'])} 条），{len(rep['unlocated'])} 条找不到")
    if rep["rules"]:
        print("\n检查规则（空转要打开页面才算）：")
        c = Counter(r for r, _ in rep["rules"])
        print("  " + "，".join(f"{k} {v}" for k, v in c.items()))
        for r, w in rep["rules"]:
            print(f"  [{r}] {w}")
    print("\n" + ("✗ 有错误，改完再打包。" if rep["errors"] else "✓ 通过，可以打包。"))
    sys.exit(1 if rep["errors"] else 0)


if __name__ == "__main__":
    main()
