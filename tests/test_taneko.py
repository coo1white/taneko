import io, json, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TMP = Path(tempfile.mkdtemp())
os.environ["TANEKO_ROOT"] = str(TMP)
from taneko import cli, core, state, subtitle  # noqa: E402

SRT = "1\n00:00:01,000 --> 00:00:03,000\nHello Chovy\n\n2\n00:00:04,000 --> 00:00:06,500\nBaron down\n"


def make_project(name, meta):
    d = core.PROJECTS / name
    d.mkdir(parents=True)
    core.save_meta(d, meta)
    return d


def make_video(path, secs):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%d" % secs,
                    "-c:v", "libx264", str(path)], check=True)


class Srt(unittest.TestCase):
    def test_roundtrip(self):
        cues = core.parse_srt(SRT)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[1]["end"], 6.5)
        p = TMP / "x.srt"
        core.write_srt(cues, p)
        self.assertEqual(core.parse_srt(p.read_text("utf-8")), cues)


class Flow(unittest.TestCase):
    def meta(self, **kw):
        m = {"source_url": "u", "video_glob": "*.mkv", "section": {"download": "0:00:00-0:00:10", "name": "g"},
             "subtitle": {"source_lang": "en", "asr_language": "en", "method": "asr"}, "translate": {}}
        m.update(kw)
        return m

    def test_plan_zh_source_has_no_translation(self):
        m = self.meta(subtitle={"source_lang": "zh", "asr_language": "zh", "method": "asr"})
        self.assertEqual(state.plan(m), ["fetch", "asr"])

    def test_fetch_done_requires_full_duration(self):
        d = make_project("p1", self.meta())
        self.assertFalse(state.is_done("fetch", d, core.load_meta(d)))
        make_video(d / "g.mkv", 3)  # 预期 10 秒，只有 3 秒 -> 半截
        self.assertFalse(state.is_done("fetch", d, core.load_meta(d)))
        make_video(d / "g.mkv", 10)
        self.assertTrue(state.is_done("fetch", d, core.load_meta(d)))
        (d / "_parts").mkdir()
        self.assertFalse(state.is_done("fetch", d, core.load_meta(d)))

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
                    core.write_srt([dict(c, text="中文") for c in core.parse_srt(SRT)], d / "zh.srt")
            return f

        orig = dict(cli.STAGE_FN)
        cli.STAGE_FN.update({k: fake(k) for k in ("fetch", "asr", "terms", "fix", "translate")})
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.main(["run", "p2"])
            self.assertEqual(calls, ["fetch", "asr", "terms"])  # 在术语检查点停下
            self.assertIn("approve p2 terms", buf.getvalue())
            with redirect_stdout(io.StringIO()):
                cli.main(["approve", "p2", "terms"])
                cli.main(["run", "p2"])
            self.assertEqual(calls, ["fetch", "asr", "terms", "fix", "translate"])  # check 是真实逻辑，不用假的
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.main(["run", "p2"])
            self.assertEqual(calls, ["fetch", "asr", "terms", "fix", "translate"])  # 重跑：已完成的全部跳过
            self.assertIn("approve p2 spot", buf.getvalue())
            with redirect_stdout(io.StringIO()):
                cli.main(["approve", "p2", "spot"])
                buf = io.StringIO()
            with redirect_stdout(buf):
                cli.main(["run", "p2"])
            self.assertIn("全部完成", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.main(["status", "p2"])
            self.assertNotIn("→", buf.getvalue())
        finally:
            cli.STAGE_FN.update(orig)

    def test_check_detects_timing_change(self):
        d = make_project("p3", self.meta())
        (d / "en.srt").write_text(SRT, "utf-8")
        bad = core.parse_srt(SRT)
        bad[0]["start"] += 1
        core.write_srt([dict(c, text="中") for c in bad], d / "zh.srt")
        self.assertFalse(state.is_done("check", d, core.load_meta(d)))


if __name__ == "__main__":
    unittest.main()
