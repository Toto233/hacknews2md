#!/usr/bin/env python3
"""Desktop launcher for the maintained one-click WeChat publisher."""

from __future__ import annotations

from pathlib import Path
import runpy
import sys


PUBLISHER = Path(r"D:\python\hacknews2md_re\scripts\publish_today_wechat.py")

if not PUBLISHER.is_file():
    print(f"找不到一键发布脚本：{PUBLISHER}", file=sys.stderr)
    if sys.stdin.isatty():
        input("按回车键关闭窗口……")
    raise SystemExit(2)

runpy.run_path(str(PUBLISHER), run_name="__main__")
