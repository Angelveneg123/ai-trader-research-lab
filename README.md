# AI Trader Research Lab V2.5 · Recuperado

[Arranque en Windows y primera prueba](README_V25.md) · [Resultados de la recuperación](evidencias/RECUPERACION.md)

# AI Trader Research Lab

[Instalación y operación de V2.3](README_V22.md). Las notas de las versiones anteriores se conservan a continuación como referencia.

# AI Trader Research Lab V1.6.1 — corrección de auditoría

Esta entrega es una actualización sobre V1.6. Mantiene el diseño React y la API de lectura. No incluye ejecución de órdenes, conexión a IA ni importación histórica.

## Correcciones
- Validación adicional de orden, alineación y OHLC en H1/M15/M5.
- Resultados futuros solo con velas M5 consecutivas, sin completar huecos.
- No se usa spread capturado posteriormente para simular costos históricos; las estimaciones netas quedan NULL.
- Conteos diferenciados: observaciones heredadas V1.5, auditorías V1.6 y resultados por horizonte.
- Etiqueta visual V1.6.1.

## Instalación y preservación de SQLite
1. Detén FastAPI. **Haz copia de seguridad de `data/research.sqlite3` y sus archivos `-wal` y `-shm` si existen** antes de mover datos. Lo más seguro es detener el proceso y copiar toda la carpeta `data`.
2. Extrae este ZIP en una carpeta nueva y copia tu base existente a `data/research.sqlite3` dentro de la nueva carpeta.
3. En `backend`: `python -m pip install -r requirements.txt` y `python -m uvicorn app.main:app --reload`.
4. En `frontend`: `npm install` y `npm run dev`.
5. Verifica `/api/research/status`, `/api/research/metrics` y `/api/research/audit`.
6. Ejecuta pruebas desde la raíz: `python -m pytest tests -q`.

**Advertencia:** los resultados posteriores antiguos de V1.6 pueden contener estimaciones netas con spread posterior. No deben utilizarse para inferir rentabilidad. V1.6.1 deja esos registros intactos para preservar la auditoría; interpreta `net_return_estimate` histórico como no confiable hasta recalcularlo o migrarlo con revisión.

El estado `temporal_validation=PASS` es una validación estructural, no una demostración de ausencia total de sesgo. Esta versión no verifica aún la frescura de todas las cotizaciones ni constituye un backtest completo.

## V1.7 — Importación histórica MT5 (manual, no ejecuta órdenes)

Esta versión agrega `backend/app/historical_v17.py`. **No se importa automáticamente** al arrancar FastAPI. El proceso se inicia manualmente desde PowerShell con MT5 abierto y una cuenta DEMO conectada. Los datos se guardan en `data/historical.sqlite3`, **independiente** de `data/research.sqlite3` (observaciones y auditorías en vivo). Nunca borres ni reemplaces tu `research.sqlite3` existente.

```powershell
cd backend
python -m pip install -r requirements.txt
python -m app.historical_v17 --from-date 2026-08-01
```

Importa XAUUSD, EURUSD y USDJPY, en M5, M15 y H1, hasta el instante disponible de ejecución (UTC). Usa segmentos de cinco días; puedes repetir el comando sin duplicar velas. Para probar un rango corto:

```powershell
python -m app.historical_v17 --from-date 2026-08-03 --to-date 2026-08-08
```

**API de consulta (arrancar FastAPI normalmente):**
- `GET http://127.0.0.1:8000/api/history/status` — último lote y cobertura por instrumento/temporalidad.
- `GET http://127.0.0.1:8000/api/history/quality?symbol=EURUSD&timeframe=M5` — intervalos faltantes, primera y última vela.

**Advertencias:** MT5 devuelve únicamente el histórico disponible en el servidor y en su configuración de gráficos. Si devuelve segmentos vacíos o errores, se registran en `import_segments` y no se inventan datos. Los huecos de fin de semana pueden ser normales. Las velas en formación y las OHLC inválidas se descartan. Los spreads históricos, cuando MT5 los proporciona, son puntos por barra, no cotizaciones bid/ask ejecutables ni un modelo de slippage. Ningún dato importado se convierte en una decisión en vivo o en P/L.

**Validación de resultados V1.6.1:** se mantienen intactas las tablas `audit_v16` y `outcomes_v16`; consultar `/api/research/audit?symbol=EURUSD` y revisar que `end_candle_time = candle_time + horizon*300`, con horizontes 3/6/12, y que la vela de cierre de cada horizonte exista. Para comprobar resultados contra MT5 en vivo se requiere el terminal del usuario; no se ha realizado esa comparación aquí.

## V1.7.1 — Diagnóstico de calidad (sin interpolación)

Esta actualización conserva el motor V1.7 y agrega consultas de **solo lectura**:

- `GET /api/history/gaps?symbol=EURUSD&timeframe=M5` — brechas clasificadas como `probable_weekend`, `possible_daily_pause` o `requires_review`.
- `GET /api/history/alignment?symbol=EURUSD` — verifica si cada vela M15/H1 tiene sus 3/12 velas M5 correspondientes por apertura UTC.
- `GET /api/history/rejections` — segmentos con rechazos de V1.7; motivos individuales solo en nuevas importaciones V1.7.1.

Las clasificaciones son heurísticas, **no** sustituyen el calendario de negociación del broker. Los huecos no se rellenan. No se ejecutan órdenes.

### Instalación sin perder datos

1. Detener FastAPI. Hacer copia de seguridad de `data/research.sqlite3` y `data/historical.sqlite3` (y sus archivos `-wal`/`-shm` si existen; mejor con servicios detenidos).
2. Descomprimir en carpeta nueva y copiar la carpeta `data` del proyecto anterior a la nueva raíz.
3. Ejecutar `cd backend`, `python -m pip install -r requirements.txt`, `python -m uvicorn app.main:app --reload`.
4. Consultar los endpoints indicados. **No es necesario repetir la importación** para clasificar los huecos y verificar alineación.
5. Para investigar motivos de las 9 velas inválidas antiguas, consultar `/api/history/rejections` para identificar segmentos y reimportarlos con V1.7.1; `INSERT OR IGNORE` evita duplicar velas válidas.

### Pruebas

`python -m unittest discover -s tests -p 'test_quality_v171.py' -v`

Las pruebas de integración completa requieren Windows, dependencias instaladas y MT5. No se ha verificado la conexión al terminal del usuario.

## V1.8 — Auditoría OHLC y backtest exploratorio (20 noviembre 2026)

Esta versión **no opera ni modifica las bases de datos**. Utiliza el histórico existente `backend/data/historical.sqlite3` (si tu base anterior está en otra ruta, copia el archivo a esa ruta o configura `HISTORICAL_DB` en el entorno). La base `research.sqlite3` queda intacta.

**Puerto:** si Martillazo y Gol ocupa 8000, inicia FastAPI en 8001:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

En `frontend`, crea `.env.local` con `VITE_API_BASE_URL=http://127.0.0.1:8001` y ejecuta `npm install` y `npm run dev`.

**Primero, validar OHLC** (ventanas M5 completas únicamente):

- http://127.0.0.1:8001/api/backtest/ohlc?symbol=EURUSD
- http://127.0.0.1:8001/api/backtest/ohlc?symbol=USDJPY
- http://127.0.0.1:8001/api/backtest/ohlc?symbol=XAUUSD

Si hay discrepancias, no aceptar métricas como fiables hasta investigarlas.

**Segundo, backtest ilustrativo**, exige costos explícitos; ejemplo de parámetros que deben ser confirmados con las especificaciones del símbolo del broker (NO son valores verificados):

`/api/backtest/run?symbol=EURUSD&spread_points=10&point_size=0.00001&slippage_points=1`

Usa un split cronológico 70/30, ruptura 20 velas M5 + filtro EMA20/50 H1 cerrado, SL ATR14, TP 1.5 ATR, máximo 12 velas, entrada en la siguiente apertura, sin operaciones solapadas. Las señales no utilizan velas futuras. Los trades que atraviesan brechas temporales se excluyen. La convención conservadora es SL primero si ambos niveles son tocados dentro de una vela. Se separan métricas train/test.

**Limitaciones materiales:** no se han confirmado los horarios del broker ni los 9 rechazos antiguos; el split es de desarrollo exploratorio y NO equivale a validación externa de la estrategia; no hay spread histórico real, comisiones, swap, microestructura ni slippage real. Las métricas son retornos normalizados sobre el precio, NO P/L en USD ni tamaño de lote ejecutable. El riesgo objetivo de $0.25 por operación **no se puede garantizar** sin `symbol_info` de MT5, valor del tick, lote mínimo y distancia SL. No utilizar para dinero real.

Pruebas: `python -m unittest discover -s tests -v` desde la raíz del proyecto. No se ha probado conexión real a MT5 desde este entorno.
