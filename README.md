# BetPro

Sistema interno de reportes diarios para trading deportivo.

## Base de datos (SQLite — gratis)

BetPro guarda **toda la información en SQLite**, incluido en Python. **No hay que comprar nada** ni instalar MySQL/PostgreSQL.

| | |
|---|---|
| **Archivo** | `betpro.db` (en la carpeta del proyecto) |
| **Costo** | $0 — 100% gratuito |
| **Límite** | Ideal para equipos pequeños/medianos (miles de reportes) |
| **Migración futura** | Cuando crezcan, se puede pasar a PostgreSQL o MySQL sin cambiar la lógica de la app |

### Qué se guarda

- Usuarios (admin y clientes)
- Reportes diarios (estado: borrador / enviado / confirmado)
- Cargues, retiros y descuentos por día
- Totales e historial

### Respaldo (importante)

Copia el archivo o ejecuta:

```powershell
python backup_db.py
```

O doble clic en **`respaldo.bat`**. Los respaldos quedan en la carpeta `backups/`.

### Cambiar ubicación del archivo DB

```powershell
set BETPRO_DB_PATH=D:\Datos\Betpro\betpro.db
python -m uvicorn app.main:app --reload
```

## Funciones

- **Login** para administradores y clientes
- **Panel diario** con cargues, retiros y descuentos
- **Tarifa por retiro** configurable por cliente (admin)
- **Confirmación de reportes** por el admin
- **Dashboard** con ingresos, retiros y progreso
- **Cálculo automático** del total del día y acumulado histórico

## Fórmula del total diario

```
Total del día = Total retiros − Total cargues − (Cant. retiros × Tarifa) − Otros descuentos
```

## Requisitos

- Python 3.10+

## Instalación

```powershell
cd c:\Users\pc\Desktop\Betpro
python -m pip install -r requirements.txt
python seed.py
```

## Ejecutar

Doble clic en **`iniciar.bat`** o:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Abre: http://127.0.0.1:8000

## Usuario admin inicial

| Campo | Valor |
|-------|-------|
| Nombre | Nicolas Osorio |
| Usuario | `nosorio` |
| Contraseña | `Nosorio2026!` (cámbiala en producción con `BETPRO_ADMIN_PASSWORD`) |
| Rol | admin |

Para resetear la base de datos local:

```powershell
python reset_db.py
```

## Cuándo migrar a otra base de datos

SQLite es suficiente mientras:
- Un solo servidor ejecuta BetPro
- Pocos usuarios conectados a la vez (normal en uso interno)

Considere **PostgreSQL** (también gratis en muchos hostings) cuando:
- Necesiten acceso desde varios servidores a la vez
- Tengan cientos de miles de registros y reportes muy pesados

El esquema en `sql/schema.sql` sirve de referencia para esa migración.

## Repositorio

Código en GitHub: [Noa0910/Betpro](https://github.com/Noa0910/Betpro)

## Desplegar en Vercel

BetPro incluye configuración lista para [Vercel](https://vercel.com):

1. Importa el repositorio en Vercel (New Project → GitHub → `Noa0910/Betpro`).
2. Framework Preset: **Other** (Vercel detecta `vercel.json` y Python).
3. Añade variables de entorno en **Settings → Environment Variables**:

| Variable | Obligatorio | Descripción |
|----------|-------------|-------------|
| `BETPRO_SECRET` | Sí | Texto largo aleatorio para sesiones |
| `BETPRO_ADMIN_PASSWORD` | Recomendado | Contraseña del admin inicial |
| `BETPRO_ADMIN_USER` | No | Usuario admin (default: `nosorio`) |

4. Deploy. La primera visita crea las tablas y el usuario admin si la BD está vacía.

### Base de datos persistente en Vercel (Turso — gratis)

Sin Turso, Vercel guarda datos en `/tmp` y **se pierden**. Para producción:

1. Crea cuenta en [turso.tech](https://turso.tech) (gratis).
2. Instala CLI (opcional): `curl -sSfL https://get.tur.so/install.sh | bash`
3. Crea la base de datos:

```bash
turso auth login
turso db create betpro
turso db show betpro --url
turso db tokens create betpro
```

4. En **Vercel → Settings → Environment Variables**, añade:

| Variable | Valor |
|----------|-------|
| `TURSO_DATABASE_URL` | `libsql://betpro-xxx.turso.io` |
| `TURSO_AUTH_TOKEN` | token generado arriba |
| `BETPRO_SECRET` | texto aleatorio largo |
| `BETPRO_ADMIN_PASSWORD` | contraseña segura del admin |

5. **Redeploy** el proyecto (Deployments → ⋯ → Redeploy).

6. Abre `https://www.betpro.management/acceso` — usuario `nosorio` y la contraseña en `BETPRO_ADMIN_PASSWORD`.

Turso es SQLite en la nube: mismo motor, datos permanentes, plan gratis suficiente para uso interno.

### Importante: SQLite en /tmp (sin Turso)

Si no configuras Turso, Vercel usa `/tmp/betpro.db`. Ese archivo **no persiste**. Solo sirve para pruebas.

### Archivos de deploy

- `vercel.json` — rutas y runtime Python
- `api/index.py` — entrada ASGI para Vercel
- `public/static/` — CSS/JS servidos por la CDN de Vercel
