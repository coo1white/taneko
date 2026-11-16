# -*- coding: utf-8 -*-
"""taneko 最底层：路径、退出码、错误、阶段的约定、外部工具。只用标准库，不引用 taneko 的其他模块。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

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


class Fail(Exception):
    """出错：cli 打印“错误：……”，以 EXIT_FAIL 退出。阶段只抛出，不自己退出程序。"""


def die(msg: str) -> None:
    raise Fail(msg)


def span(text: str) -> tuple:
    """"4:13:00-5:08:00" → (开始秒, 结束秒)。每个时间可写 时:分:秒、分:秒 或 秒。"""
    try:
        a, b = [sum(float(v) * 60 ** i for i, v in enumerate(reversed(t.strip().split(":")))) for t in str(text).split("-")]
    except ValueError:
        die("时间范围 %s 看不懂。写成 开始-结束，例如 4:13:00-5:08:00、13:00-14:30 或 780-870" % text)
    if b <= a:
        die("时间范围 %s 的结束时间要晚于开始时间" % text)
    return a, b


@dataclass(frozen=True)
class Stage:
    """流程里的一步。每个阶段只回答：叫什么、做完了吗、怎么做。没有 run 的是人工检查点。"""
    name: str
    label: str
    done: Callable                   # (项目目录, meta) -> bool
    run: Optional[Callable] = None   # (参数) -> None
    args: Optional[Callable] = None  # (argparse 子命令) -> None：单独运行的选项，也是 run 时的默认值
    skip: Optional[Callable] = None  # (meta) -> bool：这个项目不需要这一步
    hint: Optional[Callable] = None  # (项目目录, 项目名) -> [行]：人工检查点要人做什么


def load_config(name: str) -> dict:
    """读 config/<name>.json（asr.json、translate.json）。"""
    f = CONFIG / (name + ".json")
    if not f.exists():
        die("找不到配置 %s" % f)
    return json.loads(f.read_text("utf-8-sig"))


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
