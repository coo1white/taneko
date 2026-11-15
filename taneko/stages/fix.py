# -*- coding: utf-8 -*-
"""fix：按 meta.json 的 translate.corrections 批量改 en.srt。"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..core import Stage, die
from ..project import load_meta, project_dir
from ..srt import read_cues, write_srt


def cmd_fix(a) -> None:
    """精校第一步：按 meta.json 里 translate.corrections（错词->正确词）批量改 en.srt（首次会备份成 en.srt.orig）。"""
    d = project_dir(a.project)
    meta = load_meta(d)
    corr = meta.get("translate", {}).get("corrections", {})
    if not corr:
        die("meta.json 的 translate.corrections 是空的。先运行 terms 找出听错的名字，再把 {\"错词\": \"正确词\"} 填进去")
    src = d / "en.srt"
    cues = read_cues(src)
    if not cues:
        die("en.srt 不存在或是空的")
    if not (d / "en.srt.orig").exists():
        shutil.copyfile(src, d / "en.srt.orig")
    total = 0
    for wrong, right in corr.items():
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(wrong) + r"(?![A-Za-z0-9])")
        n = 0
        for c in cues:
            c["text"], k = pat.subn(right, c["text"])
            n += k
        print("  %s -> %s：%d 处" % (wrong, right, n))
        total += n
    write_srt(cues, src)
    print("共改了 %d 处，已写回 en.srt（原文备份：en.srt.orig）" % total)


def skip(meta: dict) -> bool:
    return not (meta.get("translate", {}) or {}).get("corrections")  # 没有要改的词，不算做过


def done(d: Path, meta: dict) -> bool:
    return skip(meta) or (d / "en.srt.orig").exists()


STAGE = Stage("fix", "按 corrections 批量改英文字幕", done, cmd_fix, skip=skip)
