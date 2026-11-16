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


def audio_packets(path):
    """返回按时间排序的 [(pts秒, 时长秒)]（只看第一条音频流）；没有音频就是 []。"""
    r = subprocess.run([_ff("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "packet=pts_time,duration_time", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    pk = []
    for line in r.stdout.splitlines():
        a = line.strip().split(",")
        try:
            pk.append((float(a[0]), float(a[1]) if len(a) > 1 and a[1] not in ("", "N/A") else 0.0))
        except ValueError:
            pass
    pk.sort()
    return pk


def tolerance(expected: float) -> float:
    """“下载完整”的唯一标准：最多比预期短 1%，至少 6 秒（关键帧间隔），最多 25 秒。"""
    return min(25.0, max(6.0, expected * 0.01))


def duration_ok(actual: float, expected: float) -> bool:
    return actual >= expected - tolerance(expected)


def _split(src, dst, kind, workdir):
    """把一条流（v 或 a）原样抽成单独的文件，时间戳不变。"""
    r = subprocess.run([_ff("ffmpeg"), "-v", "error", "-y", "-copyts", "-i", str(src), "-map", "0:%s:0" % kind,
                        "-c", "copy", str(dst)], capture_output=True, text=True, cwd=str(workdir))
    if r.returncode != 0:
        raise RuntimeError("抽取%s失败：%s" % ("视频" if kind == "v" else "音频", r.stderr[-300:]))


def _seams(chunks, seed, log):
    """算出每段的起点（inpoint）、视频和音频各自的接缝（outpoint）、在成品里占多长（duration）。

    视频在下一段的第一个关键帧处接上；音频在下一段音频的起点处接上（音频从请求的起点开始，
    比关键帧晚），所以上一段的音频要多留一点，接缝处才不会没声音。两者用同一个起点，音画同步。"""
    vpk = [video_packets(c) for c in chunks]
    apk = [audio_packets(c) for c in chunks]
    if not all(vpk):
        raise RuntimeError("有分片里没有视频包")
    audio = all(apk)
    if any(apk) and not audio:
        raise RuntimeError("有的分片有音频，有的没有，请重跑 fetch")
    fp = frame_period(vpk[0])
    vfirst = [pk[0][0] for pk in vpk]
    afirst = [pk[0][0] for pk in apk] if audio else vfirst
    start = [min(v, a) for v, a in zip(vfirst, afirst)]
    aend = lambda pk: pk[-1][0] + pk[-1][1]  # noqa: E731
    items = []
    if seed:
        d, cost, spk, _ = align(seed, chunks[0])
        sapk = audio_packets(seed) if audio else []
        s0 = min(spk[0][0], sapk[0][0]) if sapk else spk[0][0]
        if vfirst[0] - d - s0 < 1 or vfirst[0] - d > spk[-1][0] - 0.2:
            raise RuntimeError("种子和新段没有足够的重叠，无法拼接")
        if audio and (not sapk or aend(sapk) < afirst[0] - d - 0.05):
            raise RuntimeError("种子的音频没有接到新段的音频起点")
        log("  种子对齐：偏移 %.3f 秒，画面差异 %.2f，接缝在新段 %.3f 秒处" % (d, cost, vfirst[0]))
        items.append({"src": seed, "in": s0, "v": vfirst[0] - d, "a": afirst[0] - d, "dur": start[0] - d - s0})
    for i, c in enumerate(chunks):
        it = {"src": c, "in": start[i]}
        if i + 1 < len(chunks):
            if vfirst[i + 1] <= vfirst[i]:
                raise RuntimeError("第 %d 段与第 %d 段时间重叠异常" % (i, i + 1))
            if vpk[i][-1][0] + fp < vfirst[i + 1] - 0.05:
                raise RuntimeError("第 %d 段视频没有下完整（结尾 %.2f，下一段起点 %.2f），请重跑 fetch" % (i, vpk[i][-1][0], vfirst[i + 1]))
            if audio and aend(apk[i]) < afirst[i + 1] - 0.05:
                raise RuntimeError("第 %d 段音频没有接到下一段（结尾 %.2f，下一段音频起点 %.2f），请重跑 fetch" % (i, aend(apk[i]), afirst[i + 1]))
            it.update(v=vfirst[i + 1], a=afirst[i + 1], dur=start[i + 1] - start[i])
        items.append(it)
    return items, audio


def assemble(out, chunks, seed=None, workdir=None, log=print):
    """把 chunks（带绝对时间戳的小段，按时间顺序）可选地接在 seed（旧的半截文件）后面，输出 out。"""
    out = Path(out)
    workdir = Path(workdir or out.parent)
    workdir.mkdir(parents=True, exist_ok=True)
    items, audio = _seams(chunks, seed, log)
    lists = []
    for kind in ("v", "a") if audio else ("v",):
        lst = workdir / ("_concat_%s.txt" % kind)
        with open(lst, "w", encoding="utf-8") as f:
            for n, it in enumerate(items):
                part = workdir / ("_%s%d.%s" % (kind, n, "mkv" if kind == "v" else "mka"))
                _split(it["src"], part, kind, workdir)
                f.write("file '%s'\ninpoint %.6f\n" % (str(part.resolve()).replace("\\", "/").replace("'", r"'\''"), it["in"]))
                if kind in it:
                    f.write("outpoint %.6f\nduration %.6f\n" % (it[kind], it["dur"]))
        lists += ["-f", "concat", "-safe", "0", "-i", str(lst)]
    maps = ["-map", "0:v"] + (["-map", "1:a"] if audio else [])
    r = subprocess.run([_ff("ffmpeg"), "-v", "error", "-y"] + lists + maps + ["-c", "copy", "-copyts", str(out)],
                       capture_output=True, text=True, cwd=str(workdir))
    if r.returncode != 0:
        raise RuntimeError("拼接失败：" + r.stderr[-300:])
    return out


def verify(path, expected_s=None, max_gap=0.1, need_audio=False):
    """检查成品：时长；need_audio 时没有音频算失败；视频和音频的时间戳是否连续（有没有跳帧、断档、没声音的空白）。返回 (ok, 说明)。"""
    pk = video_packets(path)
    if not pk:
        return False, "没有视频包"
    ts = [p for p, _ in pk]
    vgap = max(max_gap, 1.5 * frame_period(pk))  # 低帧率时，一帧的间隔本身就可能超过 0.1 秒
    gaps = [(b - a, a) for a, b in zip(ts, ts[1:]) if b - a > vgap and a < ts[-1] - 1.0]  # 最后 1 秒是截取的边界，不算接缝
    dur = ts[-1] - ts[0]
    msg = "视频时长 %.1f 秒" % dur
    ok = True
    if gaps:
        ok = False
        msg += "；视频有 %d 处断档，最大 %.2f 秒（在 %.1f 秒处）" % (len(gaps), max(gaps)[0], max(gaps)[1])
    ap = audio_packets(path)
    if not ap:
        msg += "；没有音频"
        ok = ok and not need_audio
    else:
        agaps = [(b[0] - a[0] - a[1], a[0]) for a, b in zip(ap, ap[1:]) if b[0] - a[0] - a[1] > max_gap]
        msg += "；音频从 %.1f 秒到 %.1f 秒" % (round(ap[0][0] - ts[0], 1) + 0.0, ap[-1][0] + ap[-1][1] - ts[0])   # + 0.0：不显示 -0.0
        if agaps:
            ok = False
            msg += "，有 %d 处没声音的空白，最大 %.2f 秒（在 %.1f 秒处）" % (len(agaps), max(agaps)[0], max(agaps)[1] - ts[0])
        if ap[-1][0] + ap[-1][1] < ts[-1] - 1.0:
            ok = False
            msg += "，比视频早结束"
    if expected_s and (not duration_ok(dur, expected_s) or dur > expected_s + 25):
        ok = False
        msg += "；与预期 %.0f 秒相差较大" % expected_s
    return ok, msg
