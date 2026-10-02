#!/usr/bin/env python3
"""Compatibility CLI for the shared WeChat publication implementation."""
import sys
from pathlib import Path

# Preserve direct script execution from an uninstalled checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher_shared.wechat import publication as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
