# -*- coding: utf-8 -*-
"""在 faster-whisper 的虚拟环境里运行：把视频里的英文语音转成适合做字幕的 SRT。
由 taneko 的 asr 阶段调用，不要直接依赖它的参数。"""
import sys  # utf8 output
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import glob
import os
import sys

END = (".", "?", "!", "\u2026")
SOFT = (",", ";", ":", "\u2014")


def add_dll_dirs():
    """Windows 上 pip 装的 CUDA 库放在 site-packages\\nvidia\\*\\bin，要手动加入 DLL 搜索路径。"""
    dirs = []
    for base in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")) + \
            glob.glob(os.path.join(sys.prefix, "lib", "python*", "site-packages", "nvidia")):
        for sub in os.listdir(base):
            b = os.path.join(base, sub, "bin")
            if os.path.isdir(b):
                dirs.append(b)
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except Exception:
            pass
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])


def build_cues(words, max_chars=64, max_dur=6.5, gap=0.8):
    """words: [(start, end, text)]，text 带前导空格。按句末标点、停顿、长度切成字幕条。"""
    cues, cur = [], []

    def txt(ws):
        return "".join(w[2] for w in ws).strip()

    def flush(n=None):
        nonlocal cur
        part = cur if n is None else cur[:n]
        if part:
            cues.append([part[0][0], part[-1][1], txt(part)])
        cur = [] if n is None else cur[n:]

    for i, w in enumerate(words):
        if cur and w[0] - cur[-1][1] > gap:
            flush()
        cur.append(w)
        text = txt(cur)
        last = w[2].strip()
        dur = cur[-1][1] - cur[0][0]
        if last.endswith(END) and len(text) >= 18:
            flush()
        elif len(text) >= max_chars * 0.75 and last.endswith(SOFT):
            flush()
        elif len(text) >= max_chars or dur >= max_dur:
            k = None
            for j in range(len(cur) - 2, -1, -1):
                t = cur[j][2].strip()
                if t.endswith(END + SOFT) and len(txt(cur[:j + 1])) >= 15:
                    k = j + 1
                    break
            flush(k)
    flush()
    # 最短显示时间，且不与下一条重叠
    for i, c in enumerate(cues):
        nxt = cues[i + 1][0] if i + 1 < len(cues) else None
        if c[1] - c[0] < 0.8:
            c[1] = c[0] + 0.8
        if nxt is not None and c[1] > nxt - 0.01:
            c[1] = max(c[0] + 0.3, nxt - 0.01)
    return cues


def wrap2(text, width=42):
    if len(text) <= width:
        return text
    mid = len(text) // 2
    best, best_d = None, 1e9
    for i, ch in enumerate(text):
        if ch == " ":
            d = abs(i - mid) - (6 if text[i - 1:i] in (",", ";", ":", ".", "?", "!") else 0)
            if d < best_d:
                best, best_d = i, d
    return text if best is None else text[:best] + "\n" + text[best + 1:]


def ts(t):
    t = max(t, 0.0)
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return "%02d:%02d:%06.3f" % (h, m, s)


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(cues, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (i, ts(a).replace(".", ","), ts(b).replace(".", ","), wrap2(t)))


def transcribe(args, device, compute):
    from faster_whisper import WhisperModel
    print("加载模型 %s（%s / %s）…" % (args.model, device, compute), flush=True)
    model = WhisperModel(args.model, device=device, compute_type=compute, download_root=args.cache)
    kw = dict(language=args.language, beam_size=args.beam, word_timestamps=True, vad_filter=True,
              vad_parameters=dict(min_silence_duration_ms=500), condition_on_previous_text=False)
    if args.prompt:
        kw["initial_prompt"] = args.prompt
    if args.limit:
        kw["clip_timestamps"] = "0,%d" % args.limit
    segs, info = model.transcribe(args.video, **kw)
    total = min(info.duration, args.limit) if args.limit else info.duration
    print("音频时长 %.1f 分钟，开始转写…" % (info.duration / 60), flush=True)
    words, shown = [], -1
    for s in segs:
        for w in (s.words or []):
            words.append((w.start, w.end, w.word))
        pct = int(min(s.end / total, 1) * 100)
        if pct // 5 != shown // 5:
            print("  进度 %d%%" % pct, flush=True)
            shown = pct
    return words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="en")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--max-chars", type=int, default=64)
    ap.add_argument("--max-dur", type=float, default=6.5)
    ap.add_argument("--prompt", default="")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--limit", type=int, default=0, help="只转写前 N 秒（测试用）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    add_dll_dirs()
    if args.selftest:
        import ctranslate2
        import faster_whisper
        n = ctranslate2.get_cuda_device_count()
        print("faster-whisper %s，ctranslate2 %s" % (faster_whisper.__version__, ctranslate2.__version__))
        print("可用 GPU 数：%d" % n)
        if n:
            print("GPU 支持的计算类型：%s" % sorted(ctranslate2.get_supported_compute_types("cuda")))
        return
    if not args.video or not args.out:
        sys.exit("用法：asr_run.py <视频> <输出.srt> [选项]")
    plan = [(args.device, args.compute)] if args.device != "auto" else [("cuda", args.compute), ("cpu", "int8")]
    words, err = None, None
    for device, compute in plan:
        try:
            words = transcribe(args, device, compute)
            break
        except Exception as e:  # noqa: BLE001
            err = e
            print("在 %s 上失败：%s" % (device, e), flush=True)
            if device == "cuda":
                print("改用 CPU 重试（会慢很多）…", flush=True)
    if words is None:
        sys.exit("转写失败：%s" % err)
    cues = build_cues(words, args.max_chars, args.max_dur)
    write_srt(cues, args.out)
    print("已写出 %s（%d 条）" % (args.out, len(cues)), flush=True)


if __name__ == "__main__":
    main()
