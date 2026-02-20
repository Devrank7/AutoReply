import tkinter as tk
import logging
import pyperclip

logger = logging.getLogger(__name__)

# ── Apple macOS light palette ────────────────────────────────────
_BG       = "#F2F2F7"
_BG_WHITE = "#FFFFFF"
_SEP      = "#C6C6C8"
_ACCENT   = "#007AFF"
_ACCENT_D = "#0064D0"
_TEXT     = "#1C1C1E"
_TEXT_SEC = "#8E8E93"
_TEXT_BTN = "#FFFFFF"
_GREEN    = "#34C759"
_RED      = "#FF3B30"


class OverlayWindow:
    """Floating overlay window that shows AI-suggested replies."""

    def __init__(self, master=None, on_paste=None, on_regen=None, on_close=None):
        self.master    = master
        self.on_paste  = on_paste
        self.on_regen  = on_regen
        self.on_close  = on_close
        self.root      = None
        self._current_suggestion = ""

    def _create_window(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass

        self.root = tk.Toplevel(self.master) if self.master else tk.Tk()
        self.root.title("AutoReply AI")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(False)
        self.root.configure(bg=_BG)
        self.root.resizable(True, True)

        w, h = 540, 420
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{sw - w - 24}+{sh - h - 72}")

        # ── Header ────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=_BG_WHITE, height=48)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        tk.Label(hdr, text="AutoReply AI",
                 font=("Helvetica Neue", 13, "bold"),
                 fg=_TEXT, bg=_BG_WHITE).pack(side=tk.LEFT, padx=16)

        tk.Button(hdr, text="✕",
                  font=("Helvetica Neue", 13), fg=_TEXT_SEC, bg=_BG_WHITE,
                  bd=0, activebackground=_BG_WHITE, activeforeground=_TEXT,
                  cursor="hand2", command=self._on_close_click
                  ).pack(side=tk.RIGHT, padx=14)

        # Separator
        tk.Frame(self.root, bg=_SEP, height=1).pack(fill=tk.X)

        # ── Status label ──────────────────────────────────────────
        self.status_label = tk.Label(
            self.root, text="Analyzing…",
            font=("Helvetica Neue", 11), fg=_TEXT_SEC, bg=_BG, anchor="w",
        )
        self.status_label.pack(fill=tk.X, padx=16, pady=(10, 4))

        # ── Text area (1px border via wrapper) ────────────────────
        border = tk.Frame(self.root, bg=_SEP)
        border.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        self.text_area = tk.Text(
            border,
            font=("Helvetica Neue", 13), fg=_TEXT, bg=_BG_WHITE,
            insertbackground=_ACCENT, selectbackground=_ACCENT,
            selectforeground=_TEXT_BTN,
            bd=0, padx=12, pady=10, wrap=tk.WORD, relief=tk.FLAT,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # ── Button row ────────────────────────────────────────────
        btn_row = tk.Frame(self.root, bg=_BG)
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 16))

        self._add_btn(btn_row, "Copy",  self._on_copy_click,  "secondary").pack(side=tk.LEFT, padx=(0, 8))
        self._add_btn(btn_row, "Paste", self._on_paste_click, "primary"  ).pack(side=tk.LEFT, padx=(0, 8))
        self._add_btn(btn_row, "Regen", self._on_regen_click, "ghost"    ).pack(side=tk.LEFT)

        self.root.bind("<Escape>", lambda _: self._on_close_click())

    def _add_btn(self, parent, text: str, command, style: str = "secondary"):
        cfg = {
            "primary":   (_ACCENT,   _TEXT_BTN, _ACCENT_D),
            "secondary": (_BG_WHITE, _TEXT,     _BG),
            "ghost":     (_BG,       _TEXT_SEC, _BG_WHITE),
        }.get(style, (_BG_WHITE, _TEXT, _BG))
        bg, fg, hover = cfg

        wrap = tk.Frame(parent, bg=_SEP if style == "secondary" else bg)
        btn = tk.Button(
            wrap, text=text,
            font=("Helvetica Neue", 12), fg=fg, bg=bg,
            activebackground=hover, activeforeground=fg,
            bd=0, padx=14, pady=6, cursor="hand2",
            relief=tk.FLAT, command=command,
        )
        btn.pack(padx=1 if style == "secondary" else 0,
                 pady=1 if style == "secondary" else 0)
        btn.bind("<Enter>", lambda _: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda _: btn.configure(bg=bg))
        return wrap

    # ── Public API ───────────────────────────────────────────────

    def show_loading(self):
        self._create_window()
        self.status_label.config(text="Analyzing conversation…")
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", "Reading the chat and generating the best reply…")
        self.text_area.config(state=tk.DISABLED)
        self.root.update()

    def show_reply(self, suggestion: str):
        self._current_suggestion = suggestion
        self.status_label.config(text="AI reply  ·  edit before sending")
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", suggestion)
        self.root.update()

    def show_error(self, error_msg: str):
        self.status_label.config(text="Error")
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", error_msg)
        self.root.update()

    def get_text(self) -> str:
        return self.text_area.get("1.0", tk.END).strip()

    # ── Button handlers ──────────────────────────────────────────

    def _on_copy_click(self):
        pyperclip.copy(self.get_text())
        self.status_label.config(text="Copied to clipboard!")
        self.root.after(1500, lambda: self.status_label.config(
            text="AI reply  ·  edit before sending"))

    def _on_paste_click(self):
        text = self.get_text()
        pyperclip.copy(text)
        self.hide()
        if self.on_paste:
            self.on_paste(text)

    def _on_regen_click(self):
        self._current_suggestion = self.get_text()
        self.status_label.config(text="Regenerating…")
        self.text_area.config(state=tk.DISABLED)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", "Generating a different reply…")
        self.root.update()
        if self.on_regen:
            self.on_regen(self._current_suggestion)

    def _on_close_click(self):
        self.hide()
        if self.on_close:
            self.on_close()

    # ── Lifecycle ────────────────────────────────────────────────

    def hide(self):
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
        if self.root:
            try:
                self.root.update()
            except tk.TclError:
                self.root = None
