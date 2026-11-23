# AI Trader V2.5 - corrección Gemini (23 nov 2026)

Se corrigió `backend/prospectivo_v22.py`:
- Los errores HTTP muestran el mensaje y estado devueltos por el proveedor (sin exponer la clave).
- El modelo predeterminado pasa a `gemini-3.5-flash-lite`, salvo que `.env` configure `GEMINI_MODEL`.
- El diagnóstico identifica cada combinación de vela, proveedor y modelo; cambiar de modelo ya no produce un falso `ya diagnosticado` para la misma vela.
- No se cambió la lógica de señales, el riesgo, Telegram, ni se habilitó `--demo`.

## Instalar en tu proyecto existente (recomendado)

1. Detené el bot con Ctrl+C.
2. Hacé una copia de seguridad de tu `backend/prospectivo_v22.py`.
3. Copiá el `backend/prospectivo_v22.py` de este ZIP sobre el de tu proyecto.
4. En `backend/.env`, actualizá SOLO `GEMINI_MODEL=gemini-3.5-flash-lite` si esa variable ya existe y apunta a un modelo anterior. Conservá tus claves y demás variables.
5. Comprobá: `.\.venv\Scripts\python.exe -m py_compile .\prospectivo_v22.py`
6. Probá una sola vez (puede generar costo API):
   `.\.venv\Scripts\python.exe .\prospectivo_v22.py --symbols EURUSDmicro --providers gemini --gemini-model gemini-3.5-flash-lite --diagnostic --allow-api-cost`

**Advertencias:** no se verificó acceso real a Gemini ni a MT5 en esta máquina. HTTP 503 puede continuar y su mensaje ahora será visible. El precio por millón de tokens de un modelo nuevo NO está confirmado: para modelos sin tarifa conocida el motor reserva el límite configurado `--max-call-usd` por solicitud; verificá tu facturación. No actives `--loop` hasta tener una respuesta exitosa. `--diagnostic` no ejecuta órdenes.

## Proyecto completo sin credenciales

El ZIP completo excluye `.env`, entornos virtuales, `node_modules`, bases de datos y registros locales para no divulgar secretos ni sobrescribir resultados. Instalá las dependencias desde requirements/package.json y conservá tus datos y `.env` del proyecto original.
