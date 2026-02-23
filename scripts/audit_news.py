#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""审计脚本入口 - 调用 src/core/audit_news.py"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.core.audit_news import main
main()
