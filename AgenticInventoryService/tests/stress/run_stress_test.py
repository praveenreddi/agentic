import asyncio
import argparse
import logging
import yaml
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List
from tests.stress.stress_test import StressTestRunner, EndpointConfig


@dataclass
class ScenarioConfig:
    name: str
    description: str
    target_rps: int
    max_duration: int
    max_tokens: int
    concurrent_users: int = 1
    ramp_up_time: int = 0
    endpoints: List[EndpointConfig] = None

    @classmethod
    def from_dict(cls, name: str, data: Dict) -> "ScenarioConfig":
        data = data.copy()  # Create a copy to avoid modifying the original
        endpoints_data = data.pop("endpoints", [])
        endpoints = [EndpointConfig.from_dict(ep) for ep in endpoints_data]
        data.pop("name", None)  # Remove name if it exists in data
        return cls(name=name, endpoints=endpoints, **data)


def load_config(config_path: str = "tests/stress/stress_config.yaml"):
    """Load stress test configuration from YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Convert scenarios to ScenarioConfig objects
    scenarios = {}
    for name, scenario_data in config["scenarios"].items():
        scenarios[name] = ScenarioConfig.from_dict(name, scenario_data)

    return {
        "scenarios": scenarios,
        "test_config": config["test_config"],
        "performance_thresholds": config["performance_thresholds"],
    }


# Load configuration
CONFIG = load_config()
SCENARIOS = CONFIG["scenarios"]
TEST_CONFIG = CONFIG["test_config"]
PERFORMANCE_THRESHOLDS = CONFIG["performance_thresholds"]


def setup_logging(log_dir: Path):
    """Set up logging configuration."""
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"stress_test_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run stress test on the service")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default=TEST_CONFIG["default_scenario"],
        help="Test scenario to run",
    )
    parser.add_argument("--base-url", default=TEST_CONFIG["base_url"], help="Base URL of the service to test")
    parser.add_argument("--target-rps", type=int, help="Target requests per second (overrides scenario default)")
    parser.add_argument(
        "--max-duration", type=int, help="Maximum test duration in seconds (overrides scenario default)"
    )
    parser.add_argument(
        "--max-tokens", type=int, help="Maximum number of tokens to process (overrides scenario default)"
    )
    parser.add_argument("--report-dir", default=str(TEST_CONFIG["report_dir"]), help="Directory to store test reports")
    parser.add_argument("--log-dir", default=str(TEST_CONFIG["log_dir"]), help="Directory to store log files")
    return parser.parse_args()


def validate_thresholds(report: dict) -> list[str]:
    """Validate test results against performance thresholds."""
    violations = []

    # Check if any thresholds were exceeded
    for metric, threshold in PERFORMANCE_THRESHOLDS.items():
        if metric in report["test_summary"]:
            value = report["test_summary"][metric]
            if value > threshold:
                violations.append(f"{metric}: {value} > {threshold}")

    return violations


async def main():
    """Main entry point for running the stress test."""
    args = parse_args()
    logger = setup_logging(Path(args.log_dir))

    # Get scenario configuration
    scenario = SCENARIOS[args.scenario]

    # Override scenario settings with command line arguments
    target_rps = args.target_rps or scenario.target_rps
    max_duration = args.max_duration or scenario.max_duration
    max_tokens = args.max_tokens or scenario.max_tokens

    logger.info(f"Starting stress test with scenario: {scenario.name}")
    logger.info(f"Target RPS: {target_rps}")
    logger.info(f"Max duration: {max_duration} seconds")
    logger.info(f"Max tokens: {max_tokens}")

    # Create and run the test
    runner = StressTestRunner(
        base_url=args.base_url,
        target_rps=target_rps,
        max_duration=max_duration,
        max_tokens=max_tokens,
        report_dir=args.report_dir,
        endpoints=scenario.endpoints,
        concurrent_users=scenario.concurrent_users,
    )

    try:
        report = await runner.run()

        # Validate results against thresholds
        violations = validate_thresholds(report)

        # Log results
        logger.info("Stress test completed")
        logger.info(f"Total requests: {report['test_summary']['total_requests']}")
        logger.info(f"Success rate: {report['test_summary']['success_rate']:.2f}%")
        logger.info(f"Total tokens: {report['test_summary']['total_tokens']}")
        logger.info(f"Average latency: {report['test_summary']['average_latency']:.3f}s")
        logger.info(f"P95 latency: {report['test_summary']['p95_latency']:.3f}s")
        logger.info(f"Max memory usage: {report['test_summary']['max_memory_usage']:.2f}MB")
        logger.info(f"Average CPU usage: {report['test_summary']['average_cpu_usage']:.2f}%")

        if violations:
            logger.warning("Performance threshold violations detected:")
            for violation in violations:
                logger.warning(f"- {violation}")
            return 1
        else:
            logger.info("All performance thresholds met")
            return 0

    except Exception as e:
        logger.error(f"Stress test failed: {str(e)}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
