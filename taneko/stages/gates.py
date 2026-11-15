# -*- coding: utf-8 -*-
"""两个人工检查点：术语校对、抽查。没有 run，只能由人 approve。"""
from __future__ import annotations

from pathlib import Path

from ..core import Stage


def _approved(what: str):
    return lambda d, meta: bool((meta.get("review", {}) or {}).get(what))


def _terms_hint(d: Path, project: str) -> list:
    return ["1) 打开 %s 看听错的名字" % (d / "terms.txt"),
            "2) 把 {\"错词\": \"正确词\"} 填进 %s 的 translate.corrections" % (d / "meta.json"),
            "3) 完成后运行：taneko approve %s terms，再重新 taneko run %s" % (project, project)]


def _spot_hint(d: Path, project: str) -> list:
    return ["对着视频抽查 %s 里的击杀、大龙等关键片段" % (d / "zh.srt"),
            "3) 完成后运行：taneko approve %s spot，再重新 taneko run %s" % (project, project)]


TERMS = Stage("gate:terms", "【人工】校对术语，填 translate.corrections", _approved("terms"), hint=_terms_hint)
SPOT = Stage("gate:spot", "【人工】抽查关键片段", _approved("spot"), hint=_spot_hint)
