# -*- coding: utf-8 -*-
"""按索引下载一段：读文件自带的索引（MP4 的 sidx、WebM 的 Cues），算出这段时间在文件里的字节范围，
只下这些字节。用的是普通 HTTP Range 请求，按 10 MiB 一块顺序请求，收到多少写多少，断了从已下的字节接着下。

下来的文件 = 文件头（init）+ 覆盖这段时间的片段，ffmpeg 能直接读；起点是这段之前最近的片段边界。
没有索引的格式（HLS、直播等）抛 NoIndex，调用方改用分段下载。只用标准库，不引用 taneko 的其他模块。
"""
import json
import struct
import urllib.error
import urllib.request
from pathlib import Path

CHUNK = 10 * 1024 * 1024
HEAD = 1024 * 1024
REFUSED_WAITS = (2, 5, 10, 20)   # YouTube 新给的地址常常先回 403，等几秒就能读（2026-11-16 在 Windows 上实测）


class NoIndex(Exception):
    """这个格式不能按索引下载（不是错误，换分段下载即可）。"""


class Refused(OSError):
    """服务器拒绝了这个地址（HTTP 403），等过 REFUSED_WAITS 还是被拒。换一个新地址再试。"""


def getter(url: str, headers=None, timeout=60):
    """返回 get(a, b, sink=None)：读字节 a..b（含两端）。给了 sink 就边收边交给它（每次 64 KiB），否则返回全部字节。
    读过一次后，get.total 是服务器报的文件总大小（没报则为 None）。"""
    def get(a, b, sink=None):
        h, data, n = dict(headers or {}, Range="bytes=%d-%d" % (a, b)), [], 0
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                for blk in iter(lambda: r.read(65536), b""):
                    (sink or data.append)(blk)
                    n += len(blk)
                total = (r.headers.get("Content-Range") or "").rpartition("/")[2]
                if total.isdigit():
                    get.total = int(total)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise Refused("服务器拒绝了这个地址（HTTP 403）") from e
            raise
        if get.total and b >= get.total:
            b = get.total - 1   # 要的范围超过了文件末尾（文件比要读的头还小），服务器只给到末尾
        if n != b - a + 1:
            raise OSError("服务器返回了 %d 字节，应为 %d 字节" % (n, b - a + 1))
        return b"".join(data)
    get.total = None
    return get


# ---------- MP4：ftyp + moov 是文件头，sidx 列出每个片段的字节数和时长 ----------
def mp4_index(head: bytes):
    pos, init_end = 0, None
    while pos + 8 <= len(head):
        size, kind = struct.unpack(">I4s", head[pos:pos + 8])
        if size < 8:
            break
        if kind == b"moov":
            init_end = pos + size
        elif kind == b"sidx" and init_end:
            return init_end, _sidx(head[pos:pos + size], pos + size)
        pos += size
    raise NoIndex("MP4 文件开头没有 sidx 索引")


def _sidx(b: bytes, after: int):
    ver, ts = b[8], struct.unpack(">I", b[16:20])[0]
    if ver == 0:
        ept, first = struct.unpack(">II", b[20:28]); q = 28
    else:
        ept, first = struct.unpack(">QQ", b[20:36]); q = 36
    count = struct.unpack(">H", b[q + 2:q + 4])[0]
    q += 4
    off, t, out = after + first, ept, []
    for _ in range(count):
        ref, dur, _sap = struct.unpack(">III", b[q:q + 12]); q += 12
        if ref >> 31:
            raise NoIndex("sidx 是多级索引，暂不支持")
        out.append((t / ts, off))
        off += ref & 0x7FFFFFFF; t += dur
    return out


# ---------- WebM（EBML）：Cues 列出每个关键帧所在 Cluster 的时间和位置 ----------
def _vint(b, i, marker=False):
    first, n = b[i], 1
    while n <= 8 and not first & (0x80 >> (n - 1)):
        n += 1
    if n > 8:
        raise NoIndex("WebM 头部格式不对")
    v = first if marker else first & (0xFF >> n)
    for k in range(1, n):
        v = (v << 8) | b[i + k]
    if not marker and v == (1 << (7 * n)) - 1:
        raise NoIndex("WebM 元素长度未知（像直播流）")
    return v, i + n


def _children(b, i, end):
    while i < end:
        eid, j = _vint(b, i, True)
        size, k = _vint(b, j)
        yield eid, k, size
        i = k + size


def _uint(b, i, n):
    return int.from_bytes(b[i:i + n], "big")


def webm_index(head: bytes, more):
    """more(a, b) 用来补读 Cues 超出 head 的部分。返回 (文件头长度, [(秒, 字节位置)])。"""
    _, j = _vint(head, 0, True); s, k = _vint(head, j)
    _, j = _vint(head, k + s, True); _, seg = _vint(head, j)       # Segment 内容的起点
    scale, cues, i = 1000000, None, seg
    while i < len(head) - 12:
        eid, k = _vint(head, i, True); size, d = _vint(head, k)
        if eid == 0x1549A966:                                        # Info：TimecodeScale
            for e, p, n in _children(head, d, d + size):
                if e == 0x2AD7B1:
                    scale = _uint(head, p, n)
        elif eid == 0x1C53BB6B:                                      # Cues
            cues = (d, size)
            if d + size + 16 > len(head):
                head += more(len(head), d + size + 15)
        elif eid == 0x1F43B675:                                      # 第一个 Cluster：文件头到这里为止
            if not cues:
                break
            return i, _cue_points(head, cues[0], cues[0] + cues[1], seg, scale)
        i = d + size
    raise NoIndex("WebM 文件开头没有 Cues 索引")


def _cue_points(b, start, end, seg, scale):
    out = []
    for e, p, n in _children(b, start, end):
        if e != 0xBB:                                                # CuePoint
            continue
        t = pos = None
        for e2, p2, n2 in _children(b, p, p + n):
            if e2 == 0xB3:
                t = _uint(b, p2, n2)
            elif e2 == 0xB7:
                for e3, p3, n3 in _children(b, p2, p2 + n2):
                    if e3 == 0xF1:
                        pos = _uint(b, p3, n3)
        if t is not None and pos is not None and (not out or seg + pos > out[-1][1]):
            out.append((t * scale / 1e9, seg + pos))
    return out


def index(ext: str, get):
    """返回 (文件头长度, [(秒, 字节位置)])。"""
    try:
        head = _retry(get, 0, HEAD - 1, 3)
    except Refused:
        raise
    except OSError as e:
        raise NoIndex("读不到文件开头：%s" % e)
    try:
        init, frags = mp4_index(head) if ext in ("m4a", "mp4") else webm_index(head, get) if ext == "webm" else (0, [])
    except (struct.error, IndexError) as e:
        raise NoIndex("索引读不懂：%s" % e)
    if len(frags) < 2:
        raise NoIndex("%s 格式没有可用的索引" % ext)
    return init, frags


def pick(frags, size: int, a: float, b: float):
    """覆盖 [a, b] 的字节范围：(起点秒, 第一个字节, 最后一个字节)。"""
    lo = max([x for x, f in enumerate(frags) if f[0] <= a] or [0])
    after = [x for x, f in enumerate(frags) if f[0] >= b]
    hi = frags[after[0]][1] - 1 if after else size - 1
    return frags[lo][0], frags[lo][1], hi


def download(get, dst: Path, init: int, lo: int, hi: int, size: int, log=print, chunk=CHUNK, retries=3, tick=None):
    """下到 dst.part，收到多少写多少；旁边的 .json 记着范围，范围和文件大小没变就从已下的字节接着下。完成后改名为 dst。
    tick(已下字节, 这次收到的字节)：每收到一块调用一次，用来显示进度。"""
    part, state = dst.with_name(dst.name + ".part"), dst.with_name(dst.name + ".json")
    want = {"size": size, "init": init, "lo": lo, "hi": hi}
    try:
        same = json.loads(state.read_text("utf-8")) == want
    except (OSError, ValueError):
        same = False
    if not same:
        part.unlink(missing_ok=True)
        state.write_text(json.dumps(want), "utf-8")
    total = init + hi - lo + 1
    have = part.stat().st_size if part.exists() else 0
    if have > total:
        part.unlink(); have = 0
    if have:
        log("  接着上次下：已有 %.1f / %.1f MiB" % (have / 2**20, total / 2**20))
    got = [have, 0]

    def sink(blk):
        f.write(blk)
        got[0] += len(blk); got[1] += len(blk)
        if tick:
            tick(got[0], got[1])

    def once(*_):       # 每次（包括重试）都从文件里已有的字节接着要
        f.flush()
        a = got[0] if got[0] < init else lo + got[0] - init
        get(a, min(a + chunk - 1, init - 1 if got[0] < init else hi), sink)
    with open(part, "ab") as f:
        while got[0] < total:
            _retry(once, 0, 0, retries)
    part.replace(dst)
    state.unlink(missing_ok=True)


def _retry(get, a, b, retries):
    """网络错误重试 retries 次；403 按 REFUSED_WAITS 等一等再试，还被拒就抛 Refused。"""
    import time
    n, waits = 0, list(REFUSED_WAITS)
    while True:
        try:
            return get(a, b)
        except Refused:
            if not waits:
                raise
            time.sleep(waits.pop(0))
        except OSError:
            n += 1
            if n >= retries:
                raise
            time.sleep(3 * n)
