"""段落级结构特征对比：相邻句结构同款、段首零主语评论。

用法：
    python3 scripts/check-structure.py --human <目录...> --ai <目录...>

为什么单独一个脚本：这两项的分母是段数，不是字数。
用「每千字」会被结构差异带偏——AI 平均每篇 10 个小标题、人类 1-2 个，
按字数算问句小标题会虚高 30 倍，换成占小标题比例后差异消失。
涉及结构元素的指标，分母必须是同类元素的总数。
"""
import re
import sys
from pathlib import Path

# 段首评论语：省掉回指成分时读者要翻回上一段
COMMENT = re.compile(
    r"^(?:听起来|看起来|看上去|听上去|说白了|说到底|换句话说|意味着|值得注意|"
    r"不难看出|细看|再看|回过头看|问题在于|原因在于|结果是|有意思的是|"
    r"更重要的是|关键在于|真正的)"
)
# 回指成分：把上文接回来
ANAPHOR = re.compile(r"^(?:这|那|其|此|上面|前面|刚才|以上|该|它|他|她|它们|他们|同样|类似|相比|反过来|但|不过|所以|因此|于是|而|另|除此|与此)")
# 比喻起段（对照项，实测人类更多）
METAPHOR = re.compile(r"^(?:像|就像|好比|好像|仿佛|如同|这就像)")


def paragraphs(text):
    out = []
    for p in text.split("\n"):
        p = p.strip()
        if len(p) < 8 or p.startswith(("#", "|", "```", ">", "- ", "* ", "!", "[")):
            continue
        out.append(p)
    return out


def signature(sent):
    """句子结构指纹：逗号数、有无冒号、有无括号、长度档"""
    return (sent.count("，"), "：" in sent, ("（" in sent or "(" in sent), len(sent) // 15)


def isomorphic(para, n):
    """段内是否有连续 n 句结构指纹相同"""
    sents = [s.strip() for s in re.split(r"[。！？]", para) if len(s.strip()) > 10]
    hits = 0
    for i in range(len(sents) - n + 1):
        sigs = [signature(s) for s in sents[i:i + n]]
        if all(s == sigs[0] for s in sigs) and sigs[0][0] >= 1:
            hits += 1
    return hits


def measure(texts):
    total = iso2 = iso3 = zero = meta = nonfirst = 0
    for t in texts:
        ps = paragraphs(t)
        total += len(ps)
        for i, p in enumerate(ps):
            iso2 += isomorphic(p, 2)
            iso3 += isomorphic(p, 3)
            if METAPHOR.match(p):
                meta += 1
            if i == 0:
                continue
            nonfirst += 1
            if COMMENT.match(p) and not ANAPHOR.match(p):
                zero += 1
    return {
        "段数": total,
        "连续两句同构/百段": iso2 / total * 100 if total else 0,
        "连续三句同构/百段": iso3 / total * 100 if total else 0,
        "段首零主语评论/非首段%": zero / nonfirst * 100 if nonfirst else 0,
        "比喻起段/百段(对照)": meta / total * 100 if total else 0,
    }


def load(dirs):
    out = []
    for d in dirs:
        for f in Path(d).rglob("*.md"):
            if f.parent.name == "_meta":
                continue
            try:
                out.append(f.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                continue
    return out


def load_valid_groups(dirs, label):
    texts, groups = [], []
    for i, d in enumerate(dirs, 1):
        loaded = load([d])
        # 只筛选文档；保留已有的段落提取和结构测量方式。
        valid = [t for t in loaded
                 if any(re.search(r"[一-鿿]", p) for p in paragraphs(t))]
        if not valid:
            print(f"跳过{label}第 {i} 组：没有可统计的中文段落。", file=sys.stderr)
            continue
        if len(valid) < len(loaded):
            print(f"跳过{label}第 {i} 组中 {len(loaded) - len(valid)} 篇"
                  "没有可统计中文段落的文档。", file=sys.stderr)
        texts.extend(valid)
        groups.append(measure(valid))
    return texts, groups


def main():
    human, ai, cur = [], [], None
    for a in sys.argv[1:]:
        if a == "--human":
            cur = human
        elif a == "--ai":
            cur = ai
        elif cur is not None:
            cur.append(a)
    if not human or not ai:
        print(__doc__, file=sys.stderr)
        return 2

    human_texts, groups = load_valid_groups(human, "人类")
    ai_texts, _ = load_valid_groups(ai, "AI")
    if not human_texts or not ai_texts:
        missing = "、".join(label for label, texts in
                           (("人类", human_texts), ("AI", ai_texts)) if not texts)
        print(f"无法统计：{missing}语料没有可统计的中文段落。", file=sys.stderr)
        return 1
    hm = measure(human_texts)
    am = measure(ai_texts)

    keys = [k for k in am if k != "段数"]
    print(f"AI {am['段数']} 段，人类 {hm['段数']} 段\n")
    head = f"{'指标':<26}{'AI':>8}{'人类':>8}{'倍率':>7}{'稳定性':>8}"
    print(head)
    print("-" * len(head))
    for k in keys:
        a, h = am[k], hm[k]
        r = a / h if h > 0.001 else float("inf")
        # 各组数值只用来算稳定性，不打印
        vals = [m[k] for m in groups]
        spread = max(vals) / max(min(vals), 0.01)
        print(f"{k:<26}{a:>8.2f}{h:>8.2f}{r:>6.2f}×{'稳定' if spread <= 5 else '波动大':>8}")


if __name__ == "__main__":
    sys.exit(main())
