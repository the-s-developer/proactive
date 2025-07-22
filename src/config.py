import os
from dotenv import load_dotenv

# .env dosyasındaki değişkenleri yükle
load_dotenv()

# --- API ve Veritabanı Ayarları ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
POSTGRES_DB_URL = os.getenv("POSTGRES_DB_URL")
CHROMA_DB_PATH = "./chroma_db"

# --- Model Ayarları ---
DECOMPOSER_MODEL = os.getenv("DECOMPOSER_MODEL", "gpt-4.1")      # Sorgu ayrıştırma için
WORKER_MODEL = os.getenv("WORKER_MODEL", "gpt-4.1-mini")      # Prediction doldurma için

# --- Loglama Ayarları ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

