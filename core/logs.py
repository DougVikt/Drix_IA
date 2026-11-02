import os, sys, traceback, warnings
import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "drix.log"
_logger = None
_hooks_installed = False


def _ensure_logger():
    global _logger
    if _logger is not None:
        return _logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _logger = logging.getLogger("drix")
    _logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler(
        str(_LOG_FILE), maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    _logger.addHandler(handler)
    return _logger


def _global_excepthook(exc_type, exc_value, exc_tb):
    log = _ensure_logger()
    log.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))


def _install_hooks():
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    warnings.filterwarnings("ignore", message=".*SelectableGroups.*")

    sys.excepthook = _global_excepthook

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        str(_LOG_DIR / "all.log"), maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(name)-20s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root_logger.addHandler(file_handler)

    _old_stderr = sys.stderr
    class _StderrLogger:
        _noisy = ("SelectableGroups", "DeprecationWarning")
        def write(self, msg):
            if msg.strip():
                _ensure_logger().warning(f"[stderr] {msg.strip()}")
            if not any(n in msg for n in self._noisy):
                _old_stderr.write(msg)
        def flush(self):
            _old_stderr.flush()
    sys.stderr = _StderrLogger()


def setup():
    _ensure_logger()
    _install_hooks()


def info(msg):
    _ensure_logger().info(msg)

def warn(msg):
    _ensure_logger().warning(msg)

def error(msg):
    _ensure_logger().error(msg)

def debug(msg):
    _ensure_logger().debug(msg)

def user_query(query, response=None):
    log = _ensure_logger()
    log.info(f"USER: {query[:200]}")
    if response:
        log.info(f"AI:   {response[:500]}")

def command(cmd, args, result=None):
    log = _ensure_logger()
    log.info(f"CMD:  /{cmd} {' '.join(args)}")
    if result:
        log.info(f"RES:  {result[:200]}")

def log_path():
    return str(_LOG_FILE)
