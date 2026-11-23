# AI Trader Research Lab V2.3.1 — Diagnóstico sin operaciones

Esta versión se basa en V2.3 y mantiene los archivos y el histórico del ZIP original.

## Cambios
- `--diagnostic`: toma una instantánea de velas cerradas de MT5 DEMO y permite una consulta de IA fuera de la sesión de 02:00–10:00 Nicaragua.
- `--allow-api-cost`: autorización explícita indispensable para realizar la llamada facturable.
- Los resultados se guardan en `diagnostic_calls` con estado `DIAGNOSTIC_ONLY`. No se insertan en `prospective_cycles` ni `prospective_decisions`.
- Sin `--demo` ni `--loop` en diagnóstico. No hay envío de órdenes.
- Límite total acumulado de USD 2.50 por proveedor, incluyendo diagnóstico y prospectivo. Se conserva la reserva cuando se desconoce el cobro tras un error para evitar exceder el presupuesto.
- Máximo una consulta por proveedor, símbolo y vela M5 cerrada; una repetición no vuelve a facturar.

## Instalación
Extraer el ZIP en una **carpeta nueva**. Si ya hay un proyecto funcionando, hacer copia de seguridad de `backend/data/prospective_v22.sqlite3` antes de reemplazar archivos. El esquema se amplía automáticamente al iniciar. No sobrescribir un `.env` personal.

Abrir PowerShell en `backend`, activar el entorno virtual si corresponde e instalar dependencias de `requirements.txt` si hace falta.

## Consulta de estado, sin costo
```powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --status
```

## Diagnóstico con Gemini (consulta API facturable)
```powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --diagnostic --allow-api-cost --symbols EURUSDmicro --providers gemini
```

## Diagnóstico con ambas IA (dos consultas potencialmente facturables)
```powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --diagnostic --allow-api-cost --symbols EURUSDmicro --providers gemini openai
```

Necesitás `GEMINI_API_KEY` y/o `OPENAI_API_KEY` en tu `.env` y MetaTrader 5 conectado a una cuenta DEMO. Si el símbolo no está disponible o no hay cotización fresca, se cancela antes de llamar a la API. No usar `--demo` en estas pruebas.

## Limitaciones
Los costos son estimados a partir de los tokens reportados y tarifas configuradas, no facturas de los proveedores. Verificar tarifas reales y los modelos configurados antes de gastar. Si el servidor falla sin devolver uso de tokens, la reserva se mantiene hasta una conciliación manual. El diagnóstico prueba la integración, no la rentabilidad. Los resultados de diagnóstico no son señales operables ni forman parte del rendimiento prospectivo.

## Pruebas
Desde la raíz del proyecto:
```powershell
$env:PYTHONPATH="backend"; .\.venv\Scripts\python.exe -m pytest -q
```
