"""代码量上限（ROADMAP 决策记录 2026-11-16）：总行数目标 1,500（封顶 2,000），单个文件 400 行，单个函数 80 行。
代码里只 import 标准库。"""
import ast
import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOFT, HARD, FILE_MAX, FUNC_MAX = 1500, 2000, 400, 80


def program_files(root=ROOT):
    return [root / "taneko.py"] + sorted((root / "taneko").rglob("*.py"))


def measure(files, base=ROOT):
    """返回 (总行数, 超长文件, 超长函数, 第三方 import)；行数按 wc -l，含空行。"""
    total, long_files, long_funcs, third = 0, [], [], []
    stdlib = getattr(sys, "stdlib_module_names", None)
    for f in files:
        text = f.read_text("utf-8")
        n = text.count("\n")
        total += n
        rel = f.relative_to(base).as_posix()
        if n > FILE_MAX:
            long_files.append("%s：%d 行（上限 %d）" % (rel, n, FILE_MAX))
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = node.end_lineno - node.lineno + 1
                if size > FUNC_MAX:
                    long_funcs.append("%s %s()：%d 行（上限 %d）" % (rel, node.name, size, FUNC_MAX))
            if stdlib is None:
                continue
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            for m in names:
                top = m.split(".")[0]
                if top and top != "taneko" and top not in stdlib:
                    third.append("%s：import %s" % (rel, m))
    return total, long_files, long_funcs, third


class Size(unittest.TestCase):
    def test_limits(self):
        total, long_files, long_funcs, third = measure(program_files())
        if total > SOFT:
            warnings.warn("程序代码 %d 行，超过 %d 行：请在 ROADMAP 决策记录里写明原因" % (total, SOFT))
        self.assertLessEqual(total, HARD, "程序代码 %d 行，超过封顶 %d 行" % (total, HARD))
        self.assertEqual(long_files, [], "文件太长")
        self.assertEqual(long_funcs, [], "函数太长，请拆成小步骤")
        self.assertEqual(third, [], "只能用标准库")

    def test_the_check_bites(self):
        """临时造一个 2,600 行的文件，确认检查真的会报出来，并给出行数和上限。"""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            (base / "taneko").mkdir()
            (base / "taneko.py").write_text("import requests\n", "utf-8")
            body = "def f():\n" + "    x = 1\n" * 100 + "\n" * 2499
            (base / "taneko" / "big.py").write_text(body, "utf-8")
            total, long_files, long_funcs, third = measure(program_files(base), base)
        self.assertGreater(total, HARD)
        self.assertIn("taneko/big.py：2600 行（上限 400）", long_files)
        self.assertIn("taneko/big.py f()：101 行（上限 80）", long_funcs)
        if sys.version_info >= (3, 10):
            self.assertIn("taneko.py：import requests", third)


if __name__ == "__main__":
    unittest.main()
