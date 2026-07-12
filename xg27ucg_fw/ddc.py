# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass


TARGET_MANUFACTURER = "AUS"
TARGET_MODEL = "XG27UCG"


class DdcError(RuntimeError):
    pass


@dataclass(frozen=True)
class DdcMonitor:
    display: int
    bus: int
    connector: str
    manufacturer: str
    model: str
    serial: str

    def to_dict(self) -> dict[str, object]:
        return {
            "display": self.display,
            "bus": self.bus,
            "bus_path": f"/dev/i2c-{self.bus}",
            "connector": self.connector,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
        }


@dataclass(frozen=True)
class VcpValue:
    code: int
    mh: int
    ml: int
    sh: int
    sl: int

    @property
    def maximum(self) -> int:
        return (self.mh << 8) | self.ml

    @property
    def current(self) -> int:
        return (self.sh << 8) | self.sl

    def to_dict(self) -> dict[str, int | str]:
        return {
            "code": f"0x{self.code:02x}",
            "mh": self.mh,
            "ml": self.ml,
            "sh": self.sh,
            "sl": self.sl,
            "maximum": self.maximum,
            "current": self.current,
        }


def _ddcutil() -> str:
    command = shutil.which("ddcutil")
    if not command:
        raise DdcError("ddcutil is not installed")
    return command


def _run(arguments: list[str], timeout: int = 20) -> str:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    process = subprocess.run(
        [_ddcutil(), "--noconfig", *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=env,
        check=False,
    )
    if process.returncode != 0:
        raise DdcError(
            f"ddcutil exited with status {process.returncode}:\n{process.stdout.strip()}"
        )
    return process.stdout


def detect_monitors() -> list[DdcMonitor]:
    output = _run(["detect", "--brief"])
    sections = re.split(r"(?=^Display\s+\d+\s*$)", output, flags=re.MULTILINE)
    monitors: list[DdcMonitor] = []
    for section in sections:
        display_match = re.search(r"^Display\s+(\d+)\s*$", section, re.MULTILINE)
        bus_match = re.search(r"I2C bus:\s+/dev/i2c-(\d+)", section)
        monitor_match = re.search(r"Monitor:\s+([^:\s]+):([^:\s]+):(\S*)", section)
        if not (display_match and bus_match and monitor_match):
            continue
        connector_match = re.search(r"DRM connector:\s+(\S+)", section)
        monitors.append(
            DdcMonitor(
                display=int(display_match.group(1)),
                bus=int(bus_match.group(1)),
                connector=connector_match.group(1) if connector_match else "",
                manufacturer=monitor_match.group(1),
                model=monitor_match.group(2),
                serial=monitor_match.group(3),
            )
        )
    return monitors


def select_target_monitor(bus: int | None = None) -> DdcMonitor:
    candidates = [
        monitor
        for monitor in detect_monitors()
        if monitor.manufacturer == TARGET_MANUFACTURER and monitor.model == TARGET_MODEL
    ]
    if bus is not None:
        candidates = [monitor for monitor in candidates if monitor.bus == bus]
    if not candidates:
        qualifier = f" on /dev/i2c-{bus}" if bus is not None else ""
        raise DdcError(f"no {TARGET_MANUFACTURER}:{TARGET_MODEL} monitor found{qualifier}")
    if len(candidates) != 1:
        buses = ", ".join(str(monitor.bus) for monitor in candidates)
        raise DdcError(f"multiple XG27UCG monitors found on I2C buses {buses}; specify --bus")
    return candidates[0]


_RAW_VALUE_PATTERN = re.compile(
    r"Raw value:\s*opcode=0x([0-9a-fA-F]{2}),\s*"
    r"mh=0x([0-9a-fA-F]{2}),\s*ml=0x([0-9a-fA-F]{2}),\s*"
    r"sh=0x([0-9a-fA-F]{2}),\s*sl=0x([0-9a-fA-F]{2})"
)


def get_vcp(bus: int, code: int) -> VcpValue:
    output = _run(["--bus", str(bus), "getvcp", f"{code:02X}", "--verbose"])
    match = _RAW_VALUE_PATTERN.search(output)
    if not match:
        raise DdcError(f"could not parse VCP 0x{code:02x} response:\n{output.strip()}")
    values = [int(value, 16) for value in match.groups()]
    response = VcpValue(*values)
    if response.code != code:
        raise DdcError(
            f"monitor returned VCP 0x{response.code:02x} while 0x{code:02x} was requested"
        )
    return response


def get_firmware_number(bus: int) -> int:
    # ASUS stores the decimal MCM suffix in the maximum-value half of VCP 0xFF.
    return get_vcp(bus, 0xFF).maximum


def set_usb_update_mode(bus: int, enabled: bool) -> None:
    # Mirrors SetVCPFeature(handle, 0xDD, 1|0) in the official updater.
    value = 1 if enabled else 0
    _run(
        [
            "--bus",
            str(bus),
            "--permit-unknown-feature",
            "--noverify",
            "setvcp",
            "DD",
            str(value),
        ]
    )
