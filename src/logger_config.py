import logging
import sys
from src.config import LOG_LEVEL

def setup_logging():
    """Proje geneli için loglama yapılandırmasını ayarlar."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - (%(funcName)s:%(lineno)d) - %(message)s"
    
    root_logger = logging.getLogger()
    # Mevcut handler'ları temizleyerek tekrar tekrar eklenmesini önle
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.setLevel(LOG_LEVEL)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    file_handler = logging.FileHandler("app.log", mode='a')
    file_handler.setFormatter(logging.Formatter(log_format))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    logging.info("Logging configured successfully.")