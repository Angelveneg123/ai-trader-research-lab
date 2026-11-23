# AI Trader Research Lab V2.5 · Recuperado

Esta versión recupera el motor prospectivo y abre el dashboard junto con FastAPI. El diagnóstico de solo lectura en el equipo del usuario ya confirmó una cuenta Deriv demo en USD y una vela de EURUSDmicro. Falta verificar el dashboard recuperado con ese terminal y registrar una primera decisión prospectiva real en su diario. [Pruebas de recuperación](evidencias/RECUPERACION.md) · [Evidencia anterior por fase](evidencias/README.md)

## 1. Abrir el laboratorio en Windows

1. Extraé el ZIP en una carpeta nueva y conservá tu carpeta anterior. Cerrá con **Ctrl+C** las consolas anteriores de FastAPI y del motor prospectivo si las tenés abiertas.
2. Dejá abierto MetaTrader 5 con tu sesión de **Deriv demo** iniciada. Hacé doble clic en **INICIAR_LAB.cmd** dentro de la carpeta nueva. La primera vez se necesita internet para instalar los paquetes de Python.
3. El panel abre en el navegador. También podés abrir la dirección que aparece junto a **Panel listo** en la consola. El programa intenta el puerto 8001, luego 8002 y, si están ocupados los dos, toma otro puerto local disponible.

El dashboard lee velas y observaciones sin hacer consultas facturables de IA ni enviar órdenes. Podés abrirlo sin `backend/.env`. Mantené abiertas la consola del laboratorio y tu sesión de MT5 mientras lo uses.

Las cuatro bases incluidas se copiaron desde tu ZIP. Si tu carpeta anterior todavía contiene `data/research.sqlite3`, copiá ese archivo a `data` de la carpeta nueva antes del primer arranque, con ambas versiones detenidas. Copiá también los archivos asociados `research.sqlite3-wal` y `research.sqlite3-shm` si existen. Si tu carpeta anterior tiene un diario prospectivo posterior al ZIP, conservá una copia de ambos y retomá con el diario posterior para preservar sus registros y reservas.

## 2. Comprobar Deriv MT5

El selector usa `%APPDATA%\MetaTrader 5\terminal64.exe` si existe y no configuraste una ruta explícita. Es el ejecutable con el que se obtuvo `Deriv-Demo` en el diagnóstico. Si elegís otro, ejecutá `.\INICIAR_LAB.cmd --terminal "ruta al terminal64.exe"` desde la raíz en PowerShell, o configurá `MT5_TERMINAL_PATH` en tu copia local de `.env`. Una ruta explícita tiene prioridad. [Inicio de sesión en Deriv MT5](https://deriv.com/help-centre-question/how-to-log-in-to-deriv-mt5-account)

En el encabezado se deben ver **FastAPI conectado** y **Deriv MT5 conectado**. Seleccioná **EUR/USD** para ver las velas de `EURUSDmicro`. Si Deriv sigue sin conexión, cerrá con **Ctrl+C** la consola del laboratorio y ejecutá esta prueba desde `backend` en PowerShell:

~~~powershell
.\.venv\Scripts\python.exe .\diagnosticar_mt5.py --sin-env --terminal "$env:APPDATA\MetaTrader 5\terminal64.exe" --symbol EURUSDmicro
$LASTEXITCODE
~~~

El resultado esperado es código 0, demo en USD y una vela M5 cerrada con hora UTC. Los códigos 2 y 3 indican un problema de conexión o de lectura. Si aparece -6, revisá la sesión y el servidor dentro de MT5. Si aparece -10005, verificá que el ejecutable seleccionado y Python corran en la misma sesión de Windows y repetí el diagnóstico una vez. [Códigos de MetaTrader 5](https://www.mql5.com/en/docs/python_metatrader5/mt5lasterror_py)

La API del mismo panel expone estado en `/api/health`, velas en `/api/market/candles` y decisiones en `/api/prospective`. Para usar el control manual de entradas, configurá `LAB_CONTROL_TOKEN` con un secreto local de al menos 24 caracteres y reiniciá el laboratorio.

## 3. Primer ciclo Gemini en observación

Cuando quieras iniciar la prueba de Gemini, copiá `backend/.env.example` a `backend/.env` y configurá localmente tu clave renovada. Podés validar el archivo con `diagnosticar_mt5.py --solo-env`. Si el panel estaba abierto, reinicialo para cargar la configuración. OpenAI permanece desactivado por defecto. En la ventana de lunes a viernes de 02:00 a 10:00 en Nicaragua, desde `backend`:

~~~powershell
.\.venv\Scripts\python.exe .\prospectivo_v22.py --symbols EURUSDmicro --providers gemini --allow-api-cost
.\.venv\Scripts\python.exe .\prospectivo_v22.py --status
~~~

El primer comando puede consumir presupuesto de API. Comprobá que el mismo ciclo, vela y respuesta queden en SQLite, FastAPI y la sección IA y modelos. WAIT es una decisión válida. El diagnóstico fuera de sesión se registra aparte y no inicia una decisión prospectiva. El monitor en consola es independiente del navegador y se inicia con --loop. Para terminar una prueba técnica en una fecha definida, añadí --until AAAA-MM-DD. Esa fecha es exclusiva y utiliza Nicaragua.

El diario aplica USD 2,50 acumulados por proveedor. Incluye llamadas prospectivas, diagnósticas e históricas nuevas iniciadas por los comandos del proyecto. Cada reserva se descuenta antes de llamar. El saldo estimado persiste con el mismo archivo SQLite y no reemplaza el límite de facturación del proveedor. Los datos históricos anteriores sin costo documentado quedan como antecedentes. [Precios de Gemini](https://ai.google.dev/gemini-api/docs/pricing) · [Modelo de OpenAI](https://developers.openai.com/api/docs/models/gpt-5.4-mini)

## 4. Requisitos para probar ejecución demo

Este ZIP deja la ejecución desactivada por defecto. Antes de autorizar una prueba de órdenes, verificá contra el bróker la comisión, el spread y las especificaciones del contrato. El diagnóstico de costos de solo lectura puede tomar muestras de spread. Una comisión de cero solo se registra si se verificó como tal. Copiá demo_execution.example.json en un archivo local y completá los campos de costo, fuente, deslizamiento y spread. Configurá MT5_DEMO_LOGIN para asegurar que se gestione la cuenta prevista.

El sincronizador Finnhub escribe news_calendar_candidate.json. Una respuesta JSON con eventos permite preparar un calendario candidato. Actualmente la cobertura efectiva del plan contratado, las zonas horarias y la completitud requieren validación con el proveedor. Las órdenes requieren un calendario local vigente con fuente, lista de divisas y cobertura verificada. Conservá la plantilla news_calendar.example.json como formato. Las entradas permanecen bloqueadas durante los 20 minutos antes y después de un evento de alto impacto. Las posiciones protegidas se siguen supervisando al terminar la ventana. [Referencia de Finnhub](https://finnhub.io/docs/api/economic-calendar)

Si autorizás expresamente una prueba en la cuenta DEMO configurada y completás los controles anteriores, el modo de ejecución requiere iniciar el supervisor con --demo, --loop y --allow-api-cost. Usá solo Gemini en el primer ensayo. El diagnóstico y la prueba prospectiva anterior operan sin --demo.

Para reportes salientes, configura TELEGRAM_ENABLED=1, TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID únicamente en tu copia local y solo si autorizás el envío. El reporte se guarda primero en SQLite. La evaluación prospectiva por ticks al cierre de sesión es una referencia simulada separada del P/L de las órdenes demo.

## 5. Regresión

Desde la raíz:

~~~powershell
.\backend\.venv\Scripts\python.exe -m compileall -q backend tests evidencias
.\backend\.venv\Scripts\python.exe -m pytest -q -rA tests backend/tests
npm --prefix frontend run build
~~~

Para repetir la prueba integrada, instalá jsdom 26 en un directorio de pruebas e indicá su ruta en `JSDOM_PATH`. Desde la raíz, ejecutá `python evidencias/ejecutar_evidencia_ui.py --ocupar 8001` con 8001 y 8002 libres. La prueba reserva el primero, arranca el laboratorio en el segundo y verifica el panel con datos simulados. Los comandos y las salidas de esta versión están en [Pruebas de recuperación](evidencias/RECUPERACION.md).

Para desarrollar la interfaz, `npm run dev` desde `frontend` usa el proxy al backend del puerto 8001. Si el backend se inició en otro puerto, configurá `VITE_API_BASE_URL` en el entorno de Vite con la URL que el servidor anunció.
