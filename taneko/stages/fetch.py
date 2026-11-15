# -*- coding: utf-8 -*-
"""fetch：可续传的分片下载（像种子一样按“片”管理）。

适用于任何项目：整条视频，或 meta.json 里 section.download 指定的一段（如 "4:13:00-5:08:00"）。
- 把要下的范围切成 chunk 秒的小片（默认 600 秒），每片单独下载，带 -copyts 保留绝对时间戳。
- 每片下完立刻校验（起止时间、关键帧）。断了、被限速了、链接过期了，只影响当前这一片。
- 重跑同一条命令：已完成的片自动跳过，只补缺的。
- 全部下完后按关键帧无损拼接成 <name>.mkv，并检查时间戳是否连续。
- 旧的“半截文件”（<name>.mkv 比应有的短）会被当作种子接着用，不用从头来。
"""
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .. import stitch
from ..core import Stage, die, tool_cmd
from ..project import find_video, load_meta, project_dir


def _t2s(x) -> float:
    s = 0.0
    for v in str(x).strip().split(":"):
        s = s * 60 + float(v)
    return s


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
    a, b = [_t2s(x) for x in dl.split("-")]
    return b - a


def done(d: Path, meta: dict) -> bool:
    v = find_video(d, meta)
    if not v or (d / "_parts").exists():
        return False
    exp = expected_duration(meta)
    dur = video_duration(v)
    if exp is None or dur is None:
        return True
    return dur >= exp - min(25.0, max(1.0, exp * 0.01))  # 容差：长视频 25 秒，短的按 1%


def _verify_piece(path: Path, a: float, b: float, last: bool):
    """返回 (ok, 说明)。"""
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
        return False, "没下完整：结尾 %.1f 秒，应到 %.1f 秒" % (end, b)
    return True, "%.1f 秒 → %.1f 秒" % (first, end)


def cmd_fetch(a) -> None:
    d = project_dir(a.project)
    meta = load_meta(d)
    url = meta.get("source_url") or die("meta.json 里没有 source_url")
    sec = meta.get("section", {}) or {}
    fcfg = meta.get("fetch", {}) or {}
    fmt = a.format or fcfg.get("format") or "bv*+ba/b"
    browser = a.browser or fcfg.get("browser") or "firefox"
    name = sec.get("name") or fcfg.get("name") or "video"
    out = d / (name + ".mkv")
    parts = d / "_parts"
    parts.mkdir(exist_ok=True)
    ytdlp = tool_cmd("yt-dlp", "yt_dlp")
    cookies = [] if browser == "none" else ["--cookies-from-browser", browser]

    # 1. 下载范围
    if sec.get("download"):
        w0, w1 = [_t2s(x) for x in sec["download"].split("-")]
    else:
        r = subprocess.run(ytdlp + cookies + ["--skip-download", "--print", "%(duration)s", "--no-warnings", url],
                           capture_output=True, text=True)
        try:
            w0, w1 = 0.0, float(r.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            die("取不到视频时长。把下面的报错发给我：\n" + (r.stderr or r.stdout)[-400:])
    expected = w1 - w0
    print("下载范围 %s → %s（约 %.1f 分钟），格式 %s，每片 %d 秒" % (_s2t(w0), _s2t(w1), expected / 60, fmt, a.chunk))

    # 2. 已有的成品 / 半截文件
    seed = parts / "seed.mkv"
    if out.exists() and not seed.exists():
        pk = stitch.video_packets(out)
        dur = (pk[-1][0] - pk[0][0]) if pk else 0
        if dur >= expected - 25 and not a.force:
            ok, msg = stitch.verify(out, expected_s=expected)
            print("%s 已经存在且完整：%s" % (out.name, msg))
            return
        shutil.move(str(out), str(seed))
        print("发现半截文件 %s（%.1f 分钟），作为种子接着用" % (out.name, dur / 60))
    seed_dur = 0.0
    if seed.exists() and not a.no_seed:
        pk = stitch.video_packets(seed)
        seed_dur = (pk[-1][0] - pk[0][0]) if pk else 0
    use_seed = seed_dur > 30
    if seed.exists() and not use_seed:
        seed.unlink()

    # 3. 分片计划（种子后面留 25 秒重叠，用来对齐）
    start = max(w0, w0 + seed_dur - 25) if use_seed else w0
    start = int(start)
    plan, b = [], start
    while b < w1 - 3:
        e = min(b + a.chunk, w1)
        plan.append({"i": len(plan), "a": b, "b": e})
        b = e
    if not plan:
        die("没有需要下载的范围")
    for p in plan:
        p["file"] = parts / ("p%d.mkv" % p["i"])
        p["last"] = p["b"] >= w1 - 0.5

    # 4. 先用 20 秒小片试探：确认 -copyts 真的保留了绝对时间戳
    def fetch_piece(path: Path, ta: float, tb: float) -> int:
        stem = path.stem
        cmd = ytdlp + ["-q", "--no-warnings"] + cookies + [
            "-f", fmt, "--download-sections", "*%s-%s" % (_s2t(ta), _s2t(tb)),
            "--downloader-args", "ffmpeg_i:-copyts", "--merge-output-format", "mkv",
            "-P", str(parts), "-o", stem + ".%(ext)s", url]
        return subprocess.call(cmd)

    pending = []
    for p in plan:
        ok, _ = _verify_piece(p["file"], p["a"], p["b"], p["last"]) if p["file"].exists() else (False, "")
        if not ok:
            if p["file"].exists():
                p["file"].unlink()
            pending.append(p)
    done_n = len(plan) - len(pending)
    print("共 %d 片，已完成 %d 片，还要下 %d 片" % (len(plan), done_n, len(pending)))

    if pending and done_n == 0:
        probe = parts / "probe.mkv"
        if probe.exists():
            probe.unlink()
        print("先试探 20 秒，确认时间戳正常……")
        rc = fetch_piece(probe, plan[0]["a"], plan[0]["a"] + 20)
        pk = stitch.video_packets(probe) if probe.exists() else []
        if rc != 0 or not pk:
            die("试探失败（退出码 %s）。把上面的报错发给我。" % rc)
        if pk[0][0] < plan[0]["a"] - 15:
            die("-copyts 没有生效：试探片的起点是 %.1f 秒，应约为 %.0f 秒。把这句话发给我，我换个办法。" % (pk[0][0], plan[0]["a"]))
        probe.unlink()
        print("  时间戳正常（起点 %.1f 秒）" % pk[0][0])

    # 5. 下载缺的片（失败自动重试，下一次重跑会接着补）
    lock = threading.Lock()
    failed = []

    def work(p):
        for attempt in range(1, a.retries + 1):
            t0 = time.time()
            with lock:
                print("[%d/%d] 第 %d 片 %s → %s（第 %d 次尝试）" % (p["i"] + 1, len(plan), p["i"], _s2t(p["a"]), _s2t(p["b"]), attempt))
            rc = fetch_piece(p["file"], p["a"], p["b"])
            ok, msg = _verify_piece(p["file"], p["a"], p["b"], p["last"]) if rc == 0 else (False, "退出码 %s" % rc)
            if ok:
                with lock:
                    print("   第 %d 片完成，用时 %.0f 秒（%s）" % (p["i"], time.time() - t0, msg))
                return
            with lock:
                print("   第 %d 片失败：%s" % (p["i"], msg))
            if p["file"].exists():
                p["file"].unlink()
            time.sleep(5 * attempt)
        failed.append(p["i"])

    if pending:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            list(ex.map(work, pending))
    if failed:
        die("还有 %d 片没下成功（第 %s 片）。已完成的不会丢，重跑同一条命令会接着补。" % (len(failed), "、".join(map(str, sorted(failed)))))

    # 6. 拼接并检查
    print("全部下完，开始拼接……")
    tmp = parts / "_out.mkv"
    try:
        stitch.assemble(tmp, [p["file"] for p in plan], seed=seed if use_seed else None, workdir=parts)
    except RuntimeError as e:
        die("拼接失败：%s\n分片都还在 %s，不会丢。把这段发给我。" % (e, parts))
    ok, msg = stitch.verify(tmp, expected_s=expected)
    print("拼接结果：" + msg)
    if not ok:
        die("拼接结果没通过检查，已保留在 %s 和各分片，不会覆盖。把上面这行发给我。" % tmp)
    shutil.move(str(tmp), str(out))
    if not a.keep:
        for p in plan:
            p["file"].unlink(missing_ok=True)
        for f in list(parts.glob("_*.mkv")) + list(parts.glob("_*.txt")):
            f.unlink(missing_ok=True)
        if seed.exists():
            seed.unlink()
        try:
            parts.rmdir()
        except OSError:
            pass
    print("完成：%s" % out)


def args(p) -> None:
    p.add_argument("--format", default=None); p.add_argument("--browser", default=None)
    p.add_argument("--chunk", type=int, default=600, help="每片秒数"); p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--retries", type=int, default=3); p.add_argument("--force", action="store_true")
    p.add_argument("--no-seed", action="store_true"); p.add_argument("--keep", action="store_true")


STAGE = Stage("fetch", "下载视频（可续传分片）", done, cmd_fetch, args)
