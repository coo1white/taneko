# -*- coding: utf-8 -*-
"""translate：用 llm-subtrans + OpenAI 兼容接口把 en.srt 分段译成 zh.srt。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ..core import VENDOR, Stage, die, load_config
from ..keys import get_api_key
from ..project import load_meta, project_dir
from ..srt import read_cues, write_srt


PATCH_MARK = "# smo-patch: extra headers from env"


BODY_MARK = "# smo-patch: extra body from env"



def ensure_header_patch(tool: Path) -> None:
    """给翻译工具的 CustomClient 打两个可重复运行的小补丁：
    1) 请求头从环境变量 CUSTOM_EXTRA_HEADERS 读取（OpenCode 要 x-opencode-session）；
    2) 请求体从环境变量 CUSTOM_EXTRA_BODY 读取（如 reasoning_effort）。"""
    f = tool / "PySubtrans" / "Providers" / "Clients" / "CustomClient.py"
    t = f.read_text("utf-8")
    if PATCH_MARK not in t:
        old = "        additional_headers = settings.get('additional_headers', {})  # Keep dict access for complex types\n"
        if old not in t:
            die("翻译工具版本不同，无法自动打补丁，请把 CustomClient.py 的 _add_additional_headers 发给我")
        t = t.replace(old, old + ("        " + PATCH_MARK + "\n"
                 "        import os as _os, json as _json\n"
                 "        try:\n"
                 "            self.headers.update(_json.loads(_os.environ.get('CUSTOM_EXTRA_HEADERS') or '{}'))\n"
                 "        except Exception:\n"
                 "            pass\n"), 1)
    if BODY_MARK not in t:
        old = "        prompt : TranslationPrompt = request.prompt\n        if self.supports_conversation:\n            request_body['messages']"
        if old not in t:
            die("翻译工具版本不同，无法给请求体打补丁，请把 CustomClient.py 的 _generate_request_body 发给我")
        t = t.replace(old, ("        " + BODY_MARK + "\n"
                 "        import os as _os, json as _json\n"
                 "        try:\n"
                 "            request_body.update(_json.loads(_os.environ.get('CUSTOM_EXTRA_BODY') or '{}'))\n"
                 "        except Exception:\n"
                 "            pass\n\n") + old, 1)
    f.write_text(t, "utf-8")


def translate_segments(en, segdir, run_one, size=200):
    """分段翻译：每段单独跑一次 llm-subtrans，译完立刻存成独立文件；重跑时跳过已译完的段。
    （llm-subtrans 要等整次运行结束才写进度，一次译完整部会在中断时全丢，所以这里自己分段存盘。）
    run_one(src, out) -> bool 负责真正翻译一段；返回合并后的译文条目。"""
    segdir.mkdir(exist_ok=True)
    parts = [en[i:i + size] for i in range(0, len(en), size)]
    if len(parts) > 1 and len(parts[-1]) < max(1, size // 4):  # 最后一段太短就并入前一段
        tail = parts.pop()
        parts[-1] = parts[-1] + tail
    merged = []
    for i, part in enumerate(parts, 1):
        src, out = segdir / ("en_%02d.srt" % i), segdir / ("zh_%02d.srt" % i)
        if out.exists() and len(read_cues(out)) == len(part):
            print("✓ 第 %d/%d 段已译完，跳过" % (i, len(parts)))
            merged += read_cues(out)
            continue
        write_srt(part, src)
        print("\n== 翻译第 %d/%d 段（%d 条）==" % (i, len(parts), len(part)))
        ok = run_one(src, out)
        z = read_cues(out) if ok and out.exists() else []
        if len(z) != len(part):
            die("第 %d/%d 段没有译完（译文 %d 条 / 原文 %d 条）。前面已译完的段保存在 %s，"
                "重跑同一条命令会从这一段继续" % (i, len(parts), len(z), len(part), segdir))
        merged += z
    return merged


def cmd_translate(a) -> None:
    """用 llm-subtrans + 你自己的 API（OpenCode）把 en.srt 译成 zh.srt。密钥只放内存，不写文件。"""
    import getpass
    d = project_dir(a.project)
    meta = load_meta(d)
    cfg = load_config("translate")
    tool = VENDOR / "llm-subtrans"
    py = tool / "envsubtrans" / "Scripts" / "python.exe"
    if not py.exists():
        py = tool / "envsubtrans" / "bin" / "python"
    script = tool / "scripts" / "llm-subtrans.py"
    if not py.exists() or not script.exists():
        die("还没安装翻译工具，请先运行旧工作流里的 workflow\\setup_translate.bat")
    ensure_header_patch(tool)
    en = read_cues(d / "en.srt")
    key = get_api_key(cfg["key_env"])
    if not key:
        if not sys.stdin.isatty():
            die("没有 API 密钥，而且当前不是交互终端，无法询问。请先在交互终端运行：taneko key set")
        key = getpass.getpass("请输入 API 密钥（输入时不显示，只用于这一次；想保存请用 taneko key set）：").strip()
    if not key:
        die("没有密钥")
    if a.test:
        src = d / "en_test.srt"
        write_srt(en[:a.test], src)
        out = d / ("zh_test_%s.srt" % (a.effort or "cfg"))
    else:
        src, out = d / "en.srt", d / "zh_raw.srt"
    pt = meta.get("translate", {})          # 每个项目自己的领域、术语、额外要求
    title = pt.get("moviename") or meta.get("bili", {}).get("title", "")
    cmd = [str(py), str(script), str(src), "-o", str(out),
           "-s", cfg["server"], "-e", cfg["endpoint"], "-m", cfg["model"],
           "--chat", "--systemmessages",
           "-l", cfg["target_language"], "--temperature", str(cfg["temperature"]),
           "--maxbatchsize", str(cfg["max_batch_size"]), "--autosplit"]
    if title:
        cmd += ["--moviename", title]
    if pt.get("description"):
        cmd += ["--description", pt["description"]]
    for n in list(cfg.get("names", [])) + list(pt.get("names", [])):
        cmd += ["--name", n]
    for t_ in list(cfg.get("terminology", [])) + list(pt.get("terminology", [])):
        cmd += ["--terminology", t_]          # 格式 “英文::译法”
    instr = list(cfg.get("instructions", []))
    if pt.get("domain"):
        instr.insert(0, "这是一段%s领域的字幕，术语请按该领域的通行译法。" % pt["domain"])
    instr += list(pt.get("instructions", []))
    for t_ in instr:
        cmd += ["--instruction", t_]
    import uuid
    env = dict(os.environ, CUSTOM_API_KEY=key, PYTHONUTF8="1",
               CUSTOM_EXTRA_HEADERS=json.dumps({"x-opencode-session": "taneko-" + uuid.uuid4().hex}))
    effort = a.effort or cfg.get("reasoning_effort")
    if effort and effort != "default":
        env["CUSTOM_EXTRA_BODY"] = json.dumps({"reasoning_effort": effort})
    print("推理强度 reasoning_effort：%s" % (effort or "未设置（服务端默认）"))
    timeout, tries = cfg.get("segment_timeout", 1800), cfg.get("segment_tries", 2)

    def run_one(s, o):
        c = list(cmd)
        c[2], c[4] = str(s), str(o)  # cmd = [python, script, 源文件, "-o", 输出文件, ...]
        for n in range(1, tries + 1):
            try:
                if subprocess.run(c, cwd=str(tool), env=env, timeout=timeout).returncode == 0:
                    return True
            except subprocess.TimeoutExpired:
                print("⚠ 这一段超过 %d 秒没有结束（可能服务端卡住），已终止，第 %d/%d 次尝试" % (timeout, n, tries))
        return False

    if a.test:
        print("开始翻译 %d 条（测试）…" % a.test)
        if not run_one(src, out):
            die("翻译没有成功。把上面最后几行报错发给我，不要发密钥。")
        zh = read_cues(out)
        print("\n测试结果（前 %d 条）：" % min(8, len(zh)))
        for e, z in list(zip(en, zh))[:8]:
            print("  EN:", e["text"].replace("\n", " "))
            print("  ZH:", z["text"].replace("\n", " "))
        print("条数：原文 %d / 译文 %d。看着满意就再运行 translate（不带 --test）。" % (min(a.test, len(en)), len(zh)))
        return
    size = cfg.get("segment_lines", 200)
    print("开始翻译 %d 条：每 %d 条一段，译完一段存一段，中断后重跑会跳过已完成的段…" % (len(en), size))
    zh = translate_segments(en, d / "_translate", run_one, size)
    write_srt(zh, out)
    if len(zh) != len(en):
        die("译文条数 %d 与原文 %d 不一致，已保留 %s，需要人工处理或重跑" % (len(zh), len(en), out))
    write_srt([{"start": e["start"], "end": e["end"], "text": z["text"]} for e, z in zip(en, zh)], d / "zh.srt")
    print("已生成 %s（%d 条，时间轴沿用英文）。下一步：check，再 export。" % (d / "zh.srt", len(zh)))


def done(d: Path, meta: dict) -> bool:
    return (d / "zh.srt").exists()


def args(p) -> None:
    p.add_argument("--test", type=int, nargs="?", const=30, default=0); p.add_argument("--effort")


STAGE = Stage("translate", "翻译成中文", done, cmd_translate, args)
