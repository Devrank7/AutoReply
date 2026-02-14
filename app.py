"""
AutoReply AI — Universal Sales Assistant (macOS + Windows)

Usage: python app.py

Hotkeys:
  Ctrl+Alt+R (Win) / Cmd+Option+R (Mac) — Quick: extract text + generate reply
  Ctrl+Alt+E (Win) / Cmd+Option+E (Mac) — Deep: scroll for history + generate reply

How it works:
  1. Reads ALL text from the active chat window via OS Accessibility API
     (macOS: AXUIElement, Windows: UI Automation)
  2. Sends the full conversation + system prompt to Gemini AI
  3. Shows the suggested reply in a floating overlay
  4. Manager clicks Paste → reply auto-pastes into the chat input

Requires:
  macOS: Accessibility permission (System Preferences → Privacy & Security)
  Windows: uiautomation package (pip install uiautomation)
"""

import logging
import sys
import threading
import time

import pyautogui
import pystray
from PIL import Image, ImageDraw

from platform_utils import get_platform, MODIFIER_KEY, PASTE_HOTKEY, IS_MACOS
from services.ai_agent import AIAgent
from overlay import OverlayWindow
from config import SCREENSHOT_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1

_MIN_TEXT_LENGTH = 30

# Hotkey strings differ per platform
# Using Alt/Option instead of Shift to avoid browser conflicts (Cmd+Shift+R = hard reload)
_MOD = "<cmd>" if IS_MACOS else "<ctrl>"
_ALT = "<alt>"
_QUICK_HOTKEY = f"{_MOD}+{_ALT}+r"
_DEEP_HOTKEY = f"{_MOD}+{_ALT}+e"
_HOTKEY_LABEL_QUICK = "Cmd+Option+R" if IS_MACOS else "Ctrl+Alt+R"
_HOTKEY_LABEL_DEEP = "Cmd+Option+E" if IS_MACOS else "Ctrl+Alt+E"


def _create_tray_icon_image() -> Image.Image:
    """Create a simple tray icon (blue circle with 'AR' text)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill="#e94560")
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    except Exception:
        font = ImageDraw.Draw(img).getfont()
    draw.text((14, 16), "AR", fill="white", font=font)
    return img


class Hotkey:
    """Global hotkey listener using pynput (cross-platform)."""

    def __init__(self, on_quick, on_deep):
        self.on_quick = on_quick
        self.on_deep = on_deep
        self._listener = None

    def start(self):
        from pynput import keyboard

        hotkey_quick = keyboard.HotKey(
            keyboard.HotKey.parse(_QUICK_HOTKEY),
            lambda: self.on_quick(),
        )
        hotkey_deep = keyboard.HotKey(
            keyboard.HotKey.parse(_DEEP_HOTKEY),
            lambda: self.on_deep(),
        )

        def on_press(key):
            canonical = self._listener.canonical(key)
            hotkey_quick.press(canonical)
            hotkey_deep.press(canonical)

        def on_release(key):
            canonical = self._listener.canonical(key)
            hotkey_quick.release(canonical)
            hotkey_deep.release(canonical)

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()
        logger.info(
            "Hotkeys active: %s (quick) | %s (deep scan)",
            _HOTKEY_LABEL_QUICK, _HOTKEY_LABEL_DEEP,
        )

    def stop(self):
        if self._listener:
            self._listener.stop()


class AutoReplyApp:
    """Cross-platform system tray application."""

    def __init__(self):
        self.platform = get_platform()
        self.ai_agent = AIAgent()
        self.overlay = None
        self._source_app = None
        self._last_text = None
        self._last_app_name = None
        self._last_screenshot = None
        self._last_suggestion = None
        self._busy = False

        # Global hotkeys
        self.hotkey = Hotkey(
            on_quick=lambda: self._on_hotkey(deep=False),
            on_deep=lambda: self._on_hotkey(deep=True),
        )
        self.hotkey.start()

        # Check OS permissions
        self.platform.check_permissions()

        # System tray icon
        self.tray = pystray.Icon(
            "AutoReply AI",
            icon=_create_tray_icon_image(),
            title="AutoReply AI",
            menu=pystray.Menu(
                pystray.MenuItem(
                    f"Quick Reply ({_HOTKEY_LABEL_QUICK})",
                    lambda: self._on_hotkey(deep=False),
                ),
                pystray.MenuItem(
                    f"Deep Scan ({_HOTKEY_LABEL_DEEP})",
                    lambda: self._on_hotkey(deep=True),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("About", self._menu_about),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._menu_quit),
            ),
        )

        logger.info("=" * 50)
        logger.info("AutoReply AI is running!")
        logger.info("%s — quick reply (current view)", _HOTKEY_LABEL_QUICK)
        logger.info("%s — deep scan (scroll for history)", _HOTKEY_LABEL_DEEP)
        logger.info("=" * 50)

    def run(self):
        """Start the system tray icon (blocks the main thread)."""
        self.tray.run()

    def _on_hotkey(self, deep: bool = False):
        if self._busy:
            logger.info("Already processing, ignoring hotkey")
            return
        threading.Thread(target=self._process, args=(deep,), daemon=True).start()

    def _process(self, deep: bool):
        """Main flow: extract text → AI → overlay."""
        self._busy = True
        mode = "deep" if deep else "quick"

        try:
            # 1. Extract conversation text via OS Accessibility API
            logger.info("[%s] Extracting text from active window...", mode)
            text, app_name = self.platform.extract_conversation(deep=deep)
            self._source_app = app_name
            self._last_app_name = app_name

            # 2. Show overlay in loading state
            self.overlay = OverlayWindow(
                on_paste=self._handle_paste,
                on_regen=self._handle_regen,
                on_close=self._handle_close,
            )
            self.overlay.show_loading()

            # 3. Choose method based on extraction result
            if len(text) >= _MIN_TEXT_LENGTH:
                self._last_text = text
                self._last_screenshot = None
                logger.info(
                    "[%s] Extracted %d chars from %s — using text mode",
                    mode, len(text), app_name,
                )
                reply = self.ai_agent.generate_reply_from_text(text, app_name)
            else:
                logger.warning(
                    "[%s] Text extraction got only %d chars — falling back to screenshot",
                    mode, len(text),
                )
                self._last_text = None
                screenshot_path = SCREENSHOT_PATH
                self._last_screenshot = self.platform.capture_screenshot(screenshot_path)
                reply = self.ai_agent.generate_reply_from_screenshot(
                    self._last_screenshot
                )

            self._last_suggestion = reply

            # 4. Show the reply
            self.overlay.show_reply(reply)
            logger.info("[%s] Reply shown in overlay", mode)
            self.overlay.run_loop()

        except Exception as e:
            logger.error("Error: %s", e, exc_info=True)
            if self.overlay:
                try:
                    self.overlay.show_error(str(e))
                    self.overlay.run_loop()
                except Exception:
                    pass
        finally:
            self._busy = False

    def _handle_paste(self, text: str):
        """Copy text to clipboard and simulate paste in the source app."""
        logger.info("Pasting reply into %s", self._source_app)
        time.sleep(0.3)

        if self._source_app:
            self.platform.activate_app(self._source_app)
            time.sleep(0.3)

        pyautogui.hotkey(*PASTE_HOTKEY)
        logger.info("Paste simulated")

    def _handle_regen(self, previous: str):
        """Regenerate the AI reply."""
        def do_regen():
            try:
                if self._last_text:
                    reply = self.ai_agent.generate_reply_from_text(
                        self._last_text,
                        self._last_app_name or "Unknown",
                        previous_suggestion=previous,
                    )
                elif self._last_screenshot:
                    reply = self.ai_agent.generate_reply_from_screenshot(
                        self._last_screenshot,
                        previous_suggestion=previous,
                    )
                else:
                    return

                self._last_suggestion = reply
                if self.overlay:
                    self.overlay.show_reply(reply)
            except Exception as e:
                logger.error("Regeneration error: %s", e)
                if self.overlay:
                    self.overlay.show_error(str(e))

        threading.Thread(target=do_regen, daemon=True).start()

    def _handle_close(self):
        logger.info("Overlay closed")

    def _menu_about(self):
        import tkinter.messagebox as mb
        mb.showinfo(
            "AutoReply AI",
            f"Universal AI Sales Assistant\n\n"
            f"{_HOTKEY_LABEL_QUICK} — Quick reply (current view)\n"
            f"{_HOTKEY_LABEL_DEEP} — Deep scan (scroll for full history)\n\n"
            f"Uses OS Accessibility API to read text from any chat,\n"
            f"then Gemini AI generates the optimal sales reply.\n\n"
            f"Falls back to screenshot if text extraction fails.",
        )

    def _menu_quit(self):
        self.hotkey.stop()
        self.tray.stop()


if __name__ == "__main__":
    AutoReplyApp().run()
