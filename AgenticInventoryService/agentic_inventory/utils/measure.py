import time
import asyncio
from functools import wraps
from typing import Callable, Dict, Any
from threading import Lock
from datetime import datetime
import psutil
from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger


class StressMetricsReporter:
    """
    Singleton class for collecting and reporting stress test metrics.
    Reports metrics every 5 seconds.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(StressMetricsReporter, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.endpoints: Dict[str, Any] = {}
        self.test_metrics = None  # Will be initialized by stress_test.py
        self.start_time = time.time()
        self.is_running = False
        self.report_task = None

    def start(self):
        """Start the metrics reporter."""
        if self.is_running:
            return

        self.is_running = True
        self.start_time = time.time()
        if self.test_metrics:
            self.test_metrics.start_time = datetime.now()
        self.report_task = asyncio.create_task(self._report_loop())
        logger.info("Stress metrics reporter started")

    def stop(self):
        """Stop the metrics reporter."""
        if not self.is_running:
            return

        self.is_running = False
        if self.report_task:
            self.report_task.cancel()
            self.report_task = None
        if self.test_metrics:
            self.test_metrics.end_time = datetime.now()
        logger.info("Stress metrics reporter stopped")

    async def _report_loop(self):
        """Report metrics every 5 seconds."""
        try:
            while self.is_running:
                await asyncio.sleep(5)
                self._report_metrics()
        except asyncio.CancelledError:
            # Final report before stopping
            self._report_metrics()

    def _report_metrics(self):
        """Report current metrics."""
        if not self.endpoints or not self.test_metrics:
            return

        total_metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "average_latency": 0.0,
            "p95_latency": 0.0,
            "max_latency": 0.0,
            "min_latency": float("inf"),
            "requests_per_second": 0.0,
            "tokens_per_second": 0.0,
        }

        # Collect all latencies and calculate rates
        all_latencies = []
        elapsed_time = time.time() - self.start_time

        for endpoint, metrics in self.endpoints.items():
            # Get raw data from endpoint metrics
            all_latencies.extend(metrics.latencies)
            total_metrics["total_requests"] += metrics.total_requests
            total_metrics["successful_requests"] += metrics.successful_requests
            total_metrics["failed_requests"] += metrics.failed_requests
            total_metrics["total_tokens"] += metrics.total_tokens

        # Calculate overall metrics
        if total_metrics["total_requests"] > 0:
            # Calculate success rate
            total_metrics["success_rate"] = (
                total_metrics["successful_requests"] / total_metrics["total_requests"]
            ) * 100

            # Calculate requests per second over total time
            total_metrics["requests_per_second"] = total_metrics["total_requests"] / elapsed_time

            # Calculate tokens per second over total time
            total_metrics["tokens_per_second"] = total_metrics["total_tokens"] / elapsed_time

        # Calculate latency metrics if we have any requests
        if all_latencies:
            total_metrics["average_latency"] = sum(all_latencies) / len(all_latencies)
            total_metrics["max_latency"] = max(all_latencies)
            total_metrics["min_latency"] = min(all_latencies)
            all_latencies.sort()
            p95_index = int(len(all_latencies) * 0.95)
            total_metrics["p95_latency"] = (
                all_latencies[p95_index] if p95_index < len(all_latencies) else all_latencies[-1]
            )

        # Update test metrics
        self.test_metrics.total_requests = total_metrics["total_requests"]
        self.test_metrics.successful_requests = total_metrics["successful_requests"]
        self.test_metrics.failed_requests = total_metrics["failed_requests"]
        self.test_metrics.total_tokens = total_metrics["total_tokens"]

        # Format the metrics report
        metrics_report = f"""
            Stress Test Metrics Report:
            --------------------------
            Elapsed Time: {elapsed_time:.2f}s
            Total Requests: {total_metrics["total_requests"]}
            Success Rate: {total_metrics['success_rate']:.2f}%
            Total Tokens: {total_metrics["total_tokens"]}
            Average Latency: {total_metrics['average_latency']*1000:.2f}ms
            P95 Latency: {total_metrics['p95_latency']*1000:.2f}ms
            Max Latency: {total_metrics['max_latency']*1000:.2f}ms
            Min Latency: {total_metrics['min_latency']*1000:.2f}ms
            Requests/Second: {total_metrics['requests_per_second']:.2f}
            Tokens/Second: {total_metrics['tokens_per_second']:.2f}

            Endpoint Stats:
            ---------------"""

        # Add detailed endpoint stats
        for endpoint, metrics in self.endpoints.items():
            if metrics.latencies:
                avg_latency = sum(metrics.latencies) / len(metrics.latencies)
                recent_latencies = metrics.latencies[-5:]  # Get last 5 latencies
            else:
                avg_latency = 0
                recent_latencies = []

            metrics_report += f"""

            {endpoint}:
              Total Requests: {metrics.total_requests}
              Successful: {metrics.successful_requests}
              Failed: {metrics.failed_requests}
              Total Tokens: {metrics.total_tokens}
              Average Latency: {avg_latency*1000:.2f}ms
              Recent Latencies: {[f"{lat*1000:.2f}ms" for lat in recent_latencies]}"""

        logger.info(metrics_report)

    def record_request(self, endpoint: str, success: bool, latency: float, tokens: int = 0):
        """Record a request for an endpoint."""
        if endpoint not in self.endpoints:
            from tests.stress.stress_test import RunnerEndpointMetrics

            self.endpoints[endpoint] = RunnerEndpointMetrics()

        # Store the raw latency in seconds
        self.endpoints[endpoint].latencies.append(latency)

        # Update endpoint metrics
        if success:
            self.endpoints[endpoint].successful_requests += 1
            self.endpoints[endpoint].total_tokens += tokens
        else:
            self.endpoints[endpoint].failed_requests += 1

        self.endpoints[endpoint].total_requests += 1

        # Update global metrics
        if self.test_metrics:
            self.test_metrics.total_requests += 1
            if success:
                self.test_metrics.successful_requests += 1
                self.test_metrics.total_tokens += tokens
            else:
                self.test_metrics.failed_requests += 1

            self.test_metrics.latencies.append(latency)
            self.test_metrics.requests_per_second.append(1)
            self.test_metrics.tokens_per_second.append(tokens)

            # Update min/max latency
            self.test_metrics.min_latency = min(self.test_metrics.min_latency, latency)
            self.test_metrics.max_latency = max(self.test_metrics.max_latency, latency)

            # Record memory and CPU usage
            self.test_metrics.memory_usage.append(psutil.Process().memory_info().rss / 1024 / 1024)  # MB
            self.test_metrics.cpu_usage.append(psutil.Process().cpu_percent())


def measure_ts(func: Callable) -> Callable:
    """
    Decorator to measure and log function execution time.
    Only logs if MEASURE_LATENCY is enabled in config.

    Args:
        func: The function to measure

    Returns:
        The decorated function
    """

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = await func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = (end_time - start_time) * 1000  # Convert to milliseconds

        if config.MEASURE_LATENCY:
            logger.info(
                "Function execution time",
                extra={"function": f"{func.__module__}:{func.__name__}", "duration_ms": f"{duration:.2f}"},
            )

        return result

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = (end_time - start_time) * 1000  # Convert to milliseconds

        if config.MEASURE_LATENCY:
            logger.info(
                "Function execution time",
                extra={"function": f"{func.__module__}:{func.__name__}", "duration_ms": f"{duration:.2f}"},
            )

        return result

    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
