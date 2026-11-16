import dataclasses, io, json, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TMP = Path(tempfile.mkdtemp())
os.environ["TANEKO_ROOT"] = str(TMP)
from taneko import cli, core, doctor, flow, keys, project, srt  # noqa: E402
from taneko import ranges, stitch  # noqa: E402
from taneko.stages import fetch, translate  # noqa: E402

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


class Doctor(unittest.TestCase):
    def test_missing_tool_fails_and_says_how_to_install(self):
        old = os.environ["PATH"]
        os.environ["PATH"] = str(TMP / "empty")       # 什么工具都找不到
        try:
            rows = {name: (must, ok, msg) for must, name, ok, msg in doctor.checks("darwin")}
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["doctor"])
        finally:
            os.environ["PATH"] = old
        self.assertEqual(rc, core.EXIT_FAIL)
        self.assertEqual(rows["ffmpeg"], (True, False, "没找到。装法：brew install ffmpeg"))
        self.assertFalse(rows["Whisper 转写（字幕，实验性）"][0])  # 字幕工具是可选的
        self.assertIn("还缺：", buf.getvalue())

    def test_install_hints_per_platform(self):
        self.assertEqual(doctor._how("deno", "win32"), "winget install DenoLand.Deno")
        self.assertEqual(doctor._how("ffmpeg", "linux"), "sudo apt install ffmpeg")


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

    def test_status_json_for_scripts(self):
        make_project("js1", self.meta())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["status", "--json", "js1"])
        self.assertEqual(rc, core.EXIT_OK)
        (row,) = json.loads(buf.getvalue())["projects"]
        self.assertEqual((row["project"], row["next"], row["needs_human"]), ("js1", "fetch", False))
        self.assertEqual([s["state"] for s in row["steps"]][:2], ["next", "todo"])
        self.assertEqual(row["steps"][0]["name"], "fetch")

    def test_no_error_says_send_it_to_me(self):
        src = "".join(f.read_text("utf-8") for f in Path(core.__file__).parent.rglob("*.py"))
        self.assertNotIn("发给我", src)

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


class Ranges(unittest.TestCase):
    """按索引下载（issue #8）：读 MP4 的 sidx 和 WebM 的 Cues，只取覆盖这段时间的字节，断了接着下。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = TMP / "ranges"
        cls.dir.mkdir()
        cls.a, cls.v, cls.plain = cls.dir / "a.m4a", cls.dir / "v.webm", cls.dir / "plain.m4a"
        ff = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
        subprocess.run(ff + ["sine=frequency=440:duration=45", "-c:a", "aac", "-f", "mp4", "-movflags", "+dash+global_sidx",
                             "-frag_duration", "2000000", str(cls.a)], check=True)
        subprocess.run(ff + ["mandelbrot=size=64x64:rate=10", "-t", "45", "-c:v", "libvpx", "-g", "25", "-keyint_min", "25",
                             "-b:v", "200k", "-cues_to_front", "1", str(cls.v)], check=True)
        subprocess.run(ff + ["sine=duration=10", "-c:a", "aac", str(cls.plain)], check=True)

    @staticmethod
    def getter(path, fail_after=None):
        data, calls = path.read_bytes(), [0]

        def get(a, b):
            calls[0] += 1
            if fail_after is not None and calls[0] > fail_after:
                raise OSError("network down")
            return data[a:b + 1]
        return data, get

    def fetch_range(self, src, ext, a, b, name):
        data, get = self.getter(src)
        init, frags = ranges.index(ext, get)
        t0, lo, hi = ranges.pick(frags, len(data), a, b)
        out = self.dir / name
        ranges.download(get, out, init, lo, hi, len(data), log=lambda *_: None)
        return out, t0

    def test_both_indexes_cover_the_range(self):
        for src, ext, name in ((self.a, "m4a", "ra.m4a"), (self.v, "webm", "rv.webm")):
            out, t0 = self.fetch_range(src, ext, 10, 20, name)
            pk = stitch.video_packets(out) or stitch.audio_packets(out)
            self.assertLessEqual(pk[0][0], 10, name)
            self.assertGreaterEqual(pk[-1][0], 19.5, name)
            self.assertLess(out.stat().st_size, src.stat().st_size * 0.6, name)   # 只下了一部分

    def test_no_index_means_fallback(self):
        _, get = self.getter(self.plain)
        with self.assertRaises(ranges.NoIndex):
            ranges.index("m4a", get)

    def test_resume_after_a_break(self):
        data, get = self.getter(self.a)
        init, frags = ranges.index("m4a", get)
        _, lo, hi = ranges.pick(frags, len(data), 10, 30)
        out = self.dir / "resume.m4a"
        _, broken = self.getter(self.a, fail_after=3)
        with self.assertRaises(OSError):
            ranges.download(broken, out, init, lo, hi, len(data), log=lambda *_: None, chunk=4096, retries=1)
        part = out.with_name(out.name + ".part")
        self.assertEqual(part.stat().st_size, init + 2 * 4096)   # 文件头 + 两块，已下的没有丢
        calls = []
        ranges.download(lambda x, y: calls.append(x) or data[x:y + 1], out, init, lo, hi, len(data),
                        log=lambda *_: None, chunk=4096)
        self.assertEqual(out.read_bytes(), data[:init] + data[lo:hi + 1])
        self.assertEqual(calls[0], lo + 2 * 4096)                # 从断开的地方接着下，不从头来

    def test_refused_url_is_waited_for(self):
        """YouTube 新地址常常先回 403、等几秒就好：同一个地址等一等再试；一直被拒才抛 Refused。"""
        data, calls = self.a.read_bytes(), []

        def late(x, y):                          # 前两次 403，之后正常
            calls.append(x)
            if len(calls) <= 2:
                raise ranges.Refused("403")
            return data[x:y + 1]

        def never(x, y):
            calls.append(x)
            raise ranges.Refused("403")
        old, ranges.REFUSED_WAITS = ranges.REFUSED_WAITS, (0, 0, 0)
        try:
            init, frags = ranges.index("m4a", late)
            self.assertGreater(len(frags), 2)
            calls.clear()
            with self.assertRaises(ranges.Refused):
                ranges.download(never, self.dir / "refused.m4a", 10, 100, 200, 1000, log=lambda *_: None)
            self.assertEqual(len(calls), 4)      # 第一次 + 等了 3 次
        finally:
            ranges.REFUSED_WAITS = old

    def test_refused_url_is_fetched_again(self):
        tries = []

        def once(j, w0, w1):
            tries.append(1)
            if len(tries) < 3:
                raise ranges.Refused("403")
        old = fetch._ranges_once
        fetch._ranges_once = once
        try:
            with redirect_stdout(io.StringIO()) as out:
                fetch._fetch_ranges(None, 0, 10)
            self.assertEqual(len(tries), 3)
            self.assertIn("重新取地址", out.getvalue())
            tries.clear()
            fetch._ranges_once = lambda j, a, b: (_ for _ in ()).throw(ranges.Refused("403"))
            with redirect_stdout(io.StringIO()), self.assertRaises(ranges.NoIndex):
                fetch._fetch_ranges(None, 0, 10)           # 三次都被拒：改用分段下载
        finally:
            fetch._ranges_once = old

    def test_cut_gives_a_clean_section(self):
        v, _ = self.fetch_range(self.v, "webm", 12, 31, "cv.webm")
        a, _ = self.fetch_range(self.a, "m4a", 12, 31, "ca.m4a")
        parts = self.dir / "cut"
        parts.mkdir()
        j = SimpleNamespace(parts=parts, out=self.dir / "cut.mkv", a=SimpleNamespace(keep=True))
        with redirect_stdout(io.StringIO()):
            fetch._cut(j, [(v, True), (a, False)], 12, 31)
        ok, msg = stitch.verify(j.out, expected_s=19)
        self.assertTrue(ok, msg)
        ap, vp = stitch.audio_packets(j.out), stitch.video_packets(j.out)
        self.assertAlmostEqual(ap[0][0] - vp[0][0], 12 - 10, delta=0.05)   # 视频从 10 秒的关键帧开始，音频从 12 秒开始


class Seams(unittest.TestCase):
    """像 yt-dlp 截片段那样造分片：视频从起点前的关键帧开始，音频从起点开始。拼起来后音频不能有空白。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = TMP / "seams"
        cls.dir.mkdir()
        cls.v, cls.a = cls.dir / "src_v.mkv", cls.dir / "src_a.m4a"
        ff = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
        subprocess.run(ff + ["mandelbrot=size=64x64:rate=10", "-t", "45", "-c:v", "libx264", "-g", "25",
                             "-keyint_min", "25", "-sc_threshold", "0", str(cls.v)], check=True)
        subprocess.run(ff + ["sine=frequency=440:duration=45", "-c:a", "aac", str(cls.a)], check=True)

    def piece(self, name, a, b, audio_end=None):
        """yt-dlp --download-sections + ffmpeg_i:-copyts 的样子：两路输入各自 seek，时间戳保持绝对值。"""
        out = self.dir / name
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-copyts", "-ss", str(a), "-t", str(b - a), "-i", str(self.v),
                        "-copyts", "-ss", str(a), "-t", str((audio_end or b) - a), "-i", str(self.a),
                        "-map", "0:v", "-map", "1:a", "-c", "copy", str(out)], check=True)
        return out

    def test_pieces_start_like_ytdlp(self):
        p = self.piece("p1.mkv", 11, 20)
        self.assertLess(stitch.video_packets(p)[0][0], 11 - 0.5)      # 视频从 10 秒的关键帧开始
        self.assertAlmostEqual(stitch.audio_packets(p)[0][0], 11, delta=0.1)  # 音频从 11 秒开始
        self.assertTrue(fetch._verify_piece(p, 11, 20, False)[0])

    def test_short_audio_is_rejected(self):
        p = self.piece("short.mkv", 0, 10, audio_end=5)
        ok, msg = fetch._verify_piece(p, 0, 10, False)
        self.assertFalse(ok)
        self.assertIn("音频", msg)

    def test_assembled_audio_has_no_gaps(self):
        parts = [self.piece("q%d.mkv" % i, a, a + 9 if a < 18 else 30) for i, a in enumerate((0, 9, 18))]
        out = self.dir / "out.mkv"
        stitch.assemble(out, parts, workdir=self.dir, log=lambda *_: None)
        ok, msg = stitch.verify(out, expected_s=30)
        self.assertTrue(ok, msg)
        ap, vp = stitch.audio_packets(out), stitch.video_packets(out)
        gaps = [b[0] - a[0] - a[1] for a, b in zip(ap, ap[1:])]
        self.assertLess(max(gaps), 0.05, msg)
        self.assertAlmostEqual(ap[0][0] - vp[0][0], 0, delta=0.05)               # 开头音画对齐
        self.assertAlmostEqual(ap[-1][0] + ap[-1][1] - ap[0][0], 30, delta=0.2)  # 声音一秒不少

    def test_seed_then_pieces_have_no_gaps(self):
        seed = self.dir / "seed.mkv"  # 旧的半截文件：没有 -copyts，时间从 0 开始（原视频 5～35 秒）
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "5", "-t", "30", "-i", str(self.v), "-ss", "5", "-t", "30",
                        "-i", str(self.a), "-map", "0:v", "-map", "1:a", "-c", "copy", str(seed)], check=True)
        parts = [self.piece("s0.mkv", 10, 40), self.piece("s1.mkv", 40, 45)]  # 第一片从种子结尾前 25 秒开始，同 fetch
        out = self.dir / "seeded.mkv"
        stitch.assemble(out, parts, seed=seed, workdir=self.dir, log=lambda *_: None)
        ok, msg = stitch.verify(out, expected_s=40)
        self.assertTrue(ok, msg)
        ap = stitch.audio_packets(out)
        self.assertAlmostEqual(ap[-1][0] + ap[-1][1] - ap[0][0], 40, delta=0.2, msg=msg)

    def test_verify_reports_a_silent_gap(self):
        ff = ["ffmpeg", "-v", "error", "-y", "-copyts"]
        a1, a2, lst, out = (self.dir / n for n in ("g1.mka", "g2.mka", "gap.txt", "gap.mkv"))
        subprocess.run(ff + ["-t", "10", "-i", str(self.a), "-c", "copy", str(a1)], check=True)
        subprocess.run(ff + ["-ss", "14", "-t", "16", "-i", str(self.a), "-c", "copy", str(a2)], check=True)
        lst.write_text("file '%s'\ninpoint 0\nduration 14\nfile '%s'\ninpoint 14\n" % (a1.as_posix(), a2.as_posix()), "utf-8")
        subprocess.run(ff + ["-t", "30", "-i", str(self.v), "-f", "concat", "-safe", "0", "-i", str(lst),
                             "-map", "0:v", "-map", "1:a", "-c", "copy", str(out)], check=True)  # 10～14 秒没有音频
        ok, msg = stitch.verify(out)
        self.assertFalse(ok, msg)
        self.assertIn("没声音", msg)

    def test_one_rule_for_complete(self):
        self.assertTrue(stitch.duration_ok(594, 600))       # 短 6 秒：容差至少 6 秒
        self.assertFalse(stitch.duration_ok(590, 600))
        self.assertTrue(stitch.duration_ok(3280, 3300))     # 长片段按 1%，最多 25 秒
        self.assertFalse(stitch.duration_ok(3270, 3300))


class Layers(unittest.TestCase):
    """依赖只往下走：cli → flow → stages → project / srt / keys / stitch → core。阶段之间互不引用。"""
    ALLOWED = {"core": set(), "stitch": set(), "ranges": set(), "srt": {"core"}, "project": {"core"}, "keys": {"core"}, "doctor": {"core"},
               "stages": {"core", "project", "srt", "keys", "stitch", "ranges"}, "flow": {"core", "project", "stages"},
               "cli": {"core", "doctor", "flow", "keys", "project"}}

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
