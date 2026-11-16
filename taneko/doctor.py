# -*- coding: utf-8 -*-
"""doctor：检查这台机器能不能跑 taneko，缺什么就说怎么装。只读，不改任何东西。"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import core

# 每个平台的装法：win32 / darwin / 其他（Linux）
HOW = {
    "ffmpeg": ("winget install Gyan.FFmpeg", "brew install ffmpeg", "sudo apt install ffmpeg"),
    "yt-dlp": ("winget install yt-dlp.yt-dlp", "brew install yt-dlp", "python3 -m pip install -U yt-dlp"),
    "deno": ("winget install DenoLand.Deno", "brew install deno", "curl -fsSL https://deno.land/install.sh | sh"),
}


def _how(tool: str, platform: str) -> str:
    win, mac, linux = HOW[tool]
    return win if platform == "win32" else mac if platform == "darwin" else linux


def _version(cmd: list):
    """运行 `cmd --version`，返回第一行；运行不了返回 None。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (r.stdout or r.stderr).strip().splitlines()
    return line[0][:80] if r.returncode == 0 and line else None


def checks(platform: str = sys.platform) -> list:
    """[(是否必须, 名字, 通过与否, 说明)]。"""
    out = []
    py = sys.version_info
    out.append((True, "Python", py >= (3, 11), "%d.%d.%d" % py[:3] if py >= (3, 11) else
                "%d.%d，需要 3.11 或更新（推荐 3.12）" % py[:2]))
    for exe, ver, tool in (("ffmpeg", "-version", "ffmpeg"), ("ffprobe", "-version", "ffmpeg"), ("deno", "--version", "deno")):
        p = shutil.which(exe)
        v = _version([p, ver]) if p else None
        out.append((True, exe, bool(v), v or "没找到。装法：%s" % _how(tool, platform)))
    v = _version(core.tool_cmd("yt-dlp", "yt_dlp") + ["--version"])
    out.append((True, "yt-dlp", bool(v), v or "没找到。装法：%s" % _how("yt-dlp", platform)))
    out.append((False, "项目目录", core.PROJECTS.is_dir(), "%s%s" % (core.PROJECTS, "" if core.PROJECTS.is_dir() else
                "，还没有：第一次 taneko init 时会自动建。想放别处，设环境变量 TANEKO_PROJECTS")))
    try:
        home = Path(core.load_config("asr").get("home", ""))
    except core.Fail:
        home = Path("")
    whisper = any((home / "venv" / s / n).exists() for s, n in (("Scripts", "python.exe"), ("bin", "python")))
    out.append((False, "Whisper 转写（字幕，实验性）", whisper, str(home) if whisper else
                "没找到 venv（taneko/config/asr.json 的 home）。只下载视频不需要它"))
    tool = core.VENDOR / "llm-subtrans"
    out.append((False, "llm-subtrans 翻译（字幕，实验性）", tool.is_dir(), str(tool) if tool.is_dir() else
                "没找到。只下载视频不需要它"))
    return out


def cmd_doctor(a=None) -> int:
    rows = checks()
    for must, name, ok, msg in rows:
        print("%s %s：%s" % ("✓" if ok else ("✗" if must else "–"), name, msg))
    bad = [name for must, name, ok, _ in rows if must and not ok]
    print("\n%s" % ("下载需要的工具都齐了。" if not bad else "还缺：%s。装好后再运行 %s doctor。" % ("、".join(bad), core.COMMAND)))
    return core.EXIT_FAIL if bad else core.EXIT_OK
