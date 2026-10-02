"""Compatibility alias for the shared WeChat media implementation."""
import sys
from publisher_shared.wechat import media as _implementation
sys.modules[__name__] = _implementation
