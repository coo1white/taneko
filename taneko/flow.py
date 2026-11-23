# -*- coding: utf-8 -*-
"""流程：按顺序跑项目的各个阶段，跳过做完的。不知道任何阶段的内部细节。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import core, project
from .stages import fetch

STAGES = {s.name: s for s in (fetch.STAGE,)}
MARK = {"done": "✓", "next": "→", "todo": "·"}


def plan(meta: dict) -> list:
    return list(STAGES)


def snapshot(d: Path, meta: dict) -> list:
    """[(步骤, 状态)]，状态：done / next / todo。第一个没完成的是 next。"""
    out, found = [], False
    for name in plan(meta):
        st = STAGES[name]
        if st.done(d, meta):
            out.append((name, "done"))
        elif not found:
            out.append((name, "next"))
            found = True
        else:
            out.append((name, "todo"))
    return out


def defaults(st: core.Stage, name: str, jobs: int, connections=None) -> argparse.Namespace:
    """run 调用某阶段时的参数：就是单独运行这个阶段时的默认值（只有一处定义）。"""
    p = argparse.ArgumentParser()
    p.add_argument("project")
    if st.args:
        st.args(p)
    a = p.parse_args([name])
    if hasattr(a, "jobs"):
        a.jobs = jobs
    if hasattr(a, "connections"):
        a.connections = connections
    return a


def run(name: str, jobs: int = 1, connections=None) -> int:
    d = project.project_dir(name)
    for step in plan(project.load_meta(d)):
        st, meta = STAGES[step], project.load_meta(d)
        if st.done(d, meta):
            print("✓ 跳过（已完成）：" + st.label)
            continue
        print("\n== %s ==" % st.label)
        st.run(defaults(st, str(d), jobs, connections))  # 只找一次项目，各阶段直接用路径
        if not st.done(d, project.load_meta(d)):
            core.die("阶段“%s”跑完了但结果没通过检查，请看上面的输出" % st.label)
    print("\n全部完成。")
    return core.EXIT_OK


def status(name=None, as_json=False) -> None:
    """给人看：每个项目的下一步和每一步的状态。as_json：同样的内容，给脚本和 agent 读。"""
    rows = []
    for d in [project.project_dir(name)] if name else project.dirs():
        snap = snapshot(d, project.load_meta(d))
        nxt = next((s for s, st in snap if st == "next"), None)
        rows.append({"project": d.name, "dir": str(d), "next": nxt,
                     "steps": [{"name": s, "label": STAGES[s].label, "state": st} for s, st in snap]})
    if as_json:
        print(json.dumps({"projects": rows}, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("还没有项目（在 %s 下）。新建一个：%s init 名字 视频地址" % (project.PROJECTS, core.COMMAND))
    for r in rows:
        print("%s  %s" % (r["project"], "已完成" if r["next"] is None else "下一步：" + STAGES[r["next"]].label))
        if name or r["next"] is not None:
            for st in r["steps"]:
                print("   %s %s" % (MARK[st["state"]], st["label"]))
