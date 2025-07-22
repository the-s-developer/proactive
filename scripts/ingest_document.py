import argparse
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logger_config import setup_logging
from src.core_logic import handle_new_document
import logging

setup_logging()
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a new document into the system.")
    parser.add_argument("--file", type=str, required=True, help="Path to the markdown document.")
    parser.add_argument("--url", type=str, required=True, help="Source URL of the document.")
    
    args = parser.parse_args()
    
    logger.info(f"Received request to ingest file: {args.file}")
    handle_new_document(file_path=args.file, source_url=args.url)