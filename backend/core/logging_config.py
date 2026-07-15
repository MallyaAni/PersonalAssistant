import logging
import sys
from typing import Any

def setup_logging(level: str = "INFO") -> None:
    """Configures the global logging settings."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)