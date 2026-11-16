import io, json, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TMP = Path(tempfile.mkdtemp())
os.environ["TANEKO_ROOT"] = str(TMP)
from taneko import cli, core, doctor, flow, project  # noqa: E402
from taneko import hls, progress, ranges, stitch  # noqa: E402
from taneko.stages import fetch  # noqa: E402

def make_project(name, meta):
    d = core.PROJECTS / name
    d.mkdir(parents=True)
    project.save_meta(d, meta)
    return d


def make_video(path, secs):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%d" % secs,
                    "-c:v", "libx264", str(path)], check=True)


class ExitCodes(unittest.TestCase):
    def test_codes_are_distinct_and_stable(self):
        self.assertEqual((core.EXIT_OK, core.EXIT_FAIL, core.EXIT_USAGE), (0, 1, 2))

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

    def test_no_args_shows_short_help(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main([]), core.EXIT_OK)
        text = out.getvalue()
        self.assertIn("例子", text)

    def test_empty_status_says_what_to_do(self):
        from unittest import mock
        out = io.StringIO()
        with mock.patch.object(project, "PROJECTS", TMP / "no-projects-yet"), redirect_stdout(out):
            (TMP / "no-projects-yet").mkdir(exist_ok=True)
            cli.main(["status"])
        self.assertIn("init", out.getvalue())

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
        self.assertIn("还缺：", buf.getvalue())

    def test_install_hints_per_platform(self):
        self.assertEqual(doctor._how("deno", "win32"), "winget install DenoLand.Deno")
        self.assertEqual(doctor._how("ffmpeg", "linux"), "sudo apt install ffmpeg")


class Flow(unittest.TestCase):
    def meta(self, **kw):
        m = {"source_url": "u", "video_glob": "*.mkv", "section": {"download": "0:00:00-0:00:10", "name": "g"}}
        m.update(kw)
        return m

    def test_status_json_for_scripts(self):
        make_project("js1", self.meta())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["status", "--json", "js1"])
        self.assertEqual(rc, core.EXIT_OK)
        (row,) = json.loads(buf.getvalue())["projects"]
        self.assertEqual((row["project"], row["next"]), ("js1", "fetch"))
        self.assertEqual([s["state"] for s in row["steps"]], ["next"])
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

class Init(unittest.TestCase):
    """taneko init（issue #5）：新手不用手写 meta.json。"""

    def tearDown(self):
        shutil.rmtree(core.PROJECTS / "init-group", ignore_errors=True)

    def init(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["init", *argv])
        return rc, out.getvalue()

    def test_init_writes_a_runnable_project(self):
        rc, out = self.init("init-group/g3", "https://www.youtube.com/watch?v=x", "--section", "4:13:00-4:14:00")
        self.assertEqual(rc, core.EXIT_OK, out)
        self.assertIn("run g3", out)
        d = project.project_dir("g3")
        meta = project.load_meta(d)
        self.assertEqual(meta["section"], {"name": "g3", "download": "4:13:00-4:14:00"})
        self.assertEqual(flow.plan(meta), ["fetch"])
        self.assertEqual(fetch.expected_duration(meta), 60)
        self.assertNotIn("fetch", meta)   # 浏览器用默认的 firefox

    def test_init_refuses_bad_input(self):
        self.assertEqual(self.init("init-group/g4", '"https://x.test/v"', "--browser", "none")[0], core.EXIT_OK)
        meta = project.load_meta(project.project_dir("g4"))
        self.assertEqual((meta["fetch"], meta["source_url"]), ({"browser": "none"}, "https://x.test/v"))   # 引号去掉了
        for argv in (("init-group/g4", "https://x.test/v"),                       # 同名项目已经有了
                     ("init-group/g5", "x.test/v"),                               # 不是网址
                     ("init-group/g5", "https://x.test/v", "--section", "5:00-4:00"),
                     ("init-group/g5", "https://x.test/v", "--section", "abc"),
                     ("init-group/_g5", "https://x.test/v"), ("a/b/c/d", "https://x.test/v")):
            rc, out = self.init(*argv)
            self.assertEqual(rc, core.EXIT_FAIL, argv)
            self.assertIn("错误：", out)
        self.assertFalse((core.PROJECTS / "init-group" / "g5").exists())


class Packaging(unittest.TestCase):
    """pip 安装（issue #5）：pyproject.toml 要带上每个子包和每个配置文件，否则装好的 taneko 缺文件。"""

    def test_pyproject_lists_every_package_and_config(self):
        import tomllib
        root = Path(core.__file__).resolve().parent.parent
        conf = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
        pkgs = {".".join(f.parent.relative_to(root).parts) for f in (root / "taneko").rglob("__init__.py")}
        self.assertEqual(set(conf["tool"]["setuptools"]["packages"]), pkgs)
        self.assertEqual(conf["project"]["scripts"]["taneko"], "taneko.cli:main")
        self.assertEqual(conf["project"]["requires-python"], ">=3.11")
        self.assertEqual(conf["project"]["dependencies"], ["yt-dlp[default]>=2026.10.26"])   # 唯一的依赖，只作为命令调用
        import taneko
        self.assertEqual(conf["project"]["version"], taneko.__version__)


class Ranges(unittest.TestCase):
    """按索引下载（issue #8）：读 MP4 的 sidx 和 WebM 的 Cues，只取覆盖这段时间的字节，断了接着下。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = TMP / "ranges"
        cls.dir.mkdir()
        cls.a, cls.v, cls.plain = cls.dir / "a.m4a", cls.dir / "v.webm", cls.dir / "plain.m4a"
        cls.opus = cls.dir / "a.webm"
        ff = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
        subprocess.run(ff + ["sine=frequency=440:duration=45", "-c:a", "aac", "-f", "mp4", "-movflags", "+dash+global_sidx",
                             "-frag_duration", "2000000", str(cls.a)], check=True)
        subprocess.run(ff + ["mandelbrot=size=64x64:rate=10", "-t", "45", "-c:v", "libvpx", "-g", "25", "-keyint_min", "25",
                             "-b:v", "200k", "-cues_to_front", "1", str(cls.v)], check=True)
        subprocess.run(ff + ["sine=duration=10", "-c:a", "aac", str(cls.plain)], check=True)
        subprocess.run(ff + ["sine=frequency=440:duration=45", "-c:a", "libopus", "-cluster_time_limit", "2000",
                             "-cues_to_front", "1", str(cls.opus)], check=True)   # 像 YouTube 的 251

    @staticmethod
    def getter(path, fail_after=None):
        data, calls = path.read_bytes(), [0]

        def get(a, b, sink=None):
            calls[0] += 1
            if fail_after is not None and calls[0] > fail_after:
                raise OSError("network down")
            return sink(data[a:b + 1]) if sink else data[a:b + 1]
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
        ranges.download(lambda x, y, sink: calls.append(x) or sink(data[x:y + 1]), out, init, lo, hi, len(data),
                        log=lambda *_: None, chunk=4096)
        self.assertEqual(out.read_bytes(), data[:init] + data[lo:hi + 1])
        self.assertEqual(calls[0], lo + 2 * 4096)                # 从断开的地方接着下，不从头来

    def test_bytes_are_kept_as_they_arrive(self):
        """网慢时一块要下很久：半块时断了，收到的那半块也留在文件里，重试从那里接着要。"""
        data, get = self.getter(self.a)
        init, frags = ranges.index("m4a", get)
        _, lo, hi = ranges.pick(frags, len(data), 10, 30)
        out, calls, seen = self.dir / "half.m4a", [], []

        def flaky(a, b, sink):
            calls.append(a)
            if len(calls) == 2:          # 第二次请求：只收到一半就断了
                sink(data[a:a + 1000])
                raise OSError("connection reset")
            sink(data[a:b + 1])
        ranges.download(flaky, out, init, lo, hi, len(data), log=lambda *_: None, chunk=4096,
                        tick=lambda have, got: seen.append(have))
        self.assertEqual(out.read_bytes(), data[:init] + data[lo:hi + 1])
        self.assertEqual(calls[2], calls[1] + 1000)              # 重试从收到的地方接着要
        self.assertEqual(seen[-1], init + hi - lo + 1)

    def test_size_comes_from_the_server(self):
        """B 站不给确切大小，也要带 Referer：大小从 Content-Range 读，请求头照传。"""
        import http.server, threading
        data = self.a.read_bytes()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Referer") != "https://site.test/":
                    self.send_response(403); self.end_headers(); return
                a, b = [int(x) for x in self.headers["Range"].split("=")[1].split("-")]
                b = min(b, len(data) - 1)
                self.send_response(206)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, len(data)))
                self.send_header("Content-Length", str(b - a + 1))
                self.end_headers()
                self.wfile.write(data[a:b + 1])

            def log_message(self, *a):
                pass

        for k in ("no_proxy", "NO_PROXY"):
            os.environ[k] = ",".join(filter(None, [os.environ.get(k), "127.0.0.1"]))
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%d/a.m4a" % srv.server_port
            with self.assertRaises(ranges.Refused):
                ranges.getter(url)(0, 99)                                  # 没带 Referer
            get = ranges.getter(url, {"Referer": "https://site.test/"})
            self.assertIsNone(get.total)
            init, frags = ranges.index("m4a", get)
            self.assertEqual(get.total, len(data))
            t0, lo, hi = ranges.pick(frags, get.total, 10, 20)
            out = self.dir / "srv.m4a"
            ranges.download(get, out, init, lo, hi, get.total, log=lambda *_: None)
            self.assertEqual(out.read_bytes(), data[:init] + data[lo:hi + 1])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_refused_url_is_waited_for(self):
        """YouTube 新地址常常先回 403、等几秒就好：同一个地址等一等再试；一直被拒才抛 Refused。"""
        data, calls = self.a.read_bytes(), []

        def late(x, y):                          # 前两次 403，之后正常
            calls.append(x)
            if len(calls) <= 2:
                raise ranges.Refused("403")
            return data[x:y + 1]

        def never(x, y, sink=None):
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
        v, tv = self.fetch_range(self.v, "webm", 12, 31, "cv.webm")
        for src, ext in ((self.a, "m4a"), (self.opus, "webm")):   # WebM 音频不能在输入端跳转（Windows 试用时发现）
            with self.subTest(ext):
                a, _ = self.fetch_range(src, ext, tv, 31, "ca." + ext)   # 音频从视频的关键帧开始下，和 fetch 一样
                parts = self.dir / ("cut_" + ext)
                parts.mkdir()
                j = SimpleNamespace(parts=parts, out=self.dir / ("cut_%s.mkv" % ext), a=SimpleNamespace(keep=True))
                with redirect_stdout(io.StringIO()):
                    fetch._cut(j, [(v, True), (a, False)], 12, 31)
                ok, msg = stitch.verify(j.out, expected_s=19, need_audio=True)
                self.assertTrue(ok, msg)
                ap, vp = stitch.audio_packets(j.out), stitch.video_packets(j.out)
                self.assertAlmostEqual(ap[0][0], vp[0][0], delta=0.05)   # 视频从 10 秒的关键帧开始，音频也是：开头不会没声音

    def test_missing_audio_fails_the_check(self):
        out = self.dir / "silent.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(self.v), "-c", "copy", str(out)], check=True)
        self.assertTrue(stitch.verify(out)[0])
        self.assertFalse(stitch.verify(out, need_audio=True)[0])


class Hls(unittest.TestCase):
    """按播放列表下载（X 等用 HLS 的网站）：只下覆盖这一段的分片，断了跳过已下完的分片。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = TMP / "hls"
        cls.dir.mkdir()
        lav = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
        vid = ["mandelbrot=size=64x64:rate=10", "-t", "30", "-c:v", "libx264", "-g", "10", "-keyint_min", "10",
               "-sc_threshold", "0"]
        aud = ["sine=frequency=440:duration=30", "-c:a", "aac"]
        for kind, seg in (("fmp4", "m4s"), ("mpegts", "ts")):     # X 用 fMP4；TS 的时间戳通常从 1.4 秒开始
            for name, args in (("v", vid), ("a", aud)):
                out = "%s_%s" % (kind, name)        # 相对文件名，在测试目录里运行：Windows 上 init 文件才不会写到别处
                extra = ["-hls_fmp4_init_filename", out + "_init.mp4"] if kind == "fmp4" else []
                subprocess.run(lav + args + ["-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
                                             "-hls_segment_type", kind, "-hls_segment_filename",
                                             out + "_%03d." + seg] + extra + [out + ".m3u8"], check=True, cwd=cls.dir)

    @staticmethod
    def fetcher(fail_after=None):
        import urllib.parse, urllib.request
        calls = [0]

        def fetch(u):
            calls[0] += 1
            if fail_after is not None and calls[0] > fail_after:
                raise OSError("network down")
            return Path(urllib.request.url2pathname(urllib.parse.urlparse(u).path)).read_bytes()
        return fetch, calls

    def url(self, name):
        return (self.dir / name).as_uri()

    def test_playlist_is_the_index(self):
        text = (self.dir / "fmp4_v.m3u8").read_text()
        init, segs = hls.playlist(text, self.url("fmp4_v.m3u8"))
        self.assertTrue(init.endswith("fmp4_v_init.mp4"))
        self.assertAlmostEqual(sum(d for _, d, _ in segs), 30, delta=0.2)
        idx = hls.pick(segs, 13, 21)
        self.assertLessEqual(segs[idx[0]][0], 13)
        self.assertGreaterEqual(segs[idx[-1]][0] + segs[idx[-1]][1], 21)
        for bad in (text.replace("#EXT-X-ENDLIST", ""), text.replace("#EXTINF", '#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXTINF', 1),
                    "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nv.m3u8\n"):
            with self.assertRaises(ranges.NoIndex):
                hls.playlist(bad, self.url("x.m3u8"))

    def test_resume_skips_finished_segments(self):
        dst = self.dir / "h_v.mp4"
        fetch, calls = self.fetcher(fail_after=4)                 # 播放列表 + init + 2 片，然后断网
        with self.assertRaises(OSError):
            hls.download(fetch, self.url("fmp4_v.m3u8"), dst, 13, 21, log=lambda *_: None, retries=1)
        fetch, calls = self.fetcher()
        t0 = hls.download(fetch, self.url("fmp4_v.m3u8"), dst, 13, 21, log=lambda *_: None)
        self.assertEqual(t0, 12)
        self.assertEqual(calls[0], 1 + 5 - 2)                    # 播放列表 + 剩下的 3 片（共 5 片，已有 init 和 2 片）
        pk = stitch.video_packets(dst)
        self.assertAlmostEqual(pk[0][0], 12, delta=0.25)                  # B 帧让第一帧晚 2 帧（0.2 秒）
        self.assertGreaterEqual(pk[-1][0], 21)
        self.assertEqual(hls.download(fetch, self.url("fmp4_v.m3u8"), dst, 13, 21), 12)   # 已下完：不再下载

    def test_cut_lines_up_ts_timestamps(self):
        parts = self.dir / "cut"
        parts.mkdir()
        files, shift = [], 0.0
        for name, is_video in (("mpegts_v", True), ("mpegts_a", False)):
            dst = parts / ("h_%s.ts" % name)
            t0 = hls.download(self.fetcher()[0], self.url(name + ".m3u8"), dst, 13, 21, log=lambda *_: None)
            files.append((dst, is_video))
            if is_video:
                shift = stitch.video_packets(dst)[0][0] - t0
        self.assertGreater(shift, 1)                                # TS 的时间戳不从 0 开始
        j = SimpleNamespace(parts=parts, out=self.dir / "cut.mkv", a=SimpleNamespace(keep=True))
        with redirect_stdout(io.StringIO()):
            fetch._cut(j, files, 13, 21, shift)
        ok, msg = stitch.verify(j.out, expected_s=8, need_audio=True)
        self.assertTrue(ok, msg)
        ap, vp = stitch.audio_packets(j.out), stitch.video_packets(j.out)
        self.assertAlmostEqual(ap[0][0] - vp[0][0], 0, delta=0.1)   # 视频从 12 秒的分片开始，声音也是
        self.assertAlmostEqual(vp[-1][0] - vp[0][0], 21 - 12, delta=0.5)   # 结尾截在 21 秒；时间戳没对齐会差 1.4 秒


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


class Progress(unittest.TestCase):
    """一行进度：百分比、大小、速度、还要多久；终端里原地刷新，不是终端时每 10% 一行。"""

    class Out(io.StringIO):
        def __init__(self, tty):
            super().__init__(); self.tty = tty

        def isatty(self):
            return self.tty

    def run_bar(self, tty, start=0):
        out, now = self.Out(tty), [0.0]
        bar = progress.Bar(100 * 2**20, out=out, clock=lambda: now[0])
        for k in range(start, 101):
            now[0] = (k - start) * 0.5            # 每秒 2 MiB
            bar.update(k * 2**20, (k - start) * 2**20)
        bar.close()
        return out.getvalue()

    def test_pipe_gets_one_line_per_tenth(self):
        lines = self.run_bar(False).splitlines()
        self.assertEqual(len(lines), 11)
        self.assertIn("50%  50.0 / 100 MiB", lines[5])
        self.assertIn("2.0 MiB/s", lines[5])
        self.assertIn("还要 25 秒", lines[5])
        self.assertNotIn("\r", "".join(lines))

    def test_terminal_redraws_one_line(self):
        text = self.run_bar(True)
        self.assertEqual(text.count("\n"), 1)      # 只在结束时换行
        self.assertIn("[██████████]  100%", text)

    def test_resume_starts_from_what_is_there(self):
        first = self.run_bar(False, start=40).splitlines()[0]
        self.assertIn("40%", first)

    def test_whole_video_adds_video_and_audio(self):
        lines = ["SIZES [100, 50] 150", "GOT 0 399", "GOT 100 399", "[Merger] Merging formats", "GOT 25 251", "GOT 50 251"]
        with redirect_stdout(self.Out(False)) as out:
            fetch._whole_progress(lines)
        text = out.getvalue()
        self.assertIn(" 83%", text)                   # (100 + 25) / 150
        self.assertIn("[Merger] Merging formats", text)
        self.assertIn("100%", text)


class Layers(unittest.TestCase):
    """依赖只往下走：cli → flow → stages → project / stitch / ranges / hls / progress → core。阶段之间互不引用。"""
    ALLOWED = {"core": set(), "stitch": set(), "ranges": set(), "progress": set(), "hls": {"ranges", "progress"},
               "project": {"core"}, "doctor": {"core"},
               "stages": {"core", "project", "stitch", "ranges", "hls", "progress"}, "flow": {"core", "project", "stages"},
               "cli": {"core", "doctor", "flow", "project"}}

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
