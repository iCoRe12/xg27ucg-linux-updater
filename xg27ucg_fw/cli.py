# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .ddc import (
    DdcError,
    get_firmware_number,
    get_vcp,
    select_target_monitor,
    set_usb_update_mode,
)
from .firmware import (
    EXPECTED_MODEL,
    EXPECTED_VERSION,
    EXPECTED_VERSION_NUMBER,
    FirmwareReport,
    analyze_firmware,
    checksum_cdb,
    filesize_cdb,
    progress_cdb,
)
from .scsi import (
    TARGET_USB_PID,
    TARGET_USB_VID,
    ScsiDevice,
    ScsiError,
    device_is_mounted,
    discover_target_devices,
    usb_identity_for_device,
)
from .updater import FlashError, flash_firmware


EXPECTED_SOURCE_VERSION_NUMBER = 102
USB_ON_TOKEN = "XG27UCG-USB-ON"
USB_OFF_TOKEN = "XG27UCG-USB-OFF"


def _hex(data: bytes) -> str:
    return data.hex(" ")


def _firmware_dict(report: FirmwareReport) -> dict[str, Any]:
    data = report.to_dict()
    data["protocol"] = {
        "file_size_cdb": _hex(filesize_cdb(report.size)) if report.size <= 0xFFFFFF else None,
        "checksum_cdb": _hex(checksum_cdb(report.checksum16)),
        "progress_cdb": _hex(progress_cdb()),
        "normal_write_cdb": "e8 01 00 00 00 00 00 00 08 00",
        "final_write_cdb": f"e8 04 00 00 00 00 00 00 {report.final_transfer_bytes >> 8:02x} {report.final_transfer_bytes & 0xff:02x}",
    }
    return data


def _print_firmware(report: FirmwareReport) -> None:
    state = "VALID" if report.valid else "INVALID"
    print(f"Firmware: {state}")
    print(f"  file:       {report.path}")
    print(f"  model:      {report.model or '(missing)'}")
    print(f"  version:    {report.version or '(missing)'}")
    print(f"  size:       {report.size} bytes (0x{report.size:x})")
    print(f"  SHA-256:    {report.sha256}")
    print(f"  checksum16: 0x{report.checksum16:04x}")
    print(
        f"  transfer:   {report.normal_blocks} x 2048 bytes + "
        f"{report.final_payload_bytes} bytes padded to {report.final_transfer_bytes}"
    )
    print(f"  confirmation token: {report.confirmation_token}")
    print("  reconstructed CDBs:")
    if report.size <= 0xFFFFFF:
        print(f"    file size: {_hex(filesize_cdb(report.size))}")
    print(f"    checksum:  {_hex(checksum_cdb(report.checksum16))}")
    print(f"    progress:  {_hex(progress_cdb())}")
    for error in report.errors:
        print(f"  ERROR: {error}")


def command_firmware(args: argparse.Namespace) -> int:
    report = analyze_firmware(args.firmware)
    if args.json:
        print(json.dumps(_firmware_dict(report), indent=2, sort_keys=True))
    else:
        _print_firmware(report)
    return 0 if report.valid else 2


def _probe_usb_device(device: str) -> dict[str, Any]:
    result: dict[str, Any] = {"device": device, "ready": False}
    try:
        identity = usb_identity_for_device(device)
        result["usb"] = identity.to_dict()
        if not identity.matches_target:
            result["error"] = (
                f"USB identity is {identity.vid:04x}:{identity.pid:04x}, expected "
                f"{TARGET_USB_VID:04x}:{TARGET_USB_PID:04x}"
            )
            return result
        with ScsiDevice(device, writable=False) as transport:
            inquiry = transport.inquiry()
        result["inquiry"] = inquiry.to_dict()
        if not inquiry.is_gcreader:
            result["error"] = f"INQUIRY vendor is {inquiry.vendor!r}, expected 'GCREADER'"
            return result
        result["mounted"] = device_is_mounted(device)
        if result["mounted"]:
            result["error"] = "device or one of its partitions is mounted"
            return result
        result["ready"] = True
    except ScsiError as error:
        result["error"] = str(error)
    return result


def collect_probe(bus: int | None, firmware_path: str | None, device: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "tool_version": __version__,
        "monitor": None,
        "firmware": None,
        "usb_devices": [],
        "ready_to_flash": False,
        "blockers": [],
    }
    blockers: list[str] = result["blockers"]

    try:
        monitor = select_target_monitor(bus)
        monitor_data = monitor.to_dict()
        monitor_data["firmware_number"] = get_firmware_number(monitor.bus)
        monitor_data["firmware_version"] = f"MCM{monitor_data['firmware_number']}"
        monitor_data["usb_switch_vcp"] = get_vcp(monitor.bus, 0xDD).to_dict()
        result["monitor"] = monitor_data
        monitor_data["target_installed"] = (
            monitor_data["firmware_number"] == EXPECTED_VERSION_NUMBER
        )
        if monitor_data["target_installed"]:
            blockers.append(
                f"monitor already runs {EXPECTED_VERSION}; reflashing is intentionally blocked"
            )
        elif monitor_data["firmware_number"] != EXPECTED_SOURCE_VERSION_NUMBER:
            blockers.append(
                f"monitor source firmware is MCM{monitor_data['firmware_number']}; "
                f"this build is locked to MCM{EXPECTED_SOURCE_VERSION_NUMBER}"
            )
    except DdcError as error:
        blockers.append(f"monitor probe failed: {error}")

    if firmware_path:
        try:
            report = analyze_firmware(firmware_path)
            result["firmware"] = _firmware_dict(report)
            if not report.valid:
                blockers.append("firmware file failed strict validation")
        except OSError as error:
            blockers.append(f"cannot read firmware: {error}")
    else:
        blockers.append("no firmware path supplied")

    devices = [str(Path(device).resolve())] if device else discover_target_devices()
    if not devices:
        blockers.append(
            f"USB updater device {TARGET_USB_VID:04x}:{TARGET_USB_PID:04x} is not present"
        )
    if len(devices) > 1:
        blockers.append("multiple matching USB updater devices are present")
    usb_results = [_probe_usb_device(candidate) for candidate in devices]
    result["usb_devices"] = usb_results
    for usb_result in usb_results:
        if not usb_result.get("ready"):
            blockers.append(f"USB probe failed for {usb_result['device']}: {usb_result.get('error')}")

    result["ready_to_flash"] = not blockers
    return result


def _print_probe(result: dict[str, Any]) -> None:
    monitor = result["monitor"]
    print("Monitor:")
    if monitor:
        print(
            f"  {monitor['manufacturer']}:{monitor['model']}:{monitor['serial']} "
            f"on {monitor['bus_path']} ({monitor['connector']})"
        )
        print(f"  firmware: {monitor['firmware_version']}")
        switch = monitor["usb_switch_vcp"]
        print(
            f"  VCP 0xDD responds: max=0x{switch['maximum']:04x}, "
            f"current=0x{switch['current']:04x}"
        )
    else:
        print("  not found")

    firmware = result["firmware"]
    print("Firmware file:")
    if firmware:
        print(
            f"  {firmware['model']} {firmware['version']}, {firmware['size']} bytes, "
            f"SHA-256 {str(firmware['sha256'])[:16]}..., "
            f"{'VALID' if firmware['valid'] else 'INVALID'}"
        )
    else:
        print("  not supplied")

    print("USB updater:")
    if result["usb_devices"]:
        for usb in result["usb_devices"]:
            inquiry = usb.get("inquiry", {})
            print(
                f"  {usb['device']}: "
                f"{inquiry.get('vendor', usb.get('error', 'not readable'))} "
                f"{inquiry.get('product', '')} "
                f"({'READY' if usb.get('ready') else 'NOT READY'})"
            )
    else:
        print(f"  {TARGET_USB_VID:04x}:{TARGET_USB_PID:04x} not present")

    print(f"Flash readiness: {'READY' if result['ready_to_flash'] else 'NOT READY'}")
    for blocker in result["blockers"]:
        print(f"  - {blocker}")


def command_probe(args: argparse.Namespace) -> int:
    result = collect_probe(args.bus, args.firmware, args.device)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_probe(result)
    return 0 if result["ready_to_flash"] else 3


def command_verify(args: argparse.Namespace) -> int:
    try:
        monitor = select_target_monitor(args.bus)
        firmware_number = get_firmware_number(monitor.bus)
        result = {
            "monitor": monitor.to_dict(),
            "firmware_number": firmware_number,
            "firmware_version": f"MCM{firmware_number}",
            "expected_version": EXPECTED_VERSION,
            "target_installed": firmware_number == EXPECTED_VERSION_NUMBER,
        }
    except DdcError as error:
        if args.json:
            print(json.dumps({"target_installed": False, "error": str(error)}, indent=2))
        else:
            print(f"Verification failed: {error}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        state = "VERIFIED" if result["target_installed"] else "NOT VERIFIED"
        print(f"Installed firmware: {result['firmware_version']} ({state})")
        print(
            f"  monitor: {monitor.manufacturer}:{monitor.model}:{monitor.serial} "
            f"on /dev/i2c-{monitor.bus}"
        )
        print(f"  expected: {EXPECTED_VERSION}")
    return 0 if result["target_installed"] else 3


def _change_usb_mode(args: argparse.Namespace, enabled: bool) -> int:
    expected_token = USB_ON_TOKEN if enabled else USB_OFF_TOKEN
    if args.confirm != expected_token:
        print(
            f"Refusing DDC write. Re-run with --confirm {expected_token}",
            file=sys.stderr,
        )
        return 4
    try:
        monitor = select_target_monitor(args.bus)
        current = get_firmware_number(monitor.bus)
        if current != EXPECTED_SOURCE_VERSION_NUMBER and enabled:
            raise DdcError(
                f"monitor firmware is MCM{current}; USB-on is locked to MCM{EXPECTED_SOURCE_VERSION_NUMBER}"
            )
        set_usb_update_mode(monitor.bus, enabled)
    except DdcError as error:
        print(f"DDC operation failed: {error}", file=sys.stderr)
        return 5
    state = "enabled" if enabled else "disabled"
    print(f"USB update mode {state} on {EXPECTED_MODEL} via /dev/i2c-{monitor.bus}.")
    if enabled:
        print("Waiting briefly for USB enumeration...")
        time.sleep(2)
        devices = discover_target_devices()
        if devices:
            print("Matching USB device(s): " + ", ".join(devices))
        else:
            print(
                f"No {TARGET_USB_VID:04x}:{TARGET_USB_PID:04x} device yet. "
                "Check the USB data cable, then run probe."
            )
    return 0


def command_usb_on(args: argparse.Namespace) -> int:
    return _change_usb_mode(args, True)


def command_usb_off(args: argparse.Namespace) -> int:
    return _change_usb_mode(args, False)


def command_flash(args: argparse.Namespace) -> int:
    if os.geteuid() != 0:
        print("Refusing flash: run the flash command as root.", file=sys.stderr)
        return 6
    try:
        report = analyze_firmware(args.firmware)
    except OSError as error:
        print(f"Cannot read firmware: {error}", file=sys.stderr)
        return 2
    if not report.valid:
        _print_firmware(report)
        print("Refusing flash: firmware validation failed.", file=sys.stderr)
        return 2
    if not args.allow_device_write or args.confirm != report.confirmation_token:
        print(
            "Refusing flash. Both are required:\n"
            "  --allow-device-write\n"
            f"  --confirm {report.confirmation_token}",
            file=sys.stderr,
        )
        return 4

    probe = collect_probe(args.bus, args.firmware, args.device)
    if not probe["ready_to_flash"]:
        _print_probe(probe)
        print("Refusing flash: one or more readiness checks failed.", file=sys.stderr)
        return 3
    devices = probe["usb_devices"]
    device = devices[0]["device"]
    print("All destructive-operation gates passed:")
    print(f"  monitor:  {EXPECTED_MODEL} MCM{EXPECTED_SOURCE_VERSION_NUMBER}")
    print(f"  target:   {EXPECTED_VERSION}")
    print(f"  firmware: {report.sha256}")
    print(f"  USB/SCSI: {device}, {TARGET_USB_VID:04x}:{TARGET_USB_PID:04x}, GCREADER")
    print("Starting firmware transfer. Do not power off, unplug, suspend, or interrupt.")

    last_percent = -1

    def progress(percent: int, logical_done: int, programmed: int) -> None:
        nonlocal last_percent
        if percent != last_percent:
            print(
                f"\rTransfer {percent:3d}% ({logical_done}/{report.size}; "
                f"device reports {programmed})",
                end="",
                flush=True,
            )
            last_percent = percent

    try:
        flash_firmware(device, args.firmware, progress)
    except (FlashError, ScsiError) as error:
        print(f"\nFLASH FAILED: {error}", file=sys.stderr)
        print(
            "Keep the monitor powered and connected. Do not repeatedly power-cycle it.",
            file=sys.stderr,
        )
        return 10
    print("\nFirmware payload accepted. Wait for the monitor to restart by itself.")
    print("After restart, use the monitor OSD 'All Reset', then run verify.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xg27ucg-fw",
        description="Model-locked Linux firmware updater for ASUS XG27UCG MCM104.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    firmware = subparsers.add_parser("firmware", help="analyze a firmware file without device I/O")
    firmware.add_argument("--firmware", required=True)
    firmware.add_argument("--json", action="store_true")
    firmware.set_defaults(function=command_firmware)

    probe = subparsers.add_parser("probe", help="perform read-only monitor, USB, and firmware checks")
    probe.add_argument("--firmware")
    probe.add_argument("--bus", type=int)
    probe.add_argument("--device", help="explicit SCSI-generic node, for example /dev/sg2")
    probe.add_argument("--json", action="store_true")
    probe.set_defaults(function=command_probe)

    verify = subparsers.add_parser("verify", help="read the installed monitor firmware version")
    verify.add_argument("--bus", type=int)
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(function=command_verify)

    usb_on = subparsers.add_parser("usb-on", help="enable the monitor USB update interface over DDC")
    usb_on.add_argument("--bus", type=int)
    usb_on.add_argument("--confirm", required=True)
    usb_on.set_defaults(function=command_usb_on)

    usb_off = subparsers.add_parser("usb-off", help="disable the monitor USB update interface over DDC")
    usb_off.add_argument("--bus", type=int)
    usb_off.add_argument("--confirm", required=True)
    usb_off.set_defaults(function=command_usb_off)

    flash = subparsers.add_parser("flash", help="write MCM104 after all strict safety gates pass")
    flash.add_argument("--firmware", required=True)
    flash.add_argument("--bus", type=int)
    flash.add_argument("--device", help="explicit SCSI-generic node, for example /dev/sg2")
    flash.add_argument("--allow-device-write", action="store_true")
    flash.add_argument("--confirm", required=True)
    flash.set_defaults(function=command_flash)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.function(args))
    except KeyboardInterrupt:
        print("Interrupted before firmware writing began.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
