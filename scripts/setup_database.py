import sys
import os
# Proje kök dizinini Python path'ine ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import create_tables

if __name__ == "__main__":
    print("Creating database tables...")
    create_tables()
    print("Done.")