# -*- coding: utf-8 -*-
"""分段下载后的无缝拼接（只用标准库 + ffmpeg/ffprobe）。

背景：yt-dlp 的 --download-sections 靠 ffmpeg 截取，断了无法续传。办法是把一局切成若干小段下载，
每段都加 -copyts（保留视频里的绝对时间戳），再按关键帧精确拼接。
旧的半截文件（没有 -copyts，时间从 0 开始）作为“种子”，用画面比对找到它在绝对时间轴上的位置。
"""
import re
import shutil
import statistics
import subprocess
from pathlib import Path


def _ff(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise RuntimeError("找不到 %s，请确认 ffmpeg 已安装并在 PATH 里（ffprobe 通常和 ffmpeg 在一起）" % name)
    return p


def video_packets(path):
    """返回按时间排序的 [(pts秒, 是否关键帧)]（只看第一条视频流，不解码，很快）。"""
    r = subprocess.run([_ff("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "packet=pts_time,flags", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    pk = []
    for line in r.stdout.splitlines():
        a = line.strip().split(",")
        if len(a) >= 2 and a[0] not in ("", "N/A"):
            try:
                pk.append((float(a[0]), "K" in a[1]))
            except ValueError:
                pass
    pk.sort()
    return pk


def container_start(path) -> float:
    r = subprocess.run([_ff("ffprobe"), "-v", "error", "-show_entries", "format=start_time", "-of",
                        "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def frame_period(pk) -> float:
    ts = [p for p, _ in pk]
    d = [b - a for a, b in zip(ts, ts[1:]) if b - a > 1e-6]
    return statistics.median(d) if d else 1 / 30


def grab(path, t_from: float, count: int):
    """从文件里解码 count 帧缩略图（8x8 灰度），返回 [(pts, bytes)]；pts 与文件自己的时间轴一致。"""
    ss = max(0.0, t_from - container_start(path))
    cmd = [_ff("ffmpeg"), "-hide_banner", "-nostats", "-v", "info", "-copyts", "-ss", "%.3f" % ss, "-i", str(path),
           "-map", "0:v:0", "-vf", "scale=8:8:flags=area,format=gray,showinfo", "-frames:v", str(count + 40),
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    r = subprocess.run(cmd, capture_output=True)
    ptss = [float(m.group(1)) for m in re.finditer(r"pts_time:\s*(-?[\d.]+)", r.stderr.decode("utf-8", "replace"))]
    raw = r.stdout
    n = min(len(ptss), len(raw) // 64)
    frames = [(ptss[i], raw[i * 64:(i + 1) * 64]) for i in range(n)]
    frames = [f for f in frames if f[0] >= t_from - 1e-3]
    return frames[:count]


def _cost(a: bytes, b: bytes) -> int:
    return sum(abs(x - y) for x, y in zip(a, b))


def align(seed, chunk0, tail_s=12.0, head_s=45.0):
    """找出 seed（相对时间）和 chunk0（绝对时间）的偏移 d：chunk0 的时间 = seed 的时间 + d。"""
    spk = video_packets(seed)
    cpk = video_packets(chunk0)
    if not spk or not cpk:
        raise RuntimeError("读不到视频包，文件可能损坏")
    fp = frame_period(spk)
    seed_end = spk[-1][0]
    n_a = int(tail_s / fp)
    n_b = int(head_s / fp)
    A = grab(seed, seed_end - tail_s, n_a)
    B = grab(chunk0, cpk[0][0], n_b)
    if len(A) < 60 or len(B) < len(A):
        raise RuntimeError("用来对齐的画面太少（种子 %d 帧，新段 %d 帧）" % (len(A), len(B)))
    step = 10
    sub = list(range(0, len(A), step))
    maxk = len(B) - len(A)
    best = []
    for k in range(0, maxk + 1):
        c = sum(_cost(A[i][1], B[k + i][1]) for i in sub)
        best.append((c / (len(sub) * 64.0), k))
    best.sort()
    c0, k0 = best[0]
    others = [c for c, k in best if abs(k - k0) > 15]
    c1 = others[0] if others else 999
    # 精修：在 k0 附近逐帧、全部帧比对
    ref = []
    for k in range(max(0, k0 - 8), min(maxk, k0 + 8) + 1):
        c = sum(_cost(A[i][1], B[k + i][1]) for i in range(len(A)))
        ref.append((c / (len(A) * 64.0), k))
    ref.sort()
    cf, kf = ref[0]
    if cf > 6.0 or c1 < cf * 1.5 + 0.5:
        raise RuntimeError("画面对齐不可靠（最佳差异 %.2f，次佳 %.2f）" % (cf, c1))
    ds = sorted(B[kf + i][0] - A[i][0] for i in range(len(A)))
    d = statistics.median(ds)
    return d, cf, spk, cpk


def _cut(src, dst, duration, workdir):
    """无损截取前 duration 秒（视频包的结束点正好落在下一段的关键帧上）。"""
    r = subprocess.run([_ff("ffmpeg"), "-v", "error", "-y", "-i", str(src), "-t", "%.6f" % duration, "-map", "0",
                        "-c", "copy", str(dst)], capture_output=True, text=True, cwd=str(workdir))
    if r.returncode != 0:
        raise RuntimeError("截取失败：" + r.stderr[-300:])


def assemble(out, chunks, seed=None, workdir=None, log=print):
    """把 chunks（带绝对时间戳的小段，按时间顺序）可选地接在 seed（旧的半截文件）后面，输出 out。"""
    out = Path(out)
    workdir = Path(workdir or out.parent)
    workdir.mkdir(parents=True, exist_ok=True)
    pieces = []  # (文件, 视频时长)
    cpks = [video_packets(c) for c in chunks]
    for c, pk in zip(chunks, cpks):
        if not pk:
            raise RuntimeError("%s 里没有视频包" % c)
    fps_period = frame_period(cpks[0])
    firsts = [pk[0][0] for pk in cpks]
    if seed:
        d, cost, spk, _ = align(seed, chunks[0])
        J = firsts[0]
        t_end = J - d - spk[0][0]
        if t_end < 1 or J - d > spk[-1][0] - 0.2:
            raise RuntimeError("种子和新段没有足够的重叠，无法拼接")
        log("  种子对齐：偏移 %.3f 秒，画面差异 %.2f，接缝在新段 %.3f 秒处" % (d, cost, J))
        trimmed = workdir / "_seed_trim.mkv"
        _cut(seed, trimmed, t_end, workdir)
        pieces.append((trimmed, t_end))
    for i, c in enumerate(chunks):
        if i + 1 < len(chunks):
            J = firsts[i + 1]
            dur = J - firsts[i]
            if dur <= 0:
                raise RuntimeError("第 %d 段与第 %d 段时间重叠异常" % (i, i + 1))
            if cpks[i][-1][0] + fps_period < J - 0.05:
                raise RuntimeError("第 %d 段没有下完整（结尾 %.2f，下一段起点 %.2f），请重跑 fetch" % (i, cpks[i][-1][0], J))
            trimmed = workdir / ("_trim%d.mkv" % i)
            _cut(c, trimmed, dur, workdir)
            pieces.append((trimmed, dur))
        else:
            dur = cpks[i][-1][0] + fps_period - firsts[i]
            pieces.append((c, dur))
    lst = workdir / "_concat.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p, dur in pieces:
            f.write("file '%s'\nduration %.6f\n" % (str(Path(p).resolve()).replace("\\", "/").replace("'", r"'\''"), dur))
    r = subprocess.run([_ff("ffmpeg"), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0",
                        "-c", "copy", str(out)], capture_output=True, text=True, cwd=str(workdir))
    if r.returncode != 0:
        raise RuntimeError("拼接失败：" + r.stderr[-300:])
    return out


def verify(path, expected_s=None, max_gap=0.1):
    """检查拼接结果：时长、视频时间戳是否连续（有没有跳帧或断档）。返回 (ok, 说明)。"""
    pk = video_packets(path)
    if not pk:
        return False, "没有视频包"
    ts = [p for p, _ in pk]
    gaps = [(b - a, a) for a, b in zip(ts, ts[1:]) if b - a > max_gap]
    dur = ts[-1] - ts[0]
    msg = "视频时长 %.1f 秒" % dur
    ok = True
    if gaps:
        ok = False
        msg += "；发现 %d 处时间断档，最大 %.2f 秒（在 %.1f 秒处）" % (len(gaps), max(gaps)[0], max(gaps)[1])
    if expected_s and abs(dur - expected_s) > 20:
        ok = False
        msg += "；与预期 %.0f 秒相差较大" % expected_s
    return ok, msg
