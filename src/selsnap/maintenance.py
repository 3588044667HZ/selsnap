from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

BROWSER_NAMES = {"chrome.exe", "chromedriver.exe", "chromedriver", "chrome"}


def _normalize(path: str) -> str:
    return str(Path(path).resolve()).lower().replace("\\", "/")


def _is_orphan(proc) -> bool:
    try:
        parent = proc.parent()
        if parent is None:
            return True
        return not parent.is_running()
    except Exception:
        return True


def cleanup_orphans(profile_root: str) -> int:
    """终止引用本项目 profile 的残留 Chrome，以及遗留的本机 chromedriver。"""
    root = _normalize(profile_root)
    venv_root = _normalize(sys.prefix)
    if not root:
        return 0
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil 由依赖声明保证
        log.warning("psutil 不可用，跳过孤儿浏览器清理")
        return 0

    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in BROWSER_NAMES:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if not cmdline:
                continue
            normalized = _normalize_cmdline(cmdline)
            should_kill = root in normalized
            if not should_kill and "chromedriver" in name:
                # 本项目 venv 里的 chromedriver，且父进程已消失 → 上次服务崩溃遗留
                should_kill = (
                    venv_root in normalized
                    and "seleniumbase" in normalized
                    and _is_orphan(proc)
                )
            if not should_kill:
                continue
            proc.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    if killed:
        log.info("已清理 %s 个孤儿浏览器/驱动进程", killed)
    return killed


def _normalize_cmdline(cmdline: str) -> str:
    return cmdline.lower().replace("\\", "/")
