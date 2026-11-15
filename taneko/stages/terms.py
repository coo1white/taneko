# -*- coding: utf-8 -*-
"""terms：找出反复出现的专有名词，帮你发现听错的名字。"""
from __future__ import annotations

import re
from pathlib import Path

from ..core import Stage, die
from ..project import load_meta, project_dir
from ..srt import read_cues


def cmd_terms(a) -> None:
    """精校第二步：统计字幕里反复出现的专有名词（大写开头的词），帮你发现听错的人名、英雄名。结果存 terms.txt。"""
    from collections import Counter
    d = project_dir(a.project)
    meta = load_meta(d)
    cues = read_cues(d / "en.srt")
    if not cues:
        die("en.srt 不存在或是空的")
    known = {n.lower() for n in meta.get("translate", {}).get("names", [])}
    cnt = Counter()
    for c in cues:
        words = re.findall(r"[A-Za-z][A-Za-z'\-]*", c["text"].replace("\n", " "))
        for i, w in enumerate(words):
            prev_end = i == 0
            if w[0].isupper() and len(w) > 2 and not prev_end:
                cnt[w] += 1
    rows = [(w, n) for w, n in cnt.most_common() if n >= a.min and w.lower() not in known]
    lines = ["%4d  %s" % (n, w) for w, n in rows]
    (d / "terms.txt").write_text("\n".join(lines) + "\n", "utf-8")
    print("出现 %d 次以上、且不在 names 里的大写词（前 %d 个，全部见 terms.txt）：" % (a.min, a.top))
    print("\n".join(lines[:a.top]))
    print("\n看到拼错的名字（如 Chovie、Kiinn），填进 meta.json 的 translate.corrections，再运行 fix。")


def done(d: Path, meta: dict) -> bool:
    return (d / "terms.txt").exists()


def args(p) -> None:
    p.add_argument("--min", type=int, default=2); p.add_argument("--top", type=int, default=60)


STAGE = Stage("terms", "找出可能听错的专有名词", done, cmd_terms, args)
