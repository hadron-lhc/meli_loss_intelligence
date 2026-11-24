import logging

from loss_intelligence.logging import configure_logging


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level

    for handler in list(root.handlers):
        root.removeHandler(handler)

    try:
        configure_logging("DEBUG")
        configure_logging("INFO")
        marked_handlers = [
            handler
            for handler in root.handlers
            if getattr(handler, "_loss_intelligence_handler", False)
        ]
        assert len(marked_handlers) == 1
        assert root.level == logging.INFO
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
