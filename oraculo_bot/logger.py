import logging
import sys

def setup_logger(name="oraculo_bot"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(fmt)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger