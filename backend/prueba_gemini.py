
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

# Cargar la clave desde backend/.env
load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("No se encontró la clave de Gemini.")

# Conectar con Gemini
client = genai.Client(api_key=api_key)

print("Conectando con Gemini...")

from app.legacy_meter import generate_content
respuesta = generate_content(client,
    model="gemini-3.1-flash-lite",
    contents=(
        "Eres el analista de AI Trader Research Lab. "
        "Responde solamente: "
        "Gemini conectado correctamente. "
        "Estoy listo para analizar EURUSD."
    ),
)

print("\nRESPUESTA DE GEMINI:")
print(respuesta.text)