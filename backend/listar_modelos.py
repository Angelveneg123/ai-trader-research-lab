
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("No se encontró GEMINI_API_KEY")

client = genai.Client(api_key=api_key)

print("Consultando modelos disponibles...\n")

try:
    for modelo in client.models.list():
        acciones = getattr(modelo, "supported_actions", []) or []

        if "generateContent" in acciones:
            print(modelo.name)

except Exception as error:
    print(f"Error consultando modelos: {error}")
