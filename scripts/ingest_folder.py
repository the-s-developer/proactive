import argparse
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import frontmatter
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logger_config import setup_logging
from src.core_logic import handle_new_document

setup_logging()
logger = logging.getLogger(__name__)

def get_files_sorted_by_pub_date(directory: str) -> list[Path]:
    files_with_dates = []
    try:
        md_files = list(Path(directory).glob("*.md"))
        logger.info(f"Found {len(md_files)} markdown files in '{directory}'.")
    except FileNotFoundError:
        logger.error(f"Directory not found: {directory}")
        return []

    for file_path in md_files:
        try:
            post = frontmatter.load(file_path)
            pub_date_data = post.metadata.get('pub_date') or post.metadata.get('publication_date') # 'pub_date' veya 'publication_date'
            if pub_date_data:
                if isinstance(pub_date_data, str):
                    if pub_date_data.endswith('Z'):
                        pub_date_data = pub_date_data[:-1] + '+00:00'
                    publication_date_obj = datetime.fromisoformat(pub_date_data)
                else:
                    publication_date_obj = pub_date_data
                if publication_date_obj.tzinfo is None:
                    publication_date_obj = publication_date_obj.replace(tzinfo=timezone.utc)
                files_with_dates.append((file_path, publication_date_obj))
            else:
                logger.warning(f"Skipping file because it has no 'pub_date' or 'publication_date' in metadata: {file_path.name}")
        except Exception as e:
            logger.error(f"Could not process file {file_path.name}: {str(e)}")

    sorted_list = sorted(files_with_dates, key=lambda item: item[1])
    sorted_file_paths = [item[0] for item in sorted_list]
    return sorted_file_paths

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest all documents from a folder sorted by publication date.")
    parser.add_argument("--dir", type=str, default="documents", help="Path to the directory containing markdown documents.")
    args = parser.parse_args()
    
    logger.info(f"Starting ingestion process for directory: '{args.dir}'")
    files_to_process = get_files_sorted_by_pub_date(args.dir)
    
    if not files_to_process:
        logger.info("No documents with valid 'publication_date' found to process.")
    else:
        logger.info(f"Found {len(files_to_process)} documents to process in chronological order.")
        # SADE VE DOĞRU DÖNGÜ
        for file_path in files_to_process:
            handle_new_document(file_path=str(file_path))

    logger.info("Ingestion process finished.")