# -*- coding: utf-8 -*-
"""流程计划与阶段状态：每个阶段都能回答“我做完了吗”，run 据此跳过已完成的、在人工检查点停下。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import core, subtitle
from .download import _t2s

GATE_TERMS = "gate:terms"
GATE_SPOT = "gate:spot"

LABELS = {
    "fetch": "下载视频（可续传分片）",
    "asr": "本地 Whisper 转写",
    "subs": "抓取 YouTube 字幕",
    "terms": "找出可能听错的专有名词",
    GATE_TERMS: "【人工】校对术语，填 translate.corrections",
    "fix": "按 corrections 批量改英文字幕",
    "translate": "翻译成中文",
    "check": "检查中英字幕对应",
    GATE_SPOT: "【人工】抽查关键片段",
}


def is_gate(step: str) -> bool:
    return step.startswith("gate:")


def plan(meta: dict) -> list:
    sub = meta.get("subtitle", {}) or {}
    steps = ["fetch", "asr" if sub.get("method") == "asr" else "subs"]
    if str(sub.get("source_lang", "en")).startswith("zh"):
        return steps  # 原文已是中文，不需要翻译
    return steps + ["terms", GATE_TERMS, "fix", "translate", "check", GATE_SPOT]


def source_srt_name(meta: dict) -> str:
    sub = meta.get("subtitle", {}) or {}
    lang = sub.get("asr_language") or sub.get("source_lang") or "en"
    return "zh.srt" if str(lang).startswith("zh") else "en.srt"


def video_duration(path: Path):
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def expected_duration(meta: dict):
    """meta.section.download 形如 "4:13:00-5:08:00"；没有则返回 None（整条视频，不比时长）。"""
    dl = (meta.get("section", {}) or {}).get("download")
    if not dl:
        return None
    a, b = [_t2s(x) for x in dl.split("-")]
    return b - a


def is_done(step: str, d: Path, meta: dict) -> bool:
    if step == "fetch":
        v = core.find_video(d, meta)
        if not v or (d / "_parts").exists():
            return False
        exp = expected_duration(meta)
        dur = video_duration(v)
        if exp is None or dur is None:
            return True
        return dur >= exp - min(25.0, max(1.0, exp * 0.01))  # 容差：长视频 25 秒，短的按 1%
    if step in ("asr", "subs"):
        f = d / source_srt_name(meta)
        return f.exists() and f.stat().st_size > 0
    if step == "terms":
        return (d / "terms.txt").exists()
    if step == GATE_TERMS:
        return bool((meta.get("review", {}) or {}).get("terms"))
    if step == "fix":
        corr = (meta.get("translate", {}) or {}).get("corrections", {})
        return (not corr) or (d / "en.srt.orig").exists()
    if step == "translate":
        return (d / "zh.srt").exists()
    if step == "check":
        en, zh = d / "en.srt", d / "zh.srt"
        if not (en.exists() and zh.exists()):
            return False
        return not subtitle.problems(core.parse_srt(en.read_text("utf-8-sig")), core.parse_srt(zh.read_text("utf-8-sig")))
    if step == GATE_SPOT:
        return bool((meta.get("review", {}) or {}).get("spot"))
    raise KeyError(step)


def snapshot(d: Path, meta: dict) -> list:
    """[(步骤, 状态)]，状态：done / skip / next / todo。第一个没完成的是 next。"""
    out, found = [], False
    for s in plan(meta):
        if s == "fix" and not (meta.get("translate", {}) or {}).get("corrections"):
            out.append((s, "skip"))  # 没有要改的词，不算做过
        elif is_done(s, d, meta):
            out.append((s, "done"))
        elif not found:
            out.append((s, "next"))
            found = True
        else:
            out.append((s, "todo"))
    return out
