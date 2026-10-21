#!/usr/bin/env python3
"""Start a fully detached background command with no inherited pipe fds.

The dashboard runs start-all-local.sh as a child of control-api with
stdout/stderr pipes. A plain ``cmd >log 2>&1 &`` can still leave a grandchild
holding the original pipe (Fast DDS daemons, serial helpers, ...), which makes
the API's subprocess.communicate() wait forever even though the wrapper itself
exited. This helper closes every inherited descriptor except the log file and
returns immediately.

Usage: spawn-detached.py <logfile> <command> [args...]
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: spawn-detached.py <logfile> <command> [args...]", file=sys.stderr)
        return 2
    log_path = sys.argv[1]
    command = sys.argv[2:]
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "ab", buffering=0) as log:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
            cwd=os.getcwd(),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
