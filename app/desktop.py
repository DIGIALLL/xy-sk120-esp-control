"""XY-SK120 desktop version (pure Python/tkinter, no browser needed).

Run:  python desktop.py [--host xy-sk120.local] [--demo]
Hotkeys: Space - output on/off, Esc - EMERGENCY output off.
"""
import argparse
import asyncio
import ctypes
import math
import queue
import threading
import time
import tkinter as tk
from collections import deque

from core import Controller, DemoController, handle, U_MAX, I_MAX
import i18n
from i18n import tr, trf

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)   # чёткий текст на HiDPI
except Exception:
    pass

C = dict(bg="#0e1318", card="#161d25", card2="#1f2933", line="#2a3541", text="#e8eef4", muted="#8a97a5",
         accent="#4cc2ff", green="#2fbf71", amber="#f5a524", red="#ef5350", sel="#1e4a66")
SERIES = {"u": ("Напряжение", "В", 1, "#4cc2ff"), "i": ("Ток", "А", 2, "#f5a524"), "p": ("Мощность", "Вт", 3, "#c792ea")}
FONT = "Segoe UI"


def mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[k] * t + b[k] * (1 - t)) for k in range(3))


def nice(x):
    """Верх шкалы = 4 круглых шага (1, 2, 2.5, 5 × 10^n), чтобы деления были ровными."""
    if x <= 0:
        return 4.0
    e = math.floor(math.log10(x / 4))
    for k in (e, e + 1):
        for m in (1, 2, 2.5, 5):
            if 4 * m * 10 ** k >= x:
                return 4 * m * 10 ** k
    return 4 * 10 ** (e + 2)


class Bridge(threading.Thread):
    """Ядро (asyncio) в отдельном потоке; GUI общается через очередь и run_coroutine_threadsafe."""

    def __init__(self, host, demo=False):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.loop = asyncio.new_event_loop()
        self.ctl = DemoController(host) if demo else Controller(host)
        self.ctl.keep = True
        self.ctl.sinks.add(self.q.put)
        self.q.put(self.ctl.init_msg())

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self):
        tasks = [asyncio.create_task(self.ctl.esp_loop()), asyncio.create_task(self.ctl.ticker())]
        await self.ctl.stop.wait()
        for t in tasks:
            t.cancel()

    def send(self, m):
        asyncio.run_coroutine_threadsafe(self._safe(m), self.loop)

    async def _safe(self, m):
        try:
            await handle(self.ctl, m)
        except Exception as e:
            await self.ctl.toast(trf("Ошибка команды: {}", e), "err")

    def close(self):
        try:
            asyncio.run_coroutine_threadsafe(self.ctl.shutdown(), self.loop).result(timeout=3)
        except Exception:
            pass


class App:
    def __init__(self, root, bridge):
        self.root, self.br = root, bridge
        self.sc = root.winfo_fpixels("1i") / 96.0
        self.s = {}
        self.conn = False
        self.cfg = {}
        self.presets = []
        self.hist = deque(maxlen=2400)
        self.series = tk.StringVar(value="i")
        self.winmin = tk.IntVar(value=1)
        self.hx = None
        self.toast_job = None
        self.pbtns = []
        self.chems, self.charge, self.cdlg = {}, None, None
        self.last_m = None

        root.title("XY-SK120")
        root.configure(bg=C["bg"])
        root.geometry(f"{self.px(1220)}x{self.px(780)}")
        root.minsize(self.px(1000), self.px(660))
        self.build()
        root.bind("<space>", self.on_space)
        root.bind("<Escape>", lambda e: self.br.send({"cmd": "out", "on": False}))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll()

    def px(self, v):
        return int(v * self.sc)

    # ---------------- виджеты-помощники ----------------
    def card(self, parent, **kw):
        return tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["line"], **kw)

    def lab(self, parent, text="", size=10, bold=False, fg=None, bg=None, **kw):
        return tk.Label(parent, text=text, bg=bg or parent["bg"], fg=fg or C["text"],
                        font=(FONT, size, "bold" if bold else "normal"), **kw)

    def btn(self, parent, text, cmd, bg=None, fg=None, size=10, bold=False, **kw):
        bg = bg or C["card2"]
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg or C["text"], activebackground=mix(C["accent"], bg, 0.25),
                      activeforeground=C["text"], relief="flat", bd=0, cursor="hand2",
                      font=(FONT, size, "bold" if bold else "normal"), **kw)
        b.bind("<Enter>", lambda e: b.config(bg=mix(C["accent"], b.base, 0.18)) if str(b["state"]) != "disabled" else None)
        b.bind("<Leave>", lambda e: b.config(bg=b.base))
        b.base = bg
        return b

    def set_btn_color(self, b, bg):
        b.base = bg
        b.config(bg=bg)

    def entry(self, parent, width=7):
        return tk.Entry(parent, width=width, justify="center", bg=C["card2"], fg=C["text"], insertbackground=C["text"],
                        relief="flat", font=(FONT, 18, "bold"), highlightthickness=1, highlightbackground=C["line"],
                        highlightcolor=C["accent"])

    def radio(self, parent, text, var, value, cmd):
        return tk.Radiobutton(parent, text=text, variable=var, value=value, command=cmd, indicatoron=0, bg=C["card2"],
                              fg=C["text"], selectcolor=C["sel"], activebackground=C["sel"], activeforeground=C["text"],
                              relief="flat", bd=0, padx=self.px(12), pady=self.px(5), font=(FONT, 10), cursor="hand2")

    # ---------------- сборка окна ----------------
    def build(self):
        p = self.px
        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=p(18), pady=p(14))
        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)

        # --- шапка
        head = tk.Frame(main, bg=C["bg"])
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.lab(head, "XY-SK120", 18, True).pack(side="left")
        self.lab(head, tr("  блок питания для ремонта"), 11, fg=C["muted"]).pack(side="left", pady=(p(6), 0))
        right = tk.Frame(head, bg=C["bg"])
        right.pack(side="right")
        self.dot = tk.Canvas(right, width=p(14), height=p(14), bg=C["bg"], highlightthickness=0)
        self.dot.pack(side="left")
        self.dot_id = self.dot.create_oval(2, 2, p(12), p(12), fill=C["red"], outline="")
        self.conn_lbl = self.lab(right, tr("нет связи"), 10, fg=C["muted"])
        self.conn_lbl.pack(side="left", padx=(p(6), p(18)))
        self.uin_lbl = self.lab(right, tr("Uвх  —"), 10, fg=C["muted"])
        self.uin_lbl.pack(side="left", padx=(0, p(18)))
        self.temp_lbl = self.lab(right, "T  —", 10, fg=C["muted"])
        self.temp_lbl.pack(side="left")
        other = "EN" if i18n.get_lang() == "ru" else "RU"
        self.btn(right, other, lambda o=other: self.br.send({"cmd": "config", "lang": o.lower()}), size=9, bold=True,
                 width=4).pack(side="left", padx=(p(18), 0))

        # --- три показания
        reads = tk.Frame(main, bg=C["bg"])
        reads.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(p(12), p(12)))
        self.val = {}
        self.mode_lbl = None
        for k, (title, unit) in enumerate(((tr("НАПРЯЖЕНИЕ"), tr("В")), (tr("ТОК"), tr("А")), (tr("МОЩНОСТЬ"), tr("Вт")))):
            reads.columnconfigure(k, weight=1, uniform="r")
            c = self.card(reads)
            c.grid(row=0, column=k, sticky="ew", padx=(0 if k == 0 else p(12), 0))
            top = tk.Frame(c, bg=C["card"])
            top.pack(fill="x", padx=p(16), pady=(p(10), 0))
            self.lab(top, title, 9, True, C["muted"]).pack(side="left")
            if k == 1:
                self.mode_lbl = self.lab(top, "", 9, True, C["muted"])
                self.mode_lbl.pack(side="right")
            row = tk.Frame(c, bg=C["card"])
            row.pack(fill="x", padx=p(16), pady=(0, p(10)))
            v = self.lab(row, "—", 46, True, C["muted"])
            v.pack(side="left")
            self.lab(row, unit, 16, fg=C["muted"]).pack(side="left", padx=(p(8), 0), pady=(p(14), 0))
            self.val[k] = v

        # --- левая колонка
        left = tk.Frame(main, bg=C["bg"], width=p(400))
        left.grid(row=2, column=0, sticky="ns", padx=(0, p(14)))
        left.grid_propagate(False)
        left.pack_propagate(False)

        self.out_btn = self.btn(left, tr("ВКЛЮЧИТЬ ВЫХОД"), self.toggle, bg=C["card2"], size=15, bold=True, height=2)
        self.out_btn.pack(fill="x", pady=(0, p(12)))

        sp = self.card(left)
        sp.pack(fill="x", pady=(0, p(12)))
        self.lab(sp, tr("УСТАВКИ"), 9, True, C["muted"]).pack(anchor="w", padx=p(14), pady=(p(10), p(4)))
        self.eu = self.setpoint(sp, tr("Напряжение, В"), "u", ((-1, "−1"), (-0.1, "−0.1")), ((0.1, "+0.1"), (1, "+1")))
        self.ei = self.setpoint(sp, tr("Лимит тока, А"), "i", ((-0.1, "−0.1"), (-0.01, "−0.01")), ((0.01, "+0.01"), (0.1, "+0.1")))
        tk.Frame(sp, height=p(6), bg=C["card"]).pack()

        pc = self.card(left)
        pc.pack(fill="x", pady=(0, p(12)))
        ph = tk.Frame(pc, bg=C["card"])
        ph.pack(fill="x", padx=p(14), pady=(p(10), p(6)))
        self.lab(ph, tr("ПРЕСЕТЫ"), 9, True, C["muted"]).pack(side="left")
        tk.Button(ph, text=tr("править"), command=self.edit_presets, bg=C["card"], fg=C["accent"], relief="flat", bd=0,
                  cursor="hand2", font=(FONT, 9), activebackground=C["card"], activeforeground=C["text"]).pack(side="right")
        self.pgrid = tk.Frame(pc, bg=C["card"])
        self.pgrid.pack(fill="x", padx=p(12), pady=(0, p(12)))

        pr = self.card(left)
        pr.pack(fill="x")
        self.lab(pr, tr("ЗАЩИТЫ"), 9, True, C["muted"]).pack(anchor="w", padx=p(14), pady=(p(10), p(2)))
        self.v_short = tk.BooleanVar()
        self.v_exit = tk.BooleanVar()
        self.v_timer = tk.StringVar()
        self.v_tmax = tk.StringVar()
        self.check(pr, tr("Выкл. при КЗ / перегрузке"), self.v_short, "short_off")
        self.check(pr, tr("Выкл. выход при закрытии окна"), self.v_exit, "off_on_exit")
        self.v_hw = tk.BooleanVar()
        self.check(pr, tr("Пороги модуля (OCP/OPP/OTP) под уставки"), self.v_hw, "smart_hw")
        self.spin(pr, tr("Таймер работы, мин (0 — выкл)"), self.v_timer, 0, 600, "timer_min")
        self.spin(pr, tr("Макс. температура, °C"), self.v_tmax, 40, 95, "tmax")
        tk.Frame(pr, height=p(6), bg=C["card"]).pack()
        self.btn(left, tr("Зарядка АКБ…"), self.open_charge, size=11, bold=True).pack(fill="x", pady=(p(12), 0), ipady=p(6))

        # --- правая колонка: график
        cc = self.card(main)
        cc.grid(row=2, column=1, sticky="nsew")
        cc.rowconfigure(1, weight=1)
        cc.columnconfigure(0, weight=1)
        bar = tk.Frame(cc, bg=C["card"])
        bar.grid(row=0, column=0, sticky="ew", padx=p(14), pady=(p(10), p(4)))
        for key in ("i", "u", "p"):
            self.radio(bar, tr(SERIES[key][0]), self.series, key, self.draw).pack(side="left", padx=(0, p(4)))
        tk.Frame(bar, width=p(14), bg=C["card"]).pack(side="left")
        for m in (1, 5, 10):
            self.radio(bar, trf("{} мин", m), self.winmin, m, self.draw).pack(side="left", padx=(0, p(4)))
        self.stats = self.lab(bar, "", 10, fg=C["muted"])
        self.stats.pack(side="right")
        self.cv = tk.Canvas(cc, bg=C["card"], highlightthickness=0, cursor="crosshair")
        self.cv.grid(row=1, column=0, sticky="nsew", padx=p(6), pady=(0, p(6)))
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<Motion>", lambda e: (setattr(self, "hx", e.x), self.draw()))
        self.cv.bind("<Leave>", lambda e: (setattr(self, "hx", None), self.draw()))

        # --- низ
        foot = tk.Frame(main, bg=C["bg"])
        foot.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(p(10), 0))
        self.foot_lbl = self.lab(foot, "", 10, fg=C["muted"])
        self.foot_lbl.pack(side="left")
        self.toast_lbl = self.lab(foot, "", 10, True, C["muted"])
        self.toast_lbl.pack(side="right")

        self.render_presets()

    def setpoint(self, parent, title, key, minus, plus):
        p = self.px
        f = tk.Frame(parent, bg=C["card"])
        f.pack(fill="x", padx=p(14), pady=(p(4), p(4)))
        self.lab(f, title, 9, fg=C["muted"]).pack(anchor="w")
        row = tk.Frame(f, bg=C["card"])
        row.pack(fill="x", pady=(p(2), 0))
        for d, t in minus:
            self.btn(row, t, lambda d=d: self.nudge(key, d), size=9, width=5).pack(side="left", padx=(0, p(3)), ipady=p(4))
        e = self.entry(row)
        e.pack(side="left", fill="x", expand=True, padx=p(3), ipady=p(4))
        for d, t in plus:
            self.btn(row, t, lambda d=d: self.nudge(key, d), size=9, width=5).pack(side="left", padx=(p(3), 0), ipady=p(4))
        e.bind("<Return>", lambda ev, k=key: self.apply_entry(k))
        e.bind("<FocusOut>", lambda ev, k=key: self.apply_entry(k))
        return e

    def check(self, parent, text, var, cfgkey):
        c = tk.Checkbutton(parent, text=text, variable=var, command=lambda: self.br.send({"cmd": "config", cfgkey: bool(var.get())}),
                           bg=C["card"], fg=C["text"], selectcolor=C["card2"], activebackground=C["card"],
                           activeforeground=C["text"], font=(FONT, 10), anchor="w", bd=0, highlightthickness=0)
        c.pack(fill="x", padx=self.px(10))

    def spin(self, parent, text, var, lo, hi, cfgkey):
        f = tk.Frame(parent, bg=C["card"])
        f.pack(fill="x", padx=self.px(14), pady=(self.px(2), 0))
        self.lab(f, text, 10).pack(side="left")
        s = tk.Spinbox(f, from_=lo, to=hi, width=5, textvariable=var, bg=C["card2"], fg=C["text"], buttonbackground=C["card2"],
                       relief="flat", font=(FONT, 10), justify="center", highlightthickness=1, highlightbackground=C["line"],
                       insertbackground=C["text"], command=lambda: self.send_cfg(cfgkey, var))
        s.pack(side="right")
        s.bind("<Return>", lambda e: self.send_cfg(cfgkey, var))
        s.bind("<FocusOut>", lambda e: self.send_cfg(cfgkey, var))

    def send_cfg(self, key, var):
        try:
            self.br.send({"cmd": "config", key: int(float(var.get()))})
        except ValueError:
            pass

    # ---------------- действия ----------------
    def toggle(self):
        if self.conn:
            self.br.send({"cmd": "out", "on": not self.s.get("out")})

    def on_space(self, e):
        if isinstance(self.root.focus_get(), (tk.Entry, tk.Spinbox)):
            return
        self.toggle()

    def nudge(self, key, d):
        cur = self.s.get("set_u" if key == "u" else "set_i")
        if cur is None:
            return
        lim = U_MAX if key == "u" else I_MAX
        v = max(0.0 if key == "u" else 0.01, min(lim, round(cur + d, 3)))
        self.br.send({"cmd": "set", key: v})

    def apply_entry(self, key):
        e = self.eu if key == "u" else self.ei
        try:
            v = float(e.get().replace(",", "."))
        except ValueError:
            self.sync_entries(force=True)
            return
        cur = self.s.get("set_u" if key == "u" else "set_i")
        if cur is None or abs(v - cur) < 1e-6:
            return
        self.br.send({"cmd": "set", key: v})
        self.root.focus_set()

    def sync_entries(self, force=False):
        for e, k, fmt in ((self.eu, "set_u", "{:.2f}"), (self.ei, "set_i", "{:.3f}")):
            v = self.s.get(k)
            if v is None:
                continue
            if force or self.root.focus_get() is not e:
                e.delete(0, "end")
                e.insert(0, fmt.format(v))

    def render_presets(self):
        for w in self.pgrid.winfo_children():
            w.destroy()
        p = self.px
        self.pbtns = []
        for i, pr in enumerate(self.presets):
            b = self.btn(self.pgrid, trf("{:g} В\n{} · {:g} А", pr['u'], pr['name'], pr['i']), lambda i=i: self.br.send({"cmd": "preset", "index": i}),
                         size=10, bold=True, justify="center")
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=p(3), pady=p(3), ipady=p(5))
            self.pgrid.columnconfigure(i % 2, weight=1, uniform="pb")
            self.pbtns.append(b)

    def edit_presets(self):
        p = self.px
        win = tk.Toplevel(self.root)
        win.title(tr("Пресеты"))
        win.configure(bg=C["bg"])
        win.transient(self.root)
        win.grab_set()
        rows = []
        box = tk.Frame(win, bg=C["bg"])
        box.pack(padx=p(18), pady=p(14))
        for j, t in enumerate((tr("Название"), tr("U, В"), tr("Лимит I, А"))):
            self.lab(box, t, 9, True, C["muted"], bg=C["bg"]).grid(row=0, column=j, sticky="w", padx=p(4))

        def add(name="", u="", i=""):
            r = len(rows) + 1
            vs = [tk.StringVar(value=str(name)), tk.StringVar(value=str(u)), tk.StringVar(value=str(i))]
            es = []
            for j, v in enumerate(vs):
                e = tk.Entry(box, textvariable=v, width=18 if j == 0 else 8, bg=C["card2"], fg=C["text"],
                             insertbackground=C["text"], relief="flat", font=(FONT, 12), highlightthickness=1,
                             highlightbackground=C["line"], highlightcolor=C["accent"])
                e.grid(row=r, column=j, padx=p(4), pady=p(3), ipady=p(3))
                es.append(e)
            rows.append((vs, es))

        for pr in self.presets:
            add(pr["name"], f"{pr['u']:g}", f"{pr['i']:g}")

        def save():
            out = []
            for vs, _ in rows:
                try:
                    if vs[0].get().strip():
                        out.append({"name": vs[0].get().strip(), "u": float(vs[1].get().replace(",", ".")),
                                    "i": float(vs[2].get().replace(",", "."))})
                except ValueError:
                    pass
            if out:
                self.br.send({"cmd": "save_presets", "presets": out})
            win.destroy()

        bt = tk.Frame(win, bg=C["bg"])
        bt.pack(pady=(0, p(14)))
        self.btn(bt, tr("+ добавить"), lambda: (add(tr("Новый"), "5", "1"), None) if len(rows) < 8 else None).pack(side="left", padx=p(6), ipadx=p(10), ipady=p(4))
        self.btn(bt, tr("Сохранить"), save, bg=C["green"], bold=True).pack(side="left", padx=p(6), ipadx=p(14), ipady=p(4))
        self.btn(bt, tr("Отмена"), win.destroy).pack(side="left", padx=p(6), ipadx=p(14), ipady=p(4))

    # ---------------- зарядка АКБ ----------------
    def open_charge(self):
        if self.cdlg and self.cdlg.winfo_exists():
            self.cdlg.lift()
            return
        p = self.px
        w = tk.Toplevel(self.root)
        self.cdlg = w
        w.title(tr("Зарядка АКБ"))
        w.configure(bg=C["bg"])
        w.geometry(f"{p(520)}x{p(600)}")
        f = tk.Frame(w, bg=C["bg"])
        f.pack(fill="both", expand=True, padx=p(18), pady=p(14))
        self.lab(f, tr("Зарядка АКБ"), 15, True, bg=C["bg"]).pack(anchor="w")
        names = {k: trf("{} ({} В/банка)", v['name'], v['v']) for k, v in self.chems.items()}
        self.c_names = names
        self.c_chem = tk.StringVar(value=next(iter(names.values()), ""))
        self.c_cells, self.c_i = tk.StringVar(value="1"), tk.StringVar(value="1.0")
        self.c_cut, self.c_max = tk.StringVar(), tk.StringVar(value="600")
        self.c_ok = tk.BooleanVar()

        def row(label, var):
            r = tk.Frame(f, bg=C["bg"])
            r.pack(fill="x", pady=p(4))
            self.lab(r, label, 10, bg=C["bg"]).pack(side="left")
            e = tk.Entry(r, textvariable=var, width=9, justify="center", bg=C["card2"], fg=C["text"],
                         insertbackground=C["text"], relief="flat", font=(FONT, 12), highlightthickness=1,
                         highlightbackground=C["line"], highlightcolor=C["accent"], disabledbackground=C["card"])
            e.pack(side="right")
            return e

        self.lab(f, tr("Тип АКБ"), 10, bg=C["bg"]).pack(anchor="w", pady=(p(8), 0))
        om = tk.OptionMenu(f, self.c_chem, *names.values(), command=lambda _=None: self.c_update_target())
        om.config(bg=C["card2"], fg=C["text"], relief="flat", highlightthickness=0, activebackground=C["sel"],
                  activeforeground=C["text"], font=(FONT, 10), anchor="w")
        om["menu"].config(bg=C["card2"], fg=C["text"], font=(FONT, 10))
        om.pack(fill="x")
        self.c_widgets = [om, row(tr("Банок последовательно (S)"), self.c_cells), row(tr("Ток заряда, А"), self.c_i),
                          row(tr("Отсечка по току, А (пусто = авто)"), self.c_cut), row(tr("Макс. время, мин"), self.c_max)]
        self.c_cells.trace_add("write", lambda *a: self.c_update_target())
        self.c_target = self.lab(f, "", 11, True, C["accent"], bg=C["bg"])
        self.c_target.pack(anchor="w", pady=(p(8), 0))
        tk.Checkbutton(f, text=tr("Тип, число банок и полярность проверены"), variable=self.c_ok, bg=C["bg"], fg=C["text"],
                       selectcolor=C["card2"], activebackground=C["bg"], activeforeground=C["text"], font=(FONT, 10),
                       bd=0, highlightthickness=0).pack(anchor="w", pady=(p(8), 0))
        self.lab(f, tr("Защиты от переполюсовки нет. Li-ion без BMS не заряжать. NiMH не поддерживается."), 9, fg=C["amber"],
                 bg=C["bg"], wraplength=p(470), justify="left").pack(anchor="w", pady=(p(4), p(8)))
        self.c_go = self.btn(f, tr("Начать зарядку"), self.c_toggle, bg=C["green"], fg="white", size=13, bold=True)
        self.c_go.pack(fill="x", ipady=p(8))
        self.c_status = self.lab(f, "", 11, True, C["text"], bg=C["bg"], wraplength=p(470), justify="left")
        self.c_status.pack(anchor="w", pady=(p(14), 0))
        self.c_detail = self.lab(f, "", 10, fg=C["muted"], bg=C["bg"], wraplength=p(470), justify="left")
        self.c_detail.pack(anchor="w", pady=(p(4), 0))
        self.c_update_target()
        self.update_charge()

    def c_chem_key(self):
        cur = self.c_chem.get()
        return next((k for k, v in self.c_names.items() if v == cur), None)

    def c_update_target(self):
        try:
            c = self.chems[self.c_chem_key()]
            n = int(self.c_cells.get() or 1)
            self.c_target.config(text=trf("Цель: {:.2f} В  (предзаряд до {:.2f} В)", c['v'] * n, c['pre'] * n))
        except Exception:
            pass

    def c_toggle(self):
        if self.charge and self.charge.get("active"):
            self.br.send({"cmd": "charge_stop"})
            return
        if not self.c_ok.get():
            self.toast(tr("Подтвердите тип АКБ, число банок и полярность"), "warn")
            return
        try:
            cut = self.c_cut.get().replace(",", ".").strip()
            self.br.send({"cmd": "charge_start", "chem": self.c_chem_key(), "cells": int(self.c_cells.get()),
                          "i": float(self.c_i.get().replace(",", ".")), "cutoff": float(cut) if cut else None,
                          "max_min": int(self.c_max.get()), "confirm": True})
        except ValueError:
            self.toast(tr("Проверьте числа в окне зарядки"), "warn")

    def update_charge(self):
        if not (self.cdlg and self.cdlg.winfo_exists()):
            return
        ch, act = self.charge, bool(self.charge and self.charge.get("active"))
        self.c_go.config(text=tr("Остановить зарядку") if act else tr("Начать зарядку"), state="normal" if self.conn else "disabled")
        self.set_btn_color(self.c_go, C["red"] if act else C["green"])
        for wdg in self.c_widgets:
            wdg.config(state="disabled" if act else "normal")
        if not ch:
            self.c_status.config(text="")
            self.c_detail.config(text="")
            return
        ph = {"pre": tr("Предзаряд"), "cc": tr("Основной заряд (CC)"), "cv": tr("Добор (CV)"), "done": tr("Заряд завершён"), "stopped": tr("Остановлено")}
        e = int(ch["elapsed"])
        self.c_status.config(text=f"{ph.get(ch['phase'], ch['phase'])}: {ch['msg']}",
                             fg=C["green"] if ch["phase"] == "done" else C["red"] if ch["phase"] == "stopped" else C["text"])
        self.c_detail.config(text=trf("{:02d}:{:02d} · {:.3f} Ач · {:.2f} Втч", e // 60, e % 60, ch["ah"], ch["wh"]) + "\n"
                                  + trf("цель {} В, ток {} А, отсечка {} А", ch["target"], ch["i"], ch["cutoff"]))

    def on_close(self):
        self.br.close()
        self.root.destroy()

    # ---------------- обновление ----------------
    def poll(self):
        try:
            while True:
                self.handle_msg(self.br.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def handle_msg(self, m):
        t = m.get("type")
        if t == "init":
            self.cfg, self.presets = m["cfg"], m["presets"]
            self.chems, self.charge = m.get("chems", {}), m.get("charge")
            self.hist.extend(m["history"])
            self.apply_cfg()
            self.render_presets()
        elif t == "state":
            self.conn, self.s = m["conn"], m["s"]
            self.charge = m.get("charge")
            if m["sample"]:
                self.hist.append(m["sample"])
            self.last_m = m
            self.update_state(m)
        elif t == "presets":
            self.presets = m["presets"]
            self.render_presets()
        elif t == "cfg":
            old = self.cfg.get("lang")
            self.cfg = m["cfg"]
            if m.get("presets") is not None:
                self.presets = m["presets"]
            if m.get("chems"):
                self.chems = m["chems"]
            if self.cfg.get("lang") != old:
                i18n.set_lang(self.cfg.get("lang"))
                self.rebuild()
            else:
                self.apply_cfg()
        elif t == "history":
            self.hist.clear()
            self.hist.extend(m["history"])
        elif t == "toast":
            self.toast(m["msg"], m["level"])

    def rebuild(self):
        """Rebuild all widgets after a language switch."""
        if self.cdlg and self.cdlg.winfo_exists():
            self.cdlg.destroy()
        self.cdlg = None
        for w in self.root.winfo_children():
            w.destroy()
        self.build()
        self.apply_cfg()
        if self.last_m:
            self.update_state(self.last_m)

    def apply_cfg(self):
        self.v_short.set(bool(self.cfg.get("short_off")))
        self.v_exit.set(bool(self.cfg.get("off_on_exit")))
        self.v_hw.set(bool(self.cfg.get("smart_hw")))
        if self.root.focus_get() is None or not isinstance(self.root.focus_get(), tk.Spinbox):
            self.v_timer.set(str(self.cfg.get("timer_min", 0)))
            self.v_tmax.set(str(self.cfg.get("tmax", 75)))

    def toast(self, msg, level):
        col = {"ok": C["green"], "warn": C["amber"], "err": C["red"]}.get(level, C["accent"])
        self.toast_lbl.config(text=msg, fg=col)
        if self.toast_job:
            self.root.after_cancel(self.toast_job)
        self.toast_job = self.root.after(9000, lambda: self.toast_lbl.config(text=""))

    def update_state(self, m):
        s, on = self.s, bool(self.s.get("out"))
        self.dot.itemconfig(self.dot_id, fill=C["green"] if self.conn else C["red"])
        self.conn_lbl.config(text=tr("ESP подключена") if self.conn else tr("нет связи с ESP"))
        self.uin_lbl.config(text=tr("Uвх  %.2f В") % s["uin"] if s.get("uin") is not None else tr("Uвх  —"))
        self.temp_lbl.config(text="T  %.1f °C" % s["temp"] if s.get("temp") is not None else "T  —")
        cc = bool(s.get("cc")) and on
        bright = C["text"] if on else C["muted"]
        for k, key, fmt, col in ((0, "uout", "{:.2f}", bright), (1, "iout", "{:.3f}", C["amber"] if cc else bright),
                                 (2, "pout", "{:.1f}", bright)):
            v = s.get(key)
            self.val[k].config(text="—" if v is None else fmt.format(v), fg=col)
        self.mode_lbl.config(text=(tr("ограничение тока (CC)") if cc else tr("стабилизация напряжения (CV)")) if on else tr("выход выключен"),
                             fg=C["amber"] if cc else (C["green"] if on else C["muted"]))
        if on:
            self.out_btn.config(text=tr("ВЫХОД ВКЛЮЧЁН\nнажмите, чтобы выключить"), fg="white", state="normal")
            self.set_btn_color(self.out_btn, C["green"])
        else:
            self.out_btn.config(text=tr("ВКЛЮЧИТЬ ВЫХОД"), fg=C["text"], state="normal" if self.conn else "disabled")
            self.set_btn_color(self.out_btn, C["card2"])
        self.sync_entries()
        self.update_charge()
        ft = []
        if s.get("wh") is not None:
            ft.append(tr("%.3f Втч") % s["wh"])
        if s.get("ah") is not None:
            ft.append(tr("%.3f Ач") % s["ah"])
        if on and m.get("out_for"):
            ft.append(tr("работает %02d:%02d") % divmod(int(m["out_for"]), 60))
        if m.get("log"):
            ft.append(tr("лог: logs/") + m["log"])
        if s.get("prot"):
            ft.append(tr("ЗАЩИТА МОДУЛЯ, код %d") % int(s["prot"]))
        self.foot_lbl.config(text="   ·   ".join(ft))
        self.draw()

    # ---------------- график ----------------
    def draw(self):
        cv, p = self.cv, self.px
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 120 or H < 100:
            return
        pl, pr, pt, pb = p(58), p(16), p(14), p(28)
        pw, ph = W - pl - pr, H - pt - pb
        name, unit, idx, col = SERIES[self.series.get()]
        name, unit = tr(name), tr(unit)
        win = self.winmin.get() * 60
        now = time.time()
        pts = [q for q in self.hist if q[0] >= now - win]
        vals = [q[idx] for q in pts]
        floor = {"i": 0.5, "u": 5.0, "p": 5.0}[self.series.get()]
        top = nice(max(max(vals) * 1.15 if vals else 0, floor))
        for k in range(5):
            y = pt + ph * k / 4
            cv.create_line(pl, y, pl + pw, y, fill=C["line"])
            v = top * (1 - k / 4)
            cv.create_text(pl - p(8), y, text=("%.0f" if top >= 10 else "%.1f" if top >= 2 else "%.2f") % v,
                           anchor="e", fill=C["muted"], font=(FONT, 9))
        for k in range(5):
            x = pl + pw * k / 4
            sec = int(win * (1 - k / 4))
            cv.create_text(x, pt + ph + p(14), text=tr("сейчас") if sec == 0 else "−%d:%02d" % divmod(sec, 60),
                           fill=C["muted"], font=(FONT, 9), anchor="n" if 0 < k < 4 else ("nw" if k == 0 else "ne"))
        cv.create_text(pl, p(2), text=f"{name}, {unit}", anchor="nw", fill=C["muted"], font=(FONT, 9))
        if len(pts) >= 2:
            xy = []
            for q in pts:
                xy += [pl + (q[0] - (now - win)) / win * pw, pt + ph - min(q[idx], top) / top * ph]
            cv.create_polygon([xy[0], pt + ph] + xy + [xy[-2], pt + ph], fill=mix(col, C["card"], 0.16), outline="")
            cv.create_line(*xy, fill=col, width=max(2, p(2)), smooth=False)
            mn, mx, av = min(vals), max(vals), sum(vals) / len(vals)
            self.stats.config(text=trf("мин {:.3g}   макс {:.3g}   средн. {:.3g} {}", mn, mx, av, unit))
        else:
            self.stats.config(text="")
            cv.create_text(pl + pw / 2, pt + ph / 2, text=tr("нет данных"), fill=C["muted"], font=(FONT, 12))
        if self.hx is not None and len(pts) >= 2 and pl <= self.hx <= pl + pw:
            t = now - win + (self.hx - pl) / pw * win
            q = min(pts, key=lambda a: abs(a[0] - t))
            x = pl + (q[0] - (now - win)) / win * pw
            y = pt + ph - min(q[idx], top) / top * ph
            cv.create_line(x, pt, x, pt + ph, fill=C["muted"], dash=(3, 3))
            cv.create_oval(x - 4, y - 4, x + 4, y + 4, fill=col, outline=C["card"], width=2)
            txt = tr("%s   U %.2f В  I %.3f А  P %.1f Вт") % (time.strftime("%H:%M:%S", time.localtime(q[0])), q[1], q[2], q[3])
            bx = min(max(x - p(150), pl), pl + pw - p(300))
            cv.create_rectangle(bx, pt, bx + p(300), pt + p(24), fill=C["card2"], outline=C["line"])
            cv.create_text(bx + p(8), pt + p(12), text=txt, anchor="w", fill=C["text"], font=(FONT, 9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None)
    ap.add_argument("--demo", action="store_true", help="simulated module, no hardware needed")
    a = ap.parse_args()
    br = Bridge(a.host, a.demo)
    br.start()
    root = tk.Tk()
    App(root, br)
    root.mainloop()


if __name__ == "__main__":
    main()
