# -*- coding: utf-8 -*-
"""subs：抓取平台自带的字幕（人工字幕优先，没有就抓自动字幕并清洗）。"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..core import Stage, die, run, tool_cmd
from ..project import load_meta, project_dir, source_srt_name
from ..srt import clean_auto, parse_srt, write_srt


def cmd_subs(a) -> None:
    d = project_dir(a.project)
    meta = load_meta(d)
    lang = meta.get("subtitle", {}).get("source_lang", "en")
    raw = d / "sub_raw"
    shutil.rmtree(str(raw), ignore_errors=True)
    raw.mkdir()
    base = tool_cmd("yt-dlp", "yt_dlp") + [
        "--skip-download", "--no-playlist", "--convert-subs", "srt",
        "-o", str(raw / "%(id)s.%(ext)s")]
    auto = False
    run(base + ["--write-subs", "--sub-langs", "%s,%s-US,%s-GB" % (lang, lang, lang),
                meta["source_url"]], log=d / "logs" / "subs_manual.log")
    files = sorted(raw.glob("*.srt"))
    if not files:
        print("没有人工字幕，改抓自动字幕……")
        auto = True
        run(base + ["--write-auto-subs", "--sub-langs", lang, meta["source_url"]],
            log=d / "logs" / "subs_auto.log")
        files = sorted(raw.glob("*.srt"))
    if not files:
        die("没抓到字幕。可以改用 Whisper / Subtitle Edit 从音频生成 en.srt，放进项目目录再继续。")
    cues = parse_srt(files[0].read_text("utf-8-sig"))
    if auto:
        cues = clean_auto(cues)
    write_srt(cues, d / "en.srt")
    print("已生成 %s（%d 条，%s）" % (d / "en.srt", len(cues), "自动字幕，已清洗" if auto else "人工字幕"))
    print("下一步：把 en.srt 译成 zh.srt（时间轴保持不变），再运行 check。")


def done(d: Path, meta: dict) -> bool:
    f = d / source_srt_name(meta)
    return f.exists() and f.stat().st_size > 0


STAGE = Stage("subs", "抓取 YouTube 字幕", done, cmd_subs)
