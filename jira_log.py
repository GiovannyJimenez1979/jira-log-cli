#!/usr/bin/env python3
"""
jira_log.py — CLI para registrar worklogs en Jira/Tempo desde la terminal.

Formatos aceptados por entrada:
  TICKET,TIEMPO,HORA,Descripcion  -> hora exacta
  TICKET,TIEMPO,Descripcion       -> sin hora (se ubica despues del ultimo worklog del dia)
  TICKET,TIEMPO                   -> sin hora ni descripcion

Ejemplo mixto:
    python jira_log.py \
        "GXST-35,30m,08:30,Daily" \
        "MDMLPSE-4,1h,09:00,Reunion soporte" \
        "GXST-7,7h"

Opciones:
    --fecha YYYY-MM-DD   Fecha del registro (default: hoy)
    --dry-run            Muestra lo que se registraria sin hacer cambios
"""

import argparse
import os
import re
import sys
import json
import base64
from datetime import date, datetime, timedelta
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
# Utilidades de tiempo
# ──────────────────────────────────────────────

def es_hora(s: str) -> bool:
    """Detecta si un string tiene formato HH:MM."""
    return bool(re.match(r'^\d{1,2}:\d{2}$', s.strip()))

def tiempo_a_segundos(tiempo: str) -> int:
    t = tiempo.lower().strip()
    segs = 0
    if "d" in t:
        partes = t.split("d")
        segs += int(partes[0]) * 8 * 3600
        t = partes[1]
    if "h" in t:
        partes = t.split("h")
        segs += int(partes[0]) * 3600 if partes[0] else 0
        t = partes[1]
    if "m" in t:
        m = t.replace("m", "")
        segs += int(m) * 60 if m else 0
    return segs

def tiempo_a_minutos(tiempo: str) -> int:
    return tiempo_a_segundos(tiempo) // 60

def sumar_tiempo(hora_str: str, segundos: int) -> str:
    """Suma segundos a una hora HH:MM y retorna el resultado como HH:MM."""
    dt = datetime.strptime(hora_str, "%H:%M")
    dt_fin = dt + timedelta(seconds=segundos)
    return dt_fin.strftime("%H:%M")


# ──────────────────────────────────────────────
# Parseo de entradas
# ──────────────────────────────────────────────

def parsear_entrada(entrada: str) -> dict:
    """
    Detecta automaticamente si la entrada incluye hora o no.

    Con hora:    TICKET,TIEMPO,HH:MM[,Descripcion]
    Sin hora:    TICKET,TIEMPO[,Descripcion]
    """
    partes = entrada.split(",", 3)
    if len(partes) < 2:
        print(f"ERROR: Formato invalido: '{entrada}'")
        print("   Minimo requerido: TICKET,TIEMPO")
        sys.exit(1)

    ticket = partes[0].strip().upper()
    tiempo = partes[1].strip()

    if tiempo_a_segundos(tiempo) == 0:
        print(f"ERROR: Tiempo invalido '{tiempo}'. Usa 30m, 1h, 2h30m, 1d")
        sys.exit(1)

    # Detectar si el 3er campo es hora o descripción
    tiene_hora = len(partes) >= 3 and es_hora(partes[2])

    if tiene_hora:
        hora = partes[2].strip()
        desc = partes[3].strip() if len(partes) > 3 else ticket
        try:
            datetime.strptime(hora, "%H:%M")
        except ValueError:
            print(f"ERROR: Hora invalida '{hora}'. Usa formato HH:MM")
            sys.exit(1)
    else:
        hora = None  # se resuelve despues
        desc = partes[2].strip() if len(partes) > 2 else ticket

    return {
        "ticket":     ticket,
        "tiempo":     tiempo,
        "segundos":   tiempo_a_segundos(tiempo),
        "hora":       hora,
        "tiene_hora": tiene_hora,
        "descripcion": desc,
        "started":    None,  # se construye despues
    }


# ──────────────────────────────────────────────
# Tempo API: obtener ultimo fin de worklog del dia
# ──────────────────────────────────────────────

def obtener_ultimo_fin_tempo(fecha: str, account_id: str, tempo_token: str) -> str:
    """
    Consulta Tempo y retorna la hora de fin del ultimo worklog del dia.
    Si no hay worklogs, retorna '08:00' como hora de inicio por defecto.
    """
    url = (
        f"https://api.tempo.io/4/worklogs"
        f"?accountId={account_id}&from={fecha}&to={fecha}&limit=50"
    )
    headers = {
        "Authorization": f"Bearer {tempo_token}",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  AVISO: No se pudo consultar Tempo ({e.code}). Usando 08:00 como inicio.")
        return "08:00"

    worklogs = data.get("results", [])
    if not worklogs:
        return "08:00"

    # Calcular la hora de fin de cada worklog y quedarse con la mayor
    ultimo_fin = None
    for wl in worklogs:
        start_time = wl.get("startTime", "08:00:00")  # HH:MM:SS
        segundos   = wl.get("timeSpentSeconds", 0)
        hora_ini   = start_time[:5]  # HH:MM
        hora_fin   = sumar_tiempo(hora_ini, segundos)
        if ultimo_fin is None or hora_fin > ultimo_fin:
            ultimo_fin = hora_fin

    return ultimo_fin or "08:00"


# ──────────────────────────────────────────────
# Jira REST API: registrar worklog
# ──────────────────────────────────────────────

def registrar_worklog(ticket: str, tiempo: str, started: str, descripcion: str,
                      site_url: str, token_b64: str) -> bool:
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
Formatos:
  Con hora exacta:  "TICKET,TIEMPO,HH:MM,Descripcion"
  Sin hora:         "TICKET,TIEMPO,Descripcion"  o  "TICKET,TIEMPO"

Ejemplos:
  # Solo sin hora - el script acomoda automaticamente
  python jira_log.py "GXST-7,7h"

  # Mixto - algunos con hora exacta, otros automaticos
  python jira_log.py "GXST-35,30m,08:30,Daily" "MDMLPSE-4,1h,09:00,Soporte" "GXST-7,7h"

  # Con fecha especifica
  python jira_log.py --fecha 2026-06-17 "GXST-7,8h"
        """,
    )
    parser.add_argument(
        "entradas",
        nargs="+",
        metavar="TICKET,TIEMPO[,HORA][,Descripcion]",
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
    site_url    = env.get("JIRA_SITE_URL", "").rstrip("/")
    email       = env.get("JIRA_EMAIL", "")
    api_token   = env.get("JIRA_API_TOKEN", "")
    tempo_token = env.get("TEMPO_API_TOKEN", "")
    account_id  = env.get("JIRA_ACCOUNT_ID", "")

    for val, nombre in [(site_url, "JIRA_SITE_URL"), (email, "JIRA_EMAIL"), (api_token, "JIRA_API_TOKEN")]:
        if not val:
            print(f"ERROR: Falta {nombre} en .env")
            sys.exit(1)

    token_b64 = base64.b64encode(f"{email}:{api_token}".encode()).decode()

    # Parsear entradas
    registros = [parsear_entrada(e) for e in args.entradas]

    # Resolver horas faltantes
    necesita_cursor = any(not r["tiene_hora"] for r in registros)
    cursor = "08:00"

    if necesita_cursor:
        if tempo_token and account_id:
            print(f"Buscando ultimo worklog del dia {args.fecha}...")
            cursor = obtener_ultimo_fin_tempo(args.fecha, account_id, tempo_token)
            print(f"  Ultimo fin registrado: {cursor} — las entradas sin hora inician desde ahi.")
            print()
        else:
            print("  AVISO: Sin TEMPO_API_TOKEN/JIRA_ACCOUNT_ID en .env. Usando 08:00 como inicio.")
            print()

    # Asignar horas y construir timestamps
    for r in registros:
        if r["tiene_hora"]:
            hora = r["hora"]
            # Avanzar cursor si esta entrada supera el cursor actual
            fin = sumar_tiempo(hora, r["segundos"])
            if fin > cursor:
                cursor = fin
        else:
            hora = cursor
            r["hora"] = hora
            cursor = sumar_tiempo(hora, r["segundos"])

        r["started"] = f"{args.fecha}T{hora}:00.000-0300"

    # Mostrar resumen
    print(f"{'=' * 62}")
    print(f"  Jira Time Logger {'[DRY RUN] ' if args.dry_run else ''}-- Fecha: {args.fecha}")
    print(f"{'=' * 62}")
    print(f"  {'Ticket':<14} {'Tiempo':<8} {'Inicio':<8} {'Fin':<8} Descripcion")
    print(f"  {'-' * 56}")
    total_min = 0
    for r in registros:
        fin = sumar_tiempo(r["hora"], r["segundos"])
        auto = "" if r["tiene_hora"] else " *"
        print(f"  {r['ticket']:<14} {r['tiempo']:<8} {r['hora']:<8} {fin:<8} {r['descripcion']}{auto}")
        total_min += tiempo_a_minutos(r["tiempo"])
    total_h = total_min // 60
    total_m = total_min % 60
    total_str = f"{total_h}h {total_m}m" if total_m else f"{total_h}h"
    print(f"  {'-' * 56}")
    print(f"  {'TOTAL':<14} {total_str}")
    print(f"{'=' * 62}")
    if any(not r["tiene_hora"] for r in registros):
        print("  * Hora asignada automaticamente")
    print()

    if args.dry_run:
        print("  Modo DRY RUN - No se registro nada en Jira.\n")
        return

    # Registrar
    print("Registrando worklogs en Jira...")
    print()
    exitosos = 0
    for r in registros:
        fin = sumar_tiempo(r["hora"], r["segundos"])
        auto = "(auto)" if not r["tiene_hora"] else ""
        print(f"  >> {r['ticket']} -- {r['tiempo']} {r['hora']}-{fin} {auto}...", end=" ", flush=True)
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
        print("  -> Tempo -> Historial -> selecciona los worklogs de hoy -> Asignar cuenta")
    else:
        print("Algunos worklogs fallaron. Verifica los tickets e intentalo de nuevo.")
    print()


if __name__ == "__main__":
    main()
