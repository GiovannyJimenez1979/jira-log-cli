#!/usr/bin/env python3
"""
jira_log.py — CLI para registrar worklogs en Jira/Tempo desde la terminal.

Uso:
    python jira_log.py "TICKET,TIEMPO,HORA,Descripcion" [...]

Ejemplo:
    python jira_log.py \
        "GXST-35,30m,08:30,Daily" \
        "MDMLPSE-4,1h,09:00,Reunion soporte" \
        "GXST-7,8h,10:00,Tickets resolution"

Opciones:
    --fecha YYYY-MM-DD   Fecha del registro (default: hoy)
    --dry-run            Muestra lo que se registraria sin hacer cambios
"""

import argparse
import os
import sys
import json
import base64
from datetime import date, datetime
import urllib.request
import urllib.error


# ──────────────────────────────────────────────
# Carga de configuración desde .env
# ──────────────────────────────────────────────

def cargar_env(path: str = ".env") -> dict:
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(env_path):
        print(f"ERROR: No se encontro el archivo .env en: {env_path}")
        print("   Copia .env.example a .env y completa tus credenciales.")
        sys.exit(1)
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ──────────────────────────────────────────────
# Parseo de entradas
# ──────────────────────────────────────────────

def parsear_entrada(entrada: str, fecha: str) -> dict:
    """Parsea: TICKET,TIEMPO,HORA,Descripcion"""
    partes = entrada.split(",", 3)
    if len(partes) < 3:
        print(f"ERROR: Formato invalido: '{entrada}'")
        print("   Formato esperado: TICKET,TIEMPO,HORA,Descripcion")
        print("   Ejemplo: GXST-7,8h,10:00,Tickets resolution")
        sys.exit(1)

    ticket = partes[0].strip().upper()
    tiempo = partes[1].strip()
    hora   = partes[2].strip()
    desc   = partes[3].strip() if len(partes) > 3 else ticket

    try:
        hora_dt = datetime.strptime(hora, "%H:%M")
    except ValueError:
        print(f"ERROR: Hora invalida '{hora}'. Usa formato HH:MM (ej. 08:30)")
        sys.exit(1)

    # Timestamp con offset -03:00 (timezone del servidor Jira)
    started = f"{fecha}T{hora_dt.strftime('%H:%M')}:00.000-0300"

    return {
        "ticket":      ticket,
        "tiempo":      tiempo,
        "hora":        hora,
        "descripcion": desc,
        "started":     started,
    }


# ──────────────────────────────────────────────
# Utilidades de tiempo
# ──────────────────────────────────────────────

def tiempo_a_minutos(tiempo: str) -> int:
    t = tiempo.lower().strip()
    mins = 0
    if "d" in t:
        partes = t.split("d")
        mins += int(partes[0]) * 480
        t = partes[1]
    if "h" in t:
        partes = t.split("h")
        mins += int(partes[0]) * 60 if partes[0] else 0
        t = partes[1]
    if "m" in t:
        m = t.replace("m", "")
        mins += int(m) if m else 0
    return mins


# ──────────────────────────────────────────────
# Jira REST API
# ──────────────────────────────────────────────

def registrar_worklog(ticket: str, tiempo: str, started: str, descripcion: str,
                      site_url: str, token_b64: str) -> bool:
    """Registra un worklog en Jira via REST API v3."""
    url = f"{site_url}/rest/api/3/issue/{ticket}/worklog"
    headers = {
        "Authorization": f"Basic {token_b64}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "timeSpent": tiempo,
        "started": started,
        "comment": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": descripcion}]
                }
            ]
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return bool(result.get("id"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"\n   ERROR HTTP {e.code}: {body}")
        return False


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Registra worklogs en Jira desde la terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python jira_log.py "GXST-35,30m,08:30,Daily" "GXST-7,8h,10:00,Tickets resolution"
  python jira_log.py --fecha 2026-06-17 "MDMLPSE-97,30m,08:00,Ajustes masterclass"
  python jira_log.py --dry-run "GXST-7,2h,09:00,Prueba"
        """,
    )
    parser.add_argument(
        "entradas",
        nargs="+",
        metavar="TICKET,TIEMPO,HORA,Descripcion",
        help="Entradas a registrar",
    )
    parser.add_argument(
        "--fecha",
        default=date.today().isoformat(),
        metavar="YYYY-MM-DD",
        help="Fecha del registro (default: hoy)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra lo que se registraria sin hacer cambios",
    )

    args = parser.parse_args()

    # Cargar configuración
    env = cargar_env()
    site_url   = env.get("JIRA_SITE_URL", "").rstrip("/")
    email      = env.get("JIRA_EMAIL", "")
    api_token  = env.get("JIRA_API_TOKEN", "")

    for val, nombre in [(site_url, "JIRA_SITE_URL"), (email, "JIRA_EMAIL"), (api_token, "JIRA_API_TOKEN")]:
        if not val:
            print(f"ERROR: Falta {nombre} en .env")
            sys.exit(1)

    token_b64 = base64.b64encode(f"{email}:{api_token}".encode()).decode()

    # Parsear entradas
    registros = [parsear_entrada(e, args.fecha) for e in args.entradas]

    # Mostrar resumen
    print()
    print(f"{'=' * 60}")
    print(f"  Jira Time Logger {'[DRY RUN] ' if args.dry_run else ''}-- Fecha: {args.fecha}")
    print(f"{'=' * 60}")
    print(f"  {'Ticket':<14} {'Tiempo':<8} {'Hora':<8} Descripcion")
    print(f"  {'-' * 54}")
    total_min = 0
    for r in registros:
        print(f"  {r['ticket']:<14} {r['tiempo']:<8} {r['hora']:<8} {r['descripcion']}")
        total_min += tiempo_a_minutos(r["tiempo"])
    total_h = total_min // 60
    total_m = total_min % 60
    total_str = f"{total_h}h {total_m}m" if total_m else f"{total_h}h"
    print(f"  {'-' * 54}")
    print(f"  {'TOTAL':<14} {total_str}")
    print(f"{'=' * 60}")
    print()

    if args.dry_run:
        print("  Modo DRY RUN - No se registro nada en Jira.\n")
        return

    # Registrar
    print("Registrando worklogs en Jira...")
    print()
    exitosos = 0
    for r in registros:
        print(f"  >> {r['ticket']} -- {r['tiempo']} desde {r['hora']}...", end=" ", flush=True)
        ok = registrar_worklog(
            ticket=r["ticket"],
            tiempo=r["tiempo"],
            started=r["started"],
            descripcion=r["descripcion"],
            site_url=site_url,
            token_b64=token_b64,
        )
        if ok:
            print("OK")
            exitosos += 1
        else:
            print("FALLO")

    print()
    print(f"  Resultado: {exitosos}/{len(registros)} worklogs registrados.")
    print()
    if exitosos == len(registros):
        print("Todo registrado correctamente en Jira!")
        print()
        print("RECUERDA: Asigna la cuenta en Tempo via 'Acciones en masa'")
        print(f"  -> Tempo -> Historial -> selecciona los worklogs de hoy -> Asignar cuenta")
    else:
        print("Algunos worklogs fallaron. Verifica los tickets e intentalo de nuevo.")
    print()


if __name__ == "__main__":
    main()
