"""Conftest for handler tests.

Mocks selenium and other heavy dependencies that are imported at module level
by handler modules but are not needed for testing pure functions.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

# Mock selenium (not installed in CI / test env)
for mod_name in [
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.common",
    "selenium.webdriver.common.by",
    "selenium.webdriver.support",
    "selenium.webdriver.support.expected_conditions",
    "selenium.webdriver.support.ui",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
