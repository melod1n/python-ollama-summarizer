import logging
import os
from logging.handlers import RotatingFileHandler

from app.core.config import LOG_PATH


def setup_logger(name: str = "summary_logger") -> logging.Logger:
    logger = logging.getLogger(name)

    # If already configured, return as-is (prevents duplicate handlers)
    if getattr(logger, "_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False  # prevent double logs via root logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # --- Console handler (great for Docker) ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # --- File handler (skip if LOG_PATH is empty/None) ---
    if LOG_PATH:
        log_dir = os.path.dirname(LOG_PATH) or "."
        os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
            delay=True,  # don't open file until first write
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger._configured = True
    return logger


log = setup_logger()
