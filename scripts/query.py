# scripts/query.py
import argparse
import sys
import os
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logger_config import setup_logging
from src.core_logic import handle_new_query, update_user_query_subscription

setup_logging()
logger = logging.getLogger(__name__)

# Son sorgu ID'sini saklamak için basit bir dosya yolu
LAST_QUERY_ID_FILE = ".last_query_id"

def save_last_query_id(query_id: int):
    """Son işlenen sorgu ID'sini bir dosyaya kaydeder."""
    try:
        with open(LAST_QUERY_ID_FILE, "w") as f:
            f.write(str(query_id))
        logger.debug(f"Last query ID {query_id} saved to {LAST_QUERY_ID_FILE}")
    except IOError as e:
        logger.error(f"Failed to save last query ID: {e}")

def load_last_query_id() -> int | None:
    """Kaydedilen son sorgu ID'sini dosyadan yükler."""
    try:
        if os.path.exists(LAST_QUERY_ID_FILE):
            with open(LAST_QUERY_ID_FILE, "r") as f:
                return int(f.read().strip())
        return None
    except (IOError, ValueError) as e:
        logger.error(f"Failed to load last query ID: {e}")
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interact with the Reactive RAG system.")
    
    # Alt komutlar (subparsers) kullanarak farklı eylemler için farklı argümanları mecburi kılma
    subparsers = parser.add_subparsers(dest="action", help="Action to perform", required=True)

    # 'query' alt komutu
    query_parser = subparsers.add_parser("query", help="Ask a question to the system.")
    query_parser.add_argument("--text", type=str, required=True, help="The query text.") # --text mecburi
    
    # 'subscribe' alt komutu
    subscribe_parser = subparsers.add_parser("subscribe", help="Subscribe to updates for a query.")
    # --id mecburi değil ama eğer verilmezse son ID kullanılacak, bu yüzden required=False bırakıldı
    # Eğer her zaman ID verilmesi gerekiyorsa required=True yapılmalı
    subscribe_parser.add_argument("--id", type=int, help="The query ID to subscribe to. If not provided, the last queried ID will be used.") 

    # 'unsubscribe' alt komutu
    unsubscribe_parser = subparsers.add_parser("unsubscribe", help="Unsubscribe from updates for a query.")
    # Aynı şekilde --id mecburi değil ama eğer verilmezse son ID kullanılacak
    unsubscribe_parser.add_argument("--id", type=int, help="The query ID to unsubscribe from. If not provided, the last queried ID will be used.") 
    
    args = parser.parse_args()
    
    if args.action == "query":
        logger.info(f"Starting a new query process for: '{args.text}'")
        user_query_id = handle_new_query(query_text=args.text)
        if user_query_id:
            print(f"Sorgu başarıyla işlendi. ID: {user_query_id}")
            save_last_query_id(user_query_id)
        else:
            print("Sorgu işlenirken bir hata oluştu.")

    elif args.action == "subscribe" or args.action == "unsubscribe":
        target_query_id = args.id
        if target_query_id is None:
            target_query_id = load_last_query_id()
            if target_query_id is None:
                logger.error(f"No query ID provided and no last query ID found. Please specify --id for '{args.action}' or run a query first.")
                sys.exit(1)
            logger.info(f"Using last queried ID: {target_query_id} for {args.action} action.")
        
        subscribe_status = (args.action == "subscribe")
        update_user_query_subscription(query_id=target_query_id, subscribe=subscribe_status)
        
    else: # Bu blok, 'required=True' ile artık tetiklenmemeli, ancak varsayılan olarak bırakıldı
        parser.print_help()
        logger.warning("No valid action specified. Please use 'query', 'subscribe', or 'unsubscribe'.")