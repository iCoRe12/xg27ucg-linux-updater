# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


EXPECTED_MODEL = "XG27UCG"
EXPECTED_VERSION = "MCM104"
EXPECTED_VERSION_NUMBER = 104
EXPECTED_SIZE = 2_027_558
EXPECTED_SHA256 = "b73131c26c48cb03e990170c50fb5363cad4e211af900ec146757164a30ebd9a"
EXPECTED_CHECKSUM16 = 0x79F2

MODEL_OFFSET = 0x1EF000
VERSION_OFFSET = 0x1EF020
VERSION_DIGITS_OFFSET = 0x1EF023
BLOCK_SIZE = 0x800
SECTOR_SIZE = 0x200


@dataclass(frozen=True)
class FirmwareReport:
    path: str
    size: int
    sha256: str
    checksum16: int
    model: str
    version: str
    version_number: int | None
    normal_blocks: int
    final_payload_bytes: int
    final_transfer_bytes: int
    total_transfer_bytes: int
    valid: bool
    errors: tuple[str, ...]

    @property
    def confirmation_token(self) -> str:
        return f"{EXPECTED_MODEL}-{EXPECTED_VERSION}-{self.sha256[:8]}"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["checksum16_hex"] = f"0x{self.checksum16:04x}"
        data["confirmation_token"] = self.confirmation_token
        return data


@dataclass(frozen=True)
class TransferBlock:
    index: int
    offset: int
    payload: bytes
    transfer: bytes
    final: bool

    @property
    def cdb(self) -> bytes:
        command = bytearray(10)
        command[0] = 0xE8
        command[1] = 0x04 if self.final else 0x01
        command[6:10] = len(self.transfer).to_bytes(4, "big")
        return bytes(command)


def _ascii_field(data: bytes, start: int, length: int) -> str:
    field = data[start : start + length].split(b"\0", 1)[0]
    return field.decode("ascii", errors="replace")


def _round_up(value: int, multiple: int) -> int:
    return (value + multiple - 1) // multiple * multiple


def analyze_firmware(path: str | Path) -> FirmwareReport:
    firmware_path = Path(path).expanduser().resolve()
    data = firmware_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    checksum = sum(data) & 0xFFFF

    model = _ascii_field(data, MODEL_OFFSET, 0x20) if len(data) > MODEL_OFFSET else ""
    version = _ascii_field(data, VERSION_OFFSET, 6) if len(data) > VERSION_OFFSET else ""
    version_digits = (
        _ascii_field(data, VERSION_DIGITS_OFFSET, 3)
        if len(data) >= VERSION_DIGITS_OFFSET + 3
        else ""
    )
    version_number = int(version_digits) if version_digits.isdigit() else None

    full_blocks, remainder = divmod(len(data), BLOCK_SIZE)
    if remainder:
        normal_blocks = full_blocks
        final_payload = remainder
    elif data:
        normal_blocks = max(full_blocks - 1, 0)
        final_payload = BLOCK_SIZE
    else:
        normal_blocks = 0
        final_payload = 0
    final_transfer = _round_up(final_payload, SECTOR_SIZE) if final_payload else 0
    total_transfer = normal_blocks * BLOCK_SIZE + final_transfer

    errors: list[str] = []
    if len(data) != EXPECTED_SIZE:
        errors.append(f"unexpected size: {len(data)} (expected {EXPECTED_SIZE})")
    if digest != EXPECTED_SHA256:
        errors.append(f"unexpected SHA-256: {digest}")
    if checksum != EXPECTED_CHECKSUM16:
        errors.append(
            f"unexpected additive checksum: 0x{checksum:04x} "
            f"(expected 0x{EXPECTED_CHECKSUM16:04x})"
        )
    if model != EXPECTED_MODEL:
        errors.append(f"firmware model is {model!r}, expected {EXPECTED_MODEL!r}")
    if version != EXPECTED_VERSION:
        errors.append(f"firmware version is {version!r}, expected {EXPECTED_VERSION!r}")
    if data[VERSION_OFFSET:] != EXPECTED_VERSION.encode("ascii"):
        errors.append("firmware footer does not end exactly with MCM104")

    return FirmwareReport(
        path=str(firmware_path),
        size=len(data),
        sha256=digest,
        checksum16=checksum,
        model=model,
        version=version,
        version_number=version_number,
        normal_blocks=normal_blocks,
        final_payload_bytes=final_payload,
        final_transfer_bytes=final_transfer,
        total_transfer_bytes=total_transfer,
        valid=not errors,
        errors=tuple(errors),
    )


def filesize_cdb(size: int) -> bytes:
    if not 0 < size <= 0xFFFFFF:
        raise ValueError("firmware size must fit in the vendor protocol's 24-bit field")
    return bytes((0xE8, 0x08, (size >> 16) & 0xFF, (size >> 8) & 0xFF, size & 0xFF))


def checksum_cdb(checksum16: int) -> bytes:
    if not 0 <= checksum16 <= 0xFFFF:
        raise ValueError("checksum must fit in 16 bits")
    return bytes((0xE8, 0x0A, (checksum16 >> 8) & 0xFF, checksum16 & 0xFF))


def progress_cdb() -> bytes:
    return bytes((0xE8, 0x27, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x04))


def iter_transfer_blocks(data: bytes) -> Iterator[TransferBlock]:
    if not data:
        raise ValueError("firmware is empty")

    offset = 0
    index = 0
    while offset < len(data):
        remaining = len(data) - offset
        final = remaining <= BLOCK_SIZE
        payload_length = remaining if final else BLOCK_SIZE
        payload = data[offset : offset + payload_length]
        transfer_length = _round_up(payload_length, SECTOR_SIZE) if final else BLOCK_SIZE
        transfer = payload.ljust(transfer_length, b"\0")
        yield TransferBlock(
            index=index,
            offset=offset,
            payload=payload,
            transfer=transfer,
            final=final,
        )
        offset += BLOCK_SIZE
        index += 1
