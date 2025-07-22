import sys
import os
import logging

# Proje kök dizinini Python path'ine ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logger_config import setup_logging
from src.database import engine, Base
from src.vector_store import vector_store # Import the singleton instance

setup_logging()
logger = logging.getLogger(__name__)

def reset_databases():
    """
    Tüm PostgreSQL tablolarını ve ChromaDB koleksiyonlarını siler ve yeniden oluşturur.
    Bu işlem geri alınamaz!
    """

    # --- PostgreSQL Resetleme ---
    try:
        logger.info("Resetting PostgreSQL database...")
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        logger.info("All PostgreSQL tables recreated.")
        print("✅ PostgreSQL database has been reset successfully.")
    except Exception as e:
        logger.error(f"Failed to reset PostgreSQL database: {e}", exc_info=True)
        print(f"❌ Error during PostgreSQL reset: {e}")

    # --- ChromaDB Resetleme ---
    # Not: PersistentClient, init sırasında koleksiyon referanslarını alır.
    # Koleksiyonları sildiğimizde, bu referanslar geçersiz kalabilir.
    # Bu nedenle, silme ve yeniden oluşturma sonrası referansları güncelleyeceğiz.
    try:
        logger.info("Deleting ChromaDB collections...")
        # Check if collections exist before trying to delete (avoids ValueError if already deleted)
        if "documents" in vector_store.client.list_collections():
            vector_store.client.delete_collection(name="documents")
        if "predictions" in vector_store.client.list_collections():
            vector_store.client.delete_collection(name="predictions")
        logger.info("ChromaDB 'documents' and 'predictions' collections deleted.")
        print("✅ ChromaDB collections have been deleted successfully.")
    except Exception as e: # Catching generic Exception for robustness
        logger.warning(f"Error during ChromaDB collection deletion (might not exist): {e}")
        print(f"ℹ️ Error during ChromaDB collection deletion, possibly collections did not exist: {e}")

    # Koleksiyonları sildikten/boşalttıktan sonra yeniden oluştur ve referansları güncelle
    try:
        logger.info("Re-creating ChromaDB collections and updating singleton references...")
        vector_store.document_collection = vector_store.client.get_or_create_collection(name="documents")
        vector_store.prediction_collection = vector_store.client.get_or_create_collection(name="predictions")
        logger.info("ChromaDB 'documents' and 'predictions' collections re-created and references updated.")
        print("✅ ChromaDB collections have been re-created and references updated successfully.")
    except Exception as e:
        logger.error(f"Failed to re-create ChromaDB collections or update references: {e}", exc_info=True)
        print(f"❌ Error during ChromaDB collection re-creation or reference update: {e}")


if __name__ == "__main__":
    reset_databases()