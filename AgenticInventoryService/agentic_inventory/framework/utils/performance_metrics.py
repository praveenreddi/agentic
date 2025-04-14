import time
import functools
from typing import Any, Callable, Optional, TypeVar, cast
from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger

T = TypeVar("T")


class PerformanceTracker:
    """Singleton for tracking performance metrics across the application."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PerformanceTracker, cls).__new__(cls)
            cls._instance.metrics = {}
            cls._instance.call_counts = {}
        return cls._instance

    def record_metric(self, function_name, execution_time, metadata=None):
        """Record a performance metric."""
        if function_name not in self.metrics:
            self.metrics[function_name] = {"total_time": 0, "min_time": float("inf"), "max_time": 0, "calls": 0}

        self.metrics[function_name]["total_time"] += execution_time
        self.metrics[function_name]["min_time"] = min(self.metrics[function_name]["min_time"], execution_time)
        self.metrics[function_name]["max_time"] = max(self.metrics[function_name]["max_time"], execution_time)
        self.metrics[function_name]["calls"] += 1

        # Store in provided metadata if available
        if metadata and isinstance(metadata, dict):
            if "performance_metrics" not in metadata:
                metadata["performance_metrics"] = {}
            metadata["performance_metrics"][function_name] = execution_time

        # Increment call count
        if function_name not in self.call_counts:
            self.call_counts[function_name] = 0
        self.call_counts[function_name] += 1

    def get_metrics(self):
        """Get all recorded metrics with average time calculation."""
        result = {}
        for func_name, data in self.metrics.items():
            avg_time = data["total_time"] / data["calls"] if data["calls"] > 0 else 0
            result[func_name] = {
                "total_time": data["total_time"],
                "min_time": data["min_time"],
                "max_time": data["max_time"],
                "avg_time": avg_time,
                "calls": data["calls"],
            }
        return result

    def reset(self):
        """Reset all metrics."""
        self.metrics = {}
        self.call_counts = {}


# Global instance
tracker = PerformanceTracker()


def measure_execution_time(
    func: Optional[Callable[..., T]] = None,
    *,
    log_level: str = config.LOG_LEVEL,
    log_prefix: str = "Function execution time",
    metadata_key: Optional[str] = None,
    track_in_metrics: bool = True,
) -> Callable[..., T]:
    """
    Decorator to measure and log the execution time of a function.

    Args:
        func: The function to decorate
        log_level: The logging level to use (default: from config)
        log_prefix: Prefix for the log message
        metadata_key: If provided, store the execution time in metadata[metadata_key]
        track_in_metrics: Whether to track this function in the global metrics

    Returns:
        The decorated function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                end_time = time.perf_counter()
                duration_ms = (end_time - start_time) * 1000
                duration_sec = duration_ms / 1000

                # Log the execution time using the centralized logger
                logger.log(logger.getEffectiveLevel(), f"{log_prefix} - {func.__name__}: {duration_ms:.2f}ms")

                # Store in metadata if metadata_key is provided
                if metadata_key and "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
                    kwargs["metadata"][metadata_key] = round(duration_sec, 2)

                # Track in global metrics if requested
                if track_in_metrics:
                    tracker.record_metric(
                        func.__name__, duration_sec, kwargs.get("metadata") if "metadata" in kwargs else None
                    )

        return cast(Callable[..., T], wrapper)

    if func is None:
        return decorator
    return decorator(func)


def get_performance_metrics():
    """Get all performance metrics."""
    return tracker.get_metrics()


def reset_performance_metrics():
    """Reset all performance metrics."""
    tracker.reset()
