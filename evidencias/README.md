# Evidencias de AI Trader Research Lab V2.5 RC1

La edición recuperada tiene resultados nuevos de arranque, conservación de datos y restauración del motor. [Pruebas de recuperación](RECUPERACION.md)

Ejecución del 22 de noviembre de 2026, Nicaragua (UTC−06:00). Entorno Linux con Python 3.12. Los servicios de trading se simularon. La verificación integrada con Deriv MT5 de Windows, Gemini, Finnhub y Telegram queda pendiente.

Entrada auditada. El ZIP ai-trader-research-lab (2)(5).zip tiene SHA-256 ee48dba5ff2c5e0a4352070101d66181f21fcda520c0f2e2abc4a737e10726d1. Frente al ZIP anterior quitó backend/.env. Los archivos de código analizados coincidían. La V2.5 se construyó en una copia. Se conservaron las bases entregadas por el usuario y se probó la migración en una copia de SQLite Backup.

## Cambios y resultados por fase

| Fase | Código de referencia | Prueba y resultado observado | Estado y evidencia |
| --- | --- | --- | --- |
| 0. Auditoría | ZIP de entrada y SQLite | Compileall, build y seis pruebas aisladas ejecutadas. Las tres bases dieron integrity_check OK. El diario tenía dos diagnósticos y cero ciclos prospectivos, decisiones prospectivas y ejecuciones. | **APROBADO** local. [Línea base](00_linea_base.txt) |
| 1. Conexión | backend/app/mt5_connection.py y backend/diagnosticar_mt5.py | Mocks de -6, -10005, otro fallo IPC, selección explícita del terminal, reconexión y servidor incorrecto. FastAPI devolvió 503 estructurado al faltar MT5. | **APROBADO SIMULADA**. Conexión Windows **BLOQUEADA**. [Diagnóstico Linux](01_mt5_linux.txt) · [suite](06_pytest_completo.txt) |
| 2. Integración | React, FastAPI, supervisor y SQLite | Un WAIT de Gemini simulado pasó por SQLite y FastAPI al bundle real de React en un DOM de prueba. El observador FastAPI siguió activo al cerrar el DOM. Los controles sin token devolvieron 401. Exportación CSV comprobada. | **APROBADO SIMULADA**. [Proceso](02_e2e_simulado.txt) · [SQLite y servidor](02_backend_ui_simulado.txt) · [HTTP](02_http_simulado.json) · [Texto renderizado](02_dom_simulado.txt) |
| 3. Proveedores y presupuesto | prospectivo_v22.py, prospective_store.py y legacy_meter.py | La suite probó ambos adaptadores sin red, BUY, WAIT de diagnóstico, no duplicación, una reserva diagnóstica anterior que bloquea Gemini y saldo independiente de OpenAI. OpenAI desactivado omitió la llamada. Se registran modelo, uso, costo y latencia. | **APROBADO SIMULADA**. Primera decisión real **BLOQUEADA** por MT5 y autorización de gasto. [Suite](06_pytest_completo.txt) |
| 4. Calendario y riesgo | news_calendar_sync.py y demo_execution.py | Pruebas para deslizamiento BUY/SELL, comisión y lote mínimo. Bloqueos por noticias, cobertura sin verificar, calendario vencido y pérdida diaria. La actualización automática prepara un calendario candidato. | **APROBADO SIMULADA**. Cobertura del proveedor y comisión **NO EJECUTADAS** con cuentas reales. [Suite](06_pytest_completo.txt) |
| 5. Ejecución demo | demo_execution.py | Mocks verificaron cálculo de lote y SL/TP leídos tras apertura, cuenta no demo bloqueada, modificación que reduce riesgo, cierre incierto sin segundo envío y reconciliación. A las 10:00 se bloquearon entradas y la posición protegida siguió abierta. Telegram se probó con respuesta simulada y deduplicación. | **APROBADO SIMULADA** en los casos diseñados. Orden demo real y envío efectivo a Telegram **NO EJECUTADOS**. [Suite](06_pytest_completo.txt) |
| 6. Regresión y datos | ZIP V2.5 RC1 | Compilación Python, 47 pruebas aprobadas y build React. Migración con original intacto y conteos preservados. El estudio prospectivo de dos semanas aún no empezó. | **APROBADO LOCAL**. Estudio de dos semanas **NO EJECUTADO**. [Pytest](06_pytest_completo.txt) · [Build](06_react_build.txt) · [SQLite](06_migracion_sqlite.txt) |

## Comandos y casos de integración

- **F1 real.** Se ejecutó **python backend/diagnosticar_mt5.py --symbol EURUSDmicro**. En Windows con la cuenta lista se espera código 0, servidor, cuenta demo en USD y vela cerrada. En Linux se observó código 2, MT5_MODULE_UNAVAILABLE. Los errores previos de Windows siguen por verificar.
- **F2 simulada.** Se ejecutó **python evidencias/ejecutar_evidencia_ui.py** con JSDOM_PATH apuntando a jsdom 26. Se esperaba HTTP 200 y coincidencia de símbolo, acción e ID de ciclo. Se observó el ciclo 95ce0631621389e55cd911da, EURUSDmicro, WAIT, vela 2026-11-20T13:00:00+00:00 y respuesta 2026-11-20T13:00:12+00:00, código 0. El fixture ejecutó el motor con MT5 y Gemini simulados.
- **F3/F4/F5 simuladas.** Se ejecutó **python -m pytest -q -rA tests backend/tests**. Las aserciones de presupuesto, riesgo y gestión enumeradas en el log pasaron, junto con las regresiones heredadas. Código 0. El ejecutor usó mocks de order_check, order_send, posiciones e historial.
- **F6 local.** Se ejecutaron **python -m compileall -q backend tests evidencias**, **npm --prefix frontend run build** y **python evidencias/verificar_migracion.py**. Se comprobó la compilación correcta, build con código 0 y los conteos previos conservados en el diario migrado. SQLite original mantuvo su hash.

## Incidencias preservadas

- La primera ejecución de la suite no pudo importar LOCK tras reemplazar el bloqueo anterior. Se actualizó el importador histórico para usar el bloqueo IPC compartido y se repitió la suite. [Fallo inicial](01_05_pruebas_inicial.txt) · [Repetición](01_05_pruebas_segunda.txt)
- El intento con Chromium terminó antes de abrir el navegador. El entorno denegó el socket de proceso. El resultado aprobado de interfaz utiliza JSDOM. La captura en un navegador real queda pendiente. [Intento Chromium](02_prueba_ui.txt)
- Pytest en modo detallado no pudo resolver metadatos de una dependencia copiada a este entorno. El comando que consta en la suite final ejecutó todos los casos con código 0. [Fallo de arranque](06_pytest_metadata_faltante.txt)

## Puertas de aceptación en Windows

1. Confirmá inicio de sesión en la cuenta Deriv MT5 demo y ejecutá el diagnóstico de solo lectura. Guardá salida con servidor, modo, moneda y cierre UTC. Mantené los datos de cuenta privados.
2. Con permiso para consumir API, verificá un ciclo de Gemini en EURUSDmicro dentro de la ventana de Nicaragua. Adjuntá consola, fila SQLite y panel con la misma vela e ID.
3. Confirmá la comisión y las especificaciones de Deriv para el símbolo. Contrastá el calendario con la cobertura del proveedor. El cliente oficial de Finnhub confirma la existencia del método. La completitud de una respuesta para el plan y las divisas utilizados queda por comprobar. [Cliente de Finnhub](https://github.com/Finnhub-Stock-API/finnhub-python)
4. Solo con autorización explícita de una orden demo, registrá order_check, order_send, SL/TP leídos en la posición, cierre, P/L e historial. Anonimizá el ticket. El cierre programado de las 10:00 se sustituyó por el seguimiento de la posición protegida según el Documento Maestro.
5. Si autorizás Telegram, comprobá la recepción en tu chat. Iniciá la observación de dos semanas después de verificar los puntos anteriores y conservá su registro de sesiones.
