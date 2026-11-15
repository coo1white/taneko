# -*- coding: utf-8 -*-
"""流程：按项目的 meta 排出阶段顺序，跳过做完的，在人工检查点停下。不知道任何阶段的内部细节。"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import core, project
from .stages import asr, check, fetch, fix, gates, subs, terms, translate

STAGES = {s.name: s for s in (fetch.STAGE, asr.STAGE, subs.STAGE, terms.STAGE, gates.TERMS, fix.STAGE,
                              translate.STAGE, check.STAGE, gates.SPOT)}
MARK = {"done": "✓", "skip": "–", "next": "→", "todo": "·"}


def plan(meta: dict) -> list:
    sub = meta.get("subtitle", {}) or {}
    steps = ["fetch", "asr" if sub.get("method") == "asr" else "subs"]
    if str(sub.get("source_lang", "en")).startswith("zh"):
        return steps  # 原文已是中文，不需要翻译
    return steps + ["terms", "gate:terms", "fix", "translate", "check", "gate:spot"]


def snapshot(d: Path, meta: dict) -> list:
    """[(步骤, 状态)]，状态：done / skip / next / todo。第一个没完成的是 next。"""
    out, found = [], False
    for name in plan(meta):
        st = STAGES[name]
        if st.skip and st.skip(meta):
            out.append((name, "skip"))
        elif st.done(d, meta):
            out.append((name, "done"))
        elif not found:
            out.append((name, "next"))
            found = True
        else:
            out.append((name, "todo"))
    return out


def defaults(st: core.Stage, name: str, jobs: int) -> argparse.Namespace:
    """run 调用某阶段时的参数：就是单独运行这个阶段时的默认值（只有一处定义）。"""
    p = argparse.ArgumentParser()
    p.add_argument("project")
    if st.args:
        st.args(p)
    a = p.parse_args([name])
    if hasattr(a, "jobs"):
        a.jobs = jobs
    return a


def run(name: str, until=None, jobs: int = 1) -> int:
    d = project.project_dir(name)
    for step in plan(project.load_meta(d)):
        st, meta = STAGES[step], project.load_meta(d)  # 人工检查点之后 meta 可能被改过，每步重读
        if st.done(d, meta):
            print("✓ 跳过（已完成）：" + st.label)
        elif st.run is None:
            print("⏸ 需要你：" + st.label)
            for line in st.hint(d, name):
                print("   " + line)
            return core.EXIT_NEEDS_HUMAN
        else:
            print("\n== %s ==" % st.label)
            st.run(defaults(st, str(d), jobs))  # 只找一次项目，各阶段直接用路径
            if not st.done(d, project.load_meta(d)):
                core.die("阶段“%s”跑完了但结果没通过检查，请看上面的输出" % st.label)
        if until and step == until:
            print("已到指定的 --until 阶段，停止。")
            return core.EXIT_OK
    print("\n全部完成。")
    return core.EXIT_OK


def status(name=None) -> None:
    for d in [project.project_dir(name)] if name else project.dirs():
        n = d.name
        snap = snapshot(d, project.load_meta(d))
        nxt = next((s for s, st in snap if st == "next"), None)
        print("%s  %s" % (n, "已完成" if nxt is None else "下一步：" + STAGES[nxt].label))
        if name or nxt is not None:
            for s, st in snap:
                print("   %s %s" % (MARK[st], STAGES[s].label))
