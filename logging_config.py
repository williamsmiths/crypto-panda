import logging
import os
from pathlib import Path
from typing import Union


def setup_logging(name: str,
                  log_dir: Union[str, Path] = None,
                  level: str = None,
                  caller_file: str = None) -> logging.Logger:
    """
    Create a logger that writes to console and a single per-script logfile.
    File path: <log_dir>/<script_stem>.log (overwrites each run)

    Parameters
    ----------
    name : str
        Logger name (typically __name__).
    log_dir : str or Path, optional
        Directory for log files. Defaults to ../logs relative to this file.
    level : str, optional
        Log level. Defaults to LOG_LEVEL env var or INFO.
    caller_file : str, optional
        The __file__ of the calling module, used to name the log file.
        Defaults to this file if not provided.
    """
    base_dir = Path(__file__).resolve().parent
    log_dir = Path(log_dir or (base_dir / "../logs")).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(caller_file).stem if caller_file else Path(__file__).stem
    log_path = log_dir / f"{stem}.log"

    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    level_val = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level_val)
    logger.propagate = False

    # Prevent duplicate handlers on reload
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = "%(asctime)sZ [%(levelname)s] %(name)s | %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    ch = logging.StreamHandler()
    ch.setLevel(level_val)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(str(log_path), mode="w", encoding="utf-8", delay=False)
    fh.setLevel(level_val)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    logger.info(f"Logging started → {log_path} (level={level_name})")
    return logger
