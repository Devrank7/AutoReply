"""
AutoReply AI — Universal Sales Assistant (macOS + Windows)

Usage: python app.py

Hotkeys:
  Ctrl+Alt+R (Win) / Cmd+Option+R (Mac) — Quick: extract text + generate reply
  Ctrl+Alt+E (Win) / Cmd+Option+E (Mac) — Deep: scroll for history + generate reply
  Ctrl+Shift+E (Win) / Cmd+Shift+E (Mac) — Client Lookup: browse demo clients

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
from client_lookup_window import ClientLookupWindow
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

# Client Lookup hotkey (uses Shift, not Alt — no browser conflicts)
_SHIFT = "<shift>"
_CLIENT_HOTKEY = f"{_MOD}+{_SHIFT}+e"
_HOTKEY_LABEL_CLIENT = "Cmd+Shift+E" if IS_MACOS else "Ctrl+Shift+E"


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

    def __init__(self, on_quick, on_deep, on_client):
        self.on_quick = on_quick
        self.on_deep = on_deep
        self.on_client = on_client
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
        hotkey_client = keyboard.HotKey(
            keyboard.HotKey.parse(_CLIENT_HOTKEY),
            lambda: self.on_client(),
        )

        def on_press(key):
            canonical = self._listener.canonical(key)
            hotkey_quick.press(canonical)
            hotkey_deep.press(canonical)
            hotkey_client.press(canonical)

        def on_release(key):
            canonical = self._listener.canonical(key)
            hotkey_quick.release(canonical)
            hotkey_deep.release(canonical)
            hotkey_client.release(canonical)

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()
        logger.info(
            "Hotkeys active: %s (quick) | %s (deep) | %s (clients)",
            _HOTKEY_LABEL_QUICK, _HOTKEY_LABEL_DEEP, _HOTKEY_LABEL_CLIENT,
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
        self._client_window = None

        # Global hotkeys
        self.hotkey = Hotkey(
            on_quick=lambda: self._on_hotkey(deep=False),
            on_deep=lambda: self._on_hotkey(deep=True),
            on_client=lambda: self._on_client_lookup(),
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
                pystray.MenuItem(
                    f"Client Lookup ({_HOTKEY_LABEL_CLIENT})",
                    lambda: self._on_client_lookup(),
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
        logger.info("%s — client lookup (demo clients)", _HOTKEY_LABEL_CLIENT)
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

    # ── Client Lookup ────────────────────────────────────────────

    def _on_client_lookup(self):
        """Open the Client Lookup window."""
        if self._client_window and self._client_window.root:
            logger.info("Client Lookup window already open")
            return
        threading.Thread(target=self._show_client_lookup, daemon=True).start()

    def _show_client_lookup(self):
        """Create and show the Client Lookup window."""
        try:
            self._client_window = ClientLookupWindow(
                on_close=self._on_client_window_close,
            )
            self._client_window.show()
            self._client_window.run_loop()
        except Exception as e:
            logger.error("Client Lookup error: %s", e, exc_info=True)
        finally:
            self._client_window = None

    def _on_client_window_close(self):
        logger.info("Client Lookup window closed")
        self._client_window = None

    # ── Menu ─────────────────────────────────────────────────────

    def _menu_about(self):
        import tkinter.messagebox as mb
        mb.showinfo(
            "AutoReply AI",
            f"Universal AI Sales Assistant\n\n"
            f"{_HOTKEY_LABEL_QUICK} — Quick reply (current view)\n"
            f"{_HOTKEY_LABEL_DEEP} — Deep scan (scroll for full history)\n"
            f"{_HOTKEY_LABEL_CLIENT} — Client Lookup (demo clients)\n\n"
            f"Uses OS Accessibility API to read text from any chat,\n"
            f"then Gemini AI generates the optimal sales reply.\n\n"
            f"Falls back to screenshot if text extraction fails.",
        )

    def _menu_quit(self):
        self.hotkey.stop()
        self.tray.stop()


if __name__ == "__main__":
    AutoReplyApp().run()
