import logging
from datetime import datetime
from typing import List, Dict, Any
from src.database import get_db, UserQuery

logger = logging.getLogger(__name__)

class AnswerMonitor:
    def __init__(self):
        logger.info("AnswerMonitor initialized.")

    def get_updated_answers_since(self, last_check_time: datetime) -> List[Dict[str, Any]]:
        """
        Verilen zamandan sonra güncellenmiş ve abone olunmuş cevapları (UserQuery'leri) getirir.
        """
        db = next(get_db())
        try:
            updated_queries = db.query(UserQuery).filter(
                UserQuery.is_subscribed == True,
                UserQuery.answer_last_updated > last_check_time
            ).all()

            updated_answers_data = [{
                "query_id": q.id,
                "query_text": q.query_text,
                "final_answer": q.final_answer,
                "last_updated": q.answer_last_updated
            } for q in updated_queries]
            
            if updated_answers_data:
                logger.info(f"Found {len(updated_answers_data)} updated answers since {last_check_time}.")
            return updated_answers_data
        finally:
            db.close()

answer_monitor = AnswerMonitor()