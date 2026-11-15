# -*- coding: utf-8 -*-
"""check：中英字幕条数、时间轴一一对应，字数不超读速。"""
from __future__ import annotations

from pathlib import Path

from ..core import Stage, die
from ..project import project_dir
from ..srt import parse_srt, read_cues


def problems(en: list, zh: list) -> list:
    out = []
    if len(en) != len(zh):
        out.append("条数不一致：en=%d，zh=%d" % (len(en), len(zh)))
    for i, (e, z) in enumerate(zip(en, zh), 1):
        if abs(e["start"] - z["start"]) > 0.02 or abs(e["end"] - z["end"]) > 0.02:
            out.append("#%d 时间轴被改动" % i)
        if not z["text"].strip():
            out.append("#%d 中文为空" % i)
        dur = max(z["end"] - z["start"], 0.01)
        if len(z["text"].replace("\n", "")) / dur > 16:
            out.append("#%d 太长，读不完（%d 字 / %.1f 秒）" % (i, len(z["text"]), dur))
    return out


def cmd_check(a) -> None:
    d = project_dir(a.project)
    en, zh = read_cues(d / "en.srt"), read_cues(d / "zh.srt")
    ps = problems(en, zh)
    if ps:
        print("发现 %d 个问题：" % len(ps))
        for p in ps[:40]:
            print("  - " + p)
        if len(ps) > 40:
            print("  ……其余 %d 个略" % (len(ps) - 40))
        die("字幕检查没有通过（见上面的问题）")
    print("检查通过：%d 条，时间轴一一对应。" % len(zh))


def done(d: Path, meta: dict) -> bool:
    en, zh = d / "en.srt", d / "zh.srt"
    if not (en.exists() and zh.exists()):
        return False
    return not problems(parse_srt(en.read_text("utf-8-sig")), parse_srt(zh.read_text("utf-8-sig")))


STAGE = Stage("check", "检查中英字幕对应", done, cmd_check)
