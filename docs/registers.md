# Modbus registers used / Используемые регистры

Link: **TTL UART, Modbus RTU, 115200 8N1, slave address 1** (module menu: `bRE`, `Add`). Functions used: `0x03` read holding,
`0x06` write single register. Tested on an old-revision **XY-SK120, firmware 139 (`0x008B`), model code `0x5959`**.
Sources of the map: [csvke/XY-SK120-Modbus-RTU-TTL](https://github.com/csvke/XY-SK120-Modbus-RTU-TTL),
[donkilove/Sk150PowerSupplySDK](https://github.com/donkilove/Sk150PowerSupplySDK), [xy-modbus](https://docs.rs/xy-modbus).

| Address | Meaning | Scale | R/W | Verified |
|---|---|---|---|---|
| `0x0000` | Voltage setpoint | ÷100 V | R/W | ✅ write + read back + screen |
| `0x0001` | Current limit setpoint | ÷1000 A | R/W | ✅ write + read back + screen |
| `0x0002` | Output voltage | ÷100 V | R | ✅ |
| `0x0003` | Output current | ÷1000 A | R | ✅ (12 V fan, 0.06 A) |
| `0x0004` | Output power | ÷100 W | R | ✅ |
| `0x0005` | Input voltage | ÷100 V | R | ✅ |
| `0x0006`–`0x0007` | Accumulated charge (low, high word) | ÷1000 Ah | R | ⚠️ reads 0, not exercised long enough |
| `0x0008`–`0x0009` | Accumulated energy (low, high word) | ÷1000 Wh | R | ⚠️ same |
| `0x000D` | Internal temperature | ÷10 °C | R | ✅ |
| `0x000E` | External NTC temperature | ÷10 °C (`8888` = no probe) | R | ✅ (no probe → ignored) |
| `0x0010` | Protection code | raw | R | ✅ (0 = none) |
| `0x0011` | CV/CC mode | 0 = CV, 1 = CC | R | ✅ |
| `0x0012` | Output enable | 0 / 1 | R/W | ✅ |
| `0x0016` | Model code | raw | R | ✅ `0x5959` |
| `0x0017` | Firmware version | raw | R | ✅ `139` |
| `0x0054` | M0 over-current threshold (OCP) | ÷1000 A | R/W | ✅ write + read back |
| `0x0055` | M0 over-power threshold (OPP) | ÷10 W | R/W | ✅ write + read back |
| `0x005C` | M0 over-temperature threshold (OTP) | °C | R/W | ✅ write + read back |

Memory group M0 sits at `0x0050`; thresholds in the same block that the firmware only **reads**: `0x0052` LVP (÷100 V, factory 5.50),
`0x0053` OVP (÷100 V, factory 38.00), `0x0056`–`0x005B` timer / capacity / energy limits (factory 0 = off).

Factory thresholds of the tested unit: OCP 6.2 A, OPP 125 W, OTP 95 °C, LVP 5.5 V, OVP 38 V.

Not used: the module's built-in battery charge mode (`bCH` / `bTF` in its menu). Community tables list possible registers
(`0x0021`, `0x0029`–`0x002D`) but they are unverified, so the charger is implemented in the app instead.

> RU: таблица выше — регистры, которые реально использует проект; всё помеченное ✅ проверено на старой плате XY-SK120 (прошивка 139).
> Встроенный режим зарядки модуля (`bCH`/`bTF`) не используется — зарядка реализована в приложении.
