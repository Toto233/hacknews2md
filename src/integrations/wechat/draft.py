"""Compatibility alias for the shared WeChat draft implementation."""
import sys
from publisher_shared.wechat import draft as _implementation
sys.modules[__name__] = _implementation
