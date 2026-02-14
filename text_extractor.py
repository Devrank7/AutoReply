"""
Text extraction from any macOS application using the Accessibility API.

Uses AXUIElement to walk the accessibility tree of the frontmost window
and extract all text content — works with Telegram, Instagram, Gmail,
WhatsApp, any browser, any chat app.

Requires: macOS Accessibility permission
(System Preferences → Privacy & Security → Accessibility)
"""

import logging
import subprocess
import time

import pyautogui
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXIsProcessTrusted,
)

logger = logging.getLogger(__name__)

# AX attribute constants
_AX_ROLE = "AXRole"
_AX_VALUE = "AXValue"
_AX_TITLE = "AXTitle"
_AX_DESCRIPTION = "AXDescription"
_AX_CHILDREN = "AXChildren"
_AX_WINDOWS = "AXWindows"
_AX_FOCUSED_WINDOW = "AXFocusedWindow"
_AX_ROLE_DESCRIPTION = "AXRoleDescription"

# Roles that typically contain chat message text
_TEXT_ROLES = {
    "AXStaticText",
    "AXTextArea",
    "AXTextField",
    "AXCell",
    "AXGroup",
    "AXWebArea",
}

# Maximum tree traversal depth
_MAX_DEPTH = 40


def check_accessibility_permission() -> bool:
    """Check if the app has Accessibility permission."""
    trusted = AXIsProcessTrusted()
    if not trusted:
        logger.warning(
            "Accessibility permission NOT granted. "
            "Go to System Preferences → Privacy & Security → Accessibility "
            "and add this application."
        )
    return trusted


def get_frontmost_pid() -> int | None:
    """Get the PID of the frontmost application."""
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events" to unix id of '
                'first application process whose frontmost is true'
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except Exception as e:
        logger.error("Failed to get frontmost PID: %s", e)
    return None


def _get_attr(element, attr):
    """Safely get an AX attribute value."""
    try:
        err, value = AXUIElementCopyAttributeValue(element, attr, None)
        if err == 0:
            return value
    except Exception:
        pass
    return None


def _walk_tree(element, results: list, depth: int = 0):
    """Recursively walk the accessibility tree and collect text nodes."""
    if depth > _MAX_DEPTH:
        return

    role = _get_attr(element, _AX_ROLE) or ""

    # Extract text from this element
    value = _get_attr(element, _AX_VALUE)
    title = _get_attr(element, _AX_TITLE)
    desc = _get_attr(element, _AX_DESCRIPTION)

    text_parts = []
    if isinstance(value, str) and value.strip():
        text_parts.append(value.strip())
    if isinstance(title, str) and title.strip() and title != value:
        text_parts.append(title.strip())
    if isinstance(desc, str) and desc.strip() and desc not in (value, title):
        text_parts.append(desc.strip())

    if text_parts:
        results.append({
            "role": str(role),
            "text": " | ".join(text_parts),
            "depth": depth,
        })

    # Recurse into children
    children = _get_attr(element, _AX_CHILDREN)
    if children:
        for child in children:
            _walk_tree(child, results, depth + 1)


def extract_text_from_app(pid: int) -> list[dict]:
    """Extract all text nodes from the frontmost window of the given app.

    Returns a list of dicts: [{"role": "AXStaticText", "text": "...", "depth": N}, ...]
    """
    app_ref = AXUIElementCreateApplication(pid)
    if not app_ref:
        logger.error("Failed to create AXUIElement for PID %d", pid)
        return []

    # Try focused window first, then fall back to first window
    window = _get_attr(app_ref, _AX_FOCUSED_WINDOW)
    if not window:
        windows = _get_attr(app_ref, _AX_WINDOWS)
        if windows and len(windows) > 0:
            window = windows[0]
        else:
            logger.warning("No windows found for PID %d", pid)
            return []

    results = []
    _walk_tree(window, results)
    return results


def format_extracted_text(nodes: list[dict]) -> str:
    """Convert raw extracted nodes into a readable conversation transcript.

    Filters noise (buttons, menus) and keeps meaningful text.
    """
    # Filter: keep only nodes with substantial text (>1 char)
    # and skip obvious UI noise
    ui_noise = {
        "close", "minimize", "zoom", "back", "forward", "send",
        "attach", "emoji", "search", "menu", "file", "edit", "view",
        "window", "help", "new", "open", "save", "cut", "copy", "paste",
        "undo", "redo", "select all", "find", "×", "...", "⋮",
    }

    lines = []
    seen = set()

    for node in nodes:
        text = node["text"]

        # Skip very short text (likely button labels)
        if len(text) < 2:
            continue

        # Skip known UI elements
        if text.lower() in ui_noise:
            continue

        # Skip duplicates
        if text in seen:
            continue
        seen.add(text)

        lines.append(text)

    return "\n".join(lines)


def scroll_and_extract(pid: int, scroll_count: int = 5,
                       scroll_amount: int = 5,
                       delay: float = 0.4) -> str:
    """Scroll up in the active window to load more messages, extracting text at each position.

    This captures messages beyond what's currently visible on screen.
    """
    all_text_parts = []
    seen_lines = set()

    for i in range(scroll_count):
        # Extract text at current scroll position
        nodes = extract_text_from_app(pid)
        text = format_extracted_text(nodes)

        # Add new lines we haven't seen yet
        for line in text.split("\n"):
            if line and line not in seen_lines:
                seen_lines.add(line)
                all_text_parts.append(line)

        if i < scroll_count - 1:
            # Scroll up to load older messages
            pyautogui.scroll(scroll_amount)
            time.sleep(delay)

    # Scroll back down to the bottom so the user's view is restored
    for _ in range(scroll_count - 1):
        pyautogui.scroll(-scroll_amount)
        time.sleep(0.1)

    return "\n".join(all_text_parts)


def extract_conversation(deep: bool = False) -> tuple[str, str]:
    """Main entry point: extract conversation text from the frontmost app.

    Args:
        deep: If True, scroll up to capture more message history.

    Returns:
        (extracted_text, app_name)
    """
    pid = get_frontmost_pid()
    if not pid:
        return "", "Unknown"

    # Get app name
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events" to get name of '
                'first application process whose frontmost is true'
            ],
            capture_output=True, text=True, timeout=5,
        )
        app_name = result.stdout.strip() if result.returncode == 0 else "Unknown"
    except Exception:
        app_name = "Unknown"

    if not check_accessibility_permission():
        return "", app_name

    if deep:
        # Scroll up and extract from multiple positions
        text = scroll_and_extract(pid, scroll_count=5, scroll_amount=5)
    else:
        # Quick extraction from current view only
        nodes = extract_text_from_app(pid)
        text = format_extracted_text(nodes)

    logger.info(
        "Extracted %d chars from %s (deep=%s)",
        len(text), app_name, deep,
    )
    return text, app_name
