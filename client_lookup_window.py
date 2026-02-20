"""Client Lookup Window — browse demo clients, analyze websites, generate outreach."""

import logging
import threading
import tkinter as tk
from tkinter import font as tkfont

import pyperclip

from services.client_api import ClientAPI, ClientAPIError
from services.url_shortener import shorten_url, ShortenError
from services.client_analyzer import ClientAnalyzer, AnalysisError

logger = logging.getLogger(__name__)

# ── Color palette (matches overlay.py) ──────────────────────────
_BG = "#1a1a2e"
_BG_HEADER = "#16213e"
_BG_INPUT = "#0f3460"
_ACCENT = "#e94560"
_ACCENT_HOVER = "#ff6b81"
_PURPLE = "#533483"
_PURPLE_HOVER = "#7952b3"
_TEXT = "#eee"
_TEXT_DIM = "#aaa"
_TEXT_BRIGHT = "#fff"


class ClientLookupWindow:
    """Two-view window: client list and client detail."""

    def __init__(self, master=None, on_close=None):
        self.master = master
        self.on_close = on_close
        self.root = None

        self.client_api = ClientAPI()
        self.analyzer = ClientAnalyzer()

        self._clients = []
        self._filtered_clients = []
        self._selected_client = None
        self._short_url = None
        self._pain_points = None
        self._first_message = None

    # ── Window creation ──────────────────────────────────────────

    def show(self):
        """Create the window and start loading clients."""
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass

        self.root = tk.Toplevel(self.master) if self.master else tk.Tk()
        self.root.title("Client Lookup — WinBix AI")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(False)

        width, height = 700, 550
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.configure(bg=_BG)
        self.root.resizable(True, True)
        self.root.minsize(600, 450)
        self.root.bind("<Escape>", lambda e: self._close())

        self._show_loading("Fetching clients...")
        threading.Thread(target=self._load_clients, daemon=True).start()

    def _clear_content(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    # ── Loading screen ───────────────────────────────────────────

    def _show_loading(self, message: str):
        self._clear_content()
        self._build_header("Client Lookup")
        tk.Label(
            self.root,
            text=message,
            font=("Helvetica", 13),
            fg=_TEXT_DIM,
            bg=_BG,
            pady=40,
        ).pack(expand=True)
        self.root.update()

    # ── View 1: Client list ──────────────────────────────────────

    def _show_client_list(self):
        self._clear_content()
        self._build_header("Client Lookup")

        # Search bar
        search_frame = tk.Frame(self.root, bg=_BG)
        search_frame.pack(fill=tk.X, padx=16, pady=(12, 4))

        tk.Label(
            search_frame, text="Search:", font=("Helvetica", 11), fg=_TEXT_DIM, bg=_BG
        ).pack(side=tk.LEFT, padx=(0, 6))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(
            search_frame,
            textvariable=self._search_var,
            font=("Helvetica", 12),
            fg=_TEXT,
            bg=_BG_INPUT,
            insertbackground=_ACCENT,
            bd=0,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 12))

        # Date filters
        tk.Label(
            search_frame, text="From:", font=("Helvetica", 11), fg=_TEXT_DIM, bg=_BG
        ).pack(side=tk.LEFT, padx=(0, 4))

        self._date_from_var = tk.StringVar()
        self._date_from_var.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(
            search_frame,
            textvariable=self._date_from_var,
            width=12,
            font=("Helvetica", 11),
            fg=_TEXT,
            bg=_BG_INPUT,
            insertbackground=_ACCENT,
            bd=0,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, ipady=4, padx=(0, 8))

        tk.Label(
            search_frame, text="To:", font=("Helvetica", 11), fg=_TEXT_DIM, bg=_BG
        ).pack(side=tk.LEFT, padx=(0, 4))

        self._date_to_var = tk.StringVar()
        self._date_to_var.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(
            search_frame,
            textvariable=self._date_to_var,
            width=12,
            font=("Helvetica", 11),
            fg=_TEXT,
            bg=_BG_INPUT,
            insertbackground=_ACCENT,
            bd=0,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, ipady=4)

        # Count label
        self._count_label = tk.Label(
            self.root,
            text=f"Showing {len(self._filtered_clients)} of {len(self._clients)} clients",
            font=("Helvetica", 10),
            fg=_TEXT_DIM,
            bg=_BG,
            pady=4,
        )
        self._count_label.pack(fill=tk.X, padx=16)

        # Scrollable list
        list_frame = tk.Frame(self.root, bg=_BG, padx=16)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        canvas = tk.Canvas(list_frame, bg=_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        self._list_inner = tk.Frame(canvas, bg=_BG)

        self._list_inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self._list_inner, anchor="nw", tags="inner")

        # Make inner frame fill canvas width
        def _resize_inner(event):
            canvas.itemconfig("inner", width=event.width)

        canvas.bind("<Configure>", _resize_inner)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120 or (-1 if event.delta < 0 else 1)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        # macOS trackpad
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))

        self._canvas = canvas
        self._populate_client_list()
        self.root.update()

    def _populate_client_list(self):
        for widget in self._list_inner.winfo_children():
            widget.destroy()

        for client in self._filtered_clients:
            row = tk.Frame(self._list_inner, bg=_BG_INPUT, padx=12, pady=8, cursor="hand2")
            row.pack(fill=tk.X, pady=2)

            tk.Label(
                row,
                text=client.get("name", "Unknown"),
                font=("Helvetica", 12, "bold"),
                fg=_TEXT,
                bg=_BG_INPUT,
                anchor="w",
            ).pack(fill=tk.X)

            detail_parts = []
            website = client.get("website", "")
            if website:
                detail_parts.append(website)
            created = client.get("createdAt", "")
            if created:
                detail_parts.append(created[:10])
            tk.Label(
                row,
                text="  |  ".join(detail_parts),
                font=("Helvetica", 10),
                fg=_TEXT_DIM,
                bg=_BG_INPUT,
                anchor="w",
            ).pack(fill=tk.X)

            # Click handler
            def make_handler(c):
                return lambda e: self._select_client(c)

            row.bind("<Button-1>", make_handler(client))
            for child in row.winfo_children():
                child.bind("<Button-1>", make_handler(client))

            # Hover
            def on_enter(e, r=row):
                r.configure(bg=_BG_HEADER)
                for ch in r.winfo_children():
                    ch.configure(bg=_BG_HEADER)

            def on_leave(e, r=row):
                r.configure(bg=_BG_INPUT)
                for ch in r.winfo_children():
                    ch.configure(bg=_BG_INPUT)

            row.bind("<Enter>", on_enter)
            row.bind("<Leave>", on_leave)

    def _apply_filters(self):
        query = self._search_var.get()
        date_from = self._date_from_var.get().strip() or None
        date_to = self._date_to_var.get().strip() or None

        self._filtered_clients = self.client_api.search_clients(query, date_from, date_to)
        self._count_label.config(
            text=f"Showing {len(self._filtered_clients)} of {len(self._clients)} clients"
        )
        self._populate_client_list()

    # ── View 2: Client detail ────────────────────────────────────

    def _show_client_detail(self, client: dict):
        self._clear_content()
        name = client.get("name", "Client Details")
        self._build_header(name if len(name) <= 40 else name[:37] + "...", show_back=True)

        # Scrollable content
        outer = tk.Frame(self.root, bg=_BG)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, bg=_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        content = tk.Frame(canvas, bg=_BG, padx=20, pady=12)

        content.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=content, anchor="nw", tags="detail")

        def _resize_detail(event):
            canvas.itemconfig("detail", width=event.width)

        canvas.bind("<Configure>", _resize_detail)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Client info fields
        fields = [
            ("Name", client.get("name", "")),
            ("Website", client.get("website", "")),
            ("Email", client.get("email", "") or "N/A"),
            ("Created", (client.get("createdAt", "") or "")[:10]),
            ("Demo URL", client.get("demoUrl", "")),
        ]
        for label_text, value_text in fields:
            row = tk.Frame(content, bg=_BG, pady=2)
            row.pack(fill=tk.X)
            tk.Label(
                row,
                text=f"{label_text}:",
                width=10,
                anchor="w",
                font=("Helvetica", 11, "bold"),
                fg=_ACCENT,
                bg=_BG,
            ).pack(side=tk.LEFT)
            tk.Label(
                row,
                text=value_text,
                anchor="w",
                wraplength=500,
                font=("Helvetica", 11),
                fg=_TEXT,
                bg=_BG,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Separator
        tk.Frame(content, bg=_BG_INPUT, height=1).pack(fill=tk.X, pady=12)

        # Action buttons
        btn_frame = tk.Frame(content, bg=_BG)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        btn_style = {
            "font": ("Helvetica", 11, "bold"),
            "bd": 0,
            "padx": 14,
            "pady": 6,
            "cursor": "hand2",
        }

        tk.Button(
            btn_frame,
            text="Shorten URL",
            fg=_TEXT_BRIGHT,
            bg=_PURPLE,
            activebackground=_PURPLE_HOVER,
            command=lambda: self._do_shorten_url(client),
            **btn_style,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            btn_frame,
            text="Find Hooks",
            fg=_TEXT_BRIGHT,
            bg=_BG_INPUT,
            activebackground="#1a5276",
            command=lambda: self._do_find_hooks(client),
            **btn_style,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            btn_frame,
            text="Generate Message",
            fg=_TEXT_BRIGHT,
            bg=_ACCENT,
            activebackground=_ACCENT_HOVER,
            command=lambda: self._do_generate_message(client),
            **btn_style,
        ).pack(side=tk.LEFT)

        # Status label
        self._status_label = tk.Label(
            content, text="", font=("Helvetica", 10), fg=_TEXT_DIM, bg=_BG, anchor="w"
        )
        self._status_label.pack(fill=tk.X, pady=(8, 2))

        # Result text area
        self._result_area = tk.Text(
            content,
            font=("Helvetica", 12),
            fg=_TEXT,
            bg=_BG_INPUT,
            insertbackground=_ACCENT,
            selectbackground=_ACCENT,
            bd=0,
            padx=10,
            pady=10,
            wrap=tk.WORD,
            height=10,
        )
        self._result_area.pack(fill=tk.BOTH, expand=True)

        # Copy button
        copy_frame = tk.Frame(content, bg=_BG, pady=6)
        copy_frame.pack(fill=tk.X)

        tk.Button(
            copy_frame,
            text="Copy to Clipboard",
            fg=_TEXT_BRIGHT,
            bg=_PURPLE,
            activebackground=_PURPLE_HOVER,
            command=self._copy_result,
            **btn_style,
        ).pack(side=tk.LEFT)

        self.root.update()

    # ── Action handlers (run in threads) ─────────────────────────

    def _do_shorten_url(self, client: dict):
        demo_url = client.get("demoUrl", "")
        if not demo_url:
            self._show_result("Error", "No demo URL available for this client.")
            return

        if self._short_url:
            self._show_result("Shortened URL", self._short_url)
            return

        self._show_result("Shortening URL...", "Please wait...")

        def do_work():
            try:
                short = shorten_url(demo_url)
                self._short_url = short
                self.root.after(0, lambda: self._show_result("Shortened URL", short))
            except ShortenError as e:
                self.root.after(0, lambda: self._show_result("Error", str(e)))

        threading.Thread(target=do_work, daemon=True).start()

    def _do_find_hooks(self, client: dict):
        website = client.get("website", "")
        if not website:
            self._show_result("Error", "No website URL available for this client.")
            return

        if self._pain_points:
            self._show_result("Business Analysis / Hooks", self._pain_points)
            return

        self._show_result("Analyzing...", "Fetching website and analyzing business...")

        def do_work():
            try:
                analysis = self.analyzer.analyze_business(website)
                self._pain_points = analysis
                self.root.after(
                    0, lambda: self._show_result("Business Analysis / Hooks", analysis)
                )
            except AnalysisError as e:
                self.root.after(0, lambda: self._show_result("Error", str(e)))

        threading.Thread(target=do_work, daemon=True).start()

    def _do_generate_message(self, client: dict):
        self._show_result("Generating...", "Preparing outreach message...")

        def do_work():
            try:
                # Step 1: Ensure short URL
                if not self._short_url:
                    demo_url = client.get("demoUrl", "")
                    if demo_url:
                        try:
                            self._short_url = shorten_url(demo_url)
                        except ShortenError:
                            self._short_url = demo_url

                # Step 2: Ensure pain points
                if not self._pain_points:
                    website = client.get("website", "")
                    if website:
                        self.root.after(
                            0, lambda: self._set_status("Analyzing website first...")
                        )
                        self._pain_points = self.analyzer.analyze_business(website)

                if not self._pain_points:
                    self.root.after(
                        0,
                        lambda: self._show_result(
                            "Error",
                            "Cannot generate message without website analysis. "
                            "Click 'Find Hooks' first.",
                        ),
                    )
                    return

                # Step 3: Generate message
                self.root.after(
                    0, lambda: self._set_status("Generating outreach message...")
                )
                message = self.analyzer.generate_first_message(
                    client_name=client.get("name", ""),
                    pain_points=self._pain_points,
                    short_demo_url=self._short_url or client.get("demoUrl", ""),
                    website_url=client.get("website", ""),
                )
                self._first_message = message
                self.root.after(
                    0, lambda: self._show_result("Generated First Message", message)
                )
            except (AnalysisError, Exception) as e:
                self.root.after(
                    0, lambda: self._show_result("Error", f"Message generation failed: {e}")
                )

        threading.Thread(target=do_work, daemon=True).start()

    # ── UI helpers ───────────────────────────────────────────────

    def _build_header(self, title: str, show_back: bool = False):
        header = tk.Frame(self.root, bg=_BG_HEADER, padx=12, pady=8)
        header.pack(fill=tk.X)

        if show_back:
            back_btn = tk.Button(
                header,
                text="< Back",
                font=("Helvetica", 11),
                fg=_TEXT_DIM,
                bg=_BG_HEADER,
                bd=0,
                activebackground=_ACCENT,
                activeforeground=_TEXT_BRIGHT,
                cursor="hand2",
                command=self._go_back,
            )
            back_btn.pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(
            header, text=title, font=("Helvetica", 14, "bold"), fg=_ACCENT, bg=_BG_HEADER
        ).pack(side=tk.LEFT)

        tk.Button(
            header,
            text="X",
            font=("Helvetica", 12, "bold"),
            fg=_TEXT_DIM,
            bg=_BG_HEADER,
            bd=0,
            activebackground=_ACCENT,
            activeforeground=_TEXT_BRIGHT,
            command=self._close,
        ).pack(side=tk.RIGHT)

    def _show_result(self, label: str, text: str):
        try:
            if hasattr(self, "_status_label") and self._status_label.winfo_exists():
                self._status_label.config(text=label)
            if hasattr(self, "_result_area") and self._result_area.winfo_exists():
                self._result_area.config(state=tk.NORMAL)
                self._result_area.delete("1.0", tk.END)
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
                self._set_status("Copied to clipboard!")
                self.root.after(1500, lambda: self._set_status(""))

    def _go_back(self):
        self._selected_client = None
        self._short_url = None
        self._pain_points = None
        self._first_message = None
        self._show_client_list()

    def _select_client(self, client: dict):
        self._selected_client = client
        self._short_url = None
        self._pain_points = None
        self._first_message = None
        self._show_client_detail(client)

    def _close(self):
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None
        if self.on_close:
            self.on_close()

    # ── Data loading ─────────────────────────────────────────────

    def _load_clients(self):
        try:
            self._clients = self.client_api.fetch_clients()
            self._filtered_clients = list(self._clients)
            self.root.after(0, self._show_client_list)
        except ClientAPIError as e:
            self.root.after(0, lambda: self._show_error(str(e)))

    def _show_error(self, message: str):
        self._clear_content()
        self._build_header("Client Lookup")
        tk.Label(
            self.root,
            text=f"Error: {message}",
            font=("Helvetica", 12),
            fg=_ACCENT,
            bg=_BG,
            wraplength=500,
            pady=30,
        ).pack(expand=True)
        tk.Button(
            self.root,
            text="Retry",
            font=("Helvetica", 12, "bold"),
            fg=_TEXT_BRIGHT,
            bg=_ACCENT,
            activebackground=_ACCENT_HOVER,
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=lambda: self._retry_load(),
        ).pack(pady=10)
        self.root.update()

    def _retry_load(self):
        self._show_loading("Fetching clients...")
        threading.Thread(target=self._load_clients, daemon=True).start()

    def run_loop(self):
        """No-op: main thread's mainloop handles events."""
        pass
