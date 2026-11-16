# -*- coding: utf-8 -*-
"""一行进度：百分比、已下 / 总共、速度、还要多久。在终端里原地刷新；输出不是终端时（存进文件、给脚本读）
每 10% 打一行，不刷屏。只用标准库。"""
import sys
import time


def _mib(n: float) -> str:
    return "{:,.0f}".format(n / 2**20) if n >= 100 * 2**20 else "%.1f" % (n / 2**20)


def _w(s: str) -> int:
    """终端里占几格：中文字占两格。"""
    return sum(2 if "\u2e80" <= c <= "\uffef" else 1 for c in s)


def _left(s: float) -> str:
    s = int(s)
    return "%d 小时 %d 分" % (s // 3600, s % 3600 // 60) if s >= 3600 else "%d 分 %d 秒" % (s // 60, s % 60) if s >= 60 else "%d 秒" % s


class Bar:
    """total：总量；unit：None 表示字节（显示 MiB），否则是数量的单位（例如“片”）。
    update(done, got)：done 是已完成的量（含上次下好的），got 是这次运行收到的字节数（算速度用）。"""

    def __init__(self, total, unit=None, out=None, clock=time.monotonic):
        self.total, self.unit, self.out, self.clock = max(total, 1), unit, out or sys.stdout, clock
        self.tty = bool(getattr(self.out, "isatty", lambda: False)())
        self.t0 = self.shown = None
        self.win, self.speed, self.tenth, self.width, self.text = None, 0.0, -1, 0, ""

    def update(self, done, got=0) -> None:
        now = self.clock()
        if self.t0 is None:
            self.t0, self.done0, self.win = now, done, (now, got)
        if now - self.win[0] >= 2:      # 速度按最近几秒算，网速变了能很快反映出来
            self.speed, self.win = (got - self.win[1]) / (now - self.win[0]), (now, got)
        elif not self.speed and now > self.t0:
            self.speed = got / (now - self.t0)
        pct = min(done * 100 // self.total, 100)
        if self.tty and self.shown is not None and now - self.shown < 0.5 and done < self.total:
            return
        if not self.tty and pct // 10 == self.tenth:
            return
        self.shown, self.tenth = now, pct // 10
        rate = (done - self.done0) / (now - self.t0) if now > self.t0 else 0
        amount = ("%s / %s MiB" % (_mib(done), _mib(self.total)) if self.unit is None
                  else "%d / %d %s" % (done, self.total, self.unit))
        text = "下载中  [%s]  %3d%%  %s" % ("█" * (pct // 10) + "░" * (10 - pct // 10), pct, amount)
        if self.speed:
            text += "  %s MiB/s" % ("%.1f" % (self.speed / 2**20))
        if rate > 0 and done < self.total:
            text += "  还要 " + _left((self.total - done) / rate)
        self.text = text
        if self.tty:
            self.out.write("\r" + text + " " * max(0, self.width - _w(text)))
            self.width = _w(text)
        else:
            self.out.write(text + "\n")
        self.out.flush()

    def note(self, msg: str) -> None:
        """在进度行上面插一行说明，进度行留在最下面。"""
        if self.tty and self.width:
            msg = "\r" + msg + " " * max(0, self.width - _w(msg))
        self.out.write(msg + "\n" + ("\r" + self.text if self.tty and self.width else ""))
        self.out.flush()

    def close(self) -> None:
        if self.tty and self.width:
            self.out.write("\n")
            self.out.flush()
