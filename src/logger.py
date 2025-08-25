import io
import logging
from pathlib import Path

def get_logger(debug_log_file: Path) -> logging.Logger:
    logger = logging.getLogger("oiac")
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)

    fh = logging.FileHandler(debug_log_file)
    fh.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)

    return logger