# -*- coding: utf-8 -*-
"""asr：本地 Whisper 转写（在 Whisper 自己的 venv 里运行 workers/asr_run.py）。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..core import Stage, die, load_config
from ..project import find_video, load_meta, project_dir, source_srt_name
from ..srt import fmt_ts, read_cues


def cmd_asr(a) -> None:
    """用本地 faster-whisper（GPU）把视频里的英文语音转成 en.srt。适合没有字幕可抓的视频。"""
    d = project_dir(a.project)
    meta = load_meta(d)
    cfg = load_config("asr")
    home = Path(cfg["home"])
    py = home / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = home / "venv" / "bin" / "python"
    if not py.exists():
        die("还没安装语音识别，请先双击 workflow\\setup_asr.bat（安装位置 %s）" % home)
    video = find_video(d, meta)
    if not video:
        die("项目目录里没找到视频（meta.json 的 video_glob = %s）" % meta.get("video_glob", "*.mkv"))
    lang = meta.get("subtitle", {}).get("asr_language") or cfg.get("language", "en")
    base = "zh" if lang.startswith("zh") else "en"
    if a.test:
        out = d / ("%s_asr_test.srt" % base)
    else:
        out = d / ("%s.srt" % base)
        if out.exists() and not a.force:
            die("%s.srt 已存在。要覆盖请加 --force（会先备份成 %s.srt.bak）" % (base, base))
        if out.exists():
            shutil.copyfile(out, d / ("%s.srt.bak" % base))
    pt = meta.get("translate", {})
    hints = list(pt.get("names", [])) + ([pt["domain"]] if pt.get("domain") else [])
    prompt = ("Terms: " + ", ".join(hints) + ".") if hints else ""
    cmd = [str(py), str(Path(__file__).resolve().parent.parent / "workers" / "asr_run.py"), str(video), str(out),
           "--model", cfg["model"], "--language", lang, "--device", cfg.get("device", "auto"),
           "--compute", cfg.get("compute_type", "float16"), "--beam", str(cfg.get("beam_size", 5)),
           "--max-chars", str(cfg.get("max_chars", 64)), "--max-dur", str(cfg.get("max_duration", 6.5)),
           "--cache", str(home / "models"), "--prompt", prompt]
    if a.test:
        cmd += ["--limit", str(a.test * 60)]
    env = dict(os.environ, HF_HOME=str(home / "hf"), PYTHONUTF8="1")
    print("开始转写%s：%s" % ("（只转前 %d 分钟）" % a.test if a.test else "", video.name))
    rc = subprocess.call(cmd, env=env)
    if rc != 0 or not out.exists():
        die("转写没有成功（退出码 %s）。把上面最后几行报错发给我。" % rc)
    cues = read_cues(out)
    print("\n共 %d 条。前 8 条：" % len(cues))
    for c in cues[:8]:
        print("  [%s] %s" % (fmt_ts(c["start"]), c["text"].replace("\n", " ")))
    print("\n转写不是 100%% 准确：专有名词（人名、产品名）请对着原视频抽查，再改 %s 里的错字。" % out.name)


def done(d: Path, meta: dict) -> bool:
    f = d / source_srt_name(meta)
    return f.exists() and f.stat().st_size > 0


def args(p) -> None:
    p.add_argument("--test", type=int, nargs="?", const=3, default=0); p.add_argument("--force", action="store_true")


STAGE = Stage("asr", "本地 Whisper 转写", done, cmd_asr, args)
