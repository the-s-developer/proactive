
# scripts/deactivate_unused_predictions.py

import sys
import os
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logger_config import setup_logging
from src.database import get_db, Prediction
from src.core_logic import check_prediction_has_active_links, deactivate_prediction # Yeni fonksiyonları import et

setup_logging()
logger = logging.getLogger(__name__)

def deactivate_unused_predictions_flow():
    logger.info("Starting unused prediction deactivation process.")
    db = next(get_db())
    try:
        # Tüm FULFILLED (aktif) Prediction'ları al
        active_predictions = db.query(Prediction).filter(Prediction.status == "FULFILLED").all()

        if not active_predictions:
            logger.info("No active predictions found to check for deactivation.")
            return

        for pred in active_predictions:
            has_active_link = check_prediction_has_active_links(db, pred.id)

            if not has_active_link:
                logger.info(f"Prediction ID {pred.id} (Prompt: '{pred.prediction_prompt[:50]}...') has no active links. Deactivating.")
                deactivate_prediction(db, pred.id)
            else:
                logger.debug(f"Prediction ID {pred.id} is still in use. Skipping deactivation.")

        logger.info("Unused prediction deactivation process finished.")

    except Exception as e:
        logger.error(f"Error during unused prediction deactivation: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    deactivate_unused_predictions_flow()