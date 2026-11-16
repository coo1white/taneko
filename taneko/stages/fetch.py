# -*- coding: utf-8 -*-
"""fetch：可续传的下载。

- 整条视频（meta.json 没有 section.download）：交给 yt-dlp 直接下整个文件，它自己会续传，不切片、不拼接。
- 一段（section.download，如 "4:13:00-5:08:00"）：先试按索引下载（ranges.py）：读文件自带的索引，只下这段的字节，
  速度和整条下载一样，断了接着下；下完无损切到这段并检查。格式没有索引（HLS、直播等）或加了 --sections 时，改用分段下载。
- 分段下载：yt-dlp 截取片段靠 ffmpeg，很慢（约 2 倍实时），断了不能续传，所以像种子一样按“片”管理：
  把范围切成 chunk 秒的小片（默认 600 秒），每片带 -copyts 保留绝对时间戳单独下载，下完立刻校验视频和音频；
  重跑只补缺的片；全部下完后按关键帧无损拼接成 <name>.mkv，并检查视频和音频有没有断档。
  旧的“半截文件”（<name>.mkv 比应有的短）会被当作种子接着用，不用从头来。
“下载完整”只有一个标准：stitch.duration_ok。
"""
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .. import ranges, stitch
from ..core import Stage, die, span, tool_cmd
from ..project import find_video, load_meta, project_dir


def _s2t(x) -> str:
    x = int(x)
    return "%d:%02d:%02d" % (x // 3600, x % 3600 // 60, x % 60)


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
    a, b = span(dl)
    return b - a


def done(d: Path, meta: dict) -> bool:
    v = find_video(d, meta)
    exp = expected_duration(meta)
    if not v or (exp is not None and (d / "_parts").exists()):
        return False
    dur = video_duration(v)
    return exp is None or dur is None or stitch.duration_ok(dur, exp)


def _verify_piece(path: Path, a: float, b: float, last: bool):
    """返回 (ok, 说明)。视频要从 a 之前的关键帧开始、到 b 结束；有音频的话，音频也要盖住 a 到 b。"""
    if not path.exists():
        return False, "文件不存在"
    pk = stitch.video_packets(path)
    if not pk:
        return False, "没有视频包"
    first, end = pk[0][0], pk[-1][0]
    if not pk[0][1]:
        return False, "第一帧不是关键帧"
    if first < a - 15 or first > a + 0.6:
        return False, "起点 %.1f 秒与预期 %.1f 秒不符（-copyts 没生效，或这一片是别的范围）" % (first, a)
    tol = 6 if last else 3
    if end < b - tol:
        return False, "视频没下完整：结尾 %.1f 秒，应到 %.1f 秒" % (end, b)
    ap = stitch.audio_packets(path)
    if ap:
        if ap[0][0] > a + 1.0:
            return False, "音频起点 %.1f 秒，晚于 %.1f 秒" % (ap[0][0], a)
        if ap[-1][0] + ap[-1][1] < b - tol:
            return False, "音频没下完整：结尾 %.1f 秒，应到 %.1f 秒" % (ap[-1][0] + ap[-1][1], b)
    return True, "%.1f 秒 → %.1f 秒%s" % (first, end, "" if ap else "（没有音频）")


class _Job:
    """一次 fetch 要用的东西：项目、格式、cookies、yt-dlp 命令。"""

    def __init__(self, a):
        self.a = a
        self.d = project_dir(a.project)
        meta = load_meta(self.d)
        self.url = meta.get("source_url") or die("meta.json 里没有 source_url")
        self.sec = meta.get("section", {}) or {}
        fcfg = meta.get("fetch", {}) or {}
        self.fmt = a.format or fcfg.get("format") or "bv*+ba/b"
        browser = a.browser or fcfg.get("browser") or "firefox"
        self.name = self.sec.get("name") or fcfg.get("name") or "video"
        self.out = self.d / (self.name + ".mkv")
        self.parts = self.d / "_parts"
        self.ytdlp = tool_cmd("yt-dlp", "yt_dlp")
        self.cookies = [] if browser == "none" else ["--cookies-from-browser", browser]

    def piece(self, path: Path, ta: float, tb: float) -> int:
        cmd = self.ytdlp + ["-q", "--no-warnings"] + self.cookies + [
            "-f", self.fmt, "--download-sections", "*%s-%s" % (_s2t(ta), _s2t(tb)),
            "--downloader-args", "ffmpeg_i:-copyts", "--merge-output-format", "mkv",
            "-P", str(self.parts), "-o", path.stem + ".%(ext)s", self.url]
        return subprocess.call(cmd)


def _fetch_whole(j: _Job) -> None:
    """整条视频：yt-dlp 直接下，断了重跑会从 .part 接着下；下完检查视频和音频。"""
    print("下载整条视频，格式 %s（断了重跑同一条命令，会接着下）" % j.fmt)
    rc = subprocess.call(j.ytdlp + ["--no-warnings"] + j.cookies + [
        "-f", j.fmt, "--merge-output-format", "mkv", "--remux-video", "mkv",
        "-P", str(j.d), "-o", j.name + ".%(ext)s", j.url])
    if rc != 0 or not j.out.exists():
        die("下载没有完成（退出码 %s）。重跑同一条命令会接着下。" % rc)
    ok, msg = stitch.verify(j.out)
    print("检查结果：" + msg)
    if not ok:
        die("%s 没通过检查：%s。删掉它再重跑 fetch。" % (j.out.name, msg))
    print("完成：%s" % j.out)


def _formats(j: _Job) -> list:
    """yt-dlp 选中的格式（视频+音频时是两个）。不是能按字节读的单个文件就抛 NoIndex。"""
    r = subprocess.run(j.ytdlp + ["-q", "--no-warnings", "-j"] + j.cookies + ["-f", j.fmt, j.url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not r.stdout.strip():
        raise ranges.NoIndex("yt-dlp 读不到格式信息（退出码 %s）" % r.returncode)
    info = json.loads(r.stdout.strip().splitlines()[-1])
    fs = info.get("requested_formats") or [info]
    for f in fs:
        if f.get("protocol") != "https" or not f.get("url"):
            raise ranges.NoIndex("格式 %s 不是能按字节读的单个文件" % f.get("format_id"))
    return fs


def _fetch_ranges(j: _Job, w0: float, w1: float, tries: int = 3) -> None:
    """按索引下载这一段（见 ranges.py）。地址被拒（403）就重新取地址接着下；格式没有索引，
    或换了 tries 次地址都被拒，抛 NoIndex，由调用方改用分段下载。"""
    for n in range(1, tries + 1):
        try:
            return _ranges_once(j, w0, w1)
        except ranges.Refused:
            print("网站一直拒绝这个地址（403），重新取地址再试（第 %d/%d 次）。已下的部分不会丢。" % (n, tries), flush=True)
    raise ranges.NoIndex("换了 %d 次地址都被拒绝（403）" % tries)


def _ranges_once(j: _Job, w0: float, w1: float) -> None:
    """取一次地址，读索引，下还没下完的格式（已下完的跳过），再切出这一段。"""
    todo, files = [], []
    for f in _formats(j):
        dst = j.parts / ("r_%s_%d-%d.%s" % (f["format_id"], w0, w1, f["ext"]))
        files.append((dst, f.get("vcodec") not in (None, "none")))
        if not dst.exists():
            get = ranges.getter(f["url"], f.get("http_headers"))
            init, frags = ranges.index(f["ext"], get)
            size = f.get("filesize") or get.total   # B 站等网站不给确切大小，用服务器报的
            if not size:
                raise ranges.NoIndex("不知道格式 %s 的文件大小" % f.get("format_id"))
            todo.append((f, get, dst, init, size) + ranges.pick(frags, size, w0, w1)[1:])
    j.parts.mkdir(exist_ok=True)
    for f, get, dst, init, size, lo, hi in todo:
        print("按索引下载格式 %s：%.1f MiB（整个文件 %.1f MiB）" % (f["format_id"], (init + hi - lo + 1) / 2**20, size / 2**20))
        try:
            ranges.download(get, dst, init, lo, hi, size, log=lambda m: print(m, flush=True))
        except ranges.Refused:
            raise
        except OSError as e:
            die("下载中断：%s。已下的部分在 %s，重跑同一条命令会接着下。" % (e, j.parts))
    _cut(j, files, w0, w1)


def _cut(j: _Job, files: list, w0: float, w1: float) -> None:
    """视频从 w0 之前最近的关键帧开始，音频从 w0 开始，都到 w1；不重新编码。检查通过才替换成品。"""
    vids = [p for p, v in files if v] or [files[0][0]]
    auds = [p for p, v in files if not v and p not in vids]
    pk = stitch.video_packets(vids[0]) or stitch.audio_packets(vids[0])
    if not pk:
        die("%s 读不出内容。删掉 %s 再重跑 fetch。" % (vids[0].name, j.parts))
    k0, tmp = pk[0][0], j.parts / "_out.mkv"
    # 下好的文件只有一部分字节，ffmpeg 会说“文件提前结束”，这是正常的，所以只显示致命错误
    ff = [shutil.which("ffmpeg") or "ffmpeg", "-v", "fatal", "-y"]
    cmd = ff + ["-i", str(vids[0])]
    if auds:
        a0, acut = stitch.audio_packets(auds[0])[0][0], j.parts / "_a.mka"
        # 在输出端截：WebM 的索引指向原文件的字节位置，在输入端跳转会读不到任何音频
        if subprocess.call(ff + ["-i", str(auds[0]), "-ss", "%.3f" % max(0.0, w0 - a0), "-map", "0:a:0",
                                 "-c", "copy", str(acut)]) != 0:
            die("截取音频失败。下好的文件在 %s，不会丢。" % j.parts)
        cmd += ["-itsoffset", "%.3f" % max(0.0, w0 - k0), "-i", str(acut), "-map", "0:v", "-map", "1:a"]
    else:
        cmd += ["-map", "0"]
    if subprocess.call(cmd + ["-c", "copy", "-t", "%.3f" % (w1 - k0), str(tmp)]) != 0:
        die("切出这一段失败。下好的文件在 %s，不会丢。" % j.parts)
    ok, msg = stitch.verify(tmp, expected_s=w1 - w0, need_audio=bool(auds))
    print("检查结果：" + msg)
    if not ok:
        die("结果没通过检查，已保留在 %s，不会覆盖。可以加 --sections 改用分段下载。" % tmp)
    shutil.move(str(tmp), str(j.out))
    if not j.a.keep:
        shutil.rmtree(j.parts, ignore_errors=True)
    print("完成：%s" % j.out)


def _plan(j: _Job, w0: float, w1: float, seed: Path):
    """已有的成品或半截文件，以及分片计划。返回 (plan, use_seed)；成品已完整时返回 (None, False)。"""
    expected = w1 - w0
    if j.out.exists() and not seed.exists():
        dur = video_duration(j.out) or 0.0
        if stitch.duration_ok(dur, expected) and not j.a.force:
            ok, msg = stitch.verify(j.out, expected_s=expected)
            print("%s 已经存在且完整：%s" % (j.out.name, msg))
            return None, False
        shutil.move(str(j.out), str(seed))
        print("发现半截文件 %s（%.1f 分钟），作为种子接着用" % (j.out.name, dur / 60))
    seed_dur = 0.0
    if seed.exists() and not j.a.no_seed:
        pk = stitch.video_packets(seed)
        seed_dur = (pk[-1][0] - pk[0][0]) if pk else 0
    use_seed = seed_dur > 30
    if seed.exists() and not use_seed:
        seed.unlink()
    start = int(max(w0, w0 + seed_dur - 25) if use_seed else w0)  # 种子后面留 25 秒重叠，用来对齐
    plan, b = [], start
    while b < w1 - 3:
        e = min(b + j.a.chunk, w1)
        plan.append({"i": len(plan), "a": b, "b": e, "file": j.parts / ("p%d.mkv" % len(plan)), "last": e >= w1 - 0.5})
        b = e
    if not plan:
        die("没有需要下载的范围")
    return plan, use_seed


def _probe(j: _Job, a0: float) -> None:
    """先用 20 秒小片试探：确认 -copyts 真的保留了绝对时间戳。"""
    probe = j.parts / "probe.mkv"
    probe.unlink(missing_ok=True)
    print("先试探 20 秒，确认时间戳正常……")
    rc = j.piece(probe, a0, a0 + 20)
    pk = stitch.video_packets(probe) if probe.exists() else []
    if rc != 0 or not pk:
        die("试探失败（退出码 %s）。看上面 yt-dlp 的报错：常见原因是网络、cookies 过期或格式不存在（用 yt-dlp -F 看有哪些格式）。" % rc)
    if pk[0][0] < a0 - 15:
        die("-copyts 没有生效：试探片的起点是 %.1f 秒，应约为 %.0f 秒。请升级 yt-dlp 和 ffmpeg 后重试。" % (pk[0][0], a0))
    probe.unlink()
    print("  时间戳正常（起点 %.1f 秒）" % pk[0][0])


def _download(j: _Job, plan: list, pending: list) -> None:
    """下载缺的片；每片失败自动重试，还失败就停下，已完成的不会丢。"""
    lock, failed = threading.Lock(), []

    def work(p):
        for attempt in range(1, j.a.retries + 1):
            t0 = time.time()
            with lock:
                print("[%d/%d] 第 %d 片 %s → %s（第 %d 次尝试）" % (p["i"] + 1, len(plan), p["i"], _s2t(p["a"]), _s2t(p["b"]), attempt))
            rc = j.piece(p["file"], p["a"], p["b"])
            ok, msg = _verify_piece(p["file"], p["a"], p["b"], p["last"]) if rc == 0 else (False, "退出码 %s" % rc)
            with lock:
                print("   第 %d 片%s（%s）" % (p["i"], "完成，用时 %.0f 秒" % (time.time() - t0) if ok else "失败", msg))
            if ok:
                return
            p["file"].unlink(missing_ok=True)
            time.sleep(5 * attempt)
        failed.append(p["i"])

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, j.a.jobs)) as ex:
        list(ex.map(work, pending))
    if failed:
        die("还有 %d 片没下成功（第 %s 片）。已完成的不会丢，重跑同一条命令会接着补。" % (len(failed), "、".join(map(str, sorted(failed)))))


def _finish(j: _Job, plan: list, seed: Path, use_seed: bool, expected: float) -> None:
    """拼接、检查，通过了才替换成品并清理分片。"""
    print("全部下完，开始拼接……")
    tmp = j.parts / "_out.mkv"
    try:
        stitch.assemble(tmp, [p["file"] for p in plan], seed=seed if use_seed else None, workdir=j.parts)
    except RuntimeError as e:
        die("拼接失败：%s\n分片都还在 %s，不会丢。" % (e, j.parts))
    ok, msg = stitch.verify(tmp, expected_s=expected)
    print("拼接结果：" + msg)
    if not ok:
        die("拼接结果没通过检查，已保留在 %s 和各分片，不会覆盖。可以加 --force 重新下载有问题的范围。" % tmp)
    shutil.move(str(tmp), str(j.out))
    if not j.a.keep:
        for f in [p["file"] for p in plan] + list(j.parts.glob("_*")) + list(j.parts.glob("r_*")) + [seed]:
            f.unlink(missing_ok=True)
        try:
            j.parts.rmdir()
        except OSError:
            pass
    print("完成：%s" % j.out)


def cmd_fetch(a) -> None:
    j = _Job(a)
    if not j.sec.get("download"):
        return _fetch_whole(j)
    w0, w1 = span(j.sec["download"])
    if not a.sections and not (j.parts / "seed.mkv").exists():
        if j.out.exists() and not a.force and stitch.duration_ok(video_duration(j.out) or 0.0, w1 - w0):
            return print("%s 已经存在且完整：%s" % (j.out.name, stitch.verify(j.out, expected_s=w1 - w0)[1]))
        try:
            return _fetch_ranges(j, w0, w1)
        except ranges.NoIndex as e:
            print("不能按索引下载（%s），改用分段下载" % e)
    print("下载范围 %s → %s（约 %.1f 分钟），格式 %s，每片 %d 秒" % (_s2t(w0), _s2t(w1), (w1 - w0) / 60, j.fmt, a.chunk))
    j.parts.mkdir(exist_ok=True)
    seed = j.parts / "seed.mkv"
    plan, use_seed = _plan(j, w0, w1, seed)
    if plan is None:
        return
    pending = []
    for p in plan:
        if not (p["file"].exists() and _verify_piece(p["file"], p["a"], p["b"], p["last"])[0]):
            p["file"].unlink(missing_ok=True)
            pending.append(p)
    print("共 %d 片，已完成 %d 片，还要下 %d 片" % (len(plan), len(plan) - len(pending), len(pending)))
    if pending and len(pending) == len(plan):
        _probe(j, plan[0]["a"])
    if pending:
        _download(j, plan, pending)
    _finish(j, plan, seed, use_seed, w1 - w0)


def args(p) -> None:
    p.add_argument("--format", default=None); p.add_argument("--browser", default=None)
    p.add_argument("--chunk", type=int, default=600, help="每片秒数"); p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--retries", type=int, default=3); p.add_argument("--force", action="store_true")
    p.add_argument("--no-seed", action="store_true"); p.add_argument("--keep", action="store_true")
    p.add_argument("--sections", action="store_true", help="不按索引下载，直接用分段下载")


STAGE = Stage("fetch", "下载视频（可续传）", done, cmd_fetch, args)
