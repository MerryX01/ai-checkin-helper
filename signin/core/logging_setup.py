"""日志：控制台 + 按日期滚动的文件日志（UTF-8）。"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

LOGGER_NAME = "signin"


def setup(log_dir: str = "logs") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:  # 重复调用直接复用
        return logger

    # 相对路径按工程（或 exe）所在目录解析：从别的目录启动 exe 时日志不会乱跑
    if not os.path.isabs(str(log_dir)):
        try:
            from .config import ROOT
            log_dir = str(ROOT / log_dir)
        except Exception:
            pass

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "checkin.log")
        file_handler = TimedRotatingFileHandler(path, when="midnight", backupCount=30, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception as e:  # 目录不可写时降级为纯控制台
        logger.warning("无法写入日志文件：%s", e)

    return logger
