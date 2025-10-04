#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Forms bot con Playwright (Python) — visible y sin capturas
- Chromium visible por defecto (headful) + slowmo para observar los clicks.
- Genera respuestas según distribuciones embebidas (aprox. del Excel), con variación.
- En checkbox selecciona >= 2 opciones (cuando aplique) y maneja exclusivas.

Requisitos:
  pip install playwright
  playwright install chromium

Ejemplos:
  python google_form_bot.py --url "https://docs.google.com/forms/d/e/.../viewform"
  python google_form_bot.py --url "..." --headless         # si lo quieres oculto
  python google_form_bot.py --url "..." --slowmo 80        # ajusta velocidad
"""
import argparse
import json
import random
import time
from pathlib import Path
from typing import Dict, List, Any, Sequence, Optional, Tuple

from playwright.sync_api import sync_playwright, Page, Locator

# ============================================================
# Utils
# ============================================================

def _log(msg: str):
    print(f"[bot] {msg}", flush=True)

def wait_idle(page: Page, timeout_ms: int = 8000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass

def click_next(page: Page, name: str = "Siguiente"):
    btn = page.get_by_role("button", name=name)
    if btn.count() == 0 and name.lower() == "siguiente":
        btn = page.get_by_role("button", name="Next")
    btn.first.click()
    wait_idle(page)

def click_submit(page: Page, name: str = "Enviar"):
    btn = page.get_by_role("button", name=name)
    if btn.count() == 0:
        btn = page.get_by_role("button", name="Submit")
    btn.first.click()
    wait_idle(page)

def _section_by_title(page: Page, title_substr: str) -> Locator:
    candidates = page.locator('div[role="listitem"]')
    container = candidates.filter(has=page.get_by_text(title_substr, exact=False)).first
    return container

def select_radio(page: Page, question_title: str, choice_text: str):
    cont = _section_by_title(page, question_title)
    if cont.count() == 0:
        raise RuntimeError(f"No se encontró la pregunta (radio): {question_title}")
    radio = cont.get_by_role("radio", name=choice_text, exact=False)
    if radio.count() == 0:
        radio = cont.get_by_text(choice_text, exact=False)
    radio.first.click()
    wait_idle(page)

def select_checkboxes(page: Page, question_title: str, choices: List[str]):
    cont = _section_by_title(page, question_title)
    if cont.count() == 0:
        raise RuntimeError(f"No se encontró la pregunta (checkbox): {question_title}")
    for choice in choices:
        cb = cont.get_by_role("checkbox", name=choice, exact=False)
        if cb.count() == 0:
            cb = cont.get_by_text(choice, exact=False)
        try:
            attr = cb.first.get_attribute("aria-checked")
            already = (attr == "true")
        except Exception:
            already = False
        if not already:
            cb.first.click()
            time.sleep(0.2)
    wait_idle(page)

# ============================================================
# Matrices Likert
# ============================================================

def select_linear_scale_permutation(page: Page, group_title: str):
    group = _section_by_title(page, group_title)
    if group.count() == 0:
        raise RuntimeError(f"No se encontró el bloque de escala lineal: {group_title}")

    rows = group.locator('div[role="radiogroup"]')
    row_count = rows.count()
    if row_count == 0:
        raise RuntimeError(f"No se detectaron filas en la matriz: {group_title}")

    col_count = rows.nth(0).get_by_role("radio").count()
    if col_count == 0:
        raise RuntimeError(f"No se detectaron columnas (radios) en la matriz: {group_title}")

    columns = list(range(col_count))
    random.shuffle(columns)

    for i in range(row_count):
        col_index = columns[i % col_count]
        row = rows.nth(i)
        row.scroll_into_view_if_needed(timeout=5000)
        target_radio = row.get_by_role("radio").nth(col_index)
        target_radio.click(timeout=15000)
        time.sleep(0.12)

    wait_idle(page)

def select_linear_scale_from_dict(page: Page, group_title: str, rows_to_values: Dict[str, int]):
    group = _section_by_title(page, group_title)
    if group.count() == 0:
        raise RuntimeError(f"No se encontró el bloque de escala lineal: {group_title}")

    for row_text, value in rows_to_values.items():
        row = group.locator('div[role="radiogroup"]').filter(
            has=group.get_by_text(row_text, exact=False)
        ).first
        if row.count() == 0:
            row = group.locator('div').filter(
                has=group.get_by_text(row_text, exact=False)
            ).first
        row.scroll_into_view_if_needed(timeout=5000)

        radios = row.get_by_role("radio")
        col_count = radios.count()
        idx = max(0, min(value - 1, col_count - 1))
        radios.nth(idx).click(timeout=15000)
        time.sleep(0.12)

    wait_idle(page)

# ============================================================
# Catálogo y PESOS (probabilidades) embebidos
# ============================================================

OPTS = {
    "semestre": ["1 - 3", "4 - 5", "6 - 9", "10 - 15", "Egresado / Profesional"],
    "herramientas": ["Packet Tracer", "GNS3", "EVE-NG", "Wireshark", "Snort", "Matlab", "Ninguno"],
    "so_virtualizados_main": ["Ubuntu LTS (Desktop/Server)", "Debian", "Kali Linux", "Windows Server 2019/2022", "pfSense (firewall/router)"],
    "impedimentos_main": [
        "Bajo rendimiento del equipo (CPU/RAM/disco; el programa se congela o va lento)",
        "Sistema operativo/versión no compatible (Windows/macOS/Linux/ARM)",
        "Drivers o dependencias faltantes (.NET/Java/SDKs, controladores de GPU/red)",
        "Virtualización/Docker/WSL no funcionan (VT-x/AMD-V desactivado, errores de arranque)",
        "Restricciones de red/seguridad (antivirus, firewall, VPN o internet inestable)",
    ],
    "tipo_equipo": ["Laptop (Portátil)", "Computadora de escritorio (Desktop)"],
    "cpu": ["Intel", "AMD", "Apple (Serie M)"],
    "ram": ["4GB o menos", "8 GB", "16 GB", "32 GB o más"],
    "tipo_almacenamiento": ["Disco de Estado Sólido (SSD)", "Disco duro Mecánico (HDD)", "Híbrido (SSD + HDD)"],
    "capacidad": ["256 GB o menos", "512 GB", "1 TB", "Más de 1 TB"],
    "gpu": ["Integrados", "Dedicados"],
    "preferencia": ["Servicios en la nube", "Computadora personal"],
}

WEIGHTS: Dict[str, Dict[str, float]] = {
    "semestre": {
        "6 - 9": 0.60,
        "10 - 15": 0.18,
        "1 - 3": 0.10,
        "4 - 5": 0.08,
        "Egresado / Profesional": 0.04,
    },
    "herramientas": {
        "Matlab": 0.35,
        "Packet Tracer": 0.23,
        "Wireshark": 0.19,
        "GNS3": 0.04,
        "Snort": 0.04,
        "EVE-NG": 0.02,
        "Ninguno": 0.03,
    },
    "so_virtualizados_main": {
        "Ubuntu LTS (Desktop/Server)": 0.35,
        "Kali Linux": 0.25,
        "Debian": 0.15,
        "Windows Server 2019/2022": 0.20,
        "pfSense (firewall/router)": 0.05,
    },
    "impedimentos_main": {
        "Bajo rendimiento del equipo (CPU/RAM/disco; el programa se congela o va lento)": 0.35,
        "Sistema operativo/versión no compatible (Windows/macOS/Linux/ARM)": 0.20,
        "Drivers o dependencias faltantes (.NET/Java/SDKs, controladores de GPU/red)": 0.25,
        "Virtualización/Docker/WSL no funcionan (VT-x/AMD-V desactivado, errores de arranque)": 0.10,
        "Restricciones de red/seguridad (antivirus, firewall, VPN o internet inestable)": 0.10,
    },
    "tipo_equipo": {
        "Laptop (Portátil)": 0.80,
        "Computadora de escritorio (Desktop)": 0.20,
    },
    "cpu": {"Intel": 0.75, "AMD": 0.18, "Apple (Serie M)": 0.07},
    "ram": {"4GB o menos": 0.15, "8 GB": 0.40, "16 GB": 0.35, "32 GB o más": 0.10},
    "tipo_almacenamiento": {"Disco de Estado Sólido (SSD)": 0.80, "Disco duro Mecánico (HDD)": 0.15, "Híbrido (SSD + HDD)": 0.05},
    "capacidad": {"256 GB o menos": 0.25, "512 GB": 0.35, "1 TB": 0.30, "Más de 1 TB": 0.10},
    "gpu": {"Integrados": 0.70, "Dedicados": 0.30},
    "preferencia": {"Servicios en la nube": 0.60, "Computadora personal": 0.40},
}

P_NO_VIRTUALIZA = 0.18  # exclusividad "No uso virtualización"

# ============================================================
# Helpers de muestreo
# ============================================================

def _normalize(weights: Dict[str, float]) -> List[Tuple[str, float]]:
    items = [(k, max(0.0, float(v))) for k, v in weights.items()]
    s = sum(w for _, w in items)
    if s <= 0:
        n = len(items)
        return [(k, 1.0 / n) for k, _ in items]
    return [(k, w / s) for k, w in items]

def weighted_choice(options: Sequence[str], weights_map: Dict[str, float]) -> str:
    items = _normalize({opt: weights_map.get(opt, 0.0) for opt in options})
    choices, probs = zip(*items)
    r = random.random(); acc = 0.0
    for choice, p in zip(choices, probs):
        acc += p
        if r <= acc:
            return choice
    return choices[-1]

def weighted_sample_unique(options: Sequence[str], weights_map: Dict[str, float], k: int) -> List[str]:
    k = max(0, min(k, len(options)))
    remaining = list(options)
    selected: List[str] = []
    for _ in range(k):
        if not remaining:
            break
        pick = weighted_choice(remaining, weights_map)
        selected.append(pick)
        remaining.remove(pick)
    return selected

def random_k_for_checkbox(min_k: int, max_k: int) -> int:
    return int(round(random.triangular(min_k, max_k, min_k)))

# ============================================================
# Generador de respuestas
# ============================================================

def build_prob_answers() -> Dict[str, Any]:
    # Página 1
    semestre = weighted_choice(OPTS["semestre"], WEIGHTS["semestre"])

    if random.random() < WEIGHTS["herramientas"].get("Ninguno", 0.03):
        herramientas = ["Ninguno"]
    else:
        pool = [h for h in OPTS["herramientas"] if h != "Ninguno"]
        k = random_k_for_checkbox(2, min(4, len(pool)))
        herramientas = weighted_sample_unique(pool, WEIGHTS["herramientas"], k)

    if random.random() < P_NO_VIRTUALIZA:
        so_virtualizados = ["No uso virtualización"]
    else:
        pool = OPTS["so_virtualizados_main"]
        k = random_k_for_checkbox(2, min(3, len(pool)))
        so_virtualizados = weighted_sample_unique(pool, WEIGHTS["so_virtualizados_main"], k)

    imp_pool = OPTS["impedimentos_main"]
    k_imp = random_k_for_checkbox(2, min(3, len(imp_pool)))
    impedimentos = weighted_sample_unique(imp_pool, WEIGHTS["impedimentos_main"], k_imp)

    page1 = {
        "semestre": semestre,
        "herramientas": herramientas,
        "so_virtualizados": so_virtualizados,
        "impedimentos": impedimentos,
    }

    # Página 2
    page2 = {
        "tipo_equipo": weighted_choice(OPTS["tipo_equipo"], WEIGHTS["tipo_equipo"]),
        "cpu": weighted_choice(OPTS["cpu"], WEIGHTS["cpu"]),
        "ram": weighted_choice(OPTS["ram"], WEIGHTS["ram"]),
        "tipo_almacenamiento": weighted_choice(OPTS["tipo_almacenamiento"], WEIGHTS["tipo_almacenamiento"]),
        "capacidad_almacenamiento": weighted_choice(OPTS["capacidad"], WEIGHTS["capacidad"]),
        "gpu": weighted_choice(OPTS["gpu"], WEIGHTS["gpu"]),
    }

    # Página 3
    page3 = {
        "preferencia": weighted_choice(OPTS["preferencia"], WEIGHTS["preferencia"]),
        "beneficios_permutar": True,
        "preocupaciones_permutar": True,
    }

    return {"page1": page1, "page2": page2, "page3": page3}

# ============================================================
# Runner
# ============================================================

def run_bot(url: str, answers: Dict[str, Any], headless: bool = False, slowmo: int = 120):
    """
    headless=False por defecto para ver Chromium; slowmo para observar el llenado.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slowmo)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        wait_idle(page)

        # === PAGE 1 ===
        p1 = answers.get("page1", {})
        if p1:
            if "semestre" in p1:
                select_radio(page, "¿En qué semestre te encuentras?", p1["semestre"])

            if "herramientas" in p1 and isinstance(p1["herramientas"], list):
                select_checkboxes(page, "¿Qué herramientas usas hoy para prácticas?", p1["herramientas"])

            if "so_virtualizados" in p1 and isinstance(p1["so_virtualizados"], list):
                select_checkboxes(page, "¿Qué sistemas operativos virtualizas en tu equipo personal?", p1["so_virtualizados"])

            if "impedimentos" in p1 and isinstance(p1["impedimentos"], list):
                select_checkboxes(page, "¿qué es lo que falla o te impide usarlos correctamente en tu equipo personal?", p1["impedimentos"])

        click_next(page, "Siguiente")

        # === PAGE 2 ===
        p2 = answers.get("page2", {})
        if p2:
            if "tipo_equipo" in p2:
                select_radio(page, "¿Qué tipo de equipo utilizar", p2["tipo_equipo"])

            if "cpu" in p2:
                select_radio(page, "¿Con qué procesador cuenta tu equipo", p2["cpu"])

            if "ram" in p2:
                select_radio(page, "¿Con cuánta memoria RAM", p2["ram"])

            if "tipo_almacenamiento" in p2:
                select_radio(page, "¿Cuál es el tipo de almacenamiento principal", p2["tipo_almacenamiento"])

            if "capacidad_almacenamiento" in p2:
                select_radio(page, "¿Cuál es la capacidad total de memoria principal aproximada", p2["capacidad_almacenamiento"])

            if "gpu" in p2:
                select_radio(page, "¿Con qué tipo de gráficos cuenta tu equipo principal", p2["gpu"])

        click_next(page, "Siguiente")

        # === PAGE 3 ===
        p3 = answers.get("page3", {})
        if p3:
            if "preferencia" in p3:
                select_radio(page, "¿Prefieres utilizar un servicio", p3["preferencia"])

            if p3.get("beneficios_permutar", True):
                select_linear_scale_permutation(page, "¿Qué beneficios considera más importantes")
            else:
                if isinstance(p3.get("beneficios"), dict):
                    select_linear_scale_from_dict(page, "¿Qué beneficios considera más importantes", p3["beneficios"])
                else:
                    select_linear_scale_permutation(page, "¿Qué beneficios considera más importantes")

            if p3.get("preocupaciones_permutar", True):
                select_linear_scale_permutation(page, "¿Qué preocupaciones le genera el uso")
            else:
                if isinstance(p3.get("preocupaciones"), dict):
                    select_linear_scale_from_dict(page, "¿Qué preocupaciones le genera el uso", p3["preocupaciones"])
                else:
                    select_linear_scale_permutation(page, "¿Qué preocupaciones le genera el uso")

        click_submit(page, "Enviar")
        _log("Formulario enviado.")

        ctx.close()
        browser.close()

# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(description="Google Forms bot visible y sin capturas.")
    ap.add_argument("--url", required=False, help="URL de vista del formulario (viewform)")
    ap.add_argument("--answers", default=None, help="Archivo JSON con respuestas (si no quieres probabilidades)")
    ap.add_argument("--seed", type=int, default=None, help="Semilla para aleatoriedad reproducible")
    ap.add_argument("--slowmo", type=int, default=120, help="Milisegundos de retardo por acción (default 120)")
    ap.add_argument("--headless", action="store_true", help="Ejecuta en modo headless (por defecto visible)")
    args = ap.parse_args()

    url = args.url or input("Pega la URL del formulario (viewform): ").strip()
    if not url:
        print("[bot] No se proporcionó URL. Saliendo.")
        return

    if args.seed is not None:
        random.seed(args.seed)

    if args.answers:
        p = Path(args.answers)
        if not p.exists():
            alt = input(f"No se encontró '{p}'. Ruta alternativa (o Enter para cancelar): ").strip()
            if not alt:
                print("[bot] No hay archivo de respuestas. Saliendo.")
                return
            p = Path(alt)
        answers = json.loads(p.read_text(encoding="utf-8"))
    else:
        answers = build_prob_answers()

    run_bot(url=url, answers=answers, headless=args.headless, slowmo=args.slowmo)

if __name__ == "__main__":
    main()
