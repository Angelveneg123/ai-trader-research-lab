# V1.8.1 — Auditoría exploratoria

**No habilita trading real, no conecta API de IA y no calcula ganancias en USD.**

## Instalación segura
1. Detener backend y frontend.
2. Respaldar íntegramente la carpeta `data` existente y los archivos `.env` / `.env.local`.
3. Extraer este ZIP en una carpeta NUEVA; no sobrescribir la carpeta actual sin respaldo.
4. Copiar `data` desde el proyecto actual a la carpeta nueva. El ZIP no contiene bases SQLite.
5. Si se usa `.env.local`, mantener `VITE_API_BASE_URL=http://127.0.0.1:8001`.
6. Iniciar backend: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload`.

## Endpoint nuevo
`GET /api/backtest/audit?symbol=EURUSD&spread_points=9&point_size=0.00001&slippage_points=0`

Incluye resultados de entrenamiento/prueba, revisión limitada de las primeras 25 operaciones y estrés de spread 1x/1.5x/2x. **No representa una auditoría completa de las 724 operaciones**; las limitaciones se señalan explícitamente.

## Pendientes bloqueantes
- Auditoría independiente de TODAS las operaciones y de su secuencia intrabar.
- Datos bid/ask y spreads históricos, comisiones, swap y slippage realista.
- `symbol_info` de MT5: volumen mínimo, paso de volumen, contrato, tick size/value, stops level.
- Diagnóstico por horario/volatilidad y estrategias alternativas bajo protocolo de validación predefinido.
- No usar la partición de prueba para ajustar parámetros.
