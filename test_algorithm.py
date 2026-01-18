#!/usr/bin/env python3
"""
Testy algorytmu sterowania regulatorem mocy.
Symulacja logiki z automations.yaml
"""

def calculate_target_level(
    pv_power: float,
    home_load: float,
    grid_power: float,
    controlled_load: float,
    battery_charging: float,
    battery_discharging: float,
    current_level: float,
    microinverter_power: float = 0.0,
    heater_max: float = 2000.0
) -> dict:
    """
    Symulacja algorytmu z automatyzacji.
    Zwraca słownik z wynikami i ścieżką decyzyjną.
    """

    # Oblicz całkowitą moc PV (główny inwerter + mikroinwerter)
    total_pv_power = pv_power + microinverter_power

    # Oblicz surplus
    base_surplus = total_pv_power - home_load - controlled_load - battery_charging
    if battery_discharging > 10:
        surplus = max(base_surplus - battery_discharging, 0)
    else:
        surplus = base_surplus

    decision_path = []
    target_level = current_level

    # Warunek 1: Brak PV
    if total_pv_power < 100:
        target_level = 0
        decision_path.append(f"PV < 100W ({total_pv_power:.0f}W) -> OFF")

    # Warunek 2: Bateria się rozładowuje
    elif battery_discharging > 50:
        reduce = (battery_discharging / heater_max * 100)
        target_level = max(current_level - reduce - 5, 0)
        target_level = min(target_level, 100)
        decision_path.append(f"Bateria(-) {battery_discharging}W > 50W -> reduce {reduce:.0f}%+5%")

    # Warunek 3: Pobieramy z sieci
    elif grid_power > 30:
        reduce = (grid_power / heater_max * 100)
        step = max(min(reduce, 20), 5)
        target_level = max(current_level - step, 0)
        target_level = min(target_level, 100)
        decision_path.append(f"Grid {grid_power}W > 30W -> reduce step {step:.0f}%")

    # Warunek 4: Surplus ujemny
    elif surplus < 0:
        reduce = ((-surplus) / heater_max * 100)
        step = max(min(reduce, 15), 3)
        target_level = max(current_level - step, 0)
        target_level = min(target_level, 100)
        decision_path.append(f"Surplus {surplus:.0f}W < 0 -> reduce step {step:.0f}%")

    # Warunek 5: Oddajemy do sieci i mamy nadwyżkę
    elif grid_power < -30 and surplus > 0:
        increase = (-grid_power / heater_max * 100)
        max_from_surplus = current_level + (surplus / heater_max * 100)
        step = min(increase, 10)
        target_level = min(current_level + step, max_from_surplus, 100)
        target_level = max(target_level, 0)
        decision_path.append(f"Grid {grid_power}W < -30 & surplus {surplus:.0f}W > 0 -> increase step {step:.0f}%")

    # Warunek 6: Utrzymaj
    else:
        decision_path.append(f"Balans OK (grid={grid_power}W, surplus={surplus:.0f}W) -> utrzymaj")

    return {
        "target_level": int(target_level),
        "surplus": surplus,
        "total_pv_power": total_pv_power,
        "decision_path": decision_path,
        "change": int(target_level) - int(current_level)
    }


def run_test(name: str, params: dict, expected: dict = None):
    """Uruchom pojedynczy test i wyświetl wyniki."""
    result = calculate_target_level(**params)

    status = "?"
    if expected:
        if expected.get("target") is not None:
            status = "PASS" if result["target_level"] == expected["target"] else "FAIL"
        if expected.get("direction") is not None:
            actual_dir = "down" if result["change"] < 0 else ("up" if result["change"] > 0 else "same")
            if status != "FAIL":
                status = "PASS" if actual_dir == expected["direction"] else "FAIL"

    micro = params.get('microinverter_power', 0)
    print(f"\n{'='*60}")
    print(f"TEST: {name} [{status}]")
    print(f"{'='*60}")
    print(f"  PV={params['pv_power']}W + Micro={micro}W = {result['total_pv_power']:.0f}W")
    print(f"  Dom={params['home_load']}W, Grid={params['grid_power']}W")
    print(f"  Grzalka={params['controlled_load']}W, Bat+={params['battery_charging']}W, Bat-={params['battery_discharging']}W")
    print(f"  Current level: {params['current_level']}%")
    print(f"  ---")
    print(f"  Surplus: {result['surplus']:.0f}W")
    print(f"  Decision: {result['decision_path'][0]}")
    print(f"  Target: {params['current_level']}% -> {result['target_level']}% (zmiana: {result['change']:+d}%)")

    if expected and status == "FAIL":
        print(f"  !!! EXPECTED: {expected}")

    return status, result


def main():
    print("\n" + "="*60)
    print(" TESTY ALGORYTMU STEROWANIA REGULATOREM MOCY")
    print("="*60)

    results = {"PASS": 0, "FAIL": 0, "?": 0}

    # ==========================================
    # GRUPA 1: Podstawowe scenariusze
    # ==========================================
    print("\n\n>>> GRUPA 1: PODSTAWOWE SCENARIUSZE <<<")

    # Test 1.1: Brak PV (noc)
    s, _ = run_test("Noc - brak PV", {
        "pv_power": 0, "home_load": 500, "grid_power": 500,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 50
    }, {"target": 0})
    results[s] += 1

    # Test 1.2: Sloneczny dzien, duza nadwyzka
    s, _ = run_test("Sloneczny dzien - duza nadwyzka", {
        "pv_power": 8000, "home_load": 1000, "grid_power": -5000,
        "controlled_load": 0, "battery_charging": 2000, "battery_discharging": 0,
        "current_level": 0
    }, {"direction": "up"})
    results[s] += 1

    # Test 1.3: Zachmurzenie - pobieramy z sieci
    s, _ = run_test("Zachmurzenie - pobieramy z sieci", {
        "pv_power": 1500, "home_load": 1000, "grid_power": 1000,
        "controlled_load": 1500, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 75
    }, {"direction": "down"})
    results[s] += 1

    # Test 1.4: Idealny balans
    s, _ = run_test("Idealny balans (grid ~0)", {
        "pv_power": 3000, "home_load": 1000, "grid_power": 0,
        "controlled_load": 1500, "battery_charging": 500, "battery_discharging": 0,
        "current_level": 75
    }, {"direction": "same"})
    results[s] += 1

    # ==========================================
    # GRUPA 2: Scenariusze z bateria
    # ==========================================
    print("\n\n>>> GRUPA 2: SCENARIUSZE Z BATERIA <<<")

    # Test 2.1: Bateria sie laduje, mamy nadwyzke
    s, _ = run_test("Bateria laduje + nadwyzka", {
        "pv_power": 6000, "home_load": 1000, "grid_power": -2000,
        "controlled_load": 1000, "battery_charging": 2000, "battery_discharging": 0,
        "current_level": 50
    }, {"direction": "up"})
    results[s] += 1

    # Test 2.2: Bateria sie rozladowuje lekko
    s, _ = run_test("Bateria rozladowuje lekko (200W)", {
        "pv_power": 1000, "home_load": 800, "grid_power": 0,
        "controlled_load": 200, "battery_charging": 0, "battery_discharging": 200,
        "current_level": 50
    }, {"direction": "down"})
    results[s] += 1

    # Test 2.3: Bateria sie rozladowuje mocno (przypadek uzytkownika)
    s, _ = run_test("Bateria rozladowuje mocno (5000W)", {
        "pv_power": 600, "home_load": 1200, "grid_power": 0,
        "controlled_load": 1000, "battery_charging": 0, "battery_discharging": 5000,
        "current_level": 50
    }, {"target": 0})
    results[s] += 1

    # Test 2.4: Bateria rozladowuje 2000W (przypadek uzytkownika)
    s, _ = run_test("Bateria rozladowuje (2000W), PV=500W", {
        "pv_power": 500, "home_load": 600, "grid_power": 0,
        "controlled_load": 1000, "battery_charging": 0, "battery_discharging": 2000,
        "current_level": 50
    }, {"target": 0})
    results[s] += 1

    # ==========================================
    # GRUPA 2B: Scenariusze z mikroinwerterem
    # ==========================================
    print("\n\n>>> GRUPA 2B: SCENARIUSZE Z MIKROINWERTEREM <<<")

    # Test 2B.1: Mikroinwerter dodaje moc do PV
    s, _ = run_test("PV + Mikroinwerter - suma mocy", {
        "pv_power": 4000, "home_load": 1000, "grid_power": -2000,
        "controlled_load": 500, "battery_charging": 500, "battery_discharging": 0,
        "current_level": 25, "microinverter_power": 1000
    }, {"direction": "up"})  # total_pv = 5000W
    results[s] += 1

    # Test 2B.2: Niskie PV ale mikroinwerter ratuje
    s, _ = run_test("Niskie PV (80W) + Mikroinwerter (50W) = 130W", {
        "pv_power": 80, "home_load": 100, "grid_power": -30,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 10, "microinverter_power": 50
    }, {"direction": "same"})  # total_pv = 130W > 100, nie wylacza
    results[s] += 1

    # Test 2B.3: Niskie PV i mikroinwerter - suma < 100W
    s, _ = run_test("Niskie PV (50W) + Mikroinwerter (40W) = 90W", {
        "pv_power": 50, "home_load": 100, "grid_power": 50,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 20, "microinverter_power": 40
    }, {"target": 0})  # total_pv = 90W < 100, wylacza
    results[s] += 1

    # Test 2B.4: Tylko mikroinwerter (glowny PV = 0)
    s, _ = run_test("Tylko mikroinwerter (500W), glowny PV=0", {
        "pv_power": 0, "home_load": 300, "grid_power": -200,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 0, "microinverter_power": 500
    }, {"direction": "up"})  # total_pv = 500W, mozna zwiekszyc
    results[s] += 1

    # Test 2B.5: Duzy mikroinwerter, duza nadwyzka
    s, _ = run_test("Duzy mikroinwerter (3000W) + PV (5000W)", {
        "pv_power": 5000, "home_load": 1000, "grid_power": -5000,
        "controlled_load": 2000, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 100, "microinverter_power": 3000
    }, {"target": 100})  # total_pv = 8000W, juz na max
    results[s] += 1

    # ==========================================
    # GRUPA 3: Przypadki brzegowe
    # ==========================================
    print("\n\n>>> GRUPA 3: PRZYPADKI BRZEGOWE <<<")

    # Test 3.1: PV ponizej progu (99W)
    s, _ = run_test("PV ponizej progu (99W)", {
        "pv_power": 99, "home_load": 100, "grid_power": 50,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 20
    }, {"target": 0})  # PV < 100 wylacza
    results[s] += 1

    # Test 3.2: PV = 101W (tuz powyzej progu)
    s, _ = run_test("PV tuz powyzej progu (101W)", {
        "pv_power": 101, "home_load": 100, "grid_power": 50,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 20
    }, {"direction": "down"})  # grid=50 > 30, wiec redukuje
    results[s] += 1

    # Test 3.3: Grid dokladnie 30W (nowy prog)
    s, _ = run_test("Grid na granicy (30W)", {
        "pv_power": 2000, "home_load": 1000, "grid_power": 30,
        "controlled_load": 900, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 45
    }, {"direction": "same"})  # grid == 30, nie > 30
    results[s] += 1

    # Test 3.4: Grid = 31W
    s, _ = run_test("Grid tuz powyzej progu (31W)", {
        "pv_power": 2000, "home_load": 1000, "grid_power": 31,
        "controlled_load": 900, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 45
    }, {"direction": "down"})
    results[s] += 1

    # Test 3.5: Regulator juz na 0%, bateria sie rozladowuje
    s, _ = run_test("Regulator=0%, bateria rozladowuje", {
        "pv_power": 500, "home_load": 1000, "grid_power": 0,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 500,
        "current_level": 0
    }, {"target": 0})
    results[s] += 1

    # Test 3.6: Regulator juz na 100%, duza nadwyzka
    s, _ = run_test("Regulator=100%, duza nadwyzka", {
        "pv_power": 10000, "home_load": 1000, "grid_power": -7000,
        "controlled_load": 2000, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 100
    }, {"target": 100})
    results[s] += 1

    # Test 3.7: Surplus ujemny ale grid negatywny
    s, _ = run_test("Surplus<0 ale oddajemy do sieci", {
        "pv_power": 2000, "home_load": 1500, "grid_power": -200,
        "controlled_load": 1000, "battery_charging": 500, "battery_discharging": 0,
        "current_level": 50
    }, {"direction": "down"})  # surplus = 2000-1500-1000-500 = -1000 < 0
    results[s] += 1

    # ==========================================
    # GRUPA 4: Scenariusze wielocyklowe
    # ==========================================
    print("\n\n>>> GRUPA 4: SYMULACJA WIELOCYKLOWA <<<")

    # Symulacja: Nagle zachmurzenie
    print("\n" + "-"*60)
    print("SYMULACJA: Nagle zachmurzenie (PV spada 6000->1000W)")
    print("-"*60)

    level = 80  # grzalka na 80%
    for cycle in range(1, 8):
        params = {
            "pv_power": 1000, "home_load": 800, "grid_power": 600,  # pobieramy z sieci
            "controlled_load": level * 20,  # 20W na 1%
            "battery_charging": 0, "battery_discharging": 0,
            "current_level": level
        }
        result = calculate_target_level(**params)
        print(f"  Cykl {cycle}: {level}% -> {result['target_level']}% ({result['decision_path'][0]})")
        level = result['target_level']
        if level == 0:
            print(f"  -> Regulator wylaczony po {cycle} cyklach")
            break

    # Symulacja: Rozruch poranny
    print("\n" + "-"*60)
    print("SYMULACJA: Rozruch poranny (PV rosnie)")
    print("-"*60)

    level = 0
    pv_values = [100, 500, 1500, 3000, 5000, 6000, 7000, 8000]
    for cycle, pv in enumerate(pv_values, 1):
        grid = -max(0, pv - 1000 - level*20)  # uproszczony model
        params = {
            "pv_power": pv, "home_load": 1000, "grid_power": grid,
            "controlled_load": level * 20,
            "battery_charging": min(2000, max(0, pv - 1000 - level*20)),
            "battery_discharging": 0,
            "current_level": level
        }
        result = calculate_target_level(**params)
        print(f"  Cykl {cycle} (PV={pv}W): {level}% -> {result['target_level']}% (grid={grid}W)")
        level = result['target_level']

    # Symulacja: Bateria zaczyna sie rozladowywac
    print("\n" + "-"*60)
    print("SYMULACJA: Bateria zaczyna sie rozladowywac")
    print("-"*60)

    level = 70
    bat_discharge_values = [0, 100, 300, 800, 1500, 2500]
    for cycle, bat_dis in enumerate(bat_discharge_values, 1):
        params = {
            "pv_power": 2000, "home_load": 1000, "grid_power": 0,
            "controlled_load": level * 20,
            "battery_charging": 0, "battery_discharging": bat_dis,
            "current_level": level
        }
        result = calculate_target_level(**params)
        print(f"  Cykl {cycle} (Bat-={bat_dis}W): {level}% -> {result['target_level']}%")
        level = result['target_level']

    # ==========================================
    # GRUPA 5: Testy spojnosci energetycznej
    # ==========================================
    print("\n\n>>> GRUPA 5: TESTY SPOJNOSCI ENERGETYCZNEJ <<<")

    # Test 5.1: Czy bilans energii sie zgadza?
    s, r = run_test("Spojnosc bilansu energii", {
        "pv_power": 5000, "home_load": 1200, "grid_power": -1800,
        "controlled_load": 1500, "battery_charging": 500, "battery_discharging": 0,
        "current_level": 75
    }, {"direction": "up"})
    # Sprawdz: PV = dom + grzalka + bateria + grid
    # 5000 = 1200 + 1500 + 500 + 1800 = 5000
    results[s] += 1

    # Test 5.2: Niespojny bilans (blad w danych wejsciowych)
    print("\n  [INFO] Test niespojnego bilansu - algorytm nie waliduje spojnosci")
    s, _ = run_test("Niespojny bilans (dane bledne)", {
        "pv_power": 1000, "home_load": 500, "grid_power": -2000,  # skad 2000W?
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 0
    }, None)
    results[s] += 1

    # ==========================================
    # GRUPA 6: Testy ekstremalnych wartosci
    # ==========================================
    print("\n\n>>> GRUPA 6: EKSTREMALNE WARTOSCI <<<")

    # Test 6.1: Bardzo wysoka produkcja PV
    s, _ = run_test("Ekstremalna produkcja PV (15kW)", {
        "pv_power": 15000, "home_load": 500, "grid_power": -12500,
        "controlled_load": 2000, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 100
    }, {"target": 100})
    results[s] += 1

    # Test 6.2: Zerowe wszystkie wartosci
    s, _ = run_test("Wszystko zero", {
        "pv_power": 0, "home_load": 0, "grid_power": 0,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 0
    }, {"target": 0})
    results[s] += 1

    # Test 6.3: Ujemne wartosci (blad sensora?)
    s, _ = run_test("Ujemna wartosc PV (blad sensora)", {
        "pv_power": -100, "home_load": 500, "grid_power": 600,
        "controlled_load": 0, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 50
    }, {"target": 0})  # PV < 50
    results[s] += 1

    # Test 6.4: Bardzo duze pobieranie z sieci
    s, _ = run_test("Duze pobieranie z sieci (5000W)", {
        "pv_power": 1000, "home_load": 4000, "grid_power": 5000,
        "controlled_load": 2000, "battery_charging": 0, "battery_discharging": 0,
        "current_level": 100
    }, {"direction": "down"})
    results[s] += 1

    # ==========================================
    # GRUPA 7: Testy logiki priorytetow
    # ==========================================
    print("\n\n>>> GRUPA 7: TESTY PRIORYTETOW <<<")

    # Test 7.1: Bateria rozladowuje I pobieramy z sieci - co ma priorytet?
    s, r = run_test("Bateria(-) + Grid(+) - priorytet baterii", {
        "pv_power": 500, "home_load": 1000, "grid_power": 800,
        "controlled_load": 500, "battery_charging": 0, "battery_discharging": 800,
        "current_level": 50
    }, None)
    print(f"  -> Priorytet: {'Bateria (poprawnie)' if 'Bateria' in r['decision_path'][0] else 'Grid (blad!)'}")
    results[s] += 1

    # Test 7.2: PV < 50 ale bateria tez sie rozladowuje - co ma priorytet?
    s, r = run_test("PV<50 + Bateria(-) - priorytet PV", {
        "pv_power": 30, "home_load": 500, "grid_power": 0,
        "controlled_load": 200, "battery_charging": 0, "battery_discharging": 500,
        "current_level": 50
    }, {"target": 0})
    print(f"  -> Priorytet: {'PV (poprawnie)' if 'PV' in r['decision_path'][0] else 'Bateria'}")
    results[s] += 1

    # ==========================================
    # PODSUMOWANIE
    # ==========================================
    print("\n\n" + "="*60)
    print(" PODSUMOWANIE TESTOW")
    print("="*60)
    total = sum(results.values())
    print(f"  PASS: {results['PASS']}/{total}")
    print(f"  FAIL: {results['FAIL']}/{total}")
    print(f"  UNDEFINED: {results['?']}/{total}")

    if results['FAIL'] > 0:
        print("\n  WYKRYTO PROBLEMY!")
    else:
        print("\n  Wszystkie zdefiniowane testy przeszly pomyslnie")

    # ==========================================
    # ZNALEZIONE PROBLEMY
    # ==========================================
    print("\n\n" + "="*60)
    print(" ANALIZA POTENCJALNYCH PROBLEMOW")
    print("="*60)

    issues = []

    # Problem 1: Brak walidacji spojnosci
    issues.append({
        "severity": "INFO",
        "title": "Brak walidacji spojnosci energetycznej",
        "desc": "Algorytm nie sprawdza czy PV = dom + grzalka + bateria + grid"
    })

    # Problem 2: Grid na granicy 30W
    issues.append({
        "severity": "LOW",
        "title": "Martwa strefa grid 0-30W",
        "desc": "Gdy grid jest miedzy 0 a 30W (lekko pobieramy), algorytm nie reaguje"
    })

    # Problem 3: Sprawdzenie dostepnosci encji regulatora - NAPRAWIONE
    issues.append({
        "severity": "FIXED",
        "title": "Sprawdzenie dostepnosci regulatora",
        "desc": "Condition teraz sprawdza czy number.power_regulator_regulator_mocy jest dostepny"
    })

    # Problem 4: Powolne zwiekszanie vs agresywne zmniejszanie
    issues.append({
        "severity": "INFO",
        "title": "Asymetria predkosci reakcji",
        "desc": "Zwiekszanie max 10%/cykl, zmniejszanie do 20%/cykl - zamierzone, ale warto wiedziec"
    })

    # Problem 5: surplus moze byc zle obliczony
    issues.append({
        "severity": "MEDIUM",
        "title": "Surplus nie uwzglednia aktualnego grid",
        "desc": "surplus = PV - dom - grzalka - bat, ale nie uwzglednia ze grid juz kompensuje"
    })

    for i, issue in enumerate(issues, 1):
        sev_icon = {"INFO": "[i]", "LOW": "[!]", "MEDIUM": "[!!]", "HIGH": "[!!!]", "FIXED": "[OK]"}[issue["severity"]]
        print(f"\n  {i}. [{issue['severity']}] {sev_icon} {issue['title']}")
        print(f"     {issue['desc']}")

    print("\n")


if __name__ == "__main__":
    main()
