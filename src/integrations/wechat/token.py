"""Compatibility alias for the shared WeChat token implementation."""
import sys
from publisher_shared.wechat import token as _implementation
sys.modules[__name__] = _implementation
