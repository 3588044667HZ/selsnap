from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BROWSER = PROJECT_ROOT / "browsers" / "chrome-win64" / "chrome.exe"

VALID_MODES = ("standard", "uc", "cdp")


def default_browser_path() -> str:
    env_path = os.environ.get("SELSNAP_BROWSER")
    if env_path:
        return str(Path(env_path).expanduser())
    if DEFAULT_BROWSER.exists():
        return str(DEFAULT_BROWSER)
    return ""


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/mcp"
    browser_path: str = ""
    headless: bool = True
    pool_size: int = 4
    command_timeout: float = 90.0
    page_load_timeout: float = 30.0
    snapshot_max_nodes: int = 800
    snapshot_max_chars: int = 16000
    token: str | None = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def load_settings(argv: list[str] | None = None) -> Settings:
    parser = argparse.ArgumentParser(prog="selsnap")
    parser.add_argument("--host", default=os.environ.get("SELSNAP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_env_int("SELSNAP_PORT", 8765))
    parser.add_argument("--path", default=os.environ.get("SELSNAP_PATH", "/mcp"))
    parser.add_argument("--browser", default=default_browser_path())
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("SELSNAP_HEADLESS", True),
    )
    parser.add_argument("--pool-size", type=int, default=_env_int("SELSNAP_POOL_SIZE", 4))
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=_env_float("SELSNAP_COMMAND_TIMEOUT", 90.0),
    )
    parser.add_argument(
        "--page-load-timeout",
        type=float,
        default=_env_float("SELSNAP_PAGE_LOAD_TIMEOUT", 30.0),
    )
    parser.add_argument(
        "--snapshot-max-nodes",
        type=int,
        default=_env_int("SELSNAP_SNAPSHOT_MAX_NODES", 800),
    )
    parser.add_argument(
        "--snapshot-max-chars",
        type=int,
        default=_env_int("SELSNAP_SNAPSHOT_MAX_CHARS", 16000),
    )
    parser.add_argument("--token", default=os.environ.get("SELSNAP_TOKEN"))
    args = parser.parse_args(argv)
    return Settings(
        host=args.host,
        port=args.port,
        path=args.path,
        browser_path=args.browser,
        headless=args.headless,
        pool_size=args.pool_size,
        command_timeout=args.command_timeout,
        page_load_timeout=args.page_load_timeout,
        snapshot_max_nodes=args.snapshot_max_nodes,
        snapshot_max_chars=args.snapshot_max_chars,
        token=args.token,
    )
