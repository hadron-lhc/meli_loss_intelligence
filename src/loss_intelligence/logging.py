import logging
import sys
import time

_HANDLER_MARKER = "_loss_intelligence_handler"
_LOG_FORMAT = "%(asctime)sZ %(levelname)s %(name)s %(message)s"


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    if any(getattr(handler, _HANDLER_MARKER, False) for handler in root.handlers):
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(UTCFormatter(_LOG_FORMAT))
    setattr(handler, _HANDLER_MARKER, True)
    root.addHandler(handler)
