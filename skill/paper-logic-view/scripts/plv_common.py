"""paper-logic-view 脚本共用的部分：读 PDF 文字、归一化、原文定位、检查规则。

只用 Python 标准库。读 PDF 文字时依次尝试：pdftotext（poppler）→ pypdf → pdfminer.six。
归一化和查找顺序与 templates/viewer.html 里的 JS 保持一致。
"""
import shutil
import subprocess
import unicodedata

TYPES = {
    "claim": "主张", "evidence": "证据", "method": "方法", "definition": "定义",
    "assumption": "前提", "problem": "问题", "background": "背景", "limitation": "局限",
}
LINK_TYPES = {"supports": "支撑", "indirect": "间接", "answers": "填坑", "qualifies": "限定", "conflicts": "打架"}
ANN_KEYS = {"id", "page", "quote", "type", "importance", "note", "external", "implicit", "text", "anchor", "first_used_page"}
LINK_KEYS = {"from", "to", "type", "missing_step", "overreach", "alternative", "note"}


class NoExtractor(RuntimeError):
    pass


def extract_pages(pdf_path):
    """返回 (每页文字的列表, 用的工具名)。"""
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-raw", "-enc", "UTF-8", str(pdf_path), "-"],
                             capture_output=True, check=True).stdout.decode("utf-8", "replace")
        pages = out.split("\f")
        if pages and not pages[-1].strip():
            pages = pages[:-1]
        return pages, "pdftotext"
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(pdf_path))
        return [(p.extract_text() or "") for p in reader.pages], "pypdf"
    except ImportError:
        pass
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        from pdfminer.pdfpage import PDFPage  # type: ignore
        with open(pdf_path, "rb") as f:
            n = sum(1 for _ in PDFPage.get_pages(f))
        return [extract_text(str(pdf_path), page_numbers=[i]) for i in range(n)], "pdfminer.six"
    except ImportError:
        pass
    raise NoExtractor("读不了 PDF 文字：请装 poppler（提供 pdftotext）或者 `pip install pypdf`")


def _keep(ch):
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N")


def norm(s):
    out = []
    for ch in unicodedata.normalize("NFKC", s or "").lower():
        if _keep(ch):
            out.append(ch)
    return "".join(out)


class Locator:
    def __init__(self, pages):
        self.page_start = []
        parts = []
        n = 0
        for t in pages:
            self.page_start.append(n)
            s = norm(t)
            parts.append(s)
            n += len(s)
        self.page_start.append(n)
        self.hay = "".join(parts)
        self.n = len(pages)

    def page_of(self, i):
        lo, hi = 0, self.n - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.page_start[mid] <= i:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    def locate(self, quote, page=None):
        """返回 dict：found(bool)、approx(bool)、page(int)、reason(str)。"""
        q = norm(quote)
        if len(q) < 6:
            return {"found": False, "reason": "引用太短，或者只有公式、符号"}
        H, P, n = self.hay, self.page_start, self.n
        ranges = []
        if page and 1 <= page <= n:
            pg = page - 1
            ranges.append((P[pg], P[pg + 1]))
            ranges.append((P[max(0, pg - 1)], P[min(n, pg + 2)]))
        ranges.append((0, len(H)))
        for s, e in ranges:
            i = H.find(q, s)
            if 0 <= i < e:
                return {"found": True, "approx": False, "page": self.page_of(i), "pos": i}
        L = len(q)
        if L >= 30:
            k = min(20, L // 3)
            mid = int(L / 2 - k / 2)
            pairs = [(0, L - k), (mid, L - k), (0, mid)]
            for s, e in ranges:
                for ao, bo in pairs:
                    A, B = q[ao:ao + k], q[bo:bo + k]
                    i = H.find(A, s)
                    while 0 <= i < e:
                        exp = i + (bo - ao)
                        j = H.find(B, max(i + k, exp - int(L * 0.3)))
                        if 0 <= j <= exp + L * 0.3:
                            return {"found": True, "approx": True, "page": self.page_of(max(0, i - ao)), "pos": max(0, i - ao)}
                        i = H.find(A, i + 1)
        return {"found": False, "reason": "在 PDF 里找不到这段文字"}


def validate(data):
    """结构检查。返回 (errors, warnings)，都是字符串列表。"""
    E, W = [], []
    if not isinstance(data, dict):
        return ["顶层必须是一个对象"], []
    if data.get("schema") != "paper-logic-view/1":
        E.append('schema 必须写 "paper-logic-view/1"')
    if data.get("mode", "read") not in ("read", "write"):
        E.append('mode 只能是 "read" 或 "write"')
    anns = data.get("annotations")
    links = data.get("links")
    if not isinstance(anns, list) or not anns:
        E.append("annotations 必须是非空数组")
        anns = []
    if not isinstance(links, list):
        E.append("links 必须是数组（没有连线就写 []）")
        links = []
    extra = set(data) - {"schema", "mode", "paper", "summary", "annotations", "links"}
    if extra:
        W.append("顶层有不认识的字段：" + "、".join(sorted(extra)))
    ids = {}
    for i, a in enumerate(anns):
        tag = f"annotations[{i}]"
        if not isinstance(a, dict):
            E.append(f"{tag} 不是对象")
            continue
        aid = a.get("id")
        if not aid or not isinstance(aid, str):
            E.append(f"{tag} 没有 id")
            continue
        tag = f"标注 {aid}"
        if aid in ids:
            E.append(f"{tag}：id 重复")
        ids[aid] = a
        bad = set(a) - ANN_KEYS
        if bad:
            E.append(f"{tag}：不认识的字段 " + "、".join(sorted(bad)))
        if a.get("type") not in TYPES:
            E.append(f"{tag}：type \"{a.get('type')}\" 不在 {list(TYPES)} 里")
        if a.get("importance") not in (1, 2, 3):
            E.append(f"{tag}：importance 只能是 1、2、3")
        if a.get("implicit"):
            if a.get("type") != "assumption":
                E.append(f"{tag}：implicit 只能配 type=assumption")
            if not a.get("text"):
                E.append(f"{tag}：隐含前提要填 text")
            if not a.get("anchor"):
                E.append(f"{tag}：隐含前提要填 anchor")
        else:
            q = a.get("quote")
            if not q or not isinstance(q, str):
                E.append(f"{tag}：没有 quote")
            else:
                if "..." in q or "…" in q:
                    W.append(f"{tag}：quote 里有省略号，拼接的引用多半定位不上，建议拆成两条")
                if len(q) > 300:
                    W.append(f"{tag}：quote 有 {len(q)} 个字符，太长，建议只引最关键的一句")
            if not isinstance(a.get("page"), int) or a.get("page", 0) < 1:
                E.append(f"{tag}：page 要填从 1 开始的整数")
        fu = a.get("first_used_page")
        if fu is not None and (a.get("type") != "definition" or not isinstance(fu, int)):
            W.append(f"{tag}：first_used_page 只给 definition 用，且要是整数")
    for a in anns:
        if isinstance(a, dict) and a.get("implicit") and a.get("anchor") and a["anchor"] not in ids:
            E.append(f"标注 {a.get('id')}：anchor {a['anchor']} 不存在")
    for i, l in enumerate(links):
        tag = f"links[{i}]"
        if not isinstance(l, dict):
            E.append(f"{tag} 不是对象")
            continue
        tag = f"连线 {l.get('from')} → {l.get('to')}"
        bad = set(l) - LINK_KEYS
        if bad:
            E.append(f"{tag}：不认识的字段 " + "、".join(sorted(bad)))
        for end in ("from", "to"):
            if l.get(end) not in ids:
                E.append(f"{tag}：{end} 指向不存在的标注")
        if l.get("from") == l.get("to"):
            E.append(f"{tag}：自己连自己")
        if l.get("type") not in LINK_TYPES:
            E.append(f"{tag}：type \"{l.get('type')}\" 不在 {list(LINK_TYPES)} 里")
        if l.get("type") == "indirect" and not l.get("missing_step"):
            E.append(f"{tag}：indirect 必须写 missing_step（缺的是哪一步）")
        if l.get("type") == "answers" and ids.get(l.get("to"), {}).get("type") != "problem":
            W.append(f"{tag}：answers 的 to 应该是 problem")
    n3 = sum(1 for a in anns if isinstance(a, dict) and a.get("importance") == 3)
    if anns and not (3 <= n3 <= 25):
        W.append(f"重要度 3 的主线标注有 {n3} 条，一般 5–15 条比较合适")
    return E, W


def rules(data, ranks=None, pages_of=None, jump_pages=3, jump_gap=0):
    """计算 A 档（除空转）和 B 档问题。返回 [(规则名, 说明)]。"""
    anns = {a["id"]: a for a in data.get("annotations", []) if isinstance(a, dict) and a.get("id")}
    links = [l for l in data.get("links", []) if isinstance(l, dict) and l.get("from") in anns and l.get("to") in anns]
    inc = {k: [] for k in anns}
    out = {k: [] for k in anns}
    for l in links:
        inc[l["to"]].append(l)
        out[l["from"]].append(l)
    sup = lambda l: l.get("type") in ("supports", "indirect")
    R = []
    short = lambda i: f"{TYPES.get(anns[i].get('type'), '?')} {i}"
    for a in anns.values():
        i = a["id"]
        if a.get("type") == "claim" and a.get("importance", 0) >= 2 and not any(sup(l) for l in inc[i]):
            R.append(("只靠引用" if a.get("external") else "坑没填", f"{short(i)}：" + (f"靠 {a['external']}" if a.get("external") else "没有任何箭头撑它")))
        if a.get("type") == "problem" and not any(l.get("type") == "answers" for l in inc[i]):
            R.append(("坑没填", f"{short(i)}：这个问题 / 承诺后文没有回答"))
        if a.get("type") == "evidence" and not out[i]:
            R.append(("孤立证据", f"{short(i)}：没有撑任何东西"))
        if a.get("implicit"):
            R.append(("隐含前提", f"{i}：{a.get('text', '')}"))
        fu, pg = a.get("first_used_page"), a.get("page")
        if a.get("type") == "definition" and isinstance(fu, int) and isinstance(pg, int) and fu < pg:
            R.append(("先用后定义", f"{short(i)}：第 {fu} 页就用了，第 {pg} 页才定义"))
    for l in links:
        tag = f"{short(l['from'])} → {short(l['to'])}"
        if l.get("type") == "indirect":
            R.append(("跳帧", f"{tag}：缺一步：{l.get('missing_step', '')}"))
        elif (l.get("type") == "supports" and pages_of and ranks
              and l["from"] in ranks and l["to"] in ranks and ranks[l["from"]] < ranks[l["to"]]):
            # 只查"理由在前、结论在后"的；结论在前、证据在后是正常的先挖坑后填坑
            pf, pt = pages_of.get(l["from"]), pages_of.get(l["to"])
            gap = ranks[l["to"]] - ranks[l["from"]] - 1
            far = []
            if pf and pt and abs(pf - pt) >= jump_pages:
                far.append(f"跨了 {abs(pf - pt)} 页")
            if jump_gap and gap >= jump_gap:
                far.append(f"中间隔了 {gap} 条标注")
            if far:
                R.append(("跳帧", f"{tag}：隔太远：" + "，".join(far)))
        if l.get("overreach"):
            R.append(("说过头", f"{tag}：{l['overreach']}"))
        if l.get("alternative"):
            R.append(("替代解释", f"{tag}：{l['alternative']}"))
        if l.get("type") == "conflicts":
            R.append(("前后打架", f"{tag}：{l.get('note', '')}"))
    for a in anns.values():
        if a.get("type") != "claim" or a.get("importance") != 3 or not any(sup(l) for l in inc[a["id"]]):
            continue
        seen, st, ok = {a["id"]}, [a["id"]], False
        while st and not ok:
            x = st.pop()
            for l in inc[x]:
                f = l["from"]
                if not sup(l) or f in seen:
                    continue
                if anns[f].get("type") == "evidence" or anns[f].get("external"):
                    ok = True
                    break
                seen.add(f)
                st.append(f)
        if not ok:
            R.append(("空中楼阁", f"{short(a['id'])}：往回追了 {len(seen) - 1} 条，都不是证据"))
    color, found = {}, set()

    def dfs(u, path):
        color[u] = 1
        path.append(u)
        for l in out[u]:
            if not sup(l):
                continue
            v = l["to"]
            if color.get(v) == 1:
                cyc = path[path.index(v):]
                key = ",".join(sorted(cyc))
                if key not in found:
                    found.add(key)
                    R.append(("循环论证", " → ".join(cyc) + " → 回到起点"))
            elif not color.get(v):
                dfs(v, path)
        path.pop()
        color[u] = 2

    for k in anns:
        if not color.get(k):
            dfs(k, [])
    return R
