# -*- coding: utf-8 -*-
"""API 密钥：只来自环境变量；Windows 上也读“用户环境变量”（taneko key set 存的），
这样已经打开的窗口不用重开就能用。密钥从不写进项目文件或仓库。"""
from __future__ import annotations

import os
import sys

from . import core

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


def cmd_key(a) -> int:
    """管理翻译用的 API 密钥：set 保存（输入时不显示）、status 只看有没有和长度、clear 删除。"""
    name = core.load_config("translate")["key_env"]
    if a.action == "set":
        if not sys.stdin.isatty():
            core.die("需要在交互终端里运行（输入时不显示）")
        import getpass
        v = getpass.getpass("粘贴 %s（输入时不显示，粘贴后直接回车）：" % name).strip()
        if not v:
            core.die("没有输入内容，没有保存")
        if sys.platform != "win32":
            print("非 Windows 系统：请自己把它写进 shell 配置，例如 export %s=...（不要提交到 git）" % name)
            return core.EXIT_OK
        _win_env_set(name, v)
        print("已保存 %s（%d 个字符）。新开的窗口自动可用；它以明文存在你的 Windows 账户环境变量里，不在项目和仓库里。" % (name, len(v)))
        print("删除：taneko key clear")
    elif a.action == "clear":
        if sys.platform == "win32":
            _win_env_set(name, None)
        print("已删除保存的 %s（当前窗口里已有的变量要关闭窗口才会消失）。" % name)
    else:  # status：只报告有没有、多长、从哪来，绝不显示内容
        if os.environ.get(name):
            src, k = "当前窗口的环境变量", os.environ[name]
        elif os.environ.get("CUSTOM_API_KEY"):
            src, k = "CUSTOM_API_KEY 环境变量", os.environ["CUSTOM_API_KEY"]
        elif _win_env_get(name):
            src, k = "Windows 用户环境变量", _win_env_get(name)
        else:
            print("没有找到 %s。运行 taneko key set 保存一次。" % name)
            return core.EXIT_FAIL
        print("已设置（来源：%s，%d 个字符）" % (src, len(k)))
    return core.EXIT_OK
