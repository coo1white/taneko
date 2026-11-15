# -*- coding: utf-8 -*-
"""命令行入口：taneko run / status / approve，以及可单独运行的各阶段。"""
from __future__ import annotations

import argparse
import sys
from argparse import Namespace

from . import core, download, state, subtitle

MARK = {"done": "✓", "skip": "–", "next": "→", "todo": "·"}

# 单独运行的阶段 -> 处理函数
STAGE_FN = {"fetch": download.cmd_fetch, "subs": subtitle.cmd_subs, "asr": subtitle.cmd_asr,
            "terms": subtitle.cmd_terms, "fix": subtitle.cmd_fix, "translate": subtitle.cmd_translate,
            "check": subtitle.cmd_check}


def stage_args(step: str, project: str, jobs: int = 1) -> Namespace:
    """run 调用各阶段时用的默认参数（与单独运行时的默认值一致）。"""
    base = dict(project=project)
    extra = {
        "fetch": dict(format=None, browser=None, chunk=600, jobs=jobs, retries=3, force=False, no_seed=False, keep=False),
        "asr": dict(test=0, force=False),
        "terms": dict(min=2, top=60),
        "translate": dict(test=0, effort=None),
    }.get(step, {})
    return Namespace(**base, **extra)


def cmd_status(a) -> None:
    names = [a.project] if a.project else sorted(
        p.name for p in core.PROJECTS.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "meta.json").exists())
    for n in names:
        d = core.project_dir(n)
        meta = core.load_meta(d)
        snap = state.snapshot(d, meta)
        nxt = next((s for s, st in snap if st == "next"), None)
        print("%s  %s" % (n, "已完成" if nxt is None else "下一步：" + state.LABELS[nxt]))
        if a.project or nxt is not None:
            for s, st in snap:
                print("   %s %s" % (MARK[st], state.LABELS[s]))


def cmd_run(a) -> int:
    d = core.project_dir(a.project)
    for step in state.plan(core.load_meta(d)):
        meta = core.load_meta(d)  # 人工检查点之后 meta 可能被改过，每步重读
        if state.is_done(step, d, meta):
            print("✓ 跳过（已完成）：" + state.LABELS[step])
        elif state.is_gate(step):
            what = "terms" if step == state.GATE_TERMS else "spot"
            print("⏸ 需要你：" + state.LABELS[step])
            if what == "terms":
                print("   1) 打开 %s 看听错的名字" % (d / "terms.txt"))
                print("   2) 把 {\"错词\": \"正确词\"} 填进 %s 的 translate.corrections" % (d / "meta.json"))
            else:
                print("   对着视频抽查 %s 里的击杀、大龙等关键片段" % (d / "zh.srt"))
            print("   3) 完成后运行：taneko approve %s %s，再重新 taneko run %s" % (a.project, what, a.project))
            return core.EXIT_NEEDS_HUMAN
        else:
            print("\n== %s ==" % state.LABELS[step])
            STAGE_FN[step](stage_args(step, a.project, a.jobs))
            if not state.is_done(step, d, core.load_meta(d)):
                core.die("阶段“%s”跑完了但结果没通过检查，请看上面的输出" % state.LABELS[step])
        if a.until and step == a.until:
            print("已到指定的 --until 阶段，停止。")
            return core.EXIT_OK
    print("\n全部完成。")
    return core.EXIT_OK


def cmd_approve(a) -> None:
    d = core.project_dir(a.project)
    meta = core.load_meta(d)
    meta.setdefault("review", {})[a.what] = True
    core.save_meta(d, meta)
    print("已记录：%s 的“%s”检查点通过。" % (a.project, a.what))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="taneko", description="下载 + 字幕：可续传、可恢复、带人工检查点")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("run", help="按计划跑完下载和字幕，已完成的自动跳过，遇到人工检查点停下")
    p.add_argument("project"); p.add_argument("--until", choices=list(state.LABELS)); p.add_argument("--jobs", type=int, default=1)
    p.set_defaults(fn=cmd_run)
    p = sp.add_parser("status", help="看进度（不带项目名则列出全部）")
    p.add_argument("project", nargs="?"); p.set_defaults(fn=cmd_status)
    p = sp.add_parser("approve", help="通过人工检查点")
    p.add_argument("project"); p.add_argument("what", choices=["terms", "spot"]); p.set_defaults(fn=cmd_approve)

    p = sp.add_parser("fetch", help="可续传分片下载")
    p.add_argument("project"); p.add_argument("--format", default=None); p.add_argument("--browser", default=None)
    p.add_argument("--chunk", type=int, default=600, help="每片秒数"); p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--retries", type=int, default=3); p.add_argument("--force", action="store_true")
    p.add_argument("--no-seed", action="store_true"); p.add_argument("--keep", action="store_true")
    p.set_defaults(fn=download.cmd_fetch)
    p = sp.add_parser("subs"); p.add_argument("project"); p.set_defaults(fn=subtitle.cmd_subs)
    p = sp.add_parser("asr"); p.add_argument("project")
    p.add_argument("--test", type=int, nargs="?", const=3, default=0); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=subtitle.cmd_asr)
    p = sp.add_parser("terms"); p.add_argument("project")
    p.add_argument("--min", type=int, default=2); p.add_argument("--top", type=int, default=60); p.set_defaults(fn=subtitle.cmd_terms)
    p = sp.add_parser("fix"); p.add_argument("project"); p.set_defaults(fn=subtitle.cmd_fix)
    p = sp.add_parser("translate"); p.add_argument("project")
    p.add_argument("--test", type=int, nargs="?", const=30, default=0); p.add_argument("--effort")
    p.set_defaults(fn=subtitle.cmd_translate)
    p = sp.add_parser("check"); p.add_argument("project"); p.set_defaults(fn=subtitle.cmd_check)
    return ap


def main(argv=None) -> int:
    """返回退出码；入口脚本用 sys.exit(main())。出错时 core.die 直接以 1 退出。"""
    args = build_parser().parse_args(argv)
    rc = args.fn(args)
    return rc if isinstance(rc, int) else core.EXIT_OK


if __name__ == "__main__":
    main()
