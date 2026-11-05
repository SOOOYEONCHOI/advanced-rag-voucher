"""Date-based application logging configuration."""

import json
import logging
import logging.config
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from app.core.config import LOG_ERROR_RETENTION_DAYS, LOG_LEVEL, LOG_PATH, LOG_RETENTION_DAYS


class DailyFileHandler(logging.Handler):
    """Write directly to YYYYMMDD_LOG_<LABEL>.log and switch at midnight."""

    _NAME_RE = re.compile(r"^(\d{8})_LOG_(DEBUG|INFO|ERROR)\.log$")

    def __init__(self, directory: str, label: str, retention_days: int, encoding="utf-8"):
        super().__init__()
        self.directory = Path(directory)
        self.label = label.upper()
        self.retention_days = int(retention_days)
        self.encoding = encoding
        self.terminator = "\n"
        self._date = ""
        self._stream = None
        self.directory.mkdir(parents=True, exist_ok=True)
        self._delete_expired()

    def emit(self, record):
        try:
            current_date = datetime.now().strftime("%Y%m%d")
            if current_date != self._date:
                self._switch_file(current_date)
            self._stream.write(self.format(record) + self.terminator)
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def _switch_file(self, current_date: str) -> None:
        if self._stream:
            self._stream.close()
        path = self.directory / f"{current_date}_LOG_{self.label}.log"
        self._stream = path.open("a", encoding=self.encoding)
        self._date = current_date
        self._delete_expired()

    def _delete_expired(self) -> None:
        cutoff = date.today() - timedelta(days=self.retention_days)
        for path in self.directory.glob(f"*_LOG_{self.label}.log"):
            match = self._NAME_RE.fullmatch(path.name)
            if not match:
                continue
            try:
                file_date = datetime.strptime(match.group(1), "%Y%m%d").date()
                if file_date < cutoff:
                    path.unlink()
            except (OSError, ValueError):
                continue

    def close(self) -> None:
        if self._stream:
            self._stream.close()
            self._stream = None
        super().close()


class DebugOnlyFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == logging.DEBUG


class InfoWarningFilter(logging.Filter):
    def filter(self, record):
        return logging.INFO <= record.levelno < logging.ERROR


class LoggingLogger:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, data=None):
        if type(self)._initialized:
            return
        self.data = data
        self._configure()
        type(self)._initialized = True

    @staticmethod
    def _configure() -> None:
        try:
            with (Path(__file__).parent / "logger.json").open(encoding="utf-8") as handle:
                config = json.load(handle)
            for name in ("file_debug", "file_info", "file_error"):
                config["handlers"][name]["directory"] = LOG_PATH
            config["handlers"]["file_debug"]["retention_days"] = LOG_RETENTION_DAYS
            config["handlers"]["file_info"]["retention_days"] = LOG_RETENTION_DAYS
            config["handlers"]["file_error"]["retention_days"] = LOG_ERROR_RETENTION_DAYS
            config["handlers"]["console"]["level"] = LOG_LEVEL
            config["root"]["level"] = LOG_LEVEL
            logging.config.dictConfig(config)
        except Exception as exc:
            logging.basicConfig(
                level=logging.INFO,
                format="[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
                handlers=[logging.StreamHandler(sys.stderr)],
                force=True,
            )
            logging.getLogger(__name__).exception("Logging configuration failed: %s", exc)

    def getLogger(self, name: str | None = None):
        return logging.getLogger(name)
