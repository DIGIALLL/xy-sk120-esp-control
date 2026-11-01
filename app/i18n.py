"""Tiny i18n: Russian is the source language, EN maps Russian -> English.

tr("text")            -> translated string
trf("a {} b {:.1f}", x, y) -> translated template, then .format(x, y)
The language is global per process and stored in config.json ("lang": "ru" | "en").
"""
import locale

LANG = ["ru"]


def detect():
    try:
        loc = (locale.getlocale()[0] or "").lower()
    except Exception:
        loc = ""
    return "ru" if loc.startswith(("ru", "russian")) else "en"


def set_lang(lang):
    LANG[0] = lang if lang in ("ru", "en") else "ru"


def get_lang():
    return LANG[0]


def tr(s):
    return EN.get(s, s) if LANG[0] == "en" else s


def trf(tmpl, *args):
    return tr(tmpl).format(*args)


EN = {
    # --- core messages
    "ESP подключена": "ESP connected",
    "Связь с ESP потеряна, переподключаюсь…": "ESP link lost, reconnecting…",
    "нет связи с ESP": "no link to ESP",
    "Зарядка остановлена: выбран пресет": "Charging stopped: a preset was selected",
    "Пресет «{}»: {:g} В / {:g} А. Выход выключен — включите вручную.": "Preset “{}”: {:g} V / {:g} A. Output is OFF — switch it on manually.",
    "зарядка уже идёт": "charging is already running",
    "нужно подтверждение: тип АКБ, число банок и полярность": "confirmation required: battery type, cell count and polarity",
    "число банок 1..12": "cell count must be 1..12",
    "напряжение заряда {} В выше {:g} В": "charge voltage {} V is above {:g} V",
    "ток заряда 0.1..{:g} А": "charge current must be 0.1..{:g} A",
    "предзаряд малым током": "pre-charge at low current",
    "Зарядка {} {}S: до {:g} В, ток {:g} А, отсечка {:g} А": "Charging {} {}S: up to {:g} V, {:g} A, cutoff {:g} A",
    "Выход выключен — зарядка прервана": "Output switched off — charging aborted",
    "Таймаут зарядки {} мин": "Charge timeout {} min",
    "АКБ нагрелась до {:.0f} °C — зарядка остановлена": "Battery reached {:.0f} °C — charging stopped",
    "Перенапряжение {:.2f} В (цель {:g} В) — остановлено": "Overvoltage {:.2f} V (target {:g} V) — stopped",
    "АКБ не подключена, отключилась или уже заряжена (ток ~0 при целевом напряжении)": "Battery not connected, disconnected or already full (≈0 current at target voltage)",
    "основной заряд (постоянный ток)": "main charge (constant current)",
    "АКБ не выходит из глубокого разряда за 30 мин — похоже на неисправную": "Battery does not recover from deep discharge in 30 min — probably faulty",
    "предзаряд малым током до {:.2f} В": "pre-charge at low current up to {:.2f} V",
    "добор при постоянном напряжении": "top-off at constant voltage",
    "Заряд завершён: {:.3f} Ач, {:.2f} Втч": "Charge complete: {:.3f} Ah, {:.2f} Wh",
    "КЗ или перегрузка (режим CC, напряжение просело)": "short circuit or overload (CC mode, voltage sagged)",
    "сработал таймер {} мин": "{} min timer expired",
    "перегрев модуля ({:.0f} °C)": "module overheated ({:.0f} °C)",
    "Выход выключен автоматически: ": "Output switched off automatically: ",
    "Пресеты сохранены": "Presets saved",
    "Зарядка остановлена вручную": "Charging stopped manually",
    "Ошибка команды: {}": "Command error: {}",
    # --- default presets / chemistries / series
    "USB / платы": "USB / boards",
    "Зарядки QC": "QC chargers",
    "Вентиляторы, LED": "Fans, LED",
    "Ноутбук": "Laptop",
    "Ноутбук (20 В)": "Laptop (20 V)",
    "Свинцовый (AGM/гель/кислота), банок по 2 В": "Lead-acid (AGM/gel/flooded), 2 V cells",
    "Напряжение": "Voltage",
    "Ток": "Current",
    "Мощность": "Power",
    # --- desktop UI
    "  блок питания для ремонта": "  bench power supply for repairs",
    "нет связи": "offline",
    "Uвх  —": "Uin  —",
    "НАПРЯЖЕНИЕ": "VOLTAGE",
    "В": "V",
    "ТОК": "CURRENT",
    "А": "A",
    "МОЩНОСТЬ": "POWER",
    "Вт": "W",
    "ВКЛЮЧИТЬ ВЫХОД": "SWITCH OUTPUT ON",
    "УСТАВКИ": "SETPOINTS",
    "Напряжение, В": "Voltage, V",
    "Лимит тока, А": "Current limit, A",
    "ПРЕСЕТЫ": "PRESETS",
    "править": "edit",
    "ЗАЩИТЫ": "PROTECTIONS",
    "Выкл. при КЗ / перегрузке": "Switch off on short / overload",
    "Выкл. выход при закрытии окна": "Switch output off when window closes",
    "Пороги модуля (OCP/OPP/OTP) под уставки": "Module thresholds (OCP/OPP/OTP) follow setpoints",
    "Таймер работы, мин (0 — выкл)": "Run timer, min (0 = off)",
    "Макс. температура, °C": "Max temperature, °C",
    "Зарядка АКБ…": "Battery charging…",
    "{} мин": "{} min",
    "{:g} В\n{} · {:g} А": "{:g} V\n{} · {:g} A",
    "Пресеты": "Presets",
    "Название": "Name",
    "U, В": "U, V",
    "Лимит I, А": "I limit, A",
    "+ добавить": "+ add",
    "Новый": "New",
    "Сохранить": "Save",
    "Отмена": "Cancel",
    "Зарядка АКБ": "Battery charging",
    "{} ({} В/банка)": "{} ({} V/cell)",
    "Тип АКБ": "Battery type",
    "Банок последовательно (S)": "Cells in series (S)",
    "Ток заряда, А": "Charge current, A",
    "Отсечка по току, А (пусто = авто)": "Cutoff current, A (empty = auto)",
    "Макс. время, мин": "Max time, min",
    "Тип, число банок и полярность проверены": "Type, cell count and polarity checked",
    "Защиты от переполюсовки нет. Li-ion без BMS не заряжать. NiMH не поддерживается.": "No reverse-polarity protection. Never charge Li-ion without a BMS. NiMH is not supported.",
    "Начать зарядку": "Start charging",
    "Цель: {:.2f} В  (предзаряд до {:.2f} В)": "Target: {:.2f} V  (pre-charge up to {:.2f} V)",
    "Подтвердите тип АКБ, число банок и полярность": "Confirm battery type, cell count and polarity",
    "Проверьте числа в окне зарядки": "Check the numbers in the charging window",
    "Остановить зарядку": "Stop charging",
    "Предзаряд": "Pre-charge",
    "Основной заряд (CC)": "Main charge (CC)",
    "Добор (CV)": "Top-off (CV)",
    "Заряд завершён": "Charge complete",
    "Остановлено": "Stopped",
    "Uвх  %.2f В": "Uin  %.2f V",
    "ограничение тока (CC)": "current limit (CC)",
    "стабилизация напряжения (CV)": "voltage regulation (CV)",
    "выход выключен": "output off",
    "ВЫХОД ВКЛЮЧЁН\nнажмите, чтобы выключить": "OUTPUT ON\nclick to switch off",
    "%.3f Втч": "%.3f Wh",
    "%.3f Ач": "%.3f Ah",
    "работает %02d:%02d": "running %02d:%02d",
    "лог: logs/": "log: logs/",
    "ЗАЩИТА МОДУЛЯ, код %d": "MODULE PROTECTION, code %d",
    "сейчас": "now",
    "мин {:.3g}   макс {:.3g}   средн. {:.3g} {}": "min {:.3g}   max {:.3g}   avg {:.3g} {}",
    "нет данных": "no data",
    "%s   U %.2f В  I %.3f А  P %.1f Вт": "%s   U %.2f V  I %.3f A  P %.1f W",
    "цель {} В, ток {} А, отсечка {} А": "target {} V, {} A, cutoff {} A",
    "{:02d}:{:02d} · {:.3f} Ач · {:.2f} Втч": "{:02d}:{:02d} · {:.3f} Ah · {:.2f} Wh",
}
