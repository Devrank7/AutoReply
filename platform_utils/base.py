"""Abstract base class for platform-specific operations."""

from abc import ABC, abstractmethod


class BasePlatform(ABC):
    """Interface that each platform (macOS, Windows) must implement."""

    @abstractmethod
    def check_permissions(self) -> bool:
        """Check if the app has required OS permissions (Accessibility, etc.).
        Returns True if permissions are granted.
        """
        ...

    @abstractmethod
    def get_frontmost_app_name(self) -> str:
        """Get the name of the currently focused application."""
        ...

    @abstractmethod
    def get_frontmost_app_pid(self) -> int | None:
        """Get the PID of the currently focused application."""
        ...

    @abstractmethod
    def extract_text_from_window(self, pid: int) -> str:
        """Extract all text from the frontmost window of the given app.

        Uses OS-level Accessibility / UI Automation APIs to walk the
        UI element tree and collect text content.
        """
        ...

    @abstractmethod
    def capture_screenshot(self, output_path: str) -> str:
        """Take a screenshot of the active window.
        Returns the path to the saved image file.
        """
        ...

    @abstractmethod
    def activate_app(self, app_name: str):
        """Bring the specified application to the foreground."""
        ...

    @abstractmethod
    def scroll_up(self, amount: int = 5):
        """Simulate scrolling up in the active window."""
        ...

    def extract_conversation(self, deep: bool = False) -> tuple[str, str]:
        """Main entry point: extract conversation text from the frontmost app.

        Args:
            deep: If True, scroll up to capture more message history.

        Returns:
            (extracted_text, app_name)
        """
        import time
        import logging

        logger = logging.getLogger(__name__)

        pid = self.get_frontmost_app_pid()
        if not pid:
            return "", "Unknown"

        app_name = self.get_frontmost_app_name()

        if not self.check_permissions():
            logger.warning("OS permissions not granted — text extraction may fail")

        if deep:
            # Scroll up and extract from multiple positions
            all_lines = []
            seen = set()

            for i in range(5):
                text = self.extract_text_from_window(pid)
                for line in text.split("\n"):
                    if line and line not in seen:
                        seen.add(line)
                        all_lines.append(line)
                if i < 4:
                    self.scroll_up(amount=5)
                    time.sleep(0.4)

            # Scroll back down
            import pyautogui
            for _ in range(4):
                pyautogui.scroll(-5)
                time.sleep(0.1)

            text = "\n".join(all_lines)
        else:
            text = self.extract_text_from_window(pid)

        logger.info("Extracted %d chars from %s (deep=%s)", len(text), app_name, deep)
        return text, app_name
