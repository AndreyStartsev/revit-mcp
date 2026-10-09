# -*- coding: utf-8 -*-
"""
Central path resolution and cache directory management for Revit MCP.
Single source of truth across server, client, and tools.
"""

import os
import sys

DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".revit_mcp")
CACHE_DIR = os.environ.get("REVIT_MCP_CACHE_DIR", DEFAULT_CACHE_DIR)

INSTANCES_DIR = os.path.join(CACHE_DIR, "instances")
SCREENSHOTS_DIR = os.path.join(CACHE_DIR, "screenshots")
SESSION_BINDING_FILE = os.path.join(CACHE_DIR, "session_binding.json")
SERVER_LOG_FILE = os.path.join(CACHE_DIR, "server.log")

LATEST_SCREENSHOT_PNG = os.path.join(CACHE_DIR, "latest_screenshot.png")
LATEST_SCREENSHOT_JSON = os.path.join(CACHE_DIR, "latest_screenshot.json")
LATEST_AGENT_SCREENSHOT_PNG = os.path.join(CACHE_DIR, "latest_agent_screenshot.png")
LATEST_AGENT_SCREENSHOT_JSON = os.path.join(CACHE_DIR, "latest_agent_screenshot.json")
LATEST_USER_SNIP_PNG = os.path.join(CACHE_DIR, "latest_user_snip.png")
LATEST_USER_SNIP_JSON = os.path.join(CACHE_DIR, "latest_user_snip.json")
LATEST_SELECTION_JSON = os.path.join(CACHE_DIR, "latest_selection.json")


def ensure_directories():
    """Ensures that CACHE_DIR, INSTANCES_DIR, and SCREENSHOTS_DIR exist."""
    for d in [CACHE_DIR, INSTANCES_DIR, SCREENSHOTS_DIR]:
        if not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass


def is_pid_alive(pid: int) -> bool:
    """Checks whether a process with the given PID is currently running."""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False
            STILL_ACTIVE = 259
            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return False
    else:
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ProcessLookupError, ValueError):
            return False
