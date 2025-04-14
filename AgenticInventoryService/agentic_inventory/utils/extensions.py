"""
Extension functions and add-ons that extend the FastAPI application,
including centralized logging configuration.
"""

import logging
import ecs_logging
from opencensus.ext.azure.log_exporter import AzureEventHandler
import agentic_inventory.utils.config as config


class TimingFormatter(logging.Formatter):
    """Custom formatter that includes timing information when available."""

    def format(self, record):
        # First format the record normally
        message = super().format(record)

        # If we have timing information in the extra fields, append it
        if hasattr(record, "function") and hasattr(record, "duration_ms"):
            message = f"{message} - {record.function} - {record.duration_ms} ms"

        return message


def setup_logger() -> logging.Logger:
    """
    Set up a centralized logger with ECS/Plain formatting and Azure integration.

    Returns:
        logging.Logger: Configured logger instance
    """
    # Suppress root logger to avoid double logging
    logging.getLogger().handlers = []
    logging.getLogger().addHandler(logging.NullHandler())

    _logger = logging.getLogger(__name__)
    _logger.setLevel(map_log_level())

    # Console handler setup
    ch = logging.StreamHandler()
    ch.setLevel(map_log_level())

    if not config.PLAIN_LOGS:
        # ECS format for cloud logging
        ch.setFormatter(ecs_logging.StdlibFormatter(stack_trace_limit=5))

        # Azure Monitor integration
        if config.APPLICATIONINSIGHTS_CONNECTION_STRING:
            azure_handler = AzureEventHandler(connection_string=config.APPLICATIONINSIGHTS_CONNECTION_STRING)
            azure_handler.setLevel(map_log_level())
            _logger.addHandler(azure_handler)
            _logger.debug("Azure Monitor integration enabled.")
        else:
            _logger.debug("Azure Monitor integration not configured.")
    else:
        # Plain log format for local dev
        base_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ch.setFormatter(TimingFormatter(base_format))
        _logger.debug("Using plain log format for local development.")

    _logger.addHandler(ch)

    return _logger


def map_log_level() -> int:
    """Maps the string log level to the numeric equivalent for configuring the logger."""
    if config.LOG_LEVEL == "DEBUG":
        return logging.DEBUG
    elif config.LOG_LEVEL == "INFO":
        return logging.INFO
    elif config.LOG_LEVEL == "WARNING":
        return logging.WARNING
    elif config.LOG_LEVEL == "ERROR":
        return logging.ERROR
    elif config.LOG_LEVEL == "CRITICAL":
        return logging.CRITICAL
    else:
        return logging.ERROR  # Default to ERROR


# Singleton logger instance
logger = setup_logger()
