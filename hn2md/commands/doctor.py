"""hn2md doctor: environment readiness checks."""

import os
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

from src.db.connection import get_db


class CheckResult(NamedTuple):
    name: str
    ok: bool
    detail: str


def _is_ci_environment() -> bool:
    return os.getenv("HN2MD_DOCTOR_CI", "").lower() == "true"


def _ci_skip(name: str, detail: str) -> CheckResult:
    return CheckResult(name, True, f"skipped in CI: {detail}")


def run_doctor(ctx) -> list[CheckResult]:
    checks = []
    db_path = Path(ctx.db_path)
    config_path = Path(ctx.config_path)
    output_dir = Path(ctx.output_dir)
    ci_mode = _is_ci_environment()

    # 1. Python version
    v = sys.version_info
    ok = v >= (3, 11)
    checks.append(CheckResult("Python >= 3.11", ok, f"{v.major}.{v.minor}.{v.micro}"))

    # 2. SQLite database accessible
    if ci_mode:
        checks.append(_ci_skip("SQLite database", "runtime database is not committed"))
    else:
        try:
            with get_db(str(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM news")
                count = cur.fetchone()[0]
            checks.append(CheckResult("SQLite database", True, f"{db_path} ({count} rows)"))
        except Exception as e:
            checks.append(CheckResult("SQLite database", False, str(e)))

    # 3. SQLite integrity
    try:
        from src.db.connection import check_integrity

        ok, msg = check_integrity()
        checks.append(CheckResult("SQLite integrity", ok, msg))
    except Exception as e:
        checks.append(CheckResult("SQLite integrity", False, str(e)))

    # 4. Config file exists
    if config_path.exists():
        checks.append(CheckResult("config/config.json", True, str(config_path)))
    elif ci_mode:
        checks.append(_ci_skip("config/config.json", "runtime config is supplied outside git"))
    else:
        checks.append(CheckResult("config/config.json", False, "missing"))

    # 5. WeChat credentials
    if ci_mode and not config_path.exists():
        checks.append(_ci_skip("WeChat credentials", "publish secrets are not required for CI tests"))
    else:
        try:
            from src.utils.config import Config

            c = Config(str(config_path))
            wc = c.get_wechat_config()
            checks.append(CheckResult("WeChat credentials", True, f"appid={wc['appid'][:4]}..."))
        except Exception as e:
            checks.append(CheckResult("WeChat credentials", False, str(e)))

    # 6. LLM API keys
    if ci_mode and not config_path.exists():
        checks.append(_ci_skip("LLM API keys", "LLM secrets are not required for CI tests"))
    else:
        try:
            from src.llm.llm_utils import load_llm_config

            cfg = load_llm_config()
            providers = []
            for name in ("grok", "gemini", "moonshot"):
                if cfg.get(name, {}).get("api_key"):
                    providers.append(name)
            ok = len(providers) > 0
            checks.append(
                CheckResult(
                    "LLM API keys",
                    ok,
                    ", ".join(providers) if providers else "none configured",
                )
            )
        except Exception as e:
            checks.append(CheckResult("LLM API keys", False, str(e)))

    # 7. Network (HN reachable)
    try:
        import requests

        r = requests.get("https://news.ycombinator.com", timeout=10)
        checks.append(CheckResult("Network (HN)", r.status_code == 200, f"HTTP {r.status_code}"))
    except Exception as e:
        checks.append(CheckResult("Network (HN)", False, str(e)))

    # 8. Disk space
    try:
        data_dir = os.path.dirname(str(db_path))
        if ci_mode and not os.path.exists(data_dir):
            usage = shutil.disk_usage(Path.cwd())
            free_gb = usage.free / (1024**3)
            ok = free_gb >= 1.0
            checks.append(CheckResult("Disk space", ok, f"{free_gb:.1f} GB free"))
        elif os.path.exists(data_dir):
            usage = shutil.disk_usage(data_dir)
            free_gb = usage.free / (1024**3)
            ok = free_gb >= 1.0
            checks.append(CheckResult("Disk space", ok, f"{free_gb:.1f} GB free"))
        else:
            checks.append(CheckResult("Disk space", False, "data directory missing"))
    except Exception as e:
        checks.append(CheckResult("Disk space", False, str(e)))

    # 9. Output directory writable
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        test_file = output_dir / ".write_test"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        checks.append(CheckResult("Output directory", True, str(output_dir)))
    except Exception as e:
        checks.append(CheckResult("Output directory", False, str(e)))

    return checks


def run_doctor_json(ctx) -> dict:
    """Run doctor checks and return JSON-serializable dict."""
    checks = run_doctor(ctx)
    return {
        "all_ok": all(c.ok for c in checks),
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
    }
