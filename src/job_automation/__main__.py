"""Executable module entry point for python -m job_automation."""

from __future__ import annotations

import sys
from job_automation.cli import main

if __name__ == "__main__":
    sys.exit(main())

