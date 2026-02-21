"""Client Lookup Window — browse demo clients, analyze websites, generate outreach."""

import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
import urllib.parse
import webbrowser

import pyperclip

from config import SERVICE_ACCOUNT_PATH
from services.client_api import ClientAPI, ClientAPIError
from services.sheets_service import SheetsService, SheetsServiceError, normalize_url
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
_RED        = "#FF3B30"   # Error / destructive


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

        self.client_api  = ClientAPI()
        self.analyzer    = ClientAnalyzer()
        self.sheets_svc  = SheetsService(SERVICE_ACCOUNT_PATH)

        self._clients          = []
        self._filtered_clients = []
        self._selected_client  = None
        self._short_url        = None
        self._pain_points      = None
        self._first_message    = None

        # Sheet filter state
        self._sheet_list            = None    # None = not loaded yet
        self._sheet_map: dict       = {}      # name → spreadsheet id
        self._allowed_websites      = None    # None = no filter; set = active
        self._selected_sheet_name   = ""

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

        # ── Sheet filter row ──────────────────────────────────────
        sheet_row = tk.Frame(bar, bg=_BG_WHITE)
        sheet_row.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(sheet_row, text="Sheet filter:", font=("Helvetica Neue", 12),
                 fg=_TEXT_SEC, bg=_BG_WHITE).pack(side=tk.LEFT, padx=(0, 8))

        if self._sheet_list is None:
            # Sheets not loaded yet — show placeholder, kick off background load
            sheet_opts = ["Loading sheets…"]
            sheet_init = "Loading sheets…"
            sheet_state = tk.DISABLED
            threading.Thread(target=self._load_sheet_list, daemon=True).start()
        elif not self._sheet_list:
            sheet_opts = ["No sheets found"]
            sheet_init = "No sheets found"
            sheet_state = tk.DISABLED
        else:
            sheet_opts = ["No sheet filter"] + [s["name"] for s in self._sheet_list]
            sheet_init = self._selected_sheet_name or "No sheet filter"
            sheet_state = tk.NORMAL

        self._sheet_var = tk.StringVar(value=sheet_init)
        self._sheet_menu = tk.OptionMenu(
            sheet_row, self._sheet_var, *sheet_opts,
            command=self._on_sheet_selected,
        )
        self._sheet_menu.configure(
            font=("Helvetica Neue", 12), fg=_TEXT, bg=_BG_WHITE,
            activebackground=_HOVER_ROW, activeforeground=_TEXT,
            bd=0, relief=tk.FLAT, cursor="hand2",
            highlightthickness=0, width=36,
            state=sheet_state,
        )
        self._sheet_menu.pack(side=tk.LEFT)

        # Clear-filter button (only shown when a sheet filter is active)
        if self._allowed_websites is not None:
            self._make_btn(
                sheet_row, "✕ Clear filter",
                self._clear_sheet_filter, "ghost",
            ).pack(side=tk.LEFT, padx=(8, 0))

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
        self.root.after(80, self._bring_to_front)

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

        # Apply sheet filter: keep only clients whose website is in the allowed set
        if self._allowed_websites is not None:
            self._filtered_clients = [
                c for c in self._filtered_clients
                if normalize_url(c.get("website", "")) in self._allowed_websites
            ]
            suffix = "  ·  sheet filter active"
        else:
            suffix = ""

        self._count_label.config(
            text=f"{len(self._filtered_clients)} of {len(self._clients)} clients{suffix}"
        )
        self._populate_list()

    # ── View 2 — Client detail ───────────────────────────────────

    def _show_client_detail(self, client: dict):
        self._clear()
        self._btns = {}   # reset button refs from any previous detail view

        name = client.get("name", "Client")
        self.root.title(f"Client Lookup — {name}")
        self._build_header(name[:46] + ("…" if len(name) > 46 else ""), show_back=True)
        _sep(self.root)

        # ── Pinned bottom bar — always visible regardless of scroll ───
        # Must be packed BEFORE the expanding canvas so pack gives it priority.
        bottom_bar = tk.Frame(self.root, bg=_BG)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Frame(bottom_bar, bg=_SEP, height=1).pack(fill=tk.X)
        copy_inner = tk.Frame(bottom_bar, bg=_BG)
        copy_inner.pack(fill=tk.X, padx=20, pady=12)
        self._make_btn(copy_inner, "Copy to Clipboard",
                       self._copy_result, "secondary").pack(side=tk.LEFT)

        # ── Scrollable content (fills remaining space) ─────────────
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

        def _dscroll(delta):
            try:
                canvas.yview_scroll(delta, "units")
            except tk.TclError:
                pass

        canvas.bind_all("<MouseWheel>",
                        lambda e: _dscroll(-1 * (e.delta // 120 or
                                                 (-1 if e.delta < 0 else 1))))
        canvas.bind_all("<Button-4>", lambda e: _dscroll(-3))
        canvas.bind_all("<Button-5>", lambda e: _dscroll(3))

        # ── Info card ─────────────────────────────────────────────
        card = tk.Frame(content, bg=_BG_WHITE)
        card.pack(fill=tk.X, padx=20, pady=(20, 0))

        website  = client.get("website", "") or ""
        email    = client.get("email",   "") or "—"
        created  = (client.get("createdAt", "") or "")[:10] or "—"
        demo_raw = client.get("demoUrl", "") or ""
        # Decode percent-encoding (e.g. %3A → :) and truncate for readability
        demo_display = urllib.parse.unquote(demo_raw)
        if len(demo_display) > 72:
            demo_display = demo_display[:69] + "…"

        rows_data = [
            ("Website",  website or "—",                     bool(website)),
            ("Email",    email,                               False),
            ("Created",  created,                             False),
            ("Demo URL", demo_display if demo_raw else "—",  False),
        ]
        for i, (lbl, val, clickable) in enumerate(rows_data):
            if i:
                tk.Frame(card, bg=_SEP, height=1).pack(fill=tk.X, padx=16)
            row = tk.Frame(card, bg=_BG_WHITE)
            row.pack(fill=tk.X, padx=16)
            tk.Label(row, text=lbl, width=9, anchor="w",
                     font=("Helvetica Neue", 12), fg=_TEXT_SEC,
                     bg=_BG_WHITE).pack(side=tk.LEFT, pady=11)
            if clickable:
                url_to_open = val if val.startswith("http") else f"https://{val}"
                lk = tk.Label(row, text=val, anchor="w",
                              font=("Helvetica Neue", 12), fg=_ACCENT,
                              bg=_BG_WHITE, cursor="hand2")
                lk.bind("<Button-1>",
                        lambda e, u=url_to_open: webbrowser.open(u))
                lk.bind("<Enter>",
                        lambda e, lb=lk: lb.config(
                            font=("Helvetica Neue", 12, "underline")))
                lk.bind("<Leave>",
                        lambda e, lb=lk: lb.config(
                            font=("Helvetica Neue", 12)))
                lk.pack(side=tk.LEFT, fill=tk.X, expand=True,
                        pady=11, padx=(10, 0))
            else:
                tk.Label(row, text=val, anchor="w", wraplength=480,
                         font=("Helvetica Neue", 12), fg=_TEXT,
                         bg=_BG_WHITE).pack(side=tk.LEFT, fill=tk.X,
                                            expand=True, pady=11, padx=(10, 0))

        # ── Action buttons ────────────────────────────────────────
        btn_row = tk.Frame(content, bg=_BG)
        btn_row.pack(fill=tk.X, padx=20, pady=20)

        self._make_btn(btn_row, "Shorten URL",
                       lambda: self._do_shorten_url(client), "secondary",
                       tag="shorten").pack(side=tk.LEFT, padx=(0, 8))
        self._make_btn(btn_row, "Find Hooks",
                       lambda: self._do_find_hooks(client), "secondary",
                       tag="hooks").pack(side=tk.LEFT, padx=(0, 8))
        self._make_btn(btn_row, "Generate Message",
                       lambda: self._do_generate_message(client), "primary",
                       tag="generate").pack(side=tk.LEFT)

        # ── Status label ──────────────────────────────────────────
        self._status_label = tk.Label(content, text="",
                                      font=("Helvetica Neue", 11),
                                      fg=_TEXT_SEC, bg=_BG, anchor="w")
        self._status_label.pack(fill=tk.X, padx=20, pady=(0, 4))

        # ── Result text area (1px border, fills remaining space) ──
        self._result_border = tk.Frame(content, bg=_SEP)
        self._result_border.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))
        self._result_area = tk.Text(
            self._result_border,
            font=("Helvetica Neue", 13), fg=_TEXT, bg=_BG_WHITE,
            insertbackground=_ACCENT, selectbackground=_ACCENT,
            selectforeground=_TEXT_BTN, bd=0, padx=14, pady=12,
            wrap=tk.WORD, relief=tk.FLAT, height=7,
        )
        self._result_area.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.root.update()

    # ── Button factory ───────────────────────────────────────────

    def _make_btn(self, parent, text: str, command, style: str = "secondary",
                  tag: str = None):
        """Return a styled button wrapper frame.

        Pass tag= to store a reference in self._btns[tag] so the button
        text/state can be updated from action handlers (e.g. loading states).
        """
        cfg = {
            "primary":   (_ACCENT,    _TEXT_BTN, _ACCENT_DIM),
            "secondary": ("#E9E9EE",  _TEXT,     "#D8D8DE"),
            "ghost":     ("#E9E9EE",  _ACCENT,   "#D8D8DE"),
        }.get(style, ("#E9E9EE", _TEXT, "#D8D8DE"))
        bg, fg, hover = cfg

        font = ("Helvetica Neue", 13, "bold") if style == "primary" else ("Helvetica Neue", 13)

        wrap = tk.Frame(parent, bg=parent.cget("bg"))
        btn = tk.Button(
            wrap, text=text,
            font=font, fg=fg, bg=bg,
            activebackground=hover, activeforeground=fg,
            bd=0, padx=20, pady=9, cursor="hand2",
            relief=tk.FLAT, command=command,
        )
        btn.pack()
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))

        if tag is not None:
            if not hasattr(self, "_btns"):
                self._btns = {}
            self._btns[tag] = btn

        return wrap

    # ── Header ───────────────────────────────────────────────────

    def _build_header(self, title: str, show_back: bool = False):
        hdr = tk.Frame(self.root, bg=_BG_WHITE, height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        if show_back:
            tk.Button(hdr, text="← Back",
                      font=("Helvetica Neue", 13), fg=_ACCENT,
                      bg=_BG_WHITE, bd=0, relief=tk.FLAT,
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

    def _show_result(self, status: str, text: str, error: bool = False):
        try:
            color = _RED if error else _TEXT_SEC
            if hasattr(self, "_status_label") and self._status_label.winfo_exists():
                self._status_label.config(text=status, fg=color)
            if hasattr(self, "_result_border") and self._result_border.winfo_exists():
                self._result_border.config(bg=_RED if error else _SEP)
            if hasattr(self, "_result_area") and self._result_area.winfo_exists():
                self._result_area.config(
                    state=tk.NORMAL,
                    fg=_RED if error else _TEXT,
                )
                self._result_area.delete("1.0", tk.END)
                if text:
                    self._result_area.insert("1.0", text)
            self.root.update()
        except tk.TclError:
            pass

    def _set_status(self, text: str, error: bool = False):
        try:
            if hasattr(self, "_status_label") and self._status_label.winfo_exists():
                self._status_label.config(text=text,
                                          fg=_RED if error else _TEXT_SEC)
            self.root.update()
        except tk.TclError:
            pass

    def _copy_result(self):
        if hasattr(self, "_result_area"):
            text = self._result_area.get("1.0", tk.END).strip()
            if text:
                pyperclip.copy(text)
                self._set_status("✓  Copied to clipboard")
                self.root.after(2000, lambda: self._set_status(""))

    def _set_btn_loading(self, tag: str, label: str):
        """Disable a tagged button and show a loading label."""
        btn = getattr(self, "_btns", {}).get(tag)
        if btn:
            try:
                btn.config(text=label, state=tk.DISABLED, cursor="")
            except tk.TclError:
                pass

    def _set_btn_ready(self, tag: str, label: str):
        """Re-enable a tagged button with its original label."""
        btn = getattr(self, "_btns", {}).get(tag)
        if btn:
            try:
                btn.config(text=label, state=tk.NORMAL, cursor="hand2")
            except tk.TclError:
                pass

    # ── Sheet filter ─────────────────────────────────────────────

    def _load_sheet_list(self):
        """Background: fetch list of 'Проверенные лиды' sheets from Drive."""
        try:
            sheets = self.sheets_svc.list_sheets()
        except SheetsServiceError as exc:
            logger.error("Could not load sheets: %s", exc)
            sheets = []

        self._sheet_list = sheets
        self._sheet_map  = {s["name"]: s["id"] for s in sheets}

        if self.root:
            self.root.after(0, self._update_sheet_dropdown)

    def _update_sheet_dropdown(self):
        """Main thread: rebuild the OptionMenu after sheets have loaded."""
        if not hasattr(self, "_sheet_menu"):
            return
        try:
            if not self._sheet_menu.winfo_exists():
                return
        except tk.TclError:
            return

        if not self._sheet_list:
            self._sheet_var.set("No sheets found")
            self._sheet_menu.configure(state=tk.DISABLED)
            return

        opts = ["No sheet filter"] + [s["name"] for s in self._sheet_list]
        menu = self._sheet_menu["menu"]
        menu.delete(0, "end")
        for opt in opts:
            menu.add_command(
                label=opt,
                command=lambda v=opt: (self._sheet_var.set(v),
                                       self._on_sheet_selected(v)),
            )
        self._sheet_menu.configure(state=tk.NORMAL)
        self._sheet_var.set(self._selected_sheet_name or "No sheet filter")

    def _on_sheet_selected(self, value: str):
        """Called when the user picks a sheet from the dropdown."""
        self._selected_sheet_name = value

        if value in ("No sheet filter", "No sheets found", "Loading sheets…"):
            self._clear_sheet_filter()
            return

        sheet_id = self._sheet_map.get(value)
        if not sheet_id:
            return

        # Disable UI while loading
        try:
            self._sheet_menu.configure(state=tk.DISABLED)
        except tk.TclError:
            pass
        try:
            self._count_label.config(text="Loading sheet…")
        except tk.TclError:
            pass

        def work():
            try:
                allowed = self.sheets_svc.get_allowed_websites(sheet_id)
            except SheetsServiceError as exc:
                logger.error("Sheet load failed: %s", exc)
                allowed = set()
            self._allowed_websites = allowed
            if self.root:
                self.root.after(0, self._after_sheet_load)

        threading.Thread(target=work, daemon=True).start()

    def _after_sheet_load(self):
        """Main thread: re-enable UI and re-filter after sheet websites loaded."""
        try:
            self._sheet_menu.configure(state=tk.NORMAL)
        except tk.TclError:
            pass
        self._apply_filters()
        # Rebuild the list view so the ✕ Clear filter button appears
        self._show_client_list()

    def _clear_sheet_filter(self):
        """Remove the active sheet filter and show all clients."""
        self._allowed_websites    = None
        self._selected_sheet_name = ""
        self._apply_filters()
        # Rebuild to remove the ✕ Clear filter button
        self._show_client_list()

    # ── Navigation ───────────────────────────────────────────────

    def _go_back(self):
        self.root.title("Client Lookup")
        self._selected_client = None
        self._short_url = self._pain_points = self._first_message = None
        self._show_client_list()

    def _select_client(self, client: dict):
        self._selected_client = client
        self._short_url = self._pain_points = self._first_message = None
        self._show_client_detail(client)

    def _bring_to_front(self):
        """Lift the window above all others and activate the app (macOS fix)."""
        if not self.root:
            return
        self.root.lift()
        self.root.focus_force()
        if sys.platform == "darwin":
            # On macOS a background Python process won't auto-activate even with
            # -topmost True.  AppleScript activates the process by PID so the
            # window pops in front of whatever app had focus (e.g. Chrome).
            subprocess.run(
                [
                    "osascript", "-e",
                    f'tell application "System Events" to set frontmost of'
                    f' (first process whose unix id is {os.getpid()}) to true',
                ],
                check=False,
            )

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
            self._show_result("No demo URL",
                              "This client has no demo URL to shorten.", error=True)
            return
        if self._short_url:
            self._show_result("Shortened URL", self._short_url)
            return
        self._set_btn_loading("shorten", "Shortening…")
        self._show_result("Shortening URL…", "")

        def work():
            try:
                s = shorten_url(demo_url)
                self._short_url = s
                self.root.after(0, lambda: (
                    self._set_btn_ready("shorten", "Shorten URL"),
                    self._show_result("Shortened URL", s),
                ))
            except ShortenError as e:
                err = str(e)
                self.root.after(0, lambda: (
                    self._set_btn_ready("shorten", "Shorten URL"),
                    self._show_result("Error", err, error=True),
                ))

        threading.Thread(target=work, daemon=True).start()

    def _do_find_hooks(self, client: dict):
        website = client.get("website", "")
        if not website:
            self._show_result("No website",
                              "This client has no website URL.", error=True)
            return
        if self._pain_points:
            self._show_result("Business Analysis", self._pain_points)
            return
        self._set_btn_loading("hooks", "Analyzing…")
        self._show_result("Analyzing website…", "Fetching content…")

        def work():
            try:
                a = self.analyzer.analyze_business(website)
                self._pain_points = a
                self.root.after(0, lambda: (
                    self._set_btn_ready("hooks", "Find Hooks"),
                    self._show_result("Business Analysis", a),
                ))
            except AnalysisError as e:
                err = str(e)
                self.root.after(0, lambda: (
                    self._set_btn_ready("hooks", "Find Hooks"),
                    self._show_result("Error", err, error=True),
                ))

        threading.Thread(target=work, daemon=True).start()

    def _do_generate_message(self, client: dict):
        self._set_btn_loading("generate", "Generating…")
        self._show_result("Generating…", "")

        def work():
            try:
                # Step 1: shorten URL if not already done
                if not self._short_url:
                    demo_url = client.get("demoUrl", "")
                    if demo_url:
                        self.root.after(0, lambda: self._set_status(
                            "Step 1/3 — Shortening demo URL…"))
                        try:
                            self._short_url = shorten_url(demo_url)
                        except ShortenError:
                            self._short_url = demo_url

                # Step 2: analyze website if not already done
                if not self._pain_points:
                    site = client.get("website", "")
                    if site:
                        self.root.after(0, lambda: self._set_status(
                            "Step 2/3 — Analyzing website…"))
                        self._pain_points = self.analyzer.analyze_business(site)

                if not self._pain_points:
                    self.root.after(0, lambda: (
                        self._set_btn_ready("generate", "Generate Message"),
                        self._show_result(
                            "Missing data",
                            "Could not analyze the website. Try 'Find Hooks' first.",
                            error=True,
                        ),
                    ))
                    return

                # Step 3: generate outreach message
                self.root.after(0, lambda: self._set_status(
                    "Step 3/3 — Writing outreach message…"))
                msg = self.analyzer.generate_first_message(
                    client_name=client.get("name", ""),
                    pain_points=self._pain_points,
                    short_demo_url=self._short_url or client.get("demoUrl", ""),
                    website_url=client.get("website", ""),
                )
                self._first_message = msg
                self.root.after(0, lambda: (
                    self._set_btn_ready("generate", "Generate Message"),
                    self._show_result("Outreach Message", msg),
                ))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: (
                    self._set_btn_ready("generate", "Generate Message"),
                    self._show_result("Error", err, error=True),
                ))

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
