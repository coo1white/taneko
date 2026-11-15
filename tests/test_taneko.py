import dataclasses, io, json, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TMP = Path(tempfile.mkdtemp())
os.environ["TANEKO_ROOT"] = str(TMP)
from taneko import cli, core, flow, keys, project, srt  # noqa: E402
from taneko.stages import translate  # noqa: E402

SRT = "1\n00:00:01,000 --> 00:00:03,000\nHello Chovy\n\n2\n00:00:04,000 --> 00:00:06,500\nBaron down\n"


def make_project(name, meta):
    d = core.PROJECTS / name
    d.mkdir(parents=True)
    project.save_meta(d, meta)
    return d


def make_video(path, secs):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%d" % secs,
                    "-c:v", "libx264", str(path)], check=True)


class Srt(unittest.TestCase):
    def test_roundtrip(self):
        cues = srt.parse_srt(SRT)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[1]["end"], 6.5)
        p = TMP / "x.srt"
        srt.write_srt(cues, p)
        self.assertEqual(srt.parse_srt(p.read_text("utf-8")), cues)


class ExitCodes(unittest.TestCase):
    def test_codes_are_distinct_and_stable(self):
        self.assertEqual((core.EXIT_OK, core.EXIT_FAIL, core.EXIT_USAGE, core.EXIT_NEEDS_HUMAN), (0, 1, 2, 10))

    def test_die_exits_with_fail(self):
        with self.assertRaises(core.Fail):
            core.die("x")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["status", "no-such-project"]), core.EXIT_FAIL)

    def test_bad_args_exit_2(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            import contextlib
            with contextlib.redirect_stderr(io.StringIO()):
                cli.main(["run"])
        self.assertEqual(cm.exception.code, 2)

    def test_unknown_project_exits_fail(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["run", "no-such-project"]), core.EXIT_FAIL)


class Lookup(unittest.TestCase):
    def setUp(self):
        self.a = make_project("look-a", {"id": "a"})
        self.b = make_project("series/look-b", {"id": "b"})
        make_project("series/look-dup", {})
        make_project("other/look-dup", {})
        make_project("_old/look-hidden", {})

    def tearDown(self):
        for n in ("look-a", "series", "other", "_old"):
            shutil.rmtree(core.PROJECTS / n)

    def test_name_is_found_in_a_subfolder(self):
        self.assertEqual(project.project_dir("look-a"), self.a)
        self.assertEqual(project.project_dir("look-b"), self.b)

    def test_path_and_dot_work(self):
        self.assertEqual(project.project_dir(str(self.b)), self.b.resolve())
        old = os.getcwd()
        try:
            os.chdir(self.b)
            self.assertEqual(project.project_dir("."), self.b.resolve())
        finally:
            os.chdir(old)

    def test_same_name_twice_is_an_error_not_a_guess(self):
        with self.assertRaises(core.Fail) as e:
            project.project_dir("look-dup")
        self.assertIn("2", str(e.exception))

    def test_underscore_folders_are_skipped(self):
        with self.assertRaises(core.Fail):
            project.project_dir("look-hidden")
        self.assertNotIn("look-hidden", [d.name for d in project.dirs()])
        self.assertIn(self.b, project.dirs())


class ApiKey(unittest.TestCase):
    def test_env_wins_and_status_never_prints_the_key(self):
        name = core.load_config("translate")["key_env"]
        old = os.environ.get(name)
        os.environ[name] = "sk-test-SECRET-123456"
        try:
            self.assertEqual(keys.get_api_key(name), "sk-test-SECRET-123456")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["key", "status"])
            self.assertEqual(rc, core.EXIT_OK)
            self.assertNotIn("SECRET", buf.getvalue())      # 不显示内容
            self.assertIn("21 个字符", buf.getvalue())       # 只显示长度
        finally:
            if old is None:
                del os.environ[name]
            else:
                os.environ[name] = old

    def test_status_without_key_returns_fail(self):
        name = core.load_config("translate")["key_env"]
        old = {k: os.environ.pop(k) for k in (name, "CUSTOM_API_KEY") if k in os.environ}
        try:
            if keys._win_env_get(name):
                self.skipTest("这台机器的用户环境变量里已有密钥")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["key", "status"]), core.EXIT_FAIL)
        finally:
            os.environ.update(old)


class KeyCheck(unittest.TestCase):
    """key check 用本机的假服务器测试：好密钥 200，坏密钥 401，额度满 429，连不上。"""

    @classmethod
    def setUpClass(cls):
        import http.server, threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                auth = self.headers.get("Authorization")
                self.send_response({"Bearer good": 200, "Bearer busy": 429}.get(auth, 401))
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        for k in ("no_proxy", "NO_PROXY"):                   # 本机有代理时，别把假服务器的请求交给代理
            os.environ[k] = ",".join(filter(None, [os.environ.get(k), "127.0.0.1"]))
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cfg = {"server": "http://127.0.0.1:%d" % cls.srv.server_port, "endpoint": "/v1/chat/completions", "model": "m"}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_check(self, key, cfg=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = keys.check(cfg or self.cfg, key, timeout=5)
        self.assertNotIn(key, buf.getvalue())               # 从不显示密钥
        return rc, buf.getvalue()

    def test_good_bad_busy_and_offline(self):
        self.assertEqual(self.run_check("good")[0], core.EXIT_OK)
        rc, out = self.run_check("bad-SECRET")
        self.assertEqual(rc, core.EXIT_FAIL)
        self.assertIn("401", out)
        self.assertIn("429", self.run_check("busy")[1])
        rc, out = self.run_check("good", dict(self.cfg, server="http://127.0.0.1:1"))
        self.assertEqual(rc, core.EXIT_FAIL)
        self.assertIn("连不上", out)


class Segments(unittest.TestCase):
    def cues(self, n):
        return [{"start": float(i), "end": i + 0.5, "text": "en%d" % i} for i in range(n)]

    def test_resume_skips_finished_segments(self):
        en, seg = self.cues(10), TMP / "seg1"
        calls = []

        def make(fail_on):
            def run_one(src, out):
                calls.append(src.name)
                if src.name == fail_on:
                    return False  # 模拟这一段卡住/失败
                srt.write_srt([dict(c, text="zh" + c["text"][2:]) for c in srt.parse_srt(src.read_text("utf-8"))], out)
                return True
            return run_one

        with redirect_stdout(io.StringIO()), self.assertRaises(core.Fail):
            translate.translate_segments(en, seg, make("en_02.srt"), size=4)
        self.assertEqual(calls, ["en_01.srt", "en_02.srt"])      # 第 2 段失败，停下
        self.assertTrue((seg / "zh_01.srt").exists())             # 第 1 段已存盘
        calls.clear()
        with redirect_stdout(io.StringIO()):
            zh = translate.translate_segments(en, seg, make(None), size=4)
        self.assertEqual(calls, ["en_02.srt", "en_03.srt"])      # 重跑：跳过第 1 段
        self.assertEqual([z["text"] for z in zh], ["zh%d" % i for i in range(10)])  # 顺序、条数完整

    def test_tiny_last_segment_is_merged(self):
        seen = []

        def run_one(src, out):
            seen.append(len(srt.parse_srt(src.read_text("utf-8"))))
            srt.write_srt(srt.parse_srt(src.read_text("utf-8")), out)
            return True

        with redirect_stdout(io.StringIO()):
            translate.translate_segments(self.cues(17), TMP / "seg2", run_one, size=8)
        self.assertEqual(seen, [8, 9])  # 末段只有 1 条（不足四分之一段），并入前一段


class Flow(unittest.TestCase):
    def meta(self, **kw):
        m = {"source_url": "u", "video_glob": "*.mkv", "section": {"download": "0:00:00-0:00:10", "name": "g"},
             "subtitle": {"source_lang": "en", "asr_language": "en", "method": "asr"}, "translate": {}}
        m.update(kw)
        return m

    def test_plan_zh_source_has_no_translation(self):
        m = self.meta(subtitle={"source_lang": "zh", "asr_language": "zh", "method": "asr"})
        self.assertEqual(flow.plan(m), ["fetch", "asr"])

    def test_plan_method_none_is_download_only(self):
        self.assertEqual(flow.plan({"subtitle": {"method": "none", "source_lang": "en"}}), ["fetch"])

    def test_fetch_done_requires_full_duration(self):
        d = make_project("p1", self.meta())
        self.assertFalse(flow.STAGES["fetch"].done(d, project.load_meta(d)))
        make_video(d / "g.mkv", 3)  # 预期 10 秒，只有 3 秒 -> 半截
        self.assertFalse(flow.STAGES["fetch"].done(d, project.load_meta(d)))
        make_video(d / "g.mkv", 10)
        self.assertTrue(flow.STAGES["fetch"].done(d, project.load_meta(d)))
        (d / "_parts").mkdir()
        self.assertFalse(flow.STAGES["fetch"].done(d, project.load_meta(d)))

    def test_run_stops_at_gates_and_resumes(self):
        d = make_project("p2", self.meta(translate={"corrections": {"Chovie": "Chovy"}}))
        calls = []

        def fake(step):
            def f(a):
                calls.append(step)
                if step == "fetch":
                    make_video(d / "g.mkv", 10)
                elif step == "asr":
                    (d / "en.srt").write_text(SRT, "utf-8")
                elif step == "terms":
                    (d / "terms.txt").write_text("2 Chovy\n", "utf-8")
                elif step == "fix":
                    shutil.copyfile(d / "en.srt", d / "en.srt.orig")
                elif step == "translate":
                    srt.write_srt([dict(c, text="中文") for c in srt.parse_srt(SRT)], d / "zh.srt")
            return f

        orig = dict(flow.STAGES)
        flow.STAGES.update({k: dataclasses.replace(orig[k], run=fake(k))
                            for k in ("fetch", "asr", "terms", "fix", "translate")})
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["run", "p2"])
            self.assertEqual(rc, core.EXIT_NEEDS_HUMAN)  # 停在人工检查点：退出码 10
            self.assertEqual(calls, ["fetch", "asr", "terms"])  # 在术语检查点停下
            self.assertIn("approve p2 terms", buf.getvalue())
            with redirect_stdout(io.StringIO()):
                cli.main(["approve", "p2", "terms"])
                cli.main(["run", "p2"])
            self.assertEqual(calls, ["fetch", "asr", "terms", "fix", "translate"])  # check 是真实逻辑，不用假的
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["run", "p2"])
            self.assertEqual(rc, core.EXIT_NEEDS_HUMAN)  # 抽查检查点：也是 10
            self.assertEqual(calls, ["fetch", "asr", "terms", "fix", "translate"])  # 重跑：已完成的全部跳过
            self.assertIn("approve p2 spot", buf.getvalue())
            with redirect_stdout(io.StringIO()):
                cli.main(["approve", "p2", "spot"])
                buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["run", "p2"])
            self.assertEqual(rc, core.EXIT_OK)  # 全部完成：0
            self.assertIn("全部完成", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.main(["status", "p2"])
            self.assertNotIn("→", buf.getvalue())
        finally:
            flow.STAGES.update(orig)

    def test_check_detects_timing_change(self):
        d = make_project("p3", self.meta())
        (d / "en.srt").write_text(SRT, "utf-8")
        bad = srt.parse_srt(SRT)
        bad[0]["start"] += 1
        srt.write_srt([dict(c, text="中") for c in bad], d / "zh.srt")
        self.assertFalse(flow.STAGES["check"].done(d, project.load_meta(d)))


class Layers(unittest.TestCase):
    """依赖只往下走：cli → flow → stages → project / srt / keys / stitch → core。阶段之间互不引用。"""
    ALLOWED = {"core": set(), "stitch": set(), "srt": {"core"}, "project": {"core"}, "keys": {"core"},
               "stages": {"core", "project", "srt", "keys", "stitch"}, "flow": {"core", "project", "stages"},
               "cli": {"core", "flow", "keys", "project"}}

    def test_imports_only_go_down(self):
        import ast
        pkg = Path(core.__file__).parent
        for f in pkg.rglob("*.py"):
            rel = f.relative_to(pkg).parts
            layer = rel[0][:-3] if len(rel) == 1 else rel[0]
            if layer in ("__init__", "__main__", "workers"):
                continue
            for n in ast.walk(ast.parse(f.read_text("utf-8"))):
                if isinstance(n, ast.ImportFrom) and n.level:
                    where = "/".join(rel)
                    self.assertFalse(len(rel) > 1 and n.level == 1, "%s 引用了同层的其他阶段" % where)
                    targets = [n.module.split(".")[0]] if n.module else [a.name for a in n.names]
                    for t in targets:
                        if t != layer:
                            self.assertIn(t, self.ALLOWED[layer], "%s 不能引用 %s" % (where, t))



class OneAgentsFile(unittest.TestCase):
    """规则只有一份 AGENTS.md。有 CLAUDE.md 时 Claude Code 只读它、不读 AGENTS.md，规则就分叉了。"""

    def test_no_claude_md_anywhere(self):
        repo = Path(__file__).resolve().parent.parent
        self.assertTrue((repo / "AGENTS.md").is_file())
        found = [str(p.relative_to(repo)) for name in ("CLAUDE.md", "CLAUDE.local.md") for p in repo.rglob(name)
                 if ".git" not in p.relative_to(repo).parts]
        self.assertEqual(found, [], "删掉这些文件，规则写进 AGENTS.md：%s" % found)

if __name__ == "__main__":
    unittest.main()
