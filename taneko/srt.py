# -*- coding: utf-8 -*-
"""SRT 读写与 YouTube 自动字幕清洗。只用标准库。"""
from __future__ import annotations

import re
from pathlib import Path

from .core import die

TIME_RE = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


TAG_RE = re.compile(r"<[^>]+>")


def _sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_srt(text: str) -> list:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = TIME_RE.search(line)
            if m:
                g = m.groups()
                body = "\n".join(x.strip() for x in lines[i + 1:] if x.strip())
                cues.append({"start": _sec(*g[:4]), "end": _sec(*g[4:]), "text": body})
                break
    return cues


def fmt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def write_srt(cues: list, path: Path) -> None:
    out = []
    for i, c in enumerate(cues, 1):
        out.append("%d\n%s --> %s\n%s\n" % (i, fmt_ts(c["start"]), fmt_ts(c["end"]), c["text"]))
    path.write_text("\n".join(out), "utf-8")


def read_cues(path: Path) -> list:
    if not path.exists():
        die("找不到 %s" % path)
    return parse_srt(path.read_text("utf-8-sig"))


def clean_auto(cues: list) -> list:
    """清洗 YouTube 自动字幕（滚动式两行字幕）：每行取首次出现→最后出现，消除重叠，过短的行并入下一行。"""
    items, cur = [], {}
    for c in cues:
        lines = [TAG_RE.sub("", l).strip() for l in c["text"].split("\n")]
        nxt = {}
        for l in (x for x in lines if x):
            it = cur.get(l)
            if it is None:
                it = {"start": c["start"], "end": c["end"], "text": l}
                items.append(it)
            else:
                it["end"] = max(it["end"], c["end"])
            nxt[l] = it
        cur = nxt
    for a, b in zip(items, items[1:]):
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    out, carry = [], None
    for it in items:
        if carry:
            it = {"start": carry["start"], "end": max(it["end"], carry["end"]),
                  "text": carry["text"] + " " + it["text"]}
            carry = None
        if it["end"] - it["start"] < 0.5:
            carry = it
            continue
        out.append(it)
    if carry:
        out.append(carry)
    return out
