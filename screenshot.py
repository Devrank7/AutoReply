import logging
import subprocess
import tempfile
from pathlib import Path

from config import SCREENSHOT_PATH, SCREENSHOT_METHOD

logger = logging.getLogger(__name__)


def get_active_window_id() -> str | None:
    """Get the window ID of the frontmost window using osascript."""
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events" to get id of first window '
                'of (first application process whose frontmost is true)'
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.warning("Could not get active window ID: %s", e)
    return None


def get_active_app_name() -> str:
    """Get the name of the frontmost application."""
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events" to get name of '
                'first application process whose frontmost is true'
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning("Could not get active app name: %s", e)
    return "Unknown"


def capture_screenshot() -> str:
    """Capture a screenshot and return the file path.

    Uses SCREENSHOT_METHOD from config:
    - "window" — captures only the active window
    - "fullscreen" — captures the entire screen
    """
    output_path = SCREENSHOT_PATH

    if SCREENSHOT_METHOD == "window":
        window_id = get_active_window_id()
        if window_id:
            cmd = ["screencapture", "-x", "-o", "-l", window_id, output_path]
        else:
            logger.info("Falling back to fullscreen capture")
            cmd = ["screencapture", "-x", output_path]
    else:
        cmd = ["screencapture", "-x", output_path]

    try:
        subprocess.run(cmd, timeout=10, check=True)
        if Path(output_path).exists():
            logger.info("Screenshot saved: %s", output_path)
            return output_path
        else:
            raise FileNotFoundError("Screenshot file was not created")
    except subprocess.CalledProcessError as e:
        logger.error("screencapture failed: %s", e)
        raise
    except subprocess.TimeoutExpired:
        logger.error("screencapture timed out")
        raise


def activate_app(app_name: str):
    """Bring the specified application to the foreground."""
    try:
        subprocess.run(
            [
                "osascript", "-e",
                f'tell application "{app_name}" to activate'
            ],
            timeout=5,
        )
        logger.info("Activated app: %s", app_name)
    except Exception as e:
        logger.warning("Could not activate app %s: %s", app_name, e)
