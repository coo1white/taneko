# -*- coding: utf-8 -*-
"""按播放列表下载一段（HLS，例如 X）：m3u8 播放列表记着每一片的时长，就是现成的索引。
只下覆盖这一段的分片，一片一个文件；断了重跑时跳过已下完的分片。下完按顺序拼成一个文件。"""
from __future__ import annotations

import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .progress import Bar
from .ranges import NoIndex, Refused, _retry


def opener(headers=None, timeout=60):
    """返回 fetch(url) -> bytes；403 变成 Refused（等一等再试，见 ranges.REFUSED_WAITS）。"""
    def fetch(url):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=dict(headers or {})), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise Refused("服务器拒绝了这个地址（HTTP 403）") from e
            raise
    return fetch


def playlist(text: str, base: str):
    """解析媒体播放列表，返回 (init 地址或 None, [(开始秒, 时长秒, 地址)])。
    直播（没有 ENDLIST）、加密、按字节范围存放的分片都不支持，抛 NoIndex。"""
    if "#EXT-X-STREAM-INF" in text:
        raise NoIndex("这是总播放列表，不是某一个格式的")
    if "#EXT-X-ENDLIST" not in text:
        raise NoIndex("播放列表还没结束（可能是直播）")
    init, segs, t, dur = None, [], 0.0, None
    for line in (l.strip() for l in text.splitlines()):
        if line.startswith("#EXT-X-KEY") and "METHOD=NONE" not in line:
            raise NoIndex("分片加密了")
        if line.startswith("#EXT-X-BYTERANGE") or (line.startswith("#EXT-X-MAP") and "BYTERANGE" in line):
            raise NoIndex("分片按字节范围存放，暂不支持")
        if line.startswith("#EXT-X-MAP"):
            m = re.search(r'URI="([^"]+)"', line)
            init = urllib.parse.urljoin(base, m.group(1)) if m else None
        elif line.startswith("#EXTINF:"):
            dur = float(line[8:].split(",")[0])
        elif line and not line.startswith("#"):
            segs.append((t, dur or 0.0, urllib.parse.urljoin(base, line)))
            t, dur = t + (dur or 0.0), None
    if len(segs) < 2:
        raise NoIndex("播放列表里不到 2 片")
    return init, segs


def pick(segs: list, a: float, b: float) -> list:
    """覆盖 [a, b] 秒的分片序号。"""
    return [i for i, (t, d, _) in enumerate(segs) if t + d > a and t < b]


def download(fetch, url: str, dst: Path, a: float, b: float, log=print, retries: int = 3, out=None) -> float:
    """把覆盖 [a, b] 的分片下到 dst（init 在最前）。返回第一片在播放列表里的开始时间（秒）。
    分片先存在 dst.segs/ 里，一片一个文件；dst.json 记着这一段对应的分片，重跑时跳过已下完的。"""
    state = dst.with_name(dst.name + ".json")
    if dst.exists() and state.exists():
        return json.loads(state.read_text("utf-8"))["t0"]
    init, segs = playlist(_retry(lambda *_: fetch(url), 0, 0, retries).decode("utf-8", "replace"), url)
    idx = pick(segs, a, b)
    if not idx:
        raise NoIndex("播放列表里没有 %.0f～%.0f 秒" % (a, b))
    want = {"n": len(segs), "first": idx[0], "last": idx[-1], "t0": segs[idx[0]][0]}
    folder = dst.with_name(dst.name + ".segs")
    if state.exists() and json.loads(state.read_text("utf-8")) != want:
        shutil.rmtree(folder, ignore_errors=True)     # 播放列表变了，已下的分片对不上
    folder.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(want), "utf-8")
    jobs = ([("init", init)] if init else []) + [("%06d" % i, segs[i][2]) for i in idx]
    have = sum(1 for n, _ in jobs if (folder / n).exists())
    if have:
        log("  接着上次下：已有 %d / %d 片" % (have, len(jobs)))
    bar, got = Bar(len(jobs), "片", out), 0
    for k, (name, u) in enumerate(jobs, 1):
        p = folder / name
        if not p.exists():
            tmp = p.with_name(name + ".tmp")
            tmp.write_bytes(_retry(lambda *_, u=u: fetch(u), 0, 0, retries))
            got += tmp.stat().st_size
            tmp.replace(p)
        bar.update(k, got)
    bar.close()
    part = dst.with_name(dst.name + ".part")
    with open(part, "wb") as out:
        for name, _ in jobs:
            out.write((folder / name).read_bytes())
    part.replace(dst)
    shutil.rmtree(folder, ignore_errors=True)
    return want["t0"]
