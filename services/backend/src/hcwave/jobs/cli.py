"""Command-line entry point for scheduled jobs (used by Kubernetes CronJobs).

Examples::

    hcwave-jobs reminders
    hcwave-jobs reminders --rules day_before,prep --hospital demo-hospital
    hcwave-jobs his-reports
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from hcwave.config import get_settings
from hcwave.core.container import Container
from hcwave.core.logging import configure_logging
from hcwave.core.telemetry import configure_telemetry
from hcwave.domain.services import Services
from hcwave.domain.tenants import sync_hospitals
from hcwave.jobs.runner import JOB_NAMES, JobRunner


async def amain(args: argparse.Namespace) -> int:
    """Runs one job and prints the JSON result. Returns the exit code."""
    settings = get_settings()
    configure_logging(settings.app.log_level, settings.app.log_format)
    configure_telemetry(settings.telemetry)
    container = Container(settings)
    try:
        await sync_hospitals(container.db, settings)
        options = {"rules": args.rules.split(",")} if args.rules else {}
        hospitals = args.hospital.split(",") if args.hospital else None
        result = await JobRunner(Services.build(container)).run(args.job, hospitals, **options)
        print(json.dumps(result, default=str))  # noqa: T201
        failed = any(isinstance(v, dict) and "error" in v for v in result.values())
        return 1 if failed else 0
    finally:
        await container.aclose()


def main() -> None:
    """Console entry point (``hcwave-jobs``)."""
    parser = argparse.ArgumentParser(description="Run an hcwave scheduled job")
    parser.add_argument("job", choices=JOB_NAMES)
    parser.add_argument("--hospital", help="Comma-separated hospital IDs (default: all)")
    parser.add_argument("--rules", help="Reminder rule IDs (reminders job only)")
    sys.exit(asyncio.run(amain(parser.parse_args())))


if __name__ == "__main__":
    main()
