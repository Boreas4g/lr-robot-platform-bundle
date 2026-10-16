"""Single-owner USB sampling process, independent of web/API restarts."""
from __future__ import annotations

import argparse
import fcntl
import logging
import signal
from pathlib import Path
from threading import Event

from xt369 import XT369Reader

from .battery import BatteryStore, boot_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--serial")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    target = Path(args.state)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = (target.parent / "collector.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    store = BatteryStore(target)
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    boot = boot_id()
    reader = XT369Reader(serial=args.serial, poll_interval=1.0, report_timeout=2.0)
    previous_error = None
    try:
        while not stop.is_set():
            try:
                info = reader.connect()
                logging.info("XT369 connected: %s serial=%s", info.path, info.serial)
                while not stop.is_set():
                    measurement = reader.read()
                    if measurement is None:
                        raise TimeoutError("XT369 读取超时，正在重连")
                    store.record(measurement, device_serial=info.serial, boot=boot)
                    previous_error = None
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                store.fail(message)
                if message != previous_error:
                    logging.warning("%s", message)
                    previous_error = message
                reader.close()
                stop.wait(3.0)
    finally:
        reader.close()
        store.fail("XT369 采集服务已停止")
        lock.close()


if __name__ == "__main__":
    main()
