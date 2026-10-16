"""Process interface: stdout contains data only, diagnostics use stderr."""
import argparse
import json
import math
import sys
import time

from .api import XT369Reader, format_measurement
from .device import AmbiguousDevice, DeviceNotFound, enumerate_devices


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be positive and finite')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description='XT369 Linux voltage/current interface')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='list XT369 candidates as JSON')
    read = sub.add_parser('read', help='stream live measurements (active query is automatic)')
    read.add_argument('--device', help='optional /dev/hidrawX path')
    read.add_argument('--serial', help='optional USB serial')
    read.add_argument('--format', choices=['text', 'json'], default='text')
    read.add_argument('--duration', type=positive, help='seconds; omit for continuous operation')
    read.add_argument('--timeout', type=positive, default=1.5, help='per-read timeout in seconds')
    read.add_argument('--poll-interval', type=positive, default=1.0, help='query interval, at least 1 second')
    # Compatibility with the established invocation; queries are always enabled.
    read.add_argument('--poll', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == 'list':
            print(json.dumps([d.to_dict() for d in enumerate_devices() if d.candidate],
                             ensure_ascii=False), flush=True)
            return 0
        with XT369Reader(args.device, serial=args.serial,
                         poll_interval=args.poll_interval,
                         report_timeout=args.timeout) as reader:
            deadline = time.monotonic() + args.duration if args.duration else math.inf
            count = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 0 if count else 3
                measurement = reader.read(timeout=min(args.timeout, remaining))
                if measurement is None:
                    if time.monotonic() >= deadline and count:
                        return 0
                    print('XT369 measurement timeout', file=sys.stderr)
                    return 3
                print(format_measurement(measurement) if args.format == 'text' else
                      json.dumps(measurement.to_dict(), ensure_ascii=False), flush=True)
                count += 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except (OSError, ValueError, DeviceNotFound, AmbiguousDevice) as exc:
        print(str(exc), file=sys.stderr)
        return 2
