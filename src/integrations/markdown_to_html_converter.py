"""Compatibility alias for shared Markdown to WeChat conversion."""
import sys
from publisher_shared.wechat import converter as _implementation

if __name__ == "__main__":
    _implementation._cli_main()
else:
    sys.modules[__name__] = _implementation
