# Recuperación de AI Trader Research Lab V2.5

Verificación realizada el 22 de noviembre de 2026, hora de Nicaragua. La entrada fue `ai-trader-research-lab (2)(6).zip`.

| Comprobación | Resultado | Registro |
| --- | --- | --- |
| Revisión del ZIP y del motor | ZIP legible. El comienzo de `prospectivo_v22.py` tenía 146 bytes de PowerShell antes del código Python. El motor restaurado coincide byte a byte con la entrega RC1. | [Datos y SHA-256](recuperacion_datos.txt) |
| Arranque de FastAPI y del panel | HTTP 200 para la página, JavaScript, CSS y API con 8001 libre, con 8001 ocupado y con ambos puertos fijos ocupados. Se usaron 8001, 8002 y un puerto asignado por el sistema, respectivamente. | [Registro de arranque](recuperacion_arranque.txt) |
| Dashboard con MT5 y Gemini simulados | Tres ciclos WAIT guardados en SQLite. React mostró los tres mercados y el mismo identificador de ciclo y horas de vela y recepción. El fallo IPC simulado dejó el panel disponible y mostró el estado de espera de las velas. | [Registro de arranque](recuperacion_arranque.txt) |
| Regresión | Compilación de Python, 59 pruebas aprobadas y build de producción de React. Incluye los códigos 10048 y 10013 simulados y la selección de AppData con dos instalaciones presentes. | [Pytest](recuperacion_pytest.txt) · [Build](recuperacion_build.txt) |
| Datos preservados | Cuatro SQLite con `integrity_check` correcto y huellas idénticas a las de la entrada. La base histórica tiene 94.134 velas y el archivo de Gemini tiene 100 decisiones históricas. El diario prospectivo incluido tiene cero ciclos. | [Datos y SHA-256](recuperacion_datos.txt) |
| Arranque desde una extracción nueva | `backend/.env` ausente. Motor prospectivo importable. Servidor y panel disponibles en el puerto alternativo con las bases incluidas. | [Prueba del paquete](recuperacion_paquete.txt) |

La entrada no incluía `data/research.sqlite3`. Si ese archivo sigue en el equipo anterior, el [arranque en Windows](../README_V25.md) indica cómo conservarlo.

El recorrido de interfaz se ejecutó en Linux con jsdom. Los servicios de trading y las decisiones de los tres mercados se simularon, con cero órdenes y cero llamadas a proveedores externos. La conexión del dashboard recuperado al terminal Deriv de Windows y la primera consulta real a Gemini quedan pendientes.
