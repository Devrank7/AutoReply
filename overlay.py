import tkinter as tk
from tkinter import font as tkfont
import logging
import pyperclip

logger = logging.getLogger(__name__)


class OverlayWindow:
    """Floating overlay window that shows AI-suggested replies."""

    def __init__(self, master=None, on_paste=None, on_regen=None, on_close=None):
        self.master = master
        self.on_paste = on_paste
        self.on_regen = on_regen
        self.on_close = on_close

        self.root = None
        self._current_suggestion = ""

    def _create_window(self):
        """Create the tkinter overlay window as a Toplevel."""
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass

        self.root = tk.Toplevel(self.master) if self.master else tk.Tk()
        self.root.title("AutoReply AI")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(False)

        # Window size and position (bottom-right corner)
        width, height = 520, 400
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - width - 30
        y = screen_h - height - 80
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # Styling
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)

        # Fonts
        title_font = tkfont.Font(family="Helvetica", size=14, weight="bold")
        text_font = tkfont.Font(family="Helvetica", size=13)
        btn_font = tkfont.Font(family="Helvetica", size=12, weight="bold")

        # Header
        header = tk.Frame(self.root, bg="#16213e", padx=12, pady=8)
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text="AutoReply AI",
            font=title_font,
            fg="#e94560",
            bg="#16213e",
        ).pack(side=tk.LEFT)

        close_btn = tk.Button(
            header,
            text="X",
            font=btn_font,
            fg="#aaa",
            bg="#16213e",
            bd=0,
            activebackground="#e94560",
            activeforeground="#fff",
            command=self._on_close_click,
        )
        close_btn.pack(side=tk.RIGHT)

        # Status label
        self.status_label = tk.Label(
            self.root,
            text="Analyzing conversation...",
            font=tkfont.Font(family="Helvetica", size=11),
            fg="#aaa",
            bg="#1a1a2e",
            pady=4,
        )
        self.status_label.pack(fill=tk.X)

        # Text area (editable)
        text_frame = tk.Frame(self.root, bg="#1a1a2e", padx=12, pady=4)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_area = tk.Text(
            text_frame,
            font=text_font,
            fg="#eee",
            bg="#0f3460",
            insertbackground="#e94560",
            selectbackground="#e94560",
            selectforeground="#fff",
            bd=0,
            padx=10,
            pady=10,
            wrap=tk.WORD,
            relief=tk.FLAT,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)

        # Buttons
        btn_frame = tk.Frame(self.root, bg="#1a1a2e", padx=12, pady=10)
        btn_frame.pack(fill=tk.X)

        btn_style = {
            "font": btn_font,
            "bd": 0,
            "padx": 16,
            "pady": 8,
            "cursor": "hand2",
        }

        tk.Button(
            btn_frame,
            text="Copy",
            fg="#fff",
            bg="#533483",
            activebackground="#7952b3",
            activeforeground="#fff",
            command=self._on_copy_click,
            **btn_style,
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            btn_frame,
            text="Paste",
            fg="#fff",
            bg="#e94560",
            activebackground="#ff6b81",
            activeforeground="#fff",
            command=self._on_paste_click,
            **btn_style,
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            btn_frame,
            text="Regen",
            fg="#fff",
            bg="#0f3460",
            activebackground="#1a5276",
            activeforeground="#fff",
            command=self._on_regen_click,
            **btn_style,
        ).pack(side=tk.LEFT)

        # Bind Escape to close
        self.root.bind("<Escape>", lambda e: self._on_close_click())

    def show_loading(self):
        """Show the overlay in loading state."""
        self._create_window()
        self.status_label.config(text="Analyzing conversation...")
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", "Reading the chat screenshot and generating the best reply...")
        self.text_area.config(state=tk.DISABLED)
        self.root.update()

    def show_reply(self, suggestion: str):
        """Display the AI-generated reply."""
        self._current_suggestion = suggestion
        self.status_label.config(text="AI-generated reply (you can edit before sending):")
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", suggestion)
        self.root.update()

    def show_error(self, error_msg: str):
        """Display an error message."""
        self.status_label.config(text="Error:")
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", f"Error: {error_msg}")
        self.root.update()

    def get_text(self) -> str:
        """Get the current text from the text area (may be edited by user)."""
        return self.text_area.get("1.0", tk.END).strip()

    def _on_copy_click(self):
        text = self.get_text()
        pyperclip.copy(text)
        self.status_label.config(text="Copied to clipboard!")
        self.root.after(1500, lambda: self.status_label.config(
            text="AI-generated reply (you can edit before sending):"))

    def _on_paste_click(self):
        text = self.get_text()
        pyperclip.copy(text)
        self.hide()
        if self.on_paste:
            self.on_paste(text)

    def _on_regen_click(self):
        self._current_suggestion = self.get_text()
        self.status_label.config(text="Regenerating...")
        self.text_area.config(state=tk.DISABLED)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", "Generating a different reply...")
        self.root.update()
        if self.on_regen:
            self.on_regen(self._current_suggestion)

    def _on_close_click(self):
        self.hide()
        if self.on_close:
            self.on_close()

    def hide(self):
        """Hide/destroy the overlay window."""
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    def run_loop(self):
        """No-op: main thread's mainloop handles events."""
        pass

    def update(self):
        """Process pending tkinter events without blocking."""
        if self.root:
            try:
                self.root.update()
            except tk.TclError:
                self.root = None
