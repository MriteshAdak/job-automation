"""Helper child process worker for multi-process worker lock testing (RUN-01-S02)."""

import argparse
import os
import sys
import time
from pathlib import Path

from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--owner-kind", default="search")
    parser.add_argument("--hold-seconds", type=float, default=2.0)
    parser.add_argument("--ready-file", default=None)
    args = parser.parse_args()

    kind = OwnerKind(args.owner_kind)
    lock = WindowsWorkerLock(args.data_root)

    try:
        with lock.acquire(owner_kind=kind, timeout_seconds=0.0):
            if args.ready_file:
                Path(args.ready_file).write_text(str(os.getpid()), encoding="utf-8")
            time.sleep(args.hold_seconds)
        return 0
    except Exception as exc:
        print(f"Lock worker error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
