# AI Trader Research Lab V2.3

El panel y el motor prospectivo comparten el diario `backend/data/prospective_v22.sqlite3`. El diario histórico de Gemini y las velas importadas siguen disponibles en `data/`. La investigación usa una vela M5 cerrada con contexto M15 y H1, de lunes a viernes entre las **02:00 y las 10:00 en Nicaragua**.

## 1. Instalar en Windows

Extrae el ZIP en una carpeta nueva y abre PowerShell en la raíz del proyecto. Usa una cuenta MT5 demo, mantén el terminal abierto y sincroniza el reloj de Windows.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe .\prospectivo_v22.py --status
```

Edita `backend/.env` y agrega la nueva clave de Gemini. Agrega la de OpenAI cuando quieras comparar ambos proveedores. Usa las claves de API del proveedor. La suscripción de ChatGPT no habilita llamadas de API.

En una terminal desde `backend`, inicia FastAPI.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

En otra terminal desde `frontend`, inicia el panel y abre [http://127.0.0.1:5173](http://127.0.0.1:5173).

```powershell
npm ci
npm run dev
```

Si ya tienes un diario prospectivo propio, detén el motor antes de copiarlo junto con sus archivos WAL si los hubiera. El motor inicializa las tablas nuevas sin sustituir las anteriores. Para usar una ruta distinta, configura `PROSPECTIVE_DB` en `backend/.env`. Las rutas relativas en ese archivo parten de `backend`.

## 2. Validar la primera vela y comparar proveedores

Desde `backend` durante la sesión, idealmente después del cierre de una vela M5.

```powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --symbols EURUSDmicro --providers gemini
```

Comprueba la acción, el motivo y la hora de recepción en **IA y modelos**. Es válido que la acción sea `WAIT`. La selección de símbolos coincide con el nombre visible en Deriv MT5. Si el bróker usa otros sufijos, configura `MT5_SYMBOLS` con sus nombres exactos, separados por comas.

Para iniciar la comparación y fijar una fecha de finalización de 14 días naturales a partir de hoy en Nicaragua, ejecuta el siguiente bloque. Vuelve a usar la misma fecha si reinicias el proceso.

```powershell
$nicZone = [TimeZoneInfo]::FindSystemTimeZoneById("Central America Standard Time")
$trialUntil = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $nicZone).AddDays(14).ToString("yyyy-MM-dd")
Write-Host "Fecha exclusiva de finalización $trialUntil"
.\.venv\Scripts\python.exe .\prospectivo_v22.py --symbols EURUSDmicro --providers gemini openai --loop --until $trialUntil
```

Puedes agregar `USDJPYmicro` y `XAUUSDmicro` a `--symbols` después de confirmar sus nombres y cotizaciones. Conserva los modelos, instrumentos y supuestos que elijas al inicio si vas a comparar resultados de toda la prueba.

El motor reclama una sola llamada por vela, símbolo y proveedor. El límite local es **USD 2,50 diarios por proveedor**. Se reserva un importe conservador y, cuando la API devuelve el uso de tokens y hay tarifas configuradas, se contabiliza su costo estimado. Los intentos inciertos mantienen su reserva para ese día. Los modelos sin precio configurado conservan la reserva por llamada de `--max-call-usd`. Contrasta las estimaciones con los paneles de facturación de [Gemini](https://ai.google.dev/gemini-api/docs/pricing) y [OpenAI](https://developers.openai.com/api/docs/pricing).

## 3. Revisar resultados y activar Telegram

Después de las 10:02, el motor evalúa las señales con ticks bid/ask posteriores a la recepción. Usa una tolerancia de cinco segundos de reloj y hasta 60 segundos para encontrar la primera cotización. Aplica el deslizamiento y la comisión indicados en la configuración de ejecución de cada instrumento. Mientras falten, el escenario de referencia usa **1 punto de deslizamiento por lado y 0 USD de comisión**, identificados en el resultado. La simulación registra los huecos de cotizaciones y muestra pips netos separados por proveedor y símbolo.

Completa `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en `backend/.env`. Inicia una conversación con tu bot desde Telegram. El diario guarda un reporte por día y el panel muestra el estado del envío. Los reportes se guardan localmente aunque Telegram aún esté pendiente. El comando para volver a procesar resultados y reportes funciona sin iniciar consultas de IA ni el motor de órdenes.

```powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --report-only
```

## 4. Habilitar el motor de órdenes en MT5 demo

Comienza después de validar el flujo anterior. Usa una cuenta **demo en USD** y habilita el trading algorítmico y el acceso de Python en MT5. Indica el login demo exacto. Desde `backend`, crea las copias locales de configuración.

```powershell
Copy-Item data\demo_execution.example.json data\demo_execution.json
Copy-Item data\news_calendar.example.json data\news_calendar.json
.\.venv\Scripts\python.exe .\mt5_costos_readonly.py --symbols EURUSDmicro --out data\costos_locales.json
```

- En `demo_execution.json`, completa comisión total de ida y vuelta en USD por 1,00 lote del instrumento, spread máximo en puntos y colchón de deslizamiento por lado en puntos. El diagnóstico de solo lectura muestra spread y especificaciones. La comisión se confirma por separado con las condiciones de la cuenta.
- En `news_calendar.json`, declara el intervalo UTC cubierto y carga los eventos con fecha UTC, divisa, impacto y título. El filtro bloquea entradas 20 minutos antes y después de un evento de alto impacto en las divisas del símbolo. El calendario se mantiene manualmente. La ejecución bloquea entradas cuando falta cobertura o el formato es inválido.
- En `backend/.env`, activa `MT5_DEMO_LOGIN`, `MT5_EXECUTION_CONFIG=data/demo_execution.json` y `MT5_NEWS_CALENDAR=data/news_calendar.json`.

```powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --symbols EURUSDmicro --providers gemini openai --loop --demo --execute-provider gemini
```

Gemini decide las entradas con este comando. OpenAI participa en la comparación. El motor admite una posición del laboratorio a la vez. Calcula el volumen con `order_calc_profit`, redondea hacia abajo, comprueba disponibilidad con `order_check` y envía SL y TP con la orden. Usa un riesgo estimado máximo de **USD 0,25** y bloquea nuevas entradas por una pérdida acumulada de **USD 1** en el día de Nicaragua. Los saltos de precio y las ejecuciones del bróker pueden superar la estimación.

A las 10:00 intenta cerrar las posiciones identificadas como propias. El proceso debe seguir activo y conectado para cerrar o reintentar. Si una entrada queda sin confirmar, el motor bloquea nuevas entradas hasta poder reconciliarla mediante el historial de MT5. El panel de **Operaciones** muestra ejecuciones, P/L y diagnósticos. Revisa la documentación de [Python para MetaTrader 5](https://www.mql5.com/en/docs/python_metatrader5).

## Verificación

Ejecuta las pruebas del backend desde la raíz y la compilación desde `frontend`.

```powershell
.\backend\.venv\Scripts\python.exe -m pytest tests -q
```

```powershell
npm run build
```
