# -*- coding: utf-8 -*-
"""字幕阶段：subs（抓取）/ asr（本地 Whisper）/ terms / fix / translate / check。
逻辑从旧 pipeline.py 原样搬来，只改了路径和导入。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .core import (CONFIG, VENDOR, FRAMEWORK_DIR, clean_auto, die, find_video, fmt_ts, load_config, load_meta,
                   parse_srt, project_dir, read_cues, run, tool_cmd, write_srt)


def cmd_subs(a) -> None:
    d = project_dir(a.project)
    meta = load_meta(d)
    lang = meta.get("subtitle", {}).get("source_lang", "en")
    raw = d / "sub_raw"
    shutil.rmtree(str(raw), ignore_errors=True)
    raw.mkdir()
    base = tool_cmd("yt-dlp", "yt_dlp") + [
        "--skip-download", "--no-playlist", "--convert-subs", "srt",
        "-o", str(raw / "%(id)s.%(ext)s")]
    auto = False
    run(base + ["--write-subs", "--sub-langs", "%s,%s-US,%s-GB" % (lang, lang, lang),
                meta["source_url"]], log=d / "logs" / "subs_manual.log")
    files = sorted(raw.glob("*.srt"))
    if not files:
        print("没有人工字幕，改抓自动字幕……")
        auto = True
        run(base + ["--write-auto-subs", "--sub-langs", lang, meta["source_url"]],
            log=d / "logs" / "subs_auto.log")
        files = sorted(raw.glob("*.srt"))
    if not files:
        die("没抓到字幕。可以改用 Whisper / Subtitle Edit 从音频生成 en.srt，放进项目目录再继续。")
    cues = parse_srt(files[0].read_text("utf-8-sig"))
    if auto:
        cues = clean_auto(cues)
    write_srt(cues, d / "en.srt")
    print("已生成 %s（%d 条，%s）" % (d / "en.srt", len(cues), "自动字幕，已清洗" if auto else "人工字幕"))
    print("下一步：把 en.srt 译成 zh.srt（时间轴保持不变），再运行 check。")


def problems(en: list, zh: list) -> list:
    out = []
    if len(en) != len(zh):
        out.append("条数不一致：en=%d，zh=%d" % (len(en), len(zh)))
    for i, (e, z) in enumerate(zip(en, zh), 1):
        if abs(e["start"] - z["start"]) > 0.02 or abs(e["end"] - z["end"]) > 0.02:
            out.append("#%d 时间轴被改动" % i)
        if not z["text"].strip():
            out.append("#%d 中文为空" % i)
        dur = max(z["end"] - z["start"], 0.01)
        if len(z["text"].replace("\n", "")) / dur > 16:
            out.append("#%d 太长，读不完（%d 字 / %.1f 秒）" % (i, len(z["text"]), dur))
    return out


def cmd_check(a) -> None:
    d = project_dir(a.project)
    en, zh = read_cues(d / "en.srt"), read_cues(d / "zh.srt")
    ps = problems(en, zh)
    if ps:
        print("发现 %d 个问题：" % len(ps))
        for p in ps[:40]:
            print("  - " + p)
        if len(ps) > 40:
            print("  ……其余 %d 个略" % (len(ps) - 40))
        sys.exit(1)
    print("检查通过：%d 条，时间轴一一对应。" % len(zh))


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
    key = os.environ.get(cfg["key_env"]) or os.environ.get("CUSTOM_API_KEY")
    if not key:
        key = getpass.getpass("请输入 API 密钥（输入时不显示，也不会保存）：").strip()
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



def cmd_asr(a) -> None:
    """用本地 faster-whisper（GPU）把视频里的英文语音转成 en.srt。适合没有字幕可抓的视频。"""
    d = project_dir(a.project)
    meta = load_meta(d)
    cfg = load_config("asr")
    home = Path(cfg["home"])
    py = home / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = home / "venv" / "bin" / "python"
    if not py.exists():
        die("还没安装语音识别，请先双击 workflow\\setup_asr.bat（安装位置 %s）" % home)
    video = find_video(d, meta)
    if not video:
        die("项目目录里没找到视频（meta.json 的 video_glob = %s）" % meta.get("video_glob", "*.mkv"))
    lang = meta.get("subtitle", {}).get("asr_language") or cfg.get("language", "en")
    base = "zh" if lang.startswith("zh") else "en"
    if a.test:
        out = d / ("%s_asr_test.srt" % base)
    else:
        out = d / ("%s.srt" % base)
        if out.exists() and not a.force:
            die("%s.srt 已存在。要覆盖请加 --force（会先备份成 %s.srt.bak）" % (base, base))
        if out.exists():
            shutil.copyfile(out, d / ("%s.srt.bak" % base))
    pt = meta.get("translate", {})
    hints = list(pt.get("names", [])) + ([pt["domain"]] if pt.get("domain") else [])
    prompt = ("Terms: " + ", ".join(hints) + ".") if hints else ""
    cmd = [str(py), str(Path(__file__).resolve().parent / "asr_run.py"), str(video), str(out),
           "--model", cfg["model"], "--language", lang, "--device", cfg.get("device", "auto"),
           "--compute", cfg.get("compute_type", "float16"), "--beam", str(cfg.get("beam_size", 5)),
           "--max-chars", str(cfg.get("max_chars", 64)), "--max-dur", str(cfg.get("max_duration", 6.5)),
           "--cache", str(home / "models"), "--prompt", prompt]
    if a.test:
        cmd += ["--limit", str(a.test * 60)]
    env = dict(os.environ, HF_HOME=str(home / "hf"), PYTHONUTF8="1")
    print("开始转写%s：%s" % ("（只转前 %d 分钟）" % a.test if a.test else "", video.name))
    rc = subprocess.call(cmd, env=env)
    if rc != 0 or not out.exists():
        die("转写没有成功（退出码 %s）。把上面最后几行报错发给我。" % rc)
    cues = read_cues(out)
    print("\n共 %d 条。前 8 条：" % len(cues))
    for c in cues[:8]:
        print("  [%s] %s" % (fmt_ts(c["start"]), c["text"].replace("\n", " ")))
    print("\n转写不是 100%% 准确：专有名词（人名、产品名）请对着原视频抽查，再改 %s 里的错字。" % out.name)


def cmd_fix(a) -> None:
    """精校第一步：按 meta.json 里 translate.corrections（错词->正确词）批量改 en.srt（首次会备份成 en.srt.orig）。"""
    d = project_dir(a.project)
    meta = load_meta(d)
    corr = meta.get("translate", {}).get("corrections", {})
    if not corr:
        die("meta.json 的 translate.corrections 是空的。先运行 terms 找出听错的名字，再把 {\"错词\": \"正确词\"} 填进去")
    src = d / "en.srt"
    cues = read_cues(src)
    if not cues:
        die("en.srt 不存在或是空的")
    if not (d / "en.srt.orig").exists():
        shutil.copyfile(src, d / "en.srt.orig")
    total = 0
    for wrong, right in corr.items():
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(wrong) + r"(?![A-Za-z0-9])")
        n = 0
        for c in cues:
            c["text"], k = pat.subn(right, c["text"])
            n += k
        print("  %s -> %s：%d 处" % (wrong, right, n))
        total += n
    write_srt(cues, src)
    print("共改了 %d 处，已写回 en.srt（原文备份：en.srt.orig）" % total)


def cmd_terms(a) -> None:
    """精校第二步：统计字幕里反复出现的专有名词（大写开头的词），帮你发现听错的人名、英雄名。结果存 terms.txt。"""
    from collections import Counter
    d = project_dir(a.project)
    meta = load_meta(d)
    cues = read_cues(d / "en.srt")
    if not cues:
        die("en.srt 不存在或是空的")
    known = {n.lower() for n in meta.get("translate", {}).get("names", [])}
    cnt = Counter()
    for c in cues:
        words = re.findall(r"[A-Za-z][A-Za-z'\-]*", c["text"].replace("\n", " "))
        for i, w in enumerate(words):
            prev_end = i == 0
            if w[0].isupper() and len(w) > 2 and not prev_end:
                cnt[w] += 1
    rows = [(w, n) for w, n in cnt.most_common() if n >= a.min and w.lower() not in known]
    lines = ["%4d  %s" % (n, w) for w, n in rows]
    (d / "terms.txt").write_text("\n".join(lines) + "\n", "utf-8")
    print("出现 %d 次以上、且不在 names 里的大写词（前 %d 个，全部见 terms.txt）：" % (a.min, a.top))
    print("\n".join(lines[:a.top]))
    print("\n看到拼错的名字（如 Chovie、Kiinn），填进 meta.json 的 translate.corrections，再运行 fix。")

