# -*- coding: utf-8 -*-
"""命令行：run / status / approve / key，以及每个阶段的单独命令（由阶段自己提供选项）。"""
from __future__ import annotations

import argparse

from . import core, flow, keys, project


def cmd_approve(a) -> None:
    d = project.project_dir(a.project)
    meta = project.load_meta(d)
    meta.setdefault("review", {})[a.what] = True
    project.save_meta(d, meta)
    print("已记录：%s 的“%s”检查点通过。" % (a.project, a.what))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="taneko", description="下载 + 字幕：可续传、可恢复、带人工检查点")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("run", help="按计划跑完下载和字幕，已完成的自动跳过，遇到人工检查点停下")
    p.add_argument("project"); p.add_argument("--until", choices=list(flow.STAGES)); p.add_argument("--jobs", type=int, default=1)
    p.set_defaults(fn=lambda a: flow.run(a.project, a.until, a.jobs))
    p = sp.add_parser("status", help="看进度（不带项目名则列出全部）")
    p.add_argument("project", nargs="?"); p.set_defaults(fn=lambda a: flow.status(a.project))
    p = sp.add_parser("approve", help="通过人工检查点")
    p.add_argument("project"); p.add_argument("what", choices=["terms", "spot"]); p.set_defaults(fn=cmd_approve)
    p = sp.add_parser("key", help="管理翻译用的 API 密钥（输入时不显示）")
    p.add_argument("action", choices=["set", "status", "check", "clear"]); p.set_defaults(fn=keys.cmd_key)
    for st in flow.STAGES.values():
        if st.run:
            p = sp.add_parser(st.name, help=st.label)
            p.add_argument("project")
            if st.args:
                st.args(p)
            p.set_defaults(fn=st.run)
    return ap


def main(argv=None) -> int:
    """返回退出码；入口脚本用 sys.exit(main())。"""
    args = build_parser().parse_args(argv)
    try:
        rc = args.fn(args)
    except core.Fail as e:
        print("错误：%s" % e)
        return core.EXIT_FAIL
    return rc if isinstance(rc, int) else core.EXIT_OK
