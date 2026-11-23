# Panel y diagnóstico de Deriv MT5 · V2.5 RC1

Estas instrucciones corresponden al parche anterior. La edición completa recuperada se abre con `INICIAR_LAB.cmd`. [Arranque actual](README_V25.md)

Extraé el ZIP sobre la raíz de ai-trader-research-lab, donde están las carpetas backend y frontend. Este parche incluye el resumen de tres mercados y el diagnóstico IPC. Podés aplicarlo a la V2.5 RC1 directamente o encima del parche de tres mercados. Se conservan el diario y la configuración local.

## Qué vas a ver

- El encabezado muestra FastAPI y Deriv MT5 por separado. Una alerta arriba muestra el problema de conexión y permite abrir el diagnóstico.
- El gráfico tiene tres selectores con nombres legibles. Al elegir una tarjeta, la vista baja al gráfico correspondiente.
- El gráfico pide velas y cotización en una sola lectura. Con Deriv MT5 desconectado, el estado de conexión se comprueba automáticamente y el gráfico espera. Las consultas a MT5 del backend comparten el reintento después de un fallo.
- El archivo histórico de Gemini queda identificado. Los registros siguen disponibles cuando falta el terminal. Las métricas demo que dependen de MT5 aparecen sin valor mientras el terminal esté desconectado.

## Cómo confirmar que FastAPI abre el terminal adecuado

1. Detené FastAPI y el motor prospectivo con Ctrl+C en sus respectivas consolas.
2. En la aplicación de escritorio, dejá abierta la instalación de MT5 que tenga la cuenta **Deriv demo** iniciada. Confirmá el servidor exacto dentro de Deriv.
3. En PowerShell, desde backend, probá el terminal que veníamos comprobando en AppData:

~~~powershell
$env:MT5_TERMINAL_PATH = "$env:APPDATA\MetaTrader 5\terminal64.exe"
.\.venv\Scripts\python.exe .\diagnosticar_mt5.py --solo-env
.\.venv\Scripts\python.exe .\diagnosticar_mt5.py --sin-env --terminal "$env:MT5_TERMINAL_PATH" --symbol EURUSDmicro
~~~

Si usás otro ejecutable, sustituí la ruta por la de la ventana abierta. El segundo comando aísla la conexión aunque el archivo .env tenga una línea inválida. Para iniciar el laboratorio, corregí también cualquier línea que señale el primer comando.

Cuando el diagnóstico indique connected y demo verdaderos y muestre una vela, iniciá FastAPI **en el mismo PowerShell** para que herede la ruta:

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
~~~

Reiniciá Vite si ya estaba abierto. Un código -6 pendiente requiere revisar la sesión de la cuenta y el servidor de Deriv. Un -10005 indica un timeout al comunicarse con el terminal. El parche reduce consultas simultáneas. La apertura de una sesión en el Windows del usuario sigue por validar. [Manual de errores de MT5](https://www.mql5.com/en/docs/python_metatrader5/mt5lasterror_py) · [Acceso a Deriv MT5](https://deriv.com/help-centre-question/how-to-log-in-to-deriv-mt5-account)

## Evidencia

Pasaron 56 pruebas y se compiló React. Dos pruebas de integración simularon MT5 conectado y un timeout de IPC. La segunda comprobó que FastAPI siguiera visible, que el aviso mostrara -10005 y que el gráfico esperara sin solicitar velas. Los registros están en evidencias/mt5_dashboard_*. Los ejemplos no envían órdenes.
