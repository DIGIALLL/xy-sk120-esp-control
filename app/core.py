"""XY-SK120 control core: ESP link (ESPHome native API), protections, history, CSV log, presets,
battery charger. Shared by the web version (server.py) and the desktop version (desktop.py).
"""
import asyncio
import csv
import json
import os
import random
import time
from collections import deque
from pathlib import Path

import aioesphomeapi
import i18n
from i18n import tr, trf

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
LOG_DIR = ROOT / "logs"
CFG_PATH = ROOT / "config.json"
PRESETS_PATH = ROOT / "presets.json"

U_MAX, I_MAX = 36.0, 6.0

FIELDS = {
    "Output Voltage": "uout", "Output Current": "iout", "Output Power": "pout", "Input Voltage": "uin",
    "Temperature": "temp", "Energy Wh": "wh", "Charge Ah": "ah",
    "CC Mode": "cc", "Output": "out", "Set Voltage": "set_u", "Set Current": "set_i",
    "Protection code": "prot", "FW version": "fw", "Model code": "model",
    "Temp ext": "temp_ext", "M0 OCP": "hw_ocp", "M0 OPP": "hw_opp", "M0 OTP": "hw_otp",
}
BOOLS = {"cc", "out"}

DEFAULT_CFG = {
    "esp_host": "xy-sk120.local",   # IP address also works
    "short_off": True,       # авто-выкл при КЗ
    "timer_min": 0,          # авто-выкл через N минут работы (0 = выкл)
    "tmax": 75,              # авто-выкл при температуре модуля выше, °C
    "off_on_exit": True,     # выключать выход при закрытии приложения
    "smart_hw": True,        # подстраивать аппаратные пороги OCP/OPP/OTP модуля под уставки
    "lang": i18n.detect(),   # "ru" | "en"
}
DEFAULT_PRESETS = [
    {"name": "USB / платы", "u": 5.0, "i": 1.0},
    {"name": "Зарядки QC", "u": 9.0, "i": 1.0},
    {"name": "Вентиляторы, LED", "u": 12.0, "i": 1.0},
    {"name": "Ноутбук", "u": 19.0, "i": 1.0},
    {"name": "Ноутбук (20 В)", "u": 20.0, "i": 1.0},
]


CHEMS = {
    "liion":   {"name": "Li-ion / Li-Po", "v": 4.20, "pre": 3.00},
    "lifepo4": {"name": "LiFePO4", "v": 3.65, "pre": 2.50},
    "pb":      {"name": "Свинцовый (AGM/гель/кислота), банок по 2 В", "v": 2.40, "pre": 1.90},
}


def hw_limits(u, i, tmax):
    """Пороги модуля под уставки: OCP/OPP с запасом, OTP на 5 °C выше программного порога."""
    ocp = min(6.2, max(0.3, round(i * 1.25 + 0.15, 3)))
    opp = min(125.0, max(5.0, round(u * i * 1.25 + 3, 1)))
    otp = min(95, max(40, int(tmax) + 5))
    return ocp, opp, otp


def load_api_key():
    """API encryption key, first match wins:
    1) env XY_API_KEY; 2) file named in env XY_ENV_FILE (line ESP_API_KEY=...); 3) api_key.txt next to this script."""
    k = os.environ.get("XY_API_KEY")
    if k:
        return k.strip()
    envf = os.environ.get("XY_ENV_FILE")
    if envf:
        try:
            for line in Path(envf).read_text(encoding="utf-8").splitlines():
                if line.startswith("ESP_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"') or None
        except OSError:
            pass
    try:
        return (ROOT / "api_key.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return json.loads(json.dumps(default))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Controller:
    def __init__(self, host, paths=None):
        self.cfg_path, self.presets_path = paths or (CFG_PATH, PRESETS_PATH)
        self.cfg = {**DEFAULT_CFG, **load_json(self.cfg_path, DEFAULT_CFG)}
        if host:
            self.cfg["esp_host"] = host
        i18n.set_lang(self.cfg.get("lang"))
        self.presets = load_json(self.presets_path, DEFAULT_PRESETS)
        self.s = {v: None for v in FIELDS.values()}
        self.conn = False
        self.cli = None
        self.keys = {}
        self.names = {}
        self.history = deque(maxlen=2400)      # [t, u, i, p] 4 Гц = 10 мин
        self.sinks = set()          # подписчики: функции(obj) (sync или async)
        self.keep = False
        self.out_since = None
        self.kz_since = None
        self.log_file = None
        self.log_writer = None
        self.log_name = None
        self.ever_client = False
        self.no_client_since = None
        self.stop = asyncio.Event()
        self.charge = None
        self.hw_sent = 0.0

    # ---------- связь с ESP ----------
    async def esp_loop(self):
        while not self.stop.is_set():
            try:
                self.cli = aioesphomeapi.APIClient(self.cfg["esp_host"], 6053, None, noise_psk=load_api_key())
                stopped = asyncio.Event()

                async def _on_stop(expected):
                    stopped.set()

                await self.cli.connect(on_stop=_on_stop, login=True)
                ents, _ = await self.cli.list_entities_services()
                self.keys = {e.name: e.key for e in ents}
                self.names = {e.key: e.name for e in ents}
                self.cli.subscribe_states(self._on_state)
                self.conn = True
                await self.toast(tr("ESP подключена"), "ok")
                await stopped.wait()
                raise ConnectionError("lost")
            except Exception:
                if self.conn:
                    await self.toast(tr("Связь с ESP потеряна, переподключаюсь…"), "warn")
                self.conn = False
                try:
                    if self.cli:
                        await self.cli.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(3)

    def _on_state(self, st):
        name = self.names.get(st.key)
        f = FIELDS.get(name)
        if f is None or getattr(st, "missing_state", False):
            return
        v = st.state
        self.s[f] = bool(v) if f in BOOLS else (None if v is None or v != v else float(v))

    # ---------- команды ----------
    def _need(self):
        if not self.conn or not self.cli:
            raise RuntimeError(tr("нет связи с ESP"))

    def cmd_out(self, on):
        self._need()
        self.cli.switch_command(self.keys["Output"], bool(on))

    def cmd_hw(self, ocp=None, opp=None, otp=None):
        self._need()
        for name, val, nd in (("M0 OCP", ocp, 3), ("M0 OPP", opp, 1), ("M0 OTP", otp, 0)):
            if val is not None and name in self.keys:
                self.cli.number_command(self.keys[name], round(float(val), nd))

    def cmd_set(self, u=None, i=None):
        self._need()
        if u is not None:
            u = round(max(0.0, min(U_MAX, float(u))), 2)
        if i is not None:
            i = round(max(0.01, min(I_MAX, float(i))), 3)
        nu = u if u is not None else (self.s["set_u"] or 0.0)
        ni = i if i is not None else (self.s["set_i"] or 0.0)
        raising = ni * max(nu, 0.1) > (self.s["set_i"] or 0.0) * max(self.s["set_u"] or 0.0, 0.1)
        hw = hw_limits(nu, ni, self.cfg["tmax"]) if self.cfg.get("smart_hw") and ni > 0 else None
        if hw and raising:
            self.cmd_hw(*hw)               # сначала поднимаем пороги
        if u is not None:
            self.cli.number_command(self.keys["Set Voltage"], u)
        if i is not None:
            self.cli.number_command(self.keys["Set Current"], i)
        if hw and not raising:
            self.cmd_hw(*hw)               # при снижении — пороги после уставок

    async def apply_preset(self, idx):
        if self.charge and self.charge["active"]:
            await self.charge_stop(tr("Зарядка остановлена: выбран пресет"), "info")
        p = self.presets[idx]
        if self.s["out"]:
            self.cmd_out(False)
            await asyncio.sleep(0.4)
        self.cmd_set(p["u"], p["i"])
        await self.toast(trf("Пресет «{}»: {:g} В / {:g} А. Выход выключен — включите вручную.", p['name'], p['u'], p['i']), "info")

    # ---------- зарядка АКБ (в приложении, не зависит от меню модуля) ----------
    def charge_summary(self):
        c = self.charge
        if not c:
            return None
        out = {k: c[k] for k in ("active", "phase", "chem", "cells", "target", "i", "cutoff", "max_min", "ah", "wh", "msg")}
        out["elapsed"] = (time.time() - c["t0"]) if c["active"] else c["elapsed"]
        return out

    async def charge_start(self, m):
        if self.charge and self.charge["active"]:
            raise RuntimeError(tr("зарядка уже идёт"))
        if not m.get("confirm"):
            raise RuntimeError(tr("нужно подтверждение: тип АКБ, число банок и полярность"))
        prof = CHEMS[m["chem"]]
        n, cur = int(m["cells"]), float(m["i"])
        if not 1 <= n <= 12:
            raise RuntimeError(tr("число банок 1..12"))
        target = round(n * prof["v"], 2)
        if target > U_MAX:
            raise RuntimeError(trf("напряжение заряда {} В выше {:g} В", target, U_MAX))
        if not 0.1 <= cur <= I_MAX:
            raise RuntimeError(trf("ток заряда 0.1..{:g} А", I_MAX))
        cutoff = max(0.02, float(m.get("cutoff") or max(0.05, round(0.1 * cur, 3))))
        max_min = int(m.get("max_min") or 600)
        ipre = min(cur, max(0.05, round(0.1 * cur, 3)))
        self._need()
        if self.s["out"]:
            self.cmd_out(False)
            await asyncio.sleep(0.4)
        self.cmd_set(target, ipre)
        await asyncio.sleep(0.6)
        self.cmd_out(True)
        now = time.time()
        self.charge = dict(active=True, phase="pre", chem=m["chem"], cells=n, target=target, i=cur, ipre=ipre,
                           cutoff=cutoff, max_min=max_min, t0=now, pt=now, last=now, ah=0.0, wh=0.0,
                           low=None, nobat=None, msg=tr("предзаряд малым током"), elapsed=0)
        await self.toast(trf("Зарядка {} {}S: до {:g} В, ток {:g} А, отсечка {:g} А", prof['name'], n, target, cur, cutoff), "ok")

    async def charge_stop(self, reason, level="warn", phase="stopped", off=True):
        c = self.charge
        if not c or not c["active"]:
            return
        c["active"], c["phase"], c["msg"] = False, phase, reason
        c["elapsed"] = time.time() - c["t0"]
        if off:
            try:
                self.cmd_out(False)
            except Exception:
                pass
        await self.toast(reason, level)

    async def charge_tick(self, now):
        c = self.charge
        if not c or not c["active"] or not self.conn:
            return
        s = self.s
        if s["uout"] is None or s["iout"] is None:
            return
        if now - c["t0"] > 3 and not s["out"]:
            await self.charge_stop(tr("Выход выключен — зарядка прервана"), "warn", off=False)
            return
        dt = min(now - c["last"], 2.0)
        c["last"] = now
        c["ah"] += s["iout"] * dt / 3600
        c["wh"] += (s["pout"] or 0) * dt / 3600
        n, target, u, i = c["cells"], c["target"], s["uout"], s["iout"]
        prof = CHEMS[c["chem"]]
        if now - c["t0"] > c["max_min"] * 60:
            await self.charge_stop(trf("Таймаут зарядки {} мин", c['max_min']), "warn")
            return
        if s["temp_ext"] is not None and s["temp_ext"] > 45:
            await self.charge_stop(trf("АКБ нагрелась до {:.0f} °C — зарядка остановлена", s['temp_ext']), "err")
            return
        if u > target + 0.1 * n + 0.1:
            await self.charge_stop(trf("Перенапряжение {:.2f} В (цель {:g} В) — остановлено", u, target), "err")
            return
        # нет АКБ / уже полная: выход на цели, тока нет
        if i < 0.01 and u >= target - 0.05:
            c["nobat"] = c["nobat"] or now
            if now - c["nobat"] > 6:
                await self.charge_stop(tr("АКБ не подключена, отключилась или уже заряжена (ток ~0 при целевом напряжении)"), "warn")
                return
        else:
            c["nobat"] = None
        if c["phase"] == "pre":
            if u >= n * prof["pre"]:
                c["phase"], c["pt"], c["msg"] = "cc", now, tr("основной заряд (постоянный ток)")
                self.cmd_set(i=c["i"])
            elif now - c["pt"] > 1800:
                await self.charge_stop(tr("АКБ не выходит из глубокого разряда за 30 мин — похоже на неисправную"), "err")
                return
            else:
                c["msg"] = trf("предзаряд малым током до {:.2f} В", n * prof['pre'])
        elif c["phase"] == "cc":
            if not s["cc"] and u >= target - 0.08:
                c["phase"], c["pt"], c["msg"] = "cv", now, tr("добор при постоянном напряжении")
        elif c["phase"] == "cv":
            if i < c["cutoff"]:
                c["low"] = c["low"] or now
                if now - c["low"] >= 20:
                    await self.charge_stop(trf("Заряд завершён: {:.3f} Ач, {:.2f} Втч", c['ah'], c['wh']), "ok", phase="done")
                    return
            else:
                c["low"] = None

    # ---------- рассылка ----------
    async def send_all(self, obj):
        for sink in list(self.sinks):
            try:
                r = sink(obj)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:
                self.sinks.discard(sink)

    def init_msg(self):
        return {"type": "init", "cfg": self.cfg, "presets": self.presets_out(),
                "history": list(self.history), "limits": {"u": U_MAX, "i": I_MAX},
                "chems": self.chems_out(), "charge": self.charge_summary(), "i18n": i18n.EN}

    def presets_out(self):
        return [{**p, "name": tr(p["name"])} for p in self.presets]

    def chems_out(self):
        return {k: {**v, "name": tr(v["name"])} for k, v in CHEMS.items()}

    async def toast(self, msg, level="info"):
        await self.send_all({"type": "toast", "msg": msg, "level": level})

    # ---------- лог CSV ----------
    def log_open(self):
        LOG_DIR.mkdir(exist_ok=True)
        self.log_name = time.strftime("session-%Y%m%d-%H%M%S.csv")
        self.log_file = open(LOG_DIR / self.log_name, "w", newline="", encoding="utf-8")
        self.log_writer = csv.writer(self.log_file)
        self.log_writer.writerow(["time", "set_u", "set_i", "uout", "iout", "pout", "uin", "temp", "mode"])

    def log_close(self):
        if self.log_file:
            self.log_file.close()
        self.log_file = self.log_writer = None

    # ---------- главный такт 4 Гц ----------
    async def ticker(self):
        while not self.stop.is_set():
            await asyncio.sleep(0.25)
            now = time.time()
            s = self.s
            sample = None
            if self.conn and s["uout"] is not None and s["iout"] is not None:
                sample = [round(now, 2), s["uout"], s["iout"], s["pout"] or 0.0]
                self.history.append(sample)

            # переходы выхода
            if s["out"] and self.out_since is None:
                self.out_since = now
                self.log_open()
            elif not s["out"] and self.out_since is not None:
                self.out_since = None
                self.kz_since = None
                self.log_close()
            if self.log_writer and sample:
                self.log_writer.writerow([time.strftime("%H:%M:%S"), s["set_u"], s["set_i"], s["uout"],
                                          s["iout"], s["pout"], s["uin"], s["temp"], "CC" if s["cc"] else "CV"])

            await self.protect(now)
            await self.charge_tick(now)
            await self.hw_sync(now)

            await self.send_all({
                "type": "state", "conn": self.conn, "s": s, "sample": sample,
                "out_for": (now - self.out_since) if self.out_since else 0,
                "charge": self.charge_summary(),
                "log": self.log_name if self.out_since else None,
            })

            # авто-выход, когда окно закрыто
            if self.sinks:
                self.ever_client = True
                self.no_client_since = None
            elif self.ever_client and not self.keep:
                self.no_client_since = self.no_client_since or now
                if now - self.no_client_since > 8:
                    await self.shutdown()

    async def hw_sync(self, now):
        s = self.s
        if not (self.cfg.get("smart_hw") and self.conn and s["set_u"] and s["set_i"] and s["hw_ocp"] is not None
                and s["hw_opp"] is not None and now - self.hw_sent > 3):
            return
        ocp, opp, otp = hw_limits(s["set_u"], s["set_i"], self.cfg["tmax"])
        if abs(ocp - s["hw_ocp"]) > 0.01 or abs(opp - s["hw_opp"]) > 0.15 or (s["hw_otp"] is not None and int(s["hw_otp"]) != otp):
            self.hw_sent = now
            try:
                self.cmd_hw(ocp, opp, otp)
            except Exception:
                pass

    async def protect(self, now):
        s, c = self.s, self.cfg
        if not (self.conn and s["out"]):
            return
        reason = None
        charging = bool(self.charge and self.charge.get("active"))
        if c["short_off"] and not charging and s["cc"] and s["set_u"] and s["uout"] is not None and s["uout"] < 0.5 * s["set_u"]:
            self.kz_since = self.kz_since or now
            if now - self.kz_since > 1.0:
                reason = tr("КЗ или перегрузка (режим CC, напряжение просело)")
        else:
            self.kz_since = None
        if not reason and not charging and c["timer_min"] and self.out_since and now - self.out_since > c["timer_min"] * 60:
            reason = trf("сработал таймер {} мин", c['timer_min'])
        if not reason and s["temp"] is not None and s["temp"] > c["tmax"]:
            reason = trf("перегрев модуля ({:.0f} °C)", s['temp'])
        if reason:
            try:
                self.cmd_out(False)
            except Exception:
                pass
            self.kz_since = None
            await self.toast(tr("Выход выключен автоматически: ") + reason, "err")

    async def shutdown(self):
        if self.stop.is_set():
            return
        if self.cfg["off_on_exit"] and self.conn and self.s["out"]:
            try:
                self.cmd_out(False)
                await asyncio.sleep(0.4)
            except Exception:
                pass
        self.log_close()
        self.stop.set()




class DemoController(Controller):
    """Simulated module for trying the UI without hardware (python desktop.py --demo).
    A resistive load with CV/CC behaviour; thresholds and counters work like the real thing."""

    def __init__(self, host=None, load=20.0):
        super().__init__(host, (ROOT / "config.demo.json", ROOT / "presets.demo.json"))
        self.load = load
        self.soc = 0.0
        self.s.update(uout=0.0, iout=0.0, pout=0.0, uin=19.4, temp=28.0, wh=0.0, ah=0.0, cc=False, out=False,
                      set_u=5.0, set_i=1.0, prot=0.0, fw=139.0, model=22873.0, temp_ext=None,
                      hw_ocp=6.2, hw_opp=125.0, hw_otp=95.0)

    def _need(self):
        pass

    async def esp_loop(self):
        self.conn = True
        dt = 0.25
        while not self.stop.is_set():
            await asyncio.sleep(dt)
            s = self.s
            ch = self.charge
            if s["out"] and ch and ch["active"]:
                # simulated small battery: open-circuit voltage rises with state of charge
                prof = CHEMS[ch["chem"]]
                n, r = ch["cells"], 0.4 * ch["cells"]
                lo = prof["pre"] - 0.3
                ocv = n * (lo + (prof["v"] - lo) * self.soc)
                i = min(s["set_i"], max(0.0, (s["set_u"] - ocv) / r))
                u = min(s["set_u"], ocv + i * r)
                s["cc"] = i >= s["set_i"] - 1e-6
                k = 1 + random.uniform(-0.002, 0.002)
                s["uout"], s["iout"] = round(u * k, 3), round(i * k, 4)
                s["pout"] = round(s["uout"] * s["iout"], 2)
                s["wh"] += s["pout"] * dt / 3600
                s["ah"] += s["iout"] * dt / 3600
                self.soc = min(1.0, self.soc + i * dt / 3600 / (0.02 * n))
            elif s["out"]:
                u = s["set_u"]
                i = u / self.load
                if i > s["set_i"]:
                    i = s["set_i"]
                    u = i * self.load
                    s["cc"] = True
                else:
                    s["cc"] = False
                k = 1 + random.uniform(-0.004, 0.004)
                s["uout"], s["iout"] = round(u * k, 3), round(i * k, 4)
                s["pout"] = round(s["uout"] * s["iout"], 2)
                s["wh"] += s["pout"] * dt / 3600
                s["ah"] += s["iout"] * dt / 3600
                s["temp"] += (28 + s["pout"] * 0.9 - s["temp"]) * 0.01
            else:
                s.update(uout=0.0, iout=0.0, pout=0.0, cc=False)
                s["temp"] += (28 - s["temp"]) * 0.01
            s["uin"] = round(19.4 + random.uniform(-0.02, 0.02), 2)

    def cmd_out(self, on):
        self.s["out"] = bool(on)

    async def charge_start(self, m):
        self.soc = 0.05
        await super().charge_start(m)

    def cmd_hw(self, ocp=None, opp=None, otp=None):
        for k, v in (("hw_ocp", ocp), ("hw_opp", opp), ("hw_otp", otp)):
            if v is not None:
                self.s[k] = float(v)

    def cmd_set(self, u=None, i=None):
        if u is not None:
            self.s["set_u"] = round(max(0.0, min(U_MAX, float(u))), 2)
        if i is not None:
            self.s["set_i"] = round(max(0.01, min(I_MAX, float(i))), 3)
        if self.cfg.get("smart_hw"):
            self.cmd_hw(*hw_limits(self.s["set_u"], self.s["set_i"], self.cfg["tmax"]))


async def handle(ctl, m):
    c = m.get("cmd")
    if c == "out":
        ctl.cmd_out(m["on"])
    elif c == "set":
        ctl.cmd_set(m.get("u"), m.get("i"))
    elif c == "preset":
        await ctl.apply_preset(int(m["index"]))
    elif c == "save_presets":
        ps = []
        for p in m["presets"][:8]:
            ps.append({"name": str(p["name"])[:24], "u": round(max(0, min(U_MAX, float(p["u"]))), 2),
                       "i": round(max(0.01, min(I_MAX, float(p["i"]))), 3)})
        ctl.presets = ps
        save_json(ctl.presets_path, ps)
        await ctl.send_all({"type": "presets", "presets": ctl.presets_out()})
        await ctl.toast(tr("Пресеты сохранены"), "ok")
    elif c == "config":
        for k in ("short_off", "off_on_exit", "smart_hw"):
            if k in m:
                ctl.cfg[k] = bool(m[k])
        if "timer_min" in m:
            ctl.cfg["timer_min"] = max(0, int(m["timer_min"]))
        if "tmax" in m:
            ctl.cfg["tmax"] = max(40, min(95, int(m["tmax"])))
        if m.get("lang") in ("ru", "en"):
            ctl.cfg["lang"] = m["lang"]
            i18n.set_lang(m["lang"])
        save_json(ctl.cfg_path, ctl.cfg)
        await ctl.send_all({"type": "cfg", "cfg": ctl.cfg, "presets": ctl.presets_out(), "chems": ctl.chems_out()})
    elif c == "charge_start":
        await ctl.charge_start(m)
    elif c == "charge_stop":
        await ctl.charge_stop(tr("Зарядка остановлена вручную"), "info")
    elif c == "clear_history":
        ctl.history.clear()
        await ctl.send_all({"type": "history", "history": []})
    elif c == "quit":
        await ctl.shutdown()
