# Jira Time Logger CLI

CLI en Python para registrar worklogs en Jira/Tempo desde la terminal, sin necesidad de abrir el navegador ni Claude Desktop.

## Requisitos

- Python 3.7 o superior
- Acceso a una instancia de Atlassian Jira (Cloud)
- Un API Token de Atlassian

## Instalación

### 1. Clona el repositorio

```bash
git clone https://github.com/tu-usuario/jira-log-cli.git
cd jira-log-cli
```

### 2. Genera tu API Token de Atlassian

1. Ve a: https://id.atlassian.com/manage-profile/security/api-tokens
2. Clic en **"Create API token"**
3. Nombre sugerido: `jira-log-cli`
4. Copia el token generado (solo se muestra una vez)

### 3. Configura tus credenciales

```bash
copy .env.example .env
notepad .env
```

Reemplaza `PEGA_AQUI_TU_API_TOKEN` con tu token y guarda.

> ⚠️ El archivo `.env` está en `.gitignore` y nunca debe subirse a Git.

## Uso

### Sintaxis

```bash
python jira_log.py "TICKET,TIEMPO,HORA,Descripcion" [...]
```

| Campo | Formato | Ejemplo |
|-------|---------|---------|
| TICKET | Clave Jira | `GXST-7` |
| TIEMPO | Duración | `30m`, `1h`, `2h30m`, `1d` |
| HORA | Inicio HH:MM | `08:30`, `09:00` |
| Descripcion | Texto libre | `Daily`, `Reunion soporte` |

### Ejemplos

**Registrar el día de hoy:**
```bash
python jira_log.py "GXST-35,30m,08:30,Daily" "MDMLPSE-4,1h,09:00,Soporte extendido" "GXST-7,8h,10:00,Tickets resolution"
```

**Registrar en una fecha específica:**
```bash
python jira_log.py --fecha 2026-06-17 "GXST-7,8h,09:00,Trabajo normal"
```

**Probar sin hacer cambios (dry run):**
```bash
python jira_log.py --dry-run "GXST-35,30m,08:30,Daily" "GXST-7,8h,10:00,Tickets resolution"
```

## Notas sobre zona horaria

La instancia `apvf2021.atlassian.net` usa **UTC-3** como zona horaria del servidor. El script registra con offset `-0300` para que los horarios se vean correctamente en Tempo.

## Estructura del proyecto

```
jira-log-cli/
├── jira_log.py       # Script principal
├── .env.example      # Plantilla de configuración
├── .env              # Tus credenciales (NO subir a Git)
├── requirements.txt  # Sin dependencias externas
├── .gitignore
└── README.md
```

## Subir a Git

```bash
git init
git add jira_log.py .env.example requirements.txt .gitignore README.md
git commit -m "feat: jira time logger CLI"
git remote add origin https://github.com/tu-usuario/jira-log-cli.git
git push -u origin main
```
