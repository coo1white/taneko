# -*- coding: utf-8 -*-
"""taneko 公共部分：路径、项目、meta.json、外部工具、SRT 读写。只用标准库。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

FRAMEWORK_DIR = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("TANEKO_ROOT") or FRAMEWORK_DIR.parent)
PROJECTS = Path(os.environ.get("TANEKO_PROJECTS") or (ROOT / "projects"))
CONFIG = Path(os.environ.get("TANEKO_CONFIG") or (FRAMEWORK_DIR / "config"))
# 翻译工具 llm-subtrans 的安装位置（沿用旧工作流里装好的那份）
VENDOR = Path(os.environ.get("TANEKO_VENDOR") or (ROOT / "workflow" / "vendor"))


# 退出码约定（agent 和脚本据此判断下一步）
EXIT_OK = 0           # 成功；run：全部完成
EXIT_FAIL = 1         # 出错（见上面的“错误：……”）
EXIT_USAGE = 2        # 命令行参数不对（argparse）
EXIT_NEEDS_HUMAN = 10  # run 停在人工检查点：不是失败，需要人处理后 approve 再重跑


def die(msg: str) -> None:
    print("错误：" + msg)
    sys.exit(EXIT_FAIL)


# ---------------------------------------------------------------- API 密钥
# 密钥只来自环境变量；Windows 上也读“用户环境变量”（taneko key set 存的），
# 这样已经打开的窗口不用重开就能用。密钥从不写进项目文件或仓库。
def _win_env_get(name: str):
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0] or None
    except OSError:
        return None


def _win_env_set(name: str, value) -> None:
    """写入（value=None 则删除）Windows 用户环境变量，并通知系统，新开的窗口立刻可用。"""
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        if value is None:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    try:
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 2, 5000, None)
    except Exception:  # noqa: BLE001
        pass


def get_api_key(name: str):
    return os.environ.get(name) or os.environ.get("CUSTOM_API_KEY") or _win_env_get(name)


# ---------------------------------------------------------------- 项目与 meta
def project_dir(name: str) -> Path:
    d = PROJECTS / name
    if not (d / "meta.json").exists():
        die("找不到项目 %s（应有 %s）" % (name, d / "meta.json"))
    return d


def load_meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text("utf-8-sig"))


def save_meta(d: Path, meta: dict) -> None:
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", "utf-8")


def load_config(name: str) -> dict:
    """读 config/<name>.json（asr.json、translate.json）。"""
    f = CONFIG / (name + ".json")
    if not f.exists():
        die("找不到配置 %s" % f)
    return json.loads(f.read_text("utf-8-sig"))


def find_video(d: Path, meta: dict):
    files = [f for f in d.glob(meta.get("video_glob", "*.mkv")) if not f.name.endswith(".part")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# ---------------------------------------------------------------- 外部工具
def tool_cmd(exe: str, module: str) -> list:
    """优先用 PATH 里的可执行文件，否则找用户目录的 Scripts，最后退回 python -m 模块。"""
    p = shutil.which(exe)
    if not p:
        import site
        for base in (Path(site.getusersitepackages()).parent, Path(sys.executable).parent):
            for cand in (base / "Scripts" / (exe + ".exe"), base / (exe + ".exe"), base / "bin" / exe):
                if cand.exists():
                    return [str(cand)]
    return [p] if p else [sys.executable, "-m", module]


def run(cmd: list, cwd=None, log=None):
    """运行命令，实时回显输出，返回 (返回码, 全部输出)。"""
    shown = " ".join(str(c) for c in cmd)
    print("$ " + (shown if len(shown) < 220 else shown[:220] + " ..."))
    p = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    chunks = []
    while True:
        data = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(1)
        if not data:
            break
        text = data.decode("utf-8", "replace")
        sys.stdout.write(text)
        sys.stdout.flush()
        chunks.append(text)
    p.wait()
    out = "".join(chunks)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(out, "utf-8")
    return p.returncode, out


# ---------------------------------------------------------------- SRT
TIME_RE = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
TAG_RE = re.compile(r"<[^>]+>")


def _sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_srt(text: str) -> list:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = TIME_RE.search(line)
            if m:
                g = m.groups()
                body = "\n".join(x.strip() for x in lines[i + 1:] if x.strip())
                cues.append({"start": _sec(*g[:4]), "end": _sec(*g[4:]), "text": body})
                break
    return cues


def fmt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def write_srt(cues: list, path: Path) -> None:
    out = []
    for i, c in enumerate(cues, 1):
        out.append("%d\n%s --> %s\n%s\n" % (i, fmt_ts(c["start"]), fmt_ts(c["end"]), c["text"]))
    path.write_text("\n".join(out), "utf-8")


def read_cues(path: Path) -> list:
    if not path.exists():
        die("找不到 %s" % path)
    return parse_srt(path.read_text("utf-8-sig"))


def clean_auto(cues: list) -> list:
    """清洗 YouTube 自动字幕（滚动式两行字幕）：每行取首次出现→最后出现，消除重叠，过短的行并入下一行。"""
    items, cur = [], {}
    for c in cues:
        lines = [TAG_RE.sub("", l).strip() for l in c["text"].split("\n")]
        nxt = {}
        for l in (x for x in lines if x):
            it = cur.get(l)
            if it is None:
                it = {"start": c["start"], "end": c["end"], "text": l}
                items.append(it)
            else:
                it["end"] = max(it["end"], c["end"])
            nxt[l] = it
        cur = nxt
    for a, b in zip(items, items[1:]):
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    out, carry = [], None
    for it in items:
        if carry:
            it = {"start": carry["start"], "end": max(it["end"], carry["end"]),
                  "text": carry["text"] + " " + it["text"]}
            carry = None
        if it["end"] - it["start"] < 0.5:
            carry = it
            continue
        out.append(it)
    if carry:
        out.append(carry)
    return out
