import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
import random
from agentic_inventory.utils.extensions import logger
from agentic_inventory.utils.measure import StressMetricsReporter
import concurrent.futures

# Remove hardcoded configurations - these will be passed from run_stress_test.py


@dataclass
class EndpointConfig:
    path: str
    method: str = "GET"
    payload: Dict = None
    expected_status: int = 200
    token_field: str = "tokens"
    depends_on: Optional[str] = None  # ID of the endpoint that needs to be called first
    response_id_field: Optional[str] = None  # Field in response to extract ID for dependent endpoints

    @classmethod
    def from_dict(cls, data: Dict) -> "EndpointConfig":
        return cls(**data)


@dataclass
class RunnerMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_tokens: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    latencies: List[float] = None
    memory_usage: List[float] = None
    cpu_usage: List[float] = None
    endpoint_stats: Dict[str, Dict] = None
    max_latency: float = 0
    min_latency: float = float("inf")
    tokens_per_endpoint: Dict[str, int] = None
    requests_per_second: List[float] = None
    tokens_per_second: List[float] = None

    def __post_init__(self):
        self.latencies = []
        self.memory_usage = []
        self.cpu_usage = []
        self.endpoint_stats = {}
        self.tokens_per_endpoint = {}
        self.requests_per_second = []
        self.tokens_per_second = []

    def update_endpoint_stats(self, endpoint: str, success: bool, latency: float, tokens: int):
        """Update statistics for a specific endpoint."""
        if endpoint not in self.endpoint_stats:
            self.endpoint_stats[endpoint] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "latencies": [],
                "total_tokens": 0,
            }

        endpoint_stats = self.endpoint_stats[endpoint]
        endpoint_stats["total_requests"] += 1
        if success:
            endpoint_stats["successful_requests"] += 1
            endpoint_stats["total_tokens"] += tokens
        else:
            endpoint_stats["failed_requests"] += 1
        endpoint_stats["latencies"].append(latency)

    def calculate_rps(self, window_size: int = 60):
        """Calculate requests per second over a sliding window."""
        if not self.latencies:
            return 0

        window_start = time.time() - window_size
        recent_requests = sum(1 for t in self.latencies if t >= window_start)
        return recent_requests / window_size

    def calculate_tps(self, window_size: int = 60):
        """Calculate tokens per second over a sliding window."""
        if not self.tokens_per_second:
            return 0

        return sum(self.tokens_per_second[-window_size:]) / min(window_size, len(self.tokens_per_second))


@dataclass
class RunnerEndpointMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_tokens: int = 0
    latencies: List[float] = field(default_factory=list)
    tokens_per_second: List[float] = field(default_factory=list)
    requests_per_second: List[float] = field(default_factory=list)
    last_token_update: float = field(default_factory=time.time)

    def add_request(self, success: bool, latency: float, tokens: int = 0):
        """Add a request to the metrics."""
        self.total_requests += 1
        if success:
            self.successful_requests += 1
            self.total_tokens += tokens
        else:
            self.failed_requests += 1

        self.latencies.append(latency)

        # Calculate tokens per second
        current_time = time.time()
        time_diff = current_time - self.last_token_update
        if time_diff > 0:
            tokens_per_second = tokens / time_diff
            self.tokens_per_second.append(tokens_per_second)
            self.last_token_update = current_time

        # Keep only the last 60 seconds of data for rate calculations
        cutoff_time = current_time - 60

        # Filter out old data
        self.latencies = [t for t in self.latencies if t >= cutoff_time]
        self.tokens_per_second = self.tokens_per_second[-60:]  # Keep last 60 values

    def get_summary(self) -> Dict:
        """Get a summary of the metrics."""
        if not self.latencies:
            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate": 0.0,
                "total_tokens": self.total_tokens,
                "average_latency": 0.0,
                "p95_latency": 0.0,
                "max_latency": 0.0,
                "min_latency": 0.0,
                "requests_per_second": 0.0,
                "tokens_per_second": 0.0,
            }

        latencies_sorted = sorted(self.latencies)
        p95_index = int(len(latencies_sorted) * 0.95)

        # Calculate tokens per second as moving average
        recent_tps = self.tokens_per_second[-60:] if self.tokens_per_second else [0]
        avg_tps = sum(recent_tps) / len(recent_tps)

        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": (self.successful_requests / self.total_requests) * 100 if self.total_requests > 0 else 0.0,
            "total_tokens": self.total_tokens,
            "average_latency": sum(self.latencies) / len(self.latencies),
            "p95_latency": latencies_sorted[p95_index] if p95_index < len(latencies_sorted) else latencies_sorted[-1],
            "max_latency": max(self.latencies),
            "min_latency": min(self.latencies),
            "requests_per_second": len(self.latencies) / 60.0,  # Average over last 60 seconds
            "tokens_per_second": avg_tps,
        }


class StressTestRunner:
    def __init__(
        self,
        base_url: str,
        target_rps: int = 10,
        max_duration: int = 24 * 60 * 60,  # 24 hours in seconds
        max_tokens: int = 100_000_000,
        report_dir: str = "stress_test_reports",
        endpoints: List[EndpointConfig] = None,
        concurrent_users: int = 1,  # Default to 1 concurrent user
    ):
        self.base_url = base_url
        self.target_rps = target_rps
        self.max_duration = max_duration
        self.max_tokens = max_tokens
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(exist_ok=True)
        self.session = None
        self.is_running = False
        self.endpoints = endpoints or []
        self.last_metrics_time = time.time()
        self.request_count_window = []
        self.token_count_window = []
        self.progress_interval = 1000
        self.session_ids = {}  # Store session IDs for dependent endpoints
        self.active_sessions = {}  # Store active sessions for reuse
        self.connection_pool = None
        self.rate_limiter = asyncio.Semaphore(target_rps)  # Rate limiting semaphore
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=concurrent_users
        )  # Use concurrent_users for thread pool
        self.max_workers = concurrent_users
        self.metrics_reporter = StressMetricsReporter()  # Initialize the metrics reporter
        self.metrics_reporter.test_metrics = RunnerMetrics()  # Initialize the metrics

    async def setup(self):
        """Initialize the test runner and create necessary resources."""
        # Create a connection pool with retry settings
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        connector = aiohttp.TCPConnector(
            limit=100,  # Limit concurrent connections
            ttl_dns_cache=300,  # Cache DNS results
            use_dns_cache=True,
            force_close=False,  # Keep connections alive
            enable_cleanup_closed=True,
            ssl=False,  # Disable SSL verification for local testing
        )
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector, headers={"Connection": "keep-alive"})

        # Start the metrics reporter
        self.metrics_reporter.start()

        # Create initial session for dependent endpoints
        session_endpoint = next(
            (ep for ep in self.endpoints if ep.method == "POST" and "sessions" in ep.path and not ep.depends_on), None
        )
        if session_endpoint:
            logger.info("Creating initial session for dependent endpoints")
            success, _, response = await self.make_request(session_endpoint)
            if success and response:
                session_id = response.get(session_endpoint.response_id_field)
                if session_id:
                    self.session_ids["session_create"] = session_id
                    logger.info(f"Created initial session with ID {session_id}")
                else:
                    logger.error("Failed to get session ID from response")
            else:
                logger.error("Failed to create initial session")

    async def cleanup(self):
        """Clean up resources after the test."""
        if self.session:
            await self.session.close()
        if self.thread_pool:
            self.thread_pool.shutdown(wait=True)
        # Stop the metrics reporter
        self.metrics_reporter.stop()

    async def make_request(self, endpoint: EndpointConfig) -> tuple[bool, float, Dict]:
        """Make a single request to the specified endpoint with improved error handling and retries."""
        start_time = time.time()
        retries = 3
        last_error = None

        while retries > 0:
            try:
                # Replace session_id placeholder if needed
                path = endpoint.path
                if "{session_id}" in path:
                    if endpoint.depends_on:
                        # Try both the exact dependency name and "session_create"
                        session_id = self.session_ids.get(endpoint.depends_on) or self.session_ids.get("session_create")
                        if not session_id:
                            # Try to create a new session if we don't have one
                            session_endpoint = next(
                                (
                                    ep
                                    for ep in self.endpoints
                                    if ep.method == "POST" and "sessions" in ep.path and not ep.depends_on
                                ),
                                None,
                            )
                            if session_endpoint:
                                success, _, response = await self.make_request(session_endpoint)
                                if success and response:
                                    session_id = response.get(session_endpoint.response_id_field)
                                    if session_id:
                                        # Store under both keys for compatibility
                                        self.session_ids["session_create"] = session_id
                                        self.session_ids[endpoint.depends_on] = session_id
                                        logger.info(f"Created new session with ID {session_id}")
                                        # Add delay after session creation
                                        await asyncio.sleep(1)
                    else:
                        # If no dependency specified, try to get the most recent session ID
                        session_id = next(iter(self.session_ids.values()), None)

                    if session_id:
                        path = path.replace("{session_id}", session_id)
                    else:
                        last_error = "No valid session ID available"
                        retries -= 1
                        await asyncio.sleep(1)
                        continue

                # Use rate limiter to control request rate
                async with self.rate_limiter:
                    if endpoint.method == "POST":
                        async with self.session.post(f"{self.base_url}{path}", json=endpoint.payload) as response:
                            latency = time.time() - start_time
                            success = response.status == endpoint.expected_status

                            # Record the request in the metrics reporter
                            tokens = 0
                            if success:
                                data = await response.json()
                                if endpoint.response_id_field:
                                    # Store the session ID if this is a session creation endpoint
                                    if "sessions" in path and endpoint.method == "POST":
                                        session_id = data.get(endpoint.response_id_field)
                                        if session_id:
                                            # Store under both keys for compatibility
                                            self.session_ids["session_create"] = session_id
                                            if endpoint.depends_on:
                                                self.session_ids[endpoint.depends_on] = session_id
                                            logger.info(f"Stored new session ID: {session_id}")
                                            # Add delay after session creation
                                            await asyncio.sleep(1)
                                    return success, latency, data
                                if endpoint.token_field:
                                    token_value = data
                                    for token_field in endpoint.token_field.split("."):
                                        token_value = token_value.get(token_field, {})
                                    if isinstance(token_value, dict):
                                        tokens = token_value.get("input", 0) + token_value.get("output", 0)
                                    else:
                                        tokens = token_value
                                else:
                                    tokens = 0

                                # Record the request in the metrics reporter
                                self.metrics_reporter.record_request(endpoint.path, success, latency, tokens)

                                return success, latency, {"tokens": tokens}
                            else:
                                error_data = await response.json()
                                last_error = f"Unexpected status code: {response.status}, Error: {error_data}"

                                # Record the failed request in the metrics reporter
                                self.metrics_reporter.record_request(endpoint.path, success, latency, 0)

                                if "BadRequest" in str(error_data):
                                    # For BadRequest errors, log more details and wait longer
                                    logger.error(f"BadRequest error details: {error_data}")
                                    await asyncio.sleep(2)  # Wait longer for BadRequest errors
                                else:
                                    await asyncio.sleep(1)
                                retries -= 1
                    else:
                        async with self.session.get(f"{self.base_url}{path}") as response:
                            latency = time.time() - start_time
                            success = response.status == endpoint.expected_status

                            # Record the request in the metrics reporter
                            if success:
                                data = await response.json()

                                # Record the request in the metrics reporter
                                self.metrics_reporter.record_request(endpoint.path, success, latency, 0)

                                return success, latency, data
                            else:
                                error_data = await response.json()
                                last_error = f"Unexpected status code: {response.status}, Error: {error_data}"

                                # Record the failed request in the metrics reporter
                                self.metrics_reporter.record_request(endpoint.path, success, latency, 0)

                                if "BadRequest" in str(error_data):
                                    # For BadRequest errors, log more details and wait longer
                                    logger.error(f"BadRequest error details: {error_data}")
                                    await asyncio.sleep(2)  # Wait longer for BadRequest errors
                                else:
                                    await asyncio.sleep(1)
                                retries -= 1
            except Exception as e:
                last_error = str(e)
                logger.error(f"Request failed: {last_error}")
                retries -= 1
                await asyncio.sleep(1)

        # If we get here, all retries failed
        logger.error(f"All retries failed for {endpoint.path}: {last_error}")
        return False, time.time() - start_time, {"error": last_error}

    async def run(self) -> Dict:
        """Run the stress test."""
        try:
            await self.setup()
            self.is_running = True
            start_time = time.time()

            while self.is_running and time.time() - start_time < self.max_duration:
                # Select a random endpoint
                endpoint = random.choice(self.endpoints)

                # Make the request
                success, latency, response = await self.make_request(endpoint)

                # Check if we've exceeded max tokens
                if self.metrics_reporter.test_metrics.total_tokens >= self.max_tokens:
                    logger.info(f"Reached max tokens limit: {self.max_tokens}")
                    break

                # Add a small delay to control RPS
                await asyncio.sleep(1.0 / self.target_rps)

            # Generate final report
            report = {
                "test_summary": {
                    "total_requests": self.metrics_reporter.test_metrics.total_requests,
                    "successful_requests": self.metrics_reporter.test_metrics.successful_requests,
                    "failed_requests": self.metrics_reporter.test_metrics.failed_requests,
                    "success_rate": (
                        (
                            self.metrics_reporter.test_metrics.successful_requests
                            / self.metrics_reporter.test_metrics.total_requests
                            * 100
                        )
                        if self.metrics_reporter.test_metrics.total_requests > 0
                        else 0.0
                    ),
                    "total_tokens": self.metrics_reporter.test_metrics.total_tokens,
                    "average_latency": (
                        sum(self.metrics_reporter.test_metrics.latencies)
                        / len(self.metrics_reporter.test_metrics.latencies)
                        if self.metrics_reporter.test_metrics.latencies
                        else 0.0
                    ),
                    "p95_latency": (
                        np.percentile(self.metrics_reporter.test_metrics.latencies, 95)
                        if self.metrics_reporter.test_metrics.latencies
                        else 0.0
                    ),
                    "max_latency": self.metrics_reporter.test_metrics.max_latency,
                    "min_latency": self.metrics_reporter.test_metrics.min_latency,
                    "max_memory_usage": (
                        max(self.metrics_reporter.test_metrics.memory_usage)
                        if self.metrics_reporter.test_metrics.memory_usage
                        else 0.0
                    ),
                    "average_memory_usage": (
                        sum(self.metrics_reporter.test_metrics.memory_usage)
                        / len(self.metrics_reporter.test_metrics.memory_usage)
                        if self.metrics_reporter.test_metrics.memory_usage
                        else 0.0
                    ),
                    "max_cpu_usage": (
                        max(self.metrics_reporter.test_metrics.cpu_usage)
                        if self.metrics_reporter.test_metrics.cpu_usage
                        else 0.0
                    ),
                    "average_cpu_usage": (
                        sum(self.metrics_reporter.test_metrics.cpu_usage)
                        / len(self.metrics_reporter.test_metrics.cpu_usage)
                        if self.metrics_reporter.test_metrics.cpu_usage
                        else 0.0
                    ),
                    "requests_per_second": self.metrics_reporter.test_metrics.calculate_rps(),
                    "tokens_per_second": self.metrics_reporter.test_metrics.calculate_tps(),
                    "endpoint_stats": self.metrics_reporter.test_metrics.endpoint_stats,
                },
                "test_config": {
                    "base_url": self.base_url,
                    "target_rps": self.target_rps,
                    "max_duration": self.max_duration,
                    "max_tokens": self.max_tokens,
                    "concurrent_users": self.max_workers,
                },
            }

            return report

        finally:
            self.is_running = False
            await self.cleanup()


async def main():
    """Main entry point for running the stress test."""
    # This function should be called from run_stress_test.py with the appropriate parameters
    # The parameters will be passed to the StressTestRunner constructor
    logger.info("This module should be imported and used by run_stress_test.py")
    logger.info("Please run the stress test using: python -m tests.stress.run_stress_test")


if __name__ == "__main__":
    asyncio.run(main())
