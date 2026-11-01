# Wiring / Подключение

🇬🇧 [English](#english) · 🇷🇺 [Русский](#русский)

---

## English

### The module's UART header

The XY-SK120 has a small 4-pin connector on the back (community reports say JST, 1.25 mm pitch).
**Nothing is printed next to it, and the pin order differs between board revisions**
(sources disagree: `5V-TX-RX-GND`, `VCC-GND-TX-RX`, …). Do **not** wire it from a table found on the internet — measure it.

### Identify the pins (module powered from its input, output off, ESP disconnected)

| Pin | How to recognise it (measured on an old-revision XY-SK120) |
|---|---|
| **GND** | continuity to the **minus of the module's input (VIN-)** with the module unpowered |
| **5 V** | steady **5 V** relative to GND — it is an **output** of the module, never feed anything into it |
| **TX** (module → ESP) | steady **3.3 V** relative to GND (idle-high output) |
| **RX** (ESP → module) | roughly **2.2 V** relative to GND (input with pull-up/divider; multimeter loads it) |

If you measured something different, the module may be a different revision — look for photos of your board and keep measuring
before connecting anything. The signal lines are 3.3 V logic and **not isolated**: UART GND is the module's input minus.

### Connect to the ESP32-C3 SuperMini

| Module | ESP32-C3 SuperMini |
|---|---|
| GND | GND |
| TX (3.3 V idle) | **GPIO20** (ESP RX) |
| RX (≈2.2 V idle) | **GPIO21** (ESP TX) |
| 5 V (output) | 5V pin — *optional, powers the ESP from the module* |
| — | GPIO3 → push-button → GND (optional output button) |

```
 XY-SK120 UART header                 ESP32-C3 SuperMini
 ┌────────────┐
 │ GND  ──────┼────────────────────── GND
 │ TX   ──────┼────────────────────── GPIO20  (RX)
 │ RX   ──────┼────────────────────── GPIO21  (TX)
 │ 5V   ──────┼────────────────────── 5V      (optional power)
 └────────────┘                       GPIO3 ──[button]── GND   (optional)
```

* If the ESP log shows `no response received`, swap the two signal wires (both are 3.3 V logic, swapping is safe), then check
  the module's baud/address (`bRE`, `Add` in its menu).
* **Powering the ESP from the module's 5 V pin** worked on the tested unit (stable, survived hard power cuts and a 0.06 A load), but the
  current capability of that pin is undocumented. If you see resets under load, power the ESP from a separate USB charger instead.
  **Never** power the ESP from the module's pin and from a USB port at the same time.
* Use short wires; 100–470 Ω in series with TX/RX is optional protection.

---

## Русский

### UART-разъём модуля

На обратной стороне XY-SK120 есть маленький 4-контактный разъём (по данным сообщества — JST, шаг 1.25 мм).
**Рядом ничего не подписано, а порядок контактов отличается у разных ревизий платы**
(источники расходятся: `5V-TX-RX-GND`, `VCC-GND-TX-RX`, …). **Не** подключайте по таблицам из интернета — измерьте.

### Как определить контакты (модуль включён по входу, выход выключен, ESP не подключена)

| Контакт | Как узнать (измерено на старой ревизии XY-SK120) |
|---|---|
| **GND** | «прозвонка» на **минус входа модуля (VIN-)** при выключенном модуле |
| **5 В** | стабильные **5 В** относительно GND — это **выход** модуля, подавать на него ничего нельзя |
| **TX** (модуль → ESP) | стабильные **3.3 В** относительно GND (выход, в простое «единица») |
| **RX** (ESP → модуль) | около **2.2 В** относительно GND (вход с подтяжкой/делителем, мультиметр его нагружает) |

Если у вас получилось другое, возможно, у вас другая ревизия — найдите фото своей платы и продолжайте измерять,
прежде чем что-то подключать. Сигнальные линии — логика 3.3 В, **без гальванической развязки**: GND UART — это минус входа модуля.

### Подключение к ESP32-C3 SuperMini

| Модуль | ESP32-C3 SuperMini |
|---|---|
| GND | GND |
| TX (3.3 В в простое) | **GPIO20** (RX ESP) |
| RX (≈2.2 В в простое) | **GPIO21** (TX ESP) |
| 5 В (выход) | пин 5V — *по желанию, питает ESP от модуля* |
| — | GPIO3 → кнопка → GND (необязательная кнопка выхода) |

* Если в логе ESP `no response received` — поменяйте местами два сигнальных провода (оба 3.3 В, это безопасно), затем проверьте
  скорость/адрес модуля (`bRE`, `Add` в его меню).
* **Питание ESP от пина 5 В модуля** на проверенном экземпляре работало (стабильно, пережило резкие отключения питания и нагрузку 0.06 А),
  но допустимый ток этого пина не документирован. Если видите перезагрузки под нагрузкой — питайте ESP от отдельного USB-блока.
  **Никогда** не питайте ESP одновременно от пина модуля и от USB.
* Провода делайте короткими; резисторы 100–470 Ом последовательно в TX/RX — по желанию, как защита.
