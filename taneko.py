#!/usr/bin/env python3
"""入口：python taneko.py run <项目>（在 framework 目录下，或写完整路径）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taneko.cli import main  # noqa: E402

sys.exit(main())
