# V1.9 — Primera decisión histórica Gemini

Se añade únicamente `backend/primera_decision_gemini.py` y pruebas. No se modifica el motor MT5, el frontend, ni las bases históricas existentes.

## Instalación

1. Hacer respaldo de `data/` de la instalación anterior.
2. Extraer esta versión en una carpeta nueva y copiar `data/` a la raíz del proyecto nuevo (sin reemplazar bases con archivos vacíos).
3. En VS Code, abrir terminal en `backend`, activar `.venv` si existe, e instalar `python -m pip install google-genai python-dotenv`.
4. Crear `backend/.env` local con `GEMINI_API_KEY=...` (no subir a GitHub).
5. Ejecutar `python primera_decision_gemini.py --preview` para comprobar la selección de velas sin gasto.
6. Ejecutar `python primera_decision_gemini.py` **una vez** para obtener y registrar la decisión.

El histórico `data/historical.sqlite3` se abre en modo lectura; las decisiones se escriben en `data/ai_decisions.sqlite3`. El programa no llama a funciones de envío de órdenes. No hay backtest, PnL, aprendizaje automático ni evaluación de resultados en esta etapa. Una misma situación histórica y modelo no se consulta dos veces si ya está guardada.

Se elige la última situación disponible dentro de 02:00–10:00 Managua con 60 M5 consecutivas, 40 M15 y 30 H1 cerradas. La respuesta JSON se valida antes de guardarla. Las M15/H1 se filtran por cierre de vela para evitar lookahead. Una llamada API puede generar costo; consultá la cuota de tu proyecto.
