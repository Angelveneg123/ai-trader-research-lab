# Parche del diagnóstico MT5 para V2.5 RC1

Extraé el contenido del ZIP sobre la raíz de ai-trader-research-lab. La ruta del diagnóstico debe quedar en backend/diagnosticar_mt5.py. Se incluyen el diagnóstico, sus módulos de conexión y lectura, las pruebas y su resultado.

## Aislar el IPC

Si todavía corre el diagnóstico anterior, detenelo con Ctrl+C. Abrí MetaTrader 5 e iniciá sesión en tu cuenta Deriv demo. Usá PowerShell en la misma sesión de Windows. Para esta prueba, dejá una sola instancia de MT5 y pausá el backend si lo tenés abierto.

Desde backend:

~~~powershell
.\.venv\Scripts\python.exe .\diagnosticar_mt5.py --sin-env --terminal 'C:\Program Files\MetaTrader 5\terminal64.exe' --symbol EURUSDmicro
$LASTEXITCODE
~~~

El diagnóstico omite el archivo .env en esta ejecución. Solicita hasta 60 segundos de timeout de inicialización y lee la cuenta y una vela cerrada con una sola conexión. Usa un timeout distinto con --timeout-ms si necesitás compararlo. El código 2 informa un problema de conexión. El código 3 indica que la cuenta se comprobó y falló la lectura de velas.

## Revisar la sintaxis del .env

~~~powershell
.\.venv\Scripts\python.exe .\diagnosticar_mt5.py --solo-env
notepad .env
~~~

Si aparece lineas_invalidas con el valor 3, corregí la sintaxis de esa línea. El formato es NOMBRE=valor o # comentario. Si la línea corresponde a la ruta MT5, podés usar:

~~~dotenv
MT5_TERMINAL_PATH="C:/Program Files/MetaTrader 5/terminal64.exe"
~~~

La revisión imprime números de línea y estado. Cuando la conexión directa funcione, repetí el diagnóstico sin --sin-env. Si únicamente conecta con una espera larga, podés ajustar MT5_TIMEOUT_MS en el archivo .env y reiniciar el backend.

Si continúa -10005 con la ruta explícita, guarda la salida del diagnóstico y verifica si PowerShell y terminal64 comparten SessionId:

~~~powershell
Get-Process -Id $PID | Select-Object ProcessName, Id, SessionId
Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Select-Object ProcessName, Id, SessionId
~~~

Si devuelve -6, verificá las credenciales dentro de MT5 y el nombre de servidor de tu cuenta demo en Deriv. [MetaTrader 5 Python](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py) · [Acceso a Deriv MT5](https://deriv.com/help-centre-question/how-to-log-in-to-deriv-mt5-account)

La salida observada de 50 pruebas se incluye en PRUEBAS_DIAGNOSTICO.txt. El acceso al terminal Windows sigue pendiente de validación en tu PC.
