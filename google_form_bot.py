#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Forms bot con Playwright (Python)
- Modo interactivo: si no pasas argumentos, pide la URL en consola y corre.
- Respuestas aleatorias (sin "Otros") para todo lo demás.
- Para las matrices Likert:
  * Usa una PERMUTACIÓN de columnas: una columna distinta por cada fila.
  * Evita timeouts usando selectores robustos por "radiogroup" e índices.

Requisitos rápidos:
  pip install playwright
  playwright install chromium

Ejecución simple:
  python google_form_bot.py
"""
import argparse
import json
import random
import time
from pathlib import Path
from typing import Dict, List, Any

from playwright.sync_api import sync_playwright, Page, Locator

# ------------------------ Utils de bot ------------------------

def _log(msg: str):
    print(f"[bot] {msg}", flush=True)

def wait_idle(page: Page):
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
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
    """
    Regresa el contenedor de la pregunta/bloque que contenga el texto del título.
    """
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

# ------------------------ Matrices Likert ------------------------

def select_linear_scale_permutation(page: Page, group_title: str):
    """
    Selecciona una opción por fila en una matriz Likert usando una PERMUTACIÓN de columnas.
    - Encuentra el bloque por título.
    - Localiza las filas como 'div[role="radiogroup"]'.
    - Obtiene el número de columnas desde la primera fila (# de radios).
    - Hace shuffle de columnas y asigna una distinta por fila (si filas > columnas, reusa).
    """
    group = _section_by_title(page, group_title)
    if group.count() == 0:
        raise RuntimeError(f"No se encontró el bloque de escala lineal: {group_title}")

    # Todas las filas de la matriz (cada fila tiene un radiogroup con sus radios)
    rows = group.locator('div[role="radiogroup"]')
    row_count = rows.count()
    if row_count == 0:
        raise RuntimeError(f"No se detectaron filas en la matriz: {group_title}")

    # Número de columnas (radios) tomando la primera fila como referencia
    col_count = rows.nth(0).get_by_role("radio").count()
    if col_count == 0:
        # Fallback defensivo
        raise RuntimeError(f"No se detectaron columnas (radios) en la matriz: {group_title}")

    # Permutación de columnas: [0..col_count-1] barajado
    columns = list(range(col_count))
    random.shuffle(columns)

    # Si hay más filas que columnas, se reutiliza empezando desde el inicio
    for i in range(row_count):
        col_index = columns[i % col_count]
        row = rows.nth(i)
        # Asegura que la fila esté en viewport (evita click fallido por estar fuera de vista)
        row.scroll_into_view_if_needed(timeout=5000)
        target_radio = row.get_by_role("radio").nth(col_index)
        target_radio.click(timeout=15000)
        time.sleep(0.12)  # pequeño respiro entre clics

    wait_idle(page)

def select_linear_scale_from_dict(page: Page, group_title: str, rows_to_values: Dict[str, int]):
    """
    Versión que recibe un dict {texto_fila: valor(1..N)}.
    Se mantiene por compatibilidad si quieres fijar manualmente cada fila.
    """
    group = _section_by_title(page, group_title)
    if group.count() == 0:
        raise RuntimeError(f"No se encontró el bloque de escala lineal: {group_title}")

    for row_text, value in rows_to_values.items():
        # Busca la fila por el texto y hace click por índice (value-1)
        row = group.locator('div[role="radiogroup"]').filter(
            has=group.get_by_text(row_text, exact=False)
        ).first
        if row.count() == 0:
            # Fallback: busca cualquier div que contenga el texto y dentro sus radios
            row = group.locator('div').filter(
                has=group.get_by_text(row_text, exact=False)
            ).first
        # Asegura estar a la vista
        row.scroll_into_view_if_needed(timeout=5000)

        radios = row.get_by_role("radio")
        col_count = radios.count()
        idx = max(0, min(value - 1, col_count - 1))
        radios.nth(idx).click(timeout=15000)
        time.sleep(0.12)

    wait_idle(page)

# ------------------------ Banco de opciones (sin "Otros") ------------------------

OPTS = {
    "semestre": ["1 - 3", "4 - 5", "6 - 9", "10 - 15", "Egresado / Profesional"],  # sin "Otros"
    "herramientas": ["Packet Tracer", "GNS3", "EVE-NG", "Wireshark", "Snort", "Matlab", "Ninguno"],
    "so_virtualizados_main": ["Ubuntu LTS (Desktop/Server)", "Debian", "Kali Linux", "Windows Server 2019/2022", "pfSense (firewall/router)"],
    "impedimentos_main": [
        "Bajo rendimiento del equipo (CPU/RAM/disco; el programa se congela o va lento)",
        "Sistema operativo/versión no compatible (Windows/macOS/Linux/ARM)",
        "Drivers o dependencias faltantes (.NET/Java/SDKs, controladores de GPU/red)",
        "Virtualización/Docker/WSL no funcionan (VT-x/AMD-V desactivado, errores de arranque)",
        "Restricciones de red/seguridad (antivirus, firewall, VPN o internet inestable)",
    ],
    "tipo_equipo": ["Laptop (Portátil)", "Computadora de escritorio (Desktop)"],  # sin "Otros"
    "cpu": ["Intel", "AMD", "Apple (Serie M)"],  # sin "Otros"
    "ram": ["4GB o menos", "8 GB", "16 GB", "32 GB o más"],
    "tipo_almacenamiento": ["Disco de Estado Sólido (SSD)", "Disco duro Mecánico (HDD)", "Híbrido (SSD + HDD)"],
    "capacidad": ["256 GB o menos", "512 GB", "1 TB", "Más de 1 TB"],
    "gpu": ["Integrados", "Dedicados"],
    "preferencia": ["Servicios en la nube", "Computadora personal"],
}

def random_subset(pool: List[str], min_items: int, max_items: int) -> List[str]:
    k = random.randint(min_items, max_items)
    k = max(0, min(k, len(pool)))
    return random.sample(pool, k) if k > 0 else []

def build_random_answers() -> Dict[str, Any]:
    """
    Genera JSON de respuestas aleatorias (sin "Otros").
    Ojo: Las matrices no se generan aquí; se resuelven con PERMUTACIÓN en tiempo real.
    """
    # Página 1
    if random.random() < 0.15:
        herramientas = ["Ninguno"]
    else:
        pool_h = [x for x in OPTS["herramientas"] if x != "Ninguno"]
        herramientas = random_subset(pool_h, 1, min(4, len(pool_h)))

    if random.random() < 0.20:
        so_virtualizados = ["No uso virtualización"]
    else:
        so_virtualizados = random_subset(OPTS["so_virtualizados_main"], 1, min(3, len(OPTS["so_virtualizados_main"])))

    if random.random() < 0.20:
        impedimentos = ["Ninguno"]
    else:
        impedimentos = random_subset(OPTS["impedimentos_main"], 1, min(3, len(OPTS["impedimentos_main"])))

    page1 = {
        "semestre": random.choice(OPTS["semestre"]),
        "herramientas": herramientas,
        "so_virtualizados": so_virtualizados,
        "impedimentos": impedimentos,
    }

    # Página 2
    page2 = {
        "tipo_equipo": random.choice(OPTS["tipo_equipo"]),
        "cpu": random.choice(OPTS["cpu"]),
        "ram": random.choice(OPTS["ram"]),
        "tipo_almacenamiento": random.choice(OPTS["tipo_almacenamiento"]),
        "capacidad_almacenamiento": random.choice(OPTS["capacidad"]),
        "gpu": random.choice(OPTS["gpu"]),
    }

    # Página 3 (las matrices se resuelven con permutación; no se pone dict aquí)
    page3 = {
        "preferencia": random.choice(OPTS["preferencia"]),
        # banderas para usar permutación:
        "beneficios_permutar": True,
        "preocupaciones_permutar": True,
    }

    return {"page1": page1, "page2": page2, "page3": page3}

# ------------------------ Ejecución principal ------------------------

def run_bot(url: str, answers: Dict[str, Any], headless: bool = True, slowmo: int = 0, screenshots: bool = True):
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

        if screenshots: page.screenshot(path="page1_filled.png", full_page=True)
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

        if screenshots: page.screenshot(path="page2_filled.png", full_page=True)
        click_next(page, "Siguiente")

        # === PAGE 3 ===
        p3 = answers.get("page3", {})
        if p3:
            if "preferencia" in p3:
                select_radio(page, "¿Prefieres utilizar un servicio", p3["preferencia"])

            # MATRIZ 1: BENEFICIOS (permutación por defecto)
            if p3.get("beneficios_permutar", True):
                select_linear_scale_permutation(page, "¿Qué beneficios considera más importantes")
            else:
                # compatibilidad si mandas un dict específico
                if isinstance(p3.get("beneficios"), dict):
                    select_linear_scale_from_dict(page, "¿Qué beneficios considera más importantes", p3["beneficios"])
                else:
                    # si no hay dict, usa permutación
                    select_linear_scale_permutation(page, "¿Qué beneficios considera más importantes")

            # MATRIZ 2: PREOCUPACIONES (permutación por defecto)
            if p3.get("preocupaciones_permutar", True):
                select_linear_scale_permutation(page, "¿Qué preocupaciones le genera el uso")
            else:
                if isinstance(p3.get("preocupaciones"), dict):
                    select_linear_scale_from_dict(page, "¿Qué preocupaciones le genera el uso", p3["preocupaciones"])
                else:
                    select_linear_scale_permutation(page, "¿Qué preocupaciones le genera el uso")

        if screenshots: page.screenshot(path="page3_filled.png", full_page=True)
        click_submit(page, "Enviar")

        if screenshots: page.screenshot(path="submitted.png", full_page=True)
        _log("Formulario enviado. Revisa submitted.png para confirmar.")

        ctx.close()
        browser.close()

def main():
    ap = argparse.ArgumentParser(description="Google Forms bot con modo interactivo (si no pasas argumentos).")
    ap.add_argument("--url", required=False, help="URL de vista del formulario (viewform)")
    ap.add_argument("--answers", default="answers.json", help="Archivo JSON con respuestas")
    ap.add_argument("--random", action="store_true", help="Generar respuestas aleatorias (ignora --answers)")
    ap.add_argument("--seed", type=int, default=None, help="Semilla para aleatoriedad reproducible")
    ap.add_argument("--print-answers", action="store_true", help="Imprime las respuestas que se usarán antes de enviar")
    ap.add_argument("--headful", action="store_true", help="Lanza navegador visible")
    ap.add_argument("--slowmo", type=int, default=0, help="Milisegundos de retardo por acción (debug)")
    args = ap.parse_args()

    # ====== Modo interactivo ======
    url = args.url or input("Pega la URL del formulario (viewform): ").strip()
    if not url:
        print("[bot] No se proporcionó URL. Saliendo.")
        return

    if args.seed is None:
        seed_str = input("Semilla (opcional, Enter para omitir): ").strip()
        if seed_str:
            try:
                args.seed = int(seed_str)
            except ValueError:
                print("[bot] Semilla inválida, se omite.")
                args.seed = None
    if args.seed is not None:
        random.seed(args.seed)

    use_random = args.random
    if not args.random:
        opt = input("¿Usar respuestas aleatorias (sin 'Otros')? [S/n]: ").strip().lower()
        use_random = (opt in ("", "s", "si", "sí", "y", "yes"))

    if not args.headful:
        opt = input("¿Mostrar navegador (headful)? [S/n]: ").strip().lower()
        args.headful = (opt in ("", "s", "si", "sí", "y", "yes"))

    if args.headful and args.slowmo == 0:
        sm = input("Slowmo ms (Enter para 150): ").strip()
        args.slowmo = int(sm) if sm else 150

    # Carga/crea respuestas
    if use_random:
        answers = build_random_answers()
        if not args.print_answers:
            opt = input("¿Imprimir respuestas (excepto matrices) antes de enviar? [s/N]: ").strip().lower()
            args.print_answers = (opt in ("s", "si", "sí", "y", "yes"))
    else:
        p = Path(args.answers or "answers.json")
        if not p.exists():
            alt = input(f"No se encontró '{p}'. Ruta alternativa (o Enter para cancelar): ").strip()
            if not alt:
                print("[bot] No hay archivo de respuestas. Saliendo.")
                return
            p = Path(alt)
        answers = json.loads(p.read_text(encoding="utf-8"))

    if args.print_answers:
        print(json.dumps(answers, ensure_ascii=False, indent=2))

    run_bot(url=url, answers=answers, headless=(not args.headful), slowmo=args.slowmo, screenshots=True)

if __name__ == "__main__":
    main()
