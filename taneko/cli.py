# -*- coding: utf-8 -*-
"""命令行：run / status / approve / doctor / key，以及每个阶段的单独命令（由阶段自己提供选项）。"""
from __future__ import annotations

import argparse
import sys

from . import core, doctor, flow, keys, project


def cmd_approve(a) -> None:
    d = project.project_dir(a.project)
    meta = project.load_meta(d)
    meta.setdefault("review", {})[a.what] = True
    project.save_meta(d, meta)
    print("已记录：%s 的“%s”检查点通过。" % (a.project, a.what))


def cmd_init(a) -> None:
    d = project.create(a.name, a.url, a.section, a.browser)
    print("已建好项目：%s" % (d / "meta.json"))
    print("下一步：%s run %s" % (core.COMMAND, d.name))


EXAMPLES = """例子：
  taneko init game3 https://www.youtube.com/watch?v=... --section 4:13:00-5:08:00
  taneko run game3          下载；断了重跑同一条命令，会接着下
  taneko status             看所有项目做到哪了

字幕命令（实验性，已暂停）：asr、subs、terms、fix、translate、check、approve、key
看某条命令的用法：taneko 命令 --help
说明和问题反馈：https://github.com/coo1white/taneko"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="taneko", description="下载视频的一段：只下需要的部分，断了能接着下。",
                                 epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True, metavar="命令", title="常用命令")
    p = sp.add_parser("init", help="新建项目：写好 meta.json（只下视频）")
    p.add_argument("name", help="项目名，可带分组，例如 lol-worlds/game3"); p.add_argument("url", help="视频地址")
    p.add_argument("--section", help="只下一段，例如 4:13:00-5:08:00；不写就下整条")
    p.add_argument("--browser", help="读哪个浏览器的登录信息（默认 firefox，none 表示不读）")
    p.set_defaults(fn=cmd_init)
    p = sp.add_parser("run", help="下载这个项目；做完的步骤自动跳过，断了重跑会接着下")
    p.add_argument("project", help="项目名（init 时起的名字），或项目文件夹的路径")
    p.add_argument("--until", choices=list(flow.STAGES), metavar="步骤", help="做完这一步就停（只在做字幕时用得到）")
    p.add_argument("--jobs", type=int, default=1, help="分段下载时同时下几段（默认 1）")
    p.set_defaults(fn=lambda a: flow.run(a.project, a.until, a.jobs))
    p = sp.add_parser("status", help="看进度（不带项目名则列出全部）")
    p.add_argument("project", nargs="?"); p.add_argument("--json", action="store_true", help="输出 JSON，给脚本和 agent 读")
    p.set_defaults(fn=lambda a: flow.status(a.project, a.json))
    p = sp.add_parser("approve")    # 字幕命令不写 help：不列在常用命令里，见 EXAMPLES
    p.add_argument("project"); p.add_argument("what", choices=["terms", "spot"]); p.set_defaults(fn=cmd_approve)
    p = sp.add_parser("doctor", help="检查这台机器缺什么工具，并告诉你怎么装")
    p.set_defaults(fn=doctor.cmd_doctor)
    p = sp.add_parser("key", description="管理翻译用的 API 密钥（输入时不显示）")
    p.add_argument("action", choices=["set", "status", "check", "clear"]); p.set_defaults(fn=keys.cmd_key)
    for st in flow.STAGES.values():
        if st.run:
            p = sp.add_parser(st.name, **({"help": st.label} if st.name == "fetch" else {"description": st.label}))
            p.add_argument("project")
            if st.args:
                st.args(p)
            p.set_defaults(fn=st.run)
    return ap


def main(argv=None) -> int:
    """返回退出码；入口脚本用 sys.exit(main())。"""
    ap = build_parser()
    if not (sys.argv[1:] if argv is None else argv):     # 什么都没写：给简短的帮助，不报错
        ap.print_help()
        return core.EXIT_OK
    args = ap.parse_args(argv)
    try:
        rc = args.fn(args)
    except core.Fail as e:
        print("错误：%s" % e)
        return core.EXIT_FAIL
    return rc if isinstance(rc, int) else core.EXIT_OK
