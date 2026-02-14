"""
Cross-platform abstraction layer.

Auto-detects the OS and provides the correct implementation
for text extraction, screenshots, window management, and hotkeys.
"""

import platform
import sys

_SYSTEM = platform.system()  # "Darwin" (macOS) or "Windows"

IS_MACOS = _SYSTEM == "Darwin"
IS_WINDOWS = _SYSTEM == "Windows"


def get_platform():
    """Get the platform-specific implementation module."""
    if IS_MACOS:
        from platform_utils.macos_support import MacOSPlatform
        return MacOSPlatform()
    elif IS_WINDOWS:
        from platform_utils.windows_support import WindowsPlatform
        return WindowsPlatform()
    else:
        raise RuntimeError(f"Unsupported platform: {_SYSTEM}. Only macOS and Windows are supported.")


# Hotkey modifier key differs per platform
MODIFIER_KEY = "cmd" if IS_MACOS else "ctrl"
PASTE_HOTKEY = ("command", "v") if IS_MACOS else ("ctrl", "v")
