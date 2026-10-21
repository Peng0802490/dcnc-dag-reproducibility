from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def ensure_dir(path: str | Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_dataframe(df: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def save_json(obj: Mapping[str, Any] | list[Any], path: str | Path) -> None:
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def build_run_logger(
    name: str,
    output_dir: str | Path,
    stem: str,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> tuple[logging.Logger, Path]:
    output_dir = ensure_dir(output_dir)
    log_dir = ensure_dir(output_dir / "logs")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{stem}_{timestamp}.log"

    logger = logging.getLogger(f"{name}.{timestamp}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(
        logging.Formatter(fmt="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
    )

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.info("Detailed log file: %s", log_path)
    return logger, log_path


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        try:
            handler.flush()
            handler.close()
        finally:
            logger.removeHandler(handler)
