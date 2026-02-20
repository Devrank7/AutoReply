"""Client Lookup Window — browse demo clients, analyze websites, generate outreach."""

import logging
import threading
import tkinter as tk

import pyperclip

from services.client_api import ClientAPI, ClientAPIError
from services.url_shortener import shorten_url, ShortenError
from services.client_analyzer import ClientAnalyzer, AnalysisError

logger = logging.getLogger(__name__)

# ── Apple macOS light color palette ─────────────────────────────
_BG         = "#F2F2F7"   # Window background (macOS secondary bg)
_BG_WHITE   = "#FFFFFF"   # Card / input background
_SEP        = "#C6C6C8"   # Separator / border
_ACCENT     = "#007AFF"   # Apple blue
_ACCENT_DIM = "#0064D0"   # Hover blue
_TEXT       = "#1C1C1E"   # Primary label
_TEXT_SEC   = "#8E8E93"   # Secondary label
_TEXT_BTN   = "#FFFFFF"   # Button text on colored bg
_HOVER_ROW  = "#F5F5F7"   # Row hover


def _sep(parent):
    """1 px horizontal separator."""
    f = tk.Frame(parent, bg=_SEP, height=1)
    f.pack(fill=tk.X)
    return f


class ClientLookupWindow:
    """Two-view window: client list → client detail."""

    def __init__(self, master=None, on_close=None):
        self.master   = master
        self.on_close = on_close
        self.root     = None

        self.client_api = ClientAPI()
        self.analyzer   = ClientAnalyzer()

        self._clients          = []
        self._filtered_clients = []
        self._selected_client  = None
        self._short_url        = None
        self._pain_points      = None
        self._first_message    = None

    # ── Window creation ──────────────────────────────────────────

    def show(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass

        self.root = tk.Toplevel(self.master) if self.master else tk.Tk()
        self.root.title("Client Lookup")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=_BG)
        self.root.resizable(True, True)
        self.root.minsize(600, 440)

        w, h = 720, 580
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.root.bind("<Escape>", lambda e: self._close())

        self._show_loading("Loading clients…")
        threading.Thread(target=self._load_clients, daemon=True).start()

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    # ── Loading screen ───────────────────────────────────────────

    def _show_loading(self, msg: str):
        self._clear()
        self._build_header("Client Lookup")
        _sep(self.root)
        f = tk.Frame(self.root, bg=_BG)
        f.pack(expand=True)
        tk.Label(f, text=msg, font=("Helvetica Neue", 14),
                 fg=_TEXT_SEC, bg=_BG).pack(pady=16)
        self.root.update()

    # ── View 1 — Client list ─────────────────────────────────────

    def _show_client_list(self):
        self._clear()
        self._build_header("Client Lookup")
        _sep(self.root)

        # ── Search / filter bar (white panel) ────────────────────
        bar = tk.Frame(self.root, bg=_BG_WHITE)
        bar.pack(fill=tk.X)

        inner = tk.Frame(bar, bg=_BG_WHITE)
        inner.pack(fill=tk.X, padx=20, pady=10)

        # Search field
        search_bg = tk.Frame(inner, bg=_BG, bd=0)
        search_bg.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=1)
        tk.Label(search_bg, text="⌕", font=("Helvetica Neue", 14),
                 fg=_TEXT_SEC, bg=_BG).pack(side=tk.LEFT, padx=(8, 2))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(search_bg, textvariable=self._search_var,
                 font=("Helvetica Neue", 13), fg=_TEXT, bg=_BG,
                 insertbackground=_ACCENT, bd=0, relief=tk.FLAT
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))

        # Date range
        tk.Label(inner, text="From", font=("Helvetica Neue", 12),
                 fg=_TEXT_SEC, bg=_BG_WHITE).pack(side=tk.LEFT, padx=(14, 4))
        self._date_from_var = tk.StringVar()
        self._date_from_var.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(inner, textvariable=self._date_from_var, width=10,
                 font=("Helvetica Neue", 12), fg=_TEXT, bg=_BG,
                 insertbackground=_ACCENT, bd=0, relief=tk.FLAT
                 ).pack(side=tk.LEFT, ipady=6)

        tk.Label(inner, text="–", font=("Helvetica Neue", 12),
                 fg=_TEXT_SEC, bg=_BG_WHITE).pack(side=tk.LEFT, padx=4)

        self._date_to_var = tk.StringVar()
        self._date_to_var.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(inner, textvariable=self._date_to_var, width=10,
                 font=("Helvetica Neue", 12), fg=_TEXT, bg=_BG,
                 insertbackground=_ACCENT, bd=0, relief=tk.FLAT
                 ).pack(side=tk.LEFT, ipady=6)

        _sep(self.root)

        # Count label
        self._count_label = tk.Label(
            self.root,
            text=f"{len(self._filtered_clients)} clients",
            font=("Helvetica Neue", 11), fg=_TEXT_SEC, bg=_BG, anchor="w",
        )
        self._count_label.pack(fill=tk.X, padx=20, pady=(10, 4))

        # ── Scrollable client list ────────────────────────────────
        wrap = tk.Frame(self.root, bg=_BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))

        canvas = tk.Canvas(wrap, bg=_BG, highlightthickness=0)
        sb = tk.Scrollbar(wrap, orient=tk.VERTICAL, command=canvas.yview)
        self._list_inner = tk.Frame(canvas, bg=_BG)

        self._list_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._list_inner, anchor="nw", tags="inner")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig("inner", width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._canvas = canvas

        def _scroll(delta):
            try:
                canvas.yview_scroll(delta, "units")
            except tk.TclError:
                pass

        canvas.bind_all("<MouseWheel>",
                        lambda e: _scroll(-1 * (e.delta // 120 or (-1 if e.delta < 0 else 1))))
        canvas.bind_all("<Button-4>", lambda e: _scroll(-3))
        canvas.bind_all("<Button-5>", lambda e: _scroll(3))

        self._populate_list()
        self.root.update()

    def _populate_list(self):
        for w in self._list_inner.winfo_children():
            w.destroy()

        for client in self._filtered_clients:
            card = tk.Frame(self._list_inner, bg=_BG_WHITE, cursor="hand2")
            card.pack(fill=tk.X, pady=(0, 1))

            body = tk.Frame(card, bg=_BG_WHITE)
            body.pack(fill=tk.X, padx=16, pady=12)

            # Name + chevron
            top_row = tk.Frame(body, bg=_BG_WHITE)
            top_row.pack(fill=tk.X)
            tk.Label(top_row, text=client.get("name", "Unknown"),
                     font=("Helvetica Neue", 13, "bold"),
                     fg=_TEXT, bg=_BG_WHITE, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(top_row, text="›", font=("Helvetica Neue", 18),
                     fg=_TEXT_SEC, bg=_BG_WHITE).pack(side=tk.RIGHT)

            # Sub-line
            parts = []
            if w := client.get("website", ""):
                parts.append(w)
            if d := (client.get("createdAt", "") or "")[:10]:
                parts.append(d)
            if parts:
                tk.Label(body, text="  ·  ".join(parts),
                         font=("Helvetica Neue", 11), fg=_TEXT_SEC,
                         bg=_BG_WHITE, anchor="w").pack(fill=tk.X, pady=(2, 0))

            def _handler(c):
                return lambda e: self._select_client(c)

            def _enter(_, c=card, b=body):
                c.configure(bg=_HOVER_ROW)
                b.configure(bg=_HOVER_ROW)
                for ch in b.winfo_children():
                    for gch in ([ch] + list(ch.winfo_children())):
                        try:
                            gch.configure(bg=_HOVER_ROW)
                        except Exception:
                            pass

            def _leave(_, c=card, b=body):
                c.configure(bg=_BG_WHITE)
                b.configure(bg=_BG_WHITE)
                for ch in b.winfo_children():
                    for gch in ([ch] + list(ch.winfo_children())):
                        try:
                            gch.configure(bg=_BG_WHITE)
                        except Exception:
                            pass

            for widget in [card, body] + list(body.winfo_children()):
                widget.bind("<Button-1>", _handler(client))
                widget.bind("<Enter>", _enter)
                widget.bind("<Leave>", _leave)

    def _apply_filters(self):
        q  = self._search_var.get()
        df = self._date_from_var.get().strip() or None
        dt = self._date_to_var.get().strip() or None
        self._filtered_clients = self.client_api.search_clients(q, df, dt)
        self._count_label.config(
            text=f"{len(self._filtered_clients)} of {len(self._clients)} clients"
        )
        self._populate_list()

    # ── View 2 — Client detail ───────────────────────────────────

    def _show_client_detail(self, client: dict):
        self._clear()
        name = client.get("name", "Client")
        self._build_header(name[:46] + ("…" if len(name) > 46 else ""), show_back=True)
        _sep(self.root)

        outer = tk.Frame(self.root, bg=_BG)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, bg=_BG, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        content = tk.Frame(canvas, bg=_BG)
        content.bind("<Configure>",
                     lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw", tags="d")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig("d", width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Info card ─────────────────────────────────────────────
        card = tk.Frame(content, bg=_BG_WHITE)
        card.pack(fill=tk.X, padx=20, pady=(20, 0))

        fields = [
            ("Website",  client.get("website", "") or "—"),
            ("Email",    client.get("email", "")   or "—"),
            ("Created",  (client.get("createdAt", "") or "")[:10] or "—"),
            ("Demo URL", client.get("demoUrl", "") or "—"),
        ]
        for i, (lbl, val) in enumerate(fields):
            if i:
                tk.Frame(card, bg=_SEP, height=1).pack(fill=tk.X, padx=16)
            row = tk.Frame(card, bg=_BG_WHITE)
            row.pack(fill=tk.X, padx=16)
            tk.Label(row, text=lbl, width=9, anchor="w",
                     font=("Helvetica Neue", 12), fg=_TEXT_SEC,
                     bg=_BG_WHITE).pack(side=tk.LEFT, pady=11)
            tk.Label(row, text=val, anchor="w", wraplength=480,
                     font=("Helvetica Neue", 12), fg=_TEXT,
                     bg=_BG_WHITE).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                        pady=11, padx=(10, 0))

        # ── Action buttons ────────────────────────────────────────
        btn_row = tk.Frame(content, bg=_BG)
        btn_row.pack(fill=tk.X, padx=20, pady=20)

        self._make_btn(btn_row, "Shorten URL",
                       lambda: self._do_shorten_url(client), "secondary"
                       ).pack(side=tk.LEFT, padx=(0, 8))
        self._make_btn(btn_row, "Find Hooks",
                       lambda: self._do_find_hooks(client), "secondary"
                       ).pack(side=tk.LEFT, padx=(0, 8))
        self._make_btn(btn_row, "Generate Message",
                       lambda: self._do_generate_message(client), "primary"
                       ).pack(side=tk.LEFT)

        # Status
        self._status_label = tk.Label(content, text="",
                                      font=("Helvetica Neue", 11),
                                      fg=_TEXT_SEC, bg=_BG, anchor="w")
        self._status_label.pack(fill=tk.X, padx=20, pady=(0, 6))

        # Result text area (with 1px border via wrapper)
        border = tk.Frame(content, bg=_SEP)
        border.pack(fill=tk.BOTH, expand=True, padx=20)
        self._result_area = tk.Text(
            border,
            font=("Helvetica Neue", 13), fg=_TEXT, bg=_BG_WHITE,
            insertbackground=_ACCENT, selectbackground=_ACCENT,
            selectforeground=_TEXT_BTN, bd=0, padx=14, pady=12,
            wrap=tk.WORD, relief=tk.FLAT, height=9,
        )
        self._result_area.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Copy button
        copy_row = tk.Frame(content, bg=_BG)
        copy_row.pack(fill=tk.X, padx=20, pady=14)
        self._make_btn(copy_row, "Copy to Clipboard", self._copy_result, "ghost"
                       ).pack(side=tk.LEFT)

        self.root.update()

    # ── Button factory ───────────────────────────────────────────

    def _make_btn(self, parent, text: str, command, style: str = "secondary"):
        """Return a styled button wrapper frame."""
        cfg = {
            "primary":   (_ACCENT,    _TEXT_BTN, _ACCENT_DIM),
            "secondary": (_BG_WHITE,  _TEXT,     _HOVER_ROW),
            "ghost":     (_BG,        _ACCENT,   _BG),
        }.get(style, (_BG_WHITE, _TEXT, _HOVER_ROW))
        bg, fg, hover = cfg

        wrap = tk.Frame(parent, bg=_SEP if style == "secondary" else bg)
        btn = tk.Button(
            wrap, text=text,
            font=("Helvetica Neue", 13), fg=fg, bg=bg,
            activebackground=hover, activeforeground=fg,
            bd=0, padx=16, pady=7, cursor="hand2",
            relief=tk.FLAT, command=command,
        )
        btn.pack(padx=1 if style == "secondary" else 0,
                 pady=1 if style == "secondary" else 0)
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return wrap

    # ── Header ───────────────────────────────────────────────────

    def _build_header(self, title: str, show_back: bool = False):
        hdr = tk.Frame(self.root, bg=_BG_WHITE, height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        if show_back:
            tk.Button(hdr, text="← Back",
                      font=("Helvetica Neue", 13), fg=_ACCENT,
                      bg=_BG_WHITE, bd=0,
                      activebackground=_BG_WHITE, activeforeground=_ACCENT_DIM,
                      cursor="hand2", command=self._go_back
                      ).pack(side=tk.LEFT, padx=(16, 0))

        tk.Label(hdr, text=title,
                 font=("Helvetica Neue", 14, "bold"),
                 fg=_TEXT, bg=_BG_WHITE
                 ).pack(side=tk.LEFT, padx=(12 if show_back else 20, 0))

        tk.Button(hdr, text="✕",
                  font=("Helvetica Neue", 14), fg=_TEXT_SEC,
                  bg=_BG_WHITE, bd=0,
                  activebackground=_BG_WHITE, activeforeground=_TEXT,
                  cursor="hand2", command=self._close
                  ).pack(side=tk.RIGHT, padx=16)

    # ── Result helpers ───────────────────────────────────────────

    def _show_result(self, status: str, text: str):
        try:
            if hasattr(self, "_status_label") and self._status_label.winfo_exists():
                self._status_label.config(text=status)
            if hasattr(self, "_result_area") and self._result_area.winfo_exists():
                self._result_area.config(state=tk.NORMAL)
                self._result_area.delete("1.0", tk.END)
                if text:
                    self._result_area.insert("1.0", text)
            self.root.update()
        except tk.TclError:
            pass

    def _set_status(self, text: str):
        try:
            if hasattr(self, "_status_label") and self._status_label.winfo_exists():
                self._status_label.config(text=text)
            self.root.update()
        except tk.TclError:
            pass

    def _copy_result(self):
        if hasattr(self, "_result_area"):
            text = self._result_area.get("1.0", tk.END).strip()
            if text:
                pyperclip.copy(text)
                self._set_status("Copied!")
                self.root.after(1500, lambda: self._set_status(""))

    # ── Navigation ───────────────────────────────────────────────

    def _go_back(self):
        self._selected_client = None
        self._short_url = self._pain_points = self._first_message = None
        self._show_client_list()

    def _select_client(self, client: dict):
        self._selected_client = client
        self._short_url = self._pain_points = self._first_message = None
        self._show_client_detail(client)

    def _close(self):
        # Unbind global scroll handlers before destroying the canvas
        if self.root:
            try:
                self.root.unbind_all("<MouseWheel>")
                self.root.unbind_all("<Button-4>")
                self.root.unbind_all("<Button-5>")
            except Exception:
                pass
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None
        if self.on_close:
            self.on_close()

    # ── Action handlers ──────────────────────────────────────────

    def _do_shorten_url(self, client: dict):
        demo_url = client.get("demoUrl", "")
        if not demo_url:
            self._show_result("No demo URL", "This client has no demo URL to shorten.")
            return
        if self._short_url:
            self._show_result("Shortened URL", self._short_url)
            return
        self._show_result("Shortening…", "")

        def work():
            try:
                s = shorten_url(demo_url)
                self._short_url = s
                self.root.after(0, lambda: self._show_result("Shortened URL", s))
            except ShortenError as e:
                self.root.after(0, lambda: self._show_result("Error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _do_find_hooks(self, client: dict):
        website = client.get("website", "")
        if not website:
            self._show_result("No website", "This client has no website URL.")
            return
        if self._pain_points:
            self._show_result("Business Analysis", self._pain_points)
            return
        self._show_result("Analyzing…", "Fetching website content…")

        def work():
            try:
                a = self.analyzer.analyze_business(website)
                self._pain_points = a
                self.root.after(0, lambda: self._show_result("Business Analysis", a))
            except AnalysisError as e:
                self.root.after(0, lambda: self._show_result("Error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _do_generate_message(self, client: dict):
        self._show_result("Generating…", "")

        def work():
            try:
                if not self._short_url:
                    demo_url = client.get("demoUrl", "")
                    if demo_url:
                        try:
                            self._short_url = shorten_url(demo_url)
                        except ShortenError:
                            self._short_url = demo_url

                if not self._pain_points:
                    site = client.get("website", "")
                    if site:
                        self.root.after(0, lambda: self._set_status("Analyzing website…"))
                        self._pain_points = self.analyzer.analyze_business(site)

                if not self._pain_points:
                    self.root.after(0, lambda: self._show_result(
                        "Missing data",
                        "Could not analyze the website. Try 'Find Hooks' first.",
                    ))
                    return

                self.root.after(0, lambda: self._set_status("Writing message…"))
                msg = self.analyzer.generate_first_message(
                    client_name=client.get("name", ""),
                    pain_points=self._pain_points,
                    short_demo_url=self._short_url or client.get("demoUrl", ""),
                    website_url=client.get("website", ""),
                )
                self._first_message = msg
                self.root.after(0, lambda: self._show_result("Outreach Message", msg))
            except Exception as e:
                self.root.after(0, lambda: self._show_result("Error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    # ── Data loading ─────────────────────────────────────────────

    def _load_clients(self):
        try:
            self._clients = self.client_api.fetch_clients()
            self._filtered_clients = list(self._clients)
            self.root.after(0, self._show_client_list)
        except ClientAPIError as e:
            self.root.after(0, lambda: self._show_error(str(e)))

    def _show_error(self, message: str):
        self._clear()
        self._build_header("Client Lookup")
        _sep(self.root)
        f = tk.Frame(self.root, bg=_BG)
        f.pack(expand=True)
        tk.Label(f, text="Could not load clients",
                 font=("Helvetica Neue", 15, "bold"), fg=_TEXT, bg=_BG).pack(pady=(0, 8))
        tk.Label(f, text=message,
                 font=("Helvetica Neue", 12), fg=_TEXT_SEC, bg=_BG,
                 wraplength=400).pack(pady=(0, 20))
        self._make_btn(f, "Try Again", self._retry_load, "primary").pack()
        self.root.update()

    def _retry_load(self):
        self._show_loading("Loading clients…")
        threading.Thread(target=self._load_clients, daemon=True).start()

    def run_loop(self):
        """No-op: main thread's mainloop handles events."""
        pass
