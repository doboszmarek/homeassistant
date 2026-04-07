# Power Regulator — Dokumentacja

System automatycznej regulacji mocy grzałki bojlera na podstawie nadwyżki energii PV.

---

## Architektura systemu

```
PV (Deye 12kW + Mikroinwerter)
         │
         ▼
   [Bateria JK BMS]
         │
         ▼
   Dom (Shelly EM3)  ←──── Sieć energetyczna (SDM630)
         │
    ┌────┴────────────────────┐
    │                         │
  Obwód NE                  Obwód UPS
  (licznik NE SDM630)       (Deye UPS out)
    │
  ┌─┴──────────┐
  │            │
Grzałka      EV (Shelly Pro 3EM)
bojlera
  │
GPIO25 ← ESP32 Power Regulator (Slow PWM 30s)
```

---

## Hardware (ESP32)

| Komponent | Opis |
|---|---|
| ESP32 dev | Główny mikrokontroler (Arduino framework) |
| Slow PWM | GPIO25 → przekaźnik grzałki, okres 30s |
| SHTC3 | Czujnik temperatury/wilgotności (I2C: SDA=GPIO26, SCL=GPIO27) |
| SSD1322 | Wyświetlacz OLED 256×64 SPI (CLK=GPIO18, MOSI=GPIO23, DC=GPIO16, CS=GPIO14, RST=GPIO17) |
| SSD1306 | Wyświetlacz OLED 128×64 I2C (adres 0x3C) |

**Dostęp:** http://192.168.1.141 (admin/admin)

---

## Firmware ESPHome (`power-regulator.yaml`)

### Zmienne globalne

| Zmienna | Typ | Opis |
|---|---|---|
| `heater_on` | bool | Czy grzałka jest fizycznie włączona (faza ON slow PWM) |
| `heater_power_when_on` | float | Zmierzona moc grzałki gdy fizycznie ON [W] (persist) |
| `first_measurement_done` | bool | Czy wykonano pierwszą kalibrację |
| `manual_watchdog_counter` | int | Licznik czasu w trybie ręcznym bez HA [s] |

### Logika główna (interval 2s)

```
1. WATCHDOG: MANUAL + brak HA + grzałka ON
   → po timeout (domyślnie 30 min) → wyłącz grzałkę

2. BEZPIECZEŃSTWO TEMPERATURY: SHTC3 > max_temperature
   → wyłącz grzałkę natychmiast

3. BEZPIECZEŃSTWO AUTO: brak HA w trybie AUTO
   → wyłącz grzałkę

4. KALIBRACJA (podczas fazy ON):
   measured = ne_power - ev_power
   jeśli 100W < measured < 5500W:
       heater_power_when_on = measured

5. OBLICZENIE ŚREDNIEJ MOCY:
   boiler_avg_power = heater_power_when_on × (duty / 100)
```

### Kalibracja mocy

- `ne_power` = `sensor.ne_total_system_power` — moc obwodu NE (grzałka + EV) [W]
- `ev_power` = `sensor.shellypro3em_ev_moc` — moc ładowarki EV [W]
- `measured = ne - ev` = rzeczywista moc samej grzałki gdy ON
- Kalibracja odbywa się **podczas całej fazy ON** (co 2s), każdy pomiar nadpisuje poprzedni
- Warunek poprawności: `measured > 100W AND measured ≤ 5500W`

---

## Sensory HA używane przez firmware

| Sensor HA | Opis |
|---|---|
| `sensor.ne_total_system_power` | Moc obwodu NE (SDM630 slave 2) |
| `sensor.shellypro3em_ev_moc` | Moc ładowarki EV |
| `input_boolean.power_regulator_auto_mode` | Tryb AUTO/MANUAL |
| `input_number.power_regulator_max_temperature` | Limit temperatury bezpieczeństwa [°C] |

---

## Template sensors (`template.yaml`)

### `sensor.bojler_moc_chwilowa`

Fizyczny pomiar mocy grzałki w czasie rzeczywistym:

```
bojler_moc_chwilowa = max(ne_total_system_power - shellypro3em_ev_moc, 0)
```

Poprawnie zeruje się gdy:
- Grzałka jest w fazie OFF (PWM)
- Termostat bojlera odciął grzałkę (woda gorąca)
- EV ładuje się (odejmowane od NE)

### `sensor.regulator_dostepna_moc_nadwyzkowa`

Dostępna nadwyżka PV dla regulatora:

```
surplus = PV_total - home_load - boiler_avg_power - battery_charging
          (jeśli bateria rozładowuje: - battery_discharging)
```

### `sensor.regulator_sugerowany_poziom`

Sugerowany poziom regulatora (0-100%) — używany poglądowo.

---

## Pomiar energii (`configuration.yaml`)

```yaml
sensor:
  - platform: integration
    source: sensor.bojler_moc_chwilowa   # fizyczny pomiar, nie model
    name: Grzalka Energia
    unit_prefix: k
    method: left

utility_meter:
  grzalka_energia_dziennie:   cycle: daily
  grzalka_energia_miesiecznie: cycle: monthly
  grzalka_energia_rocznie:    cycle: yearly
```

**Dlaczego `bojler_moc_chwilowa` zamiast `boiler_avg_power`:**
- `boiler_avg_power` = model matematyczny, nie zeruje się gdy termostat odcina grzałkę
- `bojler_moc_chwilowa` = pomiar fizyczny z licznika NE, poprawnie odzwierciedla rzeczywiste zużycie

---

## Automatyzacja (`automations.yaml`)

Uruchamiana co **15 sekund** (0.5 × okres PWM 30s).

### Priorytety decyzji `target_level`

```
1. Brak PV (< 100W)              → 0%   (wyłącz)
2. Bateria krytyczna (> 800W)    → 0%   (wyłącz)
3. Eksport > 10kW                → pilny wzrost (bez limitu kroku)
4. Bateria umiarkowana (> 150W)  → redukcja proporcjonalna
5. Import z sieci (> 50W)        → redukcja proporcjonalna
6. Ujemna nadwyżka (< -50W)      → redukcja proporcjonalna
7. Eksport + surplus > 100W      → wzrost max +30% na cykl
8. Bilans OK                     → utrzymaj
```

### Obliczenie nadwyżki (kluczowa zmiana)

```jinja2
controlled_load = sensor.power_regulator_bojler_srednia_moc  # ŚREDNIA, nie instantaniczna
surplus = PV_total - home_load - controlled_load - battery_charging
```

**Dlaczego `boiler_avg_power` zamiast `ne_total_system_power`:**

Podczas fazy ON grzałka pobiera 5000W (pełna moc). Jeśli użyć `ne_total_system_power`:
- surplus = PV - dom - 5000 = mała wartość
- `target_from_surplus` = mała wartość → automatyzacja obcinała duty do 10%!

Z `boiler_avg_power` (np. 4000W przy 80% duty):
- surplus = PV - dom - 4000 = właściwa wartość
- `target_from_surplus` = current + (surplus/5000×100) → stabilna regulacja

### Wzrost `target_from_surplus`

```jinja2
target_from_surplus = current_level + (surplus / heater_max * 100)
new_level = current_level + 30  # max krok w górę
result = min(new_level, target_from_surplus)  # nie przekrocz celu
```

### Limit eksportu 10kW

```jinja2
{% elif grid_power < -10000 %}
  excess = (-grid_power) - 10000
  increase = excess / heater_max * 100
  target = min(current_level + increase, 100)
```

---

## Zabezpieczenia

| Zabezpieczenie | Warunek | Akcja |
|---|---|---|
| Temperatura | SHTC3 > `max_temperature` | Wyłącz grzałkę natychmiast |
| Brak HA (AUTO) | Brak połączenia z HA | Wyłącz grzałkę |
| Watchdog (MANUAL) | Brak HA przez > timeout | Wyłącz po odliczeniu |
| Bateria krytyczna | Rozładowanie > 800W | Wyłącz grzałkę |
| Bateria umiarkowana | Rozładowanie > 150W | Redukcja mocy |
| Ochrona SOC (MANUAL) | SOC < 50% | Wyłącz, przywróć po SOC > 60% |
| Brak PV | PV < 100W przez > 1 min | Wyłącz grzałkę |
| Limit eksportu | Eksport > 10kW | Pilny wzrost mocy grzałki |

---

## Encje w Home Assistant

| Encja | Typ | Opis |
|---|---|---|
| `number.power_regulator_regulator_mocy` | number 0-100% | Poziom PWM grzałki |
| `number.power_regulator_watchdog_timeout` | number 5-120 min | Timeout watchdog |
| `sensor.power_regulator_bojler_srednia_moc` | sensor W | Średnia moc grzałki (model) |
| `sensor.power_regulator_bojler_moc_rzeczywista` | sensor W | Moc przy pełnym ON |
| `sensor.bojler_moc_chwilowa` | sensor W | Fizyczny pomiar (ne - ev) |
| `sensor.grzalka_energia` | sensor kWh | Całka energii z bojler_moc_chwilowa |
| `binary_sensor.power_regulator_grzalka_aktywna` | binary | Czy grzałka fizycznie ON |
| `binary_sensor.power_regulator_alarm_temperatury` | binary | Alarm temp SHTC3 |
| `input_boolean.power_regulator_auto_mode` | boolean | Tryb AUTO/MANUAL |
| `input_number.power_regulator_max_temperature` | number °C | Limit temp bezpieczeństwa |
