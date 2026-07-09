# -*- coding: utf-8 -*-
"""leo-code Meter · Panel flotante con el consumo de tokens (hoy/semana/mes).

Adaptado de la clase Meter en meter.py de claude-code-meter (MIT). Solo
tkinter (stdlib) — sin Pillow/pystray (esos solo los usan los estilos
barra-de-tareas/bandeja de la referencia, no implementados aqui).
"""
import threading
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont

from leo_code.meter.reader import (
    Reader, load_cfg, save_cfg, sum_period, days_of_week, days_of_month,
    fmt, meter_color,
)

try:
    import ctypes
    from ctypes import wintypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes = None
    wintypes = None

BG = "#161616"
FG = "#e8e8e8"
MUTED = "#8a8a8a"
ACCENT = "#d97757"
TRACK = "#2c2c2c"
GREEN = "#4caf7d"


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.reader = Reader()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=BG)
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem() if ctypes else 96
            self.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        self.f_title = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        self.f_lbl = tkfont.Font(family="Segoe UI", size=8)
        self.f_big = tkfont.Font(family="Segoe UI Semibold", size=13)
        self.f_small = tkfont.Font(family="Segoe UI", size=7)

        self._build()
        self._place_initial()
        self._bind_drag()
        self.refresh(initial=True)

    def _build(self):
        pad = 8
        root = tk.Frame(self, bg=BG, highlightbackground="#333", highlightthickness=1)
        root.pack(fill="both", expand=True)
        self.root_frame = root

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=pad, pady=(pad, 2))
        tk.Label(head, text="●", fg=ACCENT, bg=BG, font=self.f_title).pack(side="left")
        tk.Label(head, text=" leo-code · tokens", fg=FG, bg=BG, font=self.f_title).pack(side="left")
        close = tk.Label(head, text="✕", fg=MUTED, bg=BG, font=self.f_title, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.destroy())
        gear = tk.Label(head, text="⚙", fg=MUTED, bg=BG, font=self.f_title, cursor="hand2")
        gear.pack(side="right", padx=(0, 6))
        gear.bind("<Button-1>", lambda e: self.edit_budget())

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=pad, pady=(2, pad))

        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text="HOY", fg=MUTED, bg=BG, font=self.f_lbl, width=5, anchor="w").pack(side="left")
        self.today_big = tk.Label(row, text="—", fg=FG, bg=BG, font=self.f_big, anchor="w")
        self.today_big.pack(side="left")

        self.week = self._budget_row(body, "SEM")
        self.month = self._budget_row(body, "MES")

    def _budget_row(self, parent, label):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", pady=(6, 0))
        top = tk.Frame(wrap, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text=label, fg=MUTED, bg=BG, font=self.f_lbl, width=5, anchor="w").pack(side="left")
        val = tk.Label(top, text="—", fg=FG, bg=BG, font=self.f_lbl, anchor="w")
        val.pack(side="left")
        pct = tk.Label(top, text="", fg=MUTED, bg=BG, font=self.f_small, anchor="e")
        pct.pack(side="right")
        cv = tk.Canvas(wrap, height=6, bg=TRACK, highlightthickness=0)
        cv.pack(fill="x", pady=(3, 0))
        bar = cv.create_rectangle(0, 0, 0, 6, fill=GREEN, width=0)
        return {"val": val, "pct": pct, "cv": cv, "bar": bar}

    def _set_bar(self, row, used, budget):
        row["val"].config(text=f"{fmt(used)} / {fmt(budget)}")
        frac = 0 if budget <= 0 else min(used / budget, 1.0)
        pct = 0 if budget <= 0 else used / budget * 100
        row["pct"].config(text=f"{pct:.0f}%")
        color = meter_color(pct)
        w = max(row["cv"].winfo_width(), 1)
        row["cv"].coords(row["bar"], 0, 0, int(w * frac), 6)
        row["cv"].itemconfig(row["bar"], fill=color)

    # ---- posicion y arrastre ----
    def _work_area(self):
        try:
            SPI = 0x0030
            r = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(SPI, 0, ctypes.byref(r), 0)
            return r.right, r.bottom
        except Exception:
            return self.winfo_screenwidth(), self.winfo_screenheight()

    def _place_initial(self):
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 230)
        h = self.winfo_reqheight()
        if self.cfg.get("x") is not None and self.cfg.get("y") is not None:
            x, y = self.cfg["x"], self.cfg["y"]
        else:
            rx, ry = self._work_area()
            x, y = rx - w - 8, ry - h - 8
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _bind_drag(self):
        for widget in (self, self.root_frame):
            widget.bind("<Button-1>", self._start)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._end)
        self._dx = self._dy = 0

    def _start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        x = self.winfo_x() + e.x - self._dx
        y = self.winfo_y() + e.y - self._dy
        self.geometry(f"+{x}+{y}")

    def _end(self, e):
        self.cfg["x"], self.cfg["y"] = self.winfo_x(), self.winfo_y()
        save_cfg(self.cfg)

    # ---- edicion de presupuesto ----
    def edit_budget(self):
        win = tk.Toplevel(self)
        win.configure(bg=BG)
        win.title("Presupuesto")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        tk.Label(win, text="Objetivo personal de tokens de leo-code",
                 fg=FG, bg=BG, justify="center", font=self.f_title).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 8))

        def field(r, text, val):
            tk.Label(win, text=text, fg=FG, bg=BG, font=self.f_lbl).grid(
                row=r, column=0, sticky="w", padx=12, pady=4)
            e = tk.Entry(win, width=16, justify="right")
            e.insert(0, str(val))
            e.grid(row=r, column=1, padx=12, pady=4)
            return e

        e_w = field(1, "Semanal", self.cfg["weekly_budget"])
        e_m = field(2, "Mensual", self.cfg["monthly_budget"])
        tk.Label(win, text="Tip: escribe p.ej. 50000000 (=50M)", fg=MUTED, bg=BG,
                 font=self.f_small).grid(row=3, column=0, columnspan=2, padx=12, pady=(0, 4))

        def parse(s):
            s = s.strip().upper().replace(" ", "")
            mult = 1
            if s.endswith("M"):
                mult, s = 1_000_000, s[:-1]
            elif s.endswith("K"):
                mult, s = 1_000, s[:-1]
            elif s.endswith("B"):
                mult, s = 1_000_000_000, s[:-1]
            try:
                return int(float(s) * mult)
            except Exception:
                return None

        def apply():
            wv, mv = parse(e_w.get()), parse(e_m.get())
            if wv:
                self.cfg["weekly_budget"] = wv
            if mv:
                self.cfg["monthly_budget"] = mv
            save_cfg(self.cfg)
            win.destroy()
            self.refresh()

        tk.Button(win, text="Guardar", command=apply).grid(
            row=4, column=0, columnspan=2, pady=(4, 12))

    # ---- refresco ----
    def refresh(self, initial=False):
        def work():
            daily = self.reader.collect()
            today = datetime.now().astimezone().date()
            d = sum_period(daily, [today.isoformat()])
            w = sum_period(daily, days_of_week(today))
            m = sum_period(daily, days_of_month(today))
            self.after(0, lambda: self._render(d, w, m))
        threading.Thread(target=work, daemon=True).start()
        self.after(self.cfg.get("refresh_sec", 60) * 1000, self.refresh)

    def _render(self, d, w, m):
        self.today_big.config(text=fmt(d))
        self.update_idletasks()
        self._set_bar(self.week, w, self.cfg["weekly_budget"])
        self._set_bar(self.month, m, self.cfg["monthly_budget"])


if __name__ == "__main__":
    Panel().mainloop()
