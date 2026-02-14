"""macOS-specific implementation using Accessibility API (AXUIElement)."""

import logging
import subprocess

import pyautogui
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXIsProcessTrusted,
)

from platform_utils.base import BasePlatform

logger = logging.getLogger(__name__)

_MAX_DEPTH = 40

# Known UI noise to filter out
_UI_NOISE = {
    "close", "minimize", "zoom", "back", "forward", "send",
    "attach", "emoji", "search", "menu", "file", "edit", "view",
    "window", "help", "new", "open", "save", "cut", "copy", "paste",
    "undo", "redo", "select all", "find", "×", "...", "⋮",
}


def _get_attr(element, attr):
    """Safely get an AX attribute value."""
    try:
        err, value = AXUIElementCopyAttributeValue(element, attr, None)
        if err == 0:
            return value
    except Exception:
        pass
    return None


def _walk_tree(element, lines: list, seen: set, depth: int = 0):
    """Recursively walk the accessibility tree and collect text."""
    if depth > _MAX_DEPTH:
        return

    value = _get_attr(element, "AXValue")
    title = _get_attr(element, "AXTitle")
    desc = _get_attr(element, "AXDescription")

    for text in (value, title, desc):
        if isinstance(text, str) and len(text) >= 2:
            text = text.strip()
            if text and text.lower() not in _UI_NOISE and text not in seen:
                seen.add(text)
                lines.append(text)

    children = _get_attr(element, "AXChildren")
    if children:
        for child in children:
            _walk_tree(child, lines, seen, depth + 1)


class MacOSPlatform(BasePlatform):

    def check_permissions(self) -> bool:
        trusted = AXIsProcessTrusted()
        if not trusted:
            logger.warning(
                "Accessibility permission NOT granted. "
                "System Preferences → Privacy & Security → Accessibility"
            )
        return trusted

    def get_frontmost_app_name(self) -> str:
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of '
                 'first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else "Unknown"
        except Exception:
            return "Unknown"

    def get_frontmost_app_pid(self) -> int | None:
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to unix id of '
                 'first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=5,
            )
            return int(r.stdout.strip()) if r.returncode == 0 else None
        except Exception:
            return None

    def extract_text_from_window(self, pid: int) -> str:
        app_ref = AXUIElementCreateApplication(pid)
        if not app_ref:
            return ""

        window = _get_attr(app_ref, "AXFocusedWindow")
        if not window:
            windows = _get_attr(app_ref, "AXWindows")
            if windows and len(windows) > 0:
                window = windows[0]
            else:
                return ""

        lines = []
        seen = set()
        _walk_tree(window, lines, seen)
        return "\n".join(lines)

    def capture_screenshot(self, output_path: str) -> str:
        # Try capturing just the active window
        window_id = None
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get id of first window '
                 'of (first application process whose frontmost is true)'],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                window_id = r.stdout.strip()
        except Exception:
            pass

        if window_id:
            cmd = ["screencapture", "-x", "-o", "-l", window_id, output_path]
        else:
            cmd = ["screencapture", "-x", output_path]

        subprocess.run(cmd, timeout=10, check=True)
        return output_path

    def activate_app(self, app_name: str):
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to activate'],
                timeout=5,
            )
        except Exception as e:
            logger.warning("Could not activate %s: %s", app_name, e)

    def scroll_up(self, amount: int = 5):
        pyautogui.scroll(amount)
