# -*- coding: utf-8 -*-
"""项目：projects/<名字>/ 文件夹和里面的 meta.json。"""
from __future__ import annotations

import json
from pathlib import Path

from .core import PROJECTS, die

def project_dir(name: str) -> Path:
    d = PROJECTS / name
    if not (d / "meta.json").exists():
        die("找不到项目 %s（应有 %s）" % (name, d / "meta.json"))
    return d


def load_meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text("utf-8-sig"))


def save_meta(d: Path, meta: dict) -> None:
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", "utf-8")


def find_video(d: Path, meta: dict):
    files = [f for f in d.glob(meta.get("video_glob", "*.mkv")) if not f.name.endswith(".part")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def source_srt_name(meta: dict) -> str:
    sub = meta.get("subtitle", {}) or {}
    lang = sub.get("asr_language") or sub.get("source_lang") or "en"
    return "zh.srt" if str(lang).startswith("zh") else "en.srt"


def names() -> list:
    """所有项目的名字（有 meta.json、不以 _ 开头的文件夹）。"""
    return sorted(p.name for p in PROJECTS.iterdir()
                  if p.is_dir() and not p.name.startswith("_") and (p / "meta.json").exists())
