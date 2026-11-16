# -*- coding: utf-8 -*-
"""taneko 最底层：路径、退出码、错误、阶段的约定、外部工具。只用标准库，不引用 taneko 的其他模块。"""
from __future__ import annotations

import os
import shutil
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
# 从源码运行（旁边有 taneko.py）时，项目放在代码文件夹旁边；pip 安装后放在用户目录的 taneko/ 里
FROM_SOURCE = (FRAMEWORK_DIR / "taneko.py").is_file()
ROOT = Path(os.environ.get("TANEKO_ROOT") or (FRAMEWORK_DIR.parent if FROM_SOURCE else Path.home() / "taneko"))
PROJECTS = Path(os.environ.get("TANEKO_PROJECTS") or (ROOT / "projects"))
# 提示用户下一条命令时用的写法
COMMAND = "python %s/taneko.py" % FRAMEWORK_DIR.name if FROM_SOURCE else "taneko"

# 退出码约定（agent 和脚本据此判断下一步）
EXIT_OK = 0           # 成功；run：全部完成
EXIT_FAIL = 1         # 出错（见上面的“错误：……”）
EXIT_USAGE = 2        # 命令行参数不对（argparse）


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
    """流程里的一步。每个阶段只回答：叫什么、做完了吗、怎么做。"""
    name: str
    label: str
    done: Callable                   # (项目目录, meta) -> bool
    run: Callable                    # (参数) -> None
    args: Optional[Callable] = None  # (argparse 子命令) -> None：单独运行的选项，也是 run 时的默认值


# ---------------------------------------------------------------- 外部工具
def tool_cmd(exe: str, module: str) -> list:
    """优先用和 taneko 装在一起的模块（pip 安装 taneko 时会带上 yt-dlp），
    再找 PATH 里的可执行文件和用户目录的 Scripts，最后退回 python -m 模块。"""
    import importlib.util
    if importlib.util.find_spec(module):
        return [sys.executable, "-m", module]
    p = shutil.which(exe)
    if not p:
        import site
        for base in (Path(site.getusersitepackages()).parent, Path(sys.executable).parent):
            for cand in (base / "Scripts" / (exe + ".exe"), base / (exe + ".exe"), base / "bin" / exe):
                if cand.exists():
                    return [str(cand)]
    return [p] if p else [sys.executable, "-m", module]
