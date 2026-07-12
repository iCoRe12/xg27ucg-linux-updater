# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .firmware import (
    FirmwareReport,
    analyze_firmware,
    checksum_cdb,
    filesize_cdb,
    iter_transfer_blocks,
    progress_cdb,
)
from .scsi import ScsiDevice, ScsiError


ProgressCallback = Callable[[int, int, int], None]


class FlashError(RuntimeError):
    pass


def _command_with_retry(
    device: ScsiDevice,
    cdb: bytes,
    *,
    data_out: bytes | None = None,
    data_in_length: int = 0,
    attempts: int = 7,
    retry_delay_seconds: float = 0.2,
) -> bytes:
    last_error: ScsiError | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(retry_delay_seconds)
        try:
            response = device.command(
                cdb,
                data_out=data_out,
                data_in_length=data_in_length,
                timeout_seconds=20,
            )
            return response.data
        except ScsiError as error:
            last_error = error
    raise FlashError(
        f"SCSI command {cdb.hex(' ')} failed after {attempts} attempts: {last_error}"
    ) from last_error


@contextmanager
def _ignore_interrupts_during_flash() -> Iterator[None]:
    previous: dict[int, object] = {}

    def warn_only(signum: int, _frame: object) -> None:
        name = signal.Signals(signum).name
        print(
            f"\nIgnoring {name}: interrupting a firmware transfer can brick the monitor.",
            file=sys.stderr,
            flush=True,
        )

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, warn_only)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def flash_firmware(
    device_path: str,
    firmware_path: str | Path,
    progress_callback: ProgressCallback | None = None,
) -> FirmwareReport:
    report = analyze_firmware(firmware_path)
    if not report.valid:
        raise FlashError("firmware validation failed: " + "; ".join(report.errors))
    data = Path(report.path).read_bytes()
    blocks = list(iter_transfer_blocks(data))

    with ScsiDevice(device_path, writable=True, exclusive=True) as device:
        inquiry = device.inquiry()
        if not inquiry.is_gcreader:
            raise FlashError(
                f"device INQUIRY vendor is {inquiry.vendor!r}, expected 'GCREADER'"
            )

        with _ignore_interrupts_during_flash():
            try:
                device.command(filesize_cdb(report.size))
            except ScsiError as error:
                raise FlashError(f"monitor rejected firmware size: {error}") from error
            try:
                device.command(checksum_cdb(report.checksum16))
            except ScsiError as error:
                raise FlashError(f"monitor rejected firmware checksum: {error}") from error

            last_programmed = 0
            for block in blocks:
                _command_with_retry(device, block.cdb, data_out=block.transfer)
                raw_progress = _command_with_retry(
                    device,
                    progress_cdb(),
                    data_in_length=4,
                    retry_delay_seconds=0.05,
                )
                if len(raw_progress) != 4:
                    raise FlashError(
                        f"monitor returned {len(raw_progress)} progress bytes, expected 4"
                    )
                programmed = int.from_bytes(raw_progress, "big")
                expected_programmed = block.offset + len(block.transfer)
                if programmed < last_programmed:
                    raise FlashError(
                        f"monitor progress moved backwards: {last_programmed} -> {programmed}"
                    )
                if programmed != expected_programmed:
                    raise FlashError(
                        "monitor did not acknowledge the exact transfer boundary: "
                        f"reported {programmed}, expected {expected_programmed}"
                    )
                last_programmed = programmed
                logical_done = min(block.offset + len(block.payload), report.size)
                percent = min(100, logical_done * 100 // report.size)
                if progress_callback is not None:
                    progress_callback(percent, logical_done, programmed)

    return report
