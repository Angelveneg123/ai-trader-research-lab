# V1.9.6 — Integración del dashboard con Gemini (solo lectura)

Esta actualización **no ejecuta consultas de IA ni operaciones MT5**. Usa `data/ai_decisions.sqlite3` existente.

1. Hacé copia de seguridad de tu proyecto, especialmente `data/` y `backend/.env`.
2. Copiá `backend/app/ai_dashboard.py` y reemplazá `backend/app/main.py`.
3. Reemplazá `frontend/src/main.tsx`. Conservá los demás archivos del proyecto.
4. Verificá que `backend/.env` contenga `GEMINI_API_KEY` (no la compartás). No copies `.env` desde ningún ZIP.
5. En terminal backend (venv): `python -m pip install python-dotenv tzdata`; luego `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload`.
6. Abrí `http://127.0.0.1:8001/api/ai/status?symbol=EURUSD` y verificá `total_decisions` y `latest`.
7. En terminal frontend: `npm install` (si falta), `npm run dev`; abrí `http://127.0.0.1:5173` y seleccioná EURUSD.

El panel diferencia clave configurada, última respuesta histórica y disponibilidad actual no comprobada. El gasto API figura como 'Sin datos' porque el sistema no registra facturación verificada. El indicador de 'histórico registrado' no implica disponibilidad actual de Gemini.

**Importante:** el ZIP contiene solo los tres archivos modificados y estas instrucciones. No contiene credenciales, bases de datos, ni `.venv`.
