"""日志配置"""
from __future__ import annotations

import logging
import sys


def configure_logging(app) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    for name in [
        "focus_engine",
        "focus_engine.siliconflow_vlm",
        "focus_engine.session",
        "focus_engine.duration_recommender",
    ]:
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
