# -*- coding: utf-8 -*-
"""项目：projects/<名字>/ 文件夹和里面的 meta.json。"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from .core import PROJECTS, die, span

DEPTH = 3  # 项目可以放在 projects/ 下最多 3 层，例如 projects/<系列>/<项目>/


def _hidden(d: Path) -> bool:
    return any(part.startswith(("_", ".")) for part in d.relative_to(PROJECTS).parts)


def _find(pattern: str) -> list:
    """projects/ 下各层里匹配 <pattern>/meta.json 的文件夹（跳过 _ 和 . 开头的）。"""
    if not PROJECTS.is_dir():
        return []
    hits = []
    for depth in range(DEPTH):
        hits += [m.parent for m in PROJECTS.glob("/".join(["*"] * depth + [pattern, "meta.json"]))]
    return sorted(d for d in hits if not _hidden(d))


def project_dir(ref: str) -> Path:
    """ref 是路径（含 / 或 \\，或 .）就直接用；否则按名字在 projects/ 下找。"""
    if ref in (".", "..") or "/" in ref or "\\" in ref:
        d = Path(ref).resolve()
        if not (d / "meta.json").exists():
            die("%s 里没有 meta.json，不是项目文件夹" % d)
        return d
    hits = _find(glob.escape(ref))
    if not hits:
        die("在 %s 下找不到项目 %s（找了 %d 层；也可以直接给项目文件夹的路径）" % (PROJECTS, ref, DEPTH))
    if len(hits) > 1:
        die("有 %d 个项目都叫 %s，请改给路径：%s" % (len(hits), ref, "、".join(map(str, hits))))
    return hits[0]


def create(name: str, url: str, section=None, browser=None) -> Path:
    """新建 projects/<name>/meta.json。name 可以带分组，例如 lol-worlds/game3。只下视频，不做字幕。"""
    parts = name.replace("\\", "/").strip("/").split("/")
    if len(parts) > DEPTH or any(not p or p in (".", "..") or p.startswith(("_", ".")) for p in parts):
        die("项目名 %s 不行：最多 %d 层，每层不能为空，也不能以 _ 或 . 开头" % (name, DEPTH))
    url = url.strip().strip("\"'“”‘’")   # 复制网址时常带上引号
    if not url.startswith(("http://", "https://")):
        die("%s 不像视频地址，要以 https:// 开头" % url)
    if section:
        span(section)
    same = _find(glob.escape(parts[-1]))
    if same:
        die("已经有叫 %s 的项目：%s。换个名字，或者直接 run 它" % (parts[-1], same[0]))
    d = PROJECTS.joinpath(*parts)
    meta = {"source_url": url, "section": {"name": parts[-1]}, "subtitle": {"method": "none"}}
    if section:
        meta["section"]["download"] = section
    if browser:
        meta["fetch"] = {"browser": browser}
    d.mkdir(parents=True, exist_ok=True)
    save_meta(d, meta)
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


def dirs() -> list:
    """所有项目文件夹。"""
    return _find("*")
