# AI Trader Research Lab — V1.9.6 Investigación Gemini

Actualización incremental sobre el dashboard V1.9.6 ya instalado. No reemplaza SQLite ni credenciales.

## Copiar archivos

- `backend/app/main.py` → `backend/app/main.py` (reemplazar, tras respaldo)
- `backend/app/gemini_protocol.py` → `backend/app/gemini_protocol.py` (nuevo)
- `frontend/src/main.tsx` → `frontend/src/main.tsx` (reemplazar, tras respaldo)

Requiere conservar en `backend/`: `primera_decision_gemini.py`, `lote_gemini_v193.py`, `evaluar_sesion_v192.py`; en `data/`: `historical.sqlite3` y `ai_decisions.sqlite3`.

## Arranque

Terminal backend: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload`
Terminal frontend: `npm run dev`
Abrir `http://127.0.0.1:5173` → **Investigación**.

## Flujo

1. **Preparar y congelar**: selecciona hasta 89 escenarios históricos, guarda `data/gemini_v196_manifest.json` con huellas SHA256, sin llamar a Gemini. Requiere suficientes datos. No sobrescribe un manifiesto existente.
2. Revisar la huella y progreso. Las 11 decisiones del piloto se mantienen separadas.
3. Confirmar explícitamente cada lote de hasta 10 consultas. La ejecución corre en un hilo local y se detiene ante el primer error; puede reanudarse sin repetir decisiones guardadas.
4. Resultados y evaluaciones se guardan en las tablas existentes. El progreso se actualiza cada 3 segundos.

## Límites y advertencias

- **NO hay órdenes MT5**, y no se habilita trading real.
- El costo indicado es una **reserva estimada configurada**, NO consumo medido ni garantía de facturación. Comprobar cuotas y gasto en Google AI Studio antes de ejecutar lotes.
- Si el backend se reinicia a mitad de una consulta, una solicitud podría cobrarse sin que se guarde su respuesta. El sistema no puede evitar esa situación.
- El control de lotes es local, de un solo proceso de servidor. **No ejecutar múltiples instancias de uvicorn** para el mismo proyecto.
- Dos escenarios de un mismo día, si son necesarios, se separan al menos 5 horas; pueden estar correlacionados y no equivalen a 89 días independientes.
- No se garantiza independencia de los resultados: se seleccionan tiempos sin inspeccionar precios futuros, pero el histórico puede haber estado presente en el entrenamiento del modelo.
- El evaluador usa OHLC de referencia, no ticks ni fills; no demuestra PnL real.
- Si el histórico cambia, se bloquea el lote al fallar la huella del contexto.
