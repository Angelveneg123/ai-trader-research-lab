# Dashboard de tres mercados para V2.5 RC1

Extraé este ZIP sobre la raíz de ai-trader-research-lab. Se copian archivos de código y evidencias. El paquete conserva tu .env y tu diario SQLite. También incluye el diagnóstico MT5 del parche anterior para que puedas aplicarlo sobre RC1 directamente.

Reiniciá FastAPI y el frontend. En Dashboard, la sección **Observación por mercado** muestra EUR/USD, USD/JPY y XAU/USD juntos. Las tarjetas presentan la vela cerrada, el ID de ciclo, el estado o respuesta de Gemini y, cuando están disponibles, el spread de la captura y el costo estimado. Seleccionar una tarjeta cambia el gráfico y el historial. El resumen lee SQLite y se actualiza cada cinco segundos.

## Secuencia de prueba en Windows

Primero verificá la sintaxis del .env, la cuenta Deriv demo y la disponibilidad de velas. Usá la ruta al terminal ya conectado. Estos comandos se ejecutan desde backend:

~~~powershell
$env:MT5_TERMINAL_PATH = "$env:APPDATA\MetaTrader 5\terminal64.exe"
.\.venv\Scripts\python.exe .\diagnosticar_mt5.py --solo-env
if ($LASTEXITCODE -eq 0) {
    .\.venv\Scripts\python.exe .\diagnosticar_mt5.py --terminal $env:MT5_TERMINAL_PATH --symbol EURUSDmicro
}
~~~

En la ventana de 02:00 a 10:00 de Nicaragua, de lunes a viernes, empezá con una pasada de EURUSDmicro y verificá que el ciclo se vea en el dashboard. Una decisión WAIT es válida.

~~~powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --symbols EURUSDmicro --providers gemini --allow-api-cost
~~~

Luego probá una pasada de los tres mercados. La cuenta tiene que tener disponibles esos nombres. Usá el nombre exacto de MT5 si el símbolo difiere y configuralo en MT5_SYMBOLS.

~~~powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --symbols EURUSDmicro USDJPYmicro XAUUSDmicro --providers gemini --allow-api-cost
~~~

Los dos comandos usan el modo de observación y terminan al completar la pasada. Ambos pueden consumir cuota de Gemini. Si se ejecutan en la misma vela M5, el motor evita duplicar la consulta de EURUSDmicro que ya se procesó. Los tres mercados comparten el saldo acumulado asignado a Gemini de USD 2,50.

## Evidencia

- El backend pasó 52 pruebas. También se compiló el frontend.
- La integración simulada comprobó tres ciclos distintos en SQLite, los mismos tres IDs en FastAPI y las tres tarjetas en React. También se verificó la selección de mercado.
- Los registros están en evidencias/mercados_*. La prueba en el terminal Windows del usuario continúa pendiente.
