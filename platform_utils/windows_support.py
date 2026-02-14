"""Windows-specific implementation using UI Automation API."""

import logging
import subprocess
import ctypes
import ctypes.wintypes

import pyautogui

from platform_utils.base import BasePlatform

logger = logging.getLogger(__name__)

# Known UI noise to filter out
_UI_NOISE = {
    "close", "minimize", "maximize", "restore", "back", "forward", "send",
    "attach", "emoji", "search", "menu", "file", "edit", "view",
    "window", "help", "new", "open", "save", "cut", "copy", "paste",
    "undo", "redo", "select all", "find", "×", "...", "⋮",
}


class WindowsPlatform(BasePlatform):

    def __init__(self):
        # Import uiautomation only on Windows
        try:
            import uiautomation as auto
            self._auto = auto
        except ImportError:
            logger.error(
                "uiautomation not installed. Run: pip install uiautomation"
            )
            self._auto = None

    def check_permissions(self) -> bool:
        # Windows UI Automation doesn't require special permissions
        if self._auto is None:
            logger.error("uiautomation package is missing")
            return False
        return True

    def get_frontmost_app_name(self) -> str:
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            # Get process name from PID
            import psutil
            proc = psutil.Process(pid.value)
            return proc.name().replace(".exe", "")
        except Exception:
            # Fallback: get window title
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                return buf.value or "Unknown"
            except Exception:
                return "Unknown"

    def get_frontmost_app_pid(self) -> int | None:
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value
        except Exception:
            return None

    def extract_text_from_window(self, pid: int) -> str:
        if not self._auto:
            return ""

        try:
            # Get the focused window's control
            focused = self._auto.GetFocusedControl()
            if not focused:
                return ""

            # Walk up to find the top-level window
            window = focused
            while window.GetParentControl() is not None:
                parent = window.GetParentControl()
                if parent.ControlType == self._auto.ControlType.PaneControl:
                    break
                window = parent

            # Try to get the top-level window directly
            try:
                fg_window = self._auto.ControlFromHandle(
                    ctypes.windll.user32.GetForegroundWindow()
                )
                if fg_window:
                    window = fg_window
            except Exception:
                pass

            # Walk the UI tree and collect text
            lines = []
            seen = set()
            self._walk_tree(window, lines, seen, depth=0, max_depth=40)

            return "\n".join(lines)

        except Exception as e:
            logger.error("UI Automation extraction error: %s", e)
            return ""

    def _walk_tree(self, control, lines: list, seen: set,
                   depth: int, max_depth: int):
        """Recursively walk the Windows UI Automation tree."""
        if depth > max_depth:
            return

        try:
            # Extract text from this control
            name = control.Name
            if isinstance(name, str) and len(name) >= 2:
                text = name.strip()
                if text and text.lower() not in _UI_NOISE and text not in seen:
                    seen.add(text)
                    lines.append(text)

            # Also try to get Value pattern (for text fields)
            try:
                value = control.GetValuePattern().Value
                if isinstance(value, str) and len(value) >= 2:
                    text = value.strip()
                    if text and text not in seen:
                        seen.add(text)
                        lines.append(text)
            except Exception:
                pass

            # Recurse into children
            children = control.GetChildren()
            if children:
                for child in children:
                    self._walk_tree(child, lines, seen, depth + 1, max_depth)

        except Exception:
            pass

    def capture_screenshot(self, output_path: str) -> str:
        # Use mss for fast, cross-platform screenshot
        try:
            import mss
            with mss.mss() as sct:
                # Capture the primary monitor
                sct.shot(output=output_path)
            return output_path
        except ImportError:
            # Fallback to pyautogui
            screenshot = pyautogui.screenshot()
            screenshot.save(output_path)
            return output_path

    def activate_app(self, app_name: str):
        """Bring a window to foreground on Windows."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            # SetForegroundWindow needs the hwnd — we stored it during extraction
            # For now, use Alt+Tab trick to ensure we can set foreground
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception as e:
            logger.warning("Could not activate window: %s", e)

    def scroll_up(self, amount: int = 5):
        pyautogui.scroll(amount)
