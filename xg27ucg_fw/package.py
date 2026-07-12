# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .catalog import sha256_file
from .firmware import FirmwareReport, analyze_firmware
from .profiles import (
    KNOWN_UPDATER_ENGINE_SHA256,
    FirmwareProfile,
    profile_for_outer_sha256,
)


MAX_SFX_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024


class PackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackageReport:
    package_path: str
    package_sha256: str
    sfx_member: str
    engine_sha256: dict[str, str]
    firmware: FirmwareReport
    reused_payload: bool

    @property
    def profile(self) -> FirmwareProfile | None:
        return self.firmware.profile

    def to_dict(self) -> dict[str, object]:
        return {
            "package_path": self.package_path,
            "package_sha256": self.package_sha256,
            "sfx_member": self.sfx_member,
            "engine_sha256": dict(self.engine_sha256),
            "firmware": self.firmware.to_dict(),
            "profile": self.profile.to_dict() if self.profile else None,
            "reused_payload": self.reused_payload,
        }


def _extract_7z_member(seven_zip: str, sfx_path: Path, member: str) -> bytes:
    process = subprocess.run(
        [seven_zip, "e", "-so", str(sfx_path), member],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise PackageError(f"7z could not extract {member!r}: {detail}")
    if not process.stdout or len(process.stdout) > MAX_MEMBER_BYTES:
        raise PackageError(f"extracted member {member!r} has an implausible size")
    return process.stdout


def _read_sfx(package: Path) -> tuple[str, bytes]:
    try:
        with zipfile.ZipFile(package) as archive:
            matches = [
                name
                for name in archive.namelist()
                if PurePosixPath(name).name == "ASUSFirmwareOneKeyUpdate.exe"
            ]
            if len(matches) != 1:
                raise PackageError(
                    f"outer ASUS ZIP contains {len(matches)} updater executables, expected one"
                )
            info = archive.getinfo(matches[0])
            if not 0 < info.file_size <= MAX_SFX_BYTES:
                raise PackageError("ASUS self-extracting updater has an implausible size")
            return matches[0], archive.read(info)
    except zipfile.BadZipFile as error:
        raise PackageError(f"not a valid ASUS ZIP package: {error}") from error


def prepare_package(package_path: str | Path, output_directory: str | Path) -> PackageReport:
    package = Path(package_path).expanduser().resolve()
    package_digest = sha256_file(package)
    profile = profile_for_outer_sha256(package_digest)
    if profile is None:
        raise PackageError(
            "package SHA-256 has no reviewed XG27UCG profile; it may be official, "
            "but its transport must be reviewed before firmware extraction"
        )
    seven_zip = shutil.which("7z")
    if not seven_zip:
        raise PackageError("7z is required to extract the ASUS self-extracting updater")

    sfx_member, sfx_data = _read_sfx(package)
    with tempfile.TemporaryDirectory(prefix="xg27ucg-fw-") as temporary_directory:
        sfx_path = Path(temporary_directory) / "ASUSFirmwareOneKeyUpdate.exe"
        sfx_path.write_bytes(sfx_data)

        engine_digests: dict[str, str] = {}
        for member, expected_digest in KNOWN_UPDATER_ENGINE_SHA256.items():
            data = _extract_7z_member(seven_zip, sfx_path, member)
            digest = hashlib.sha256(data).hexdigest()
            engine_digests[member] = digest
            if digest != expected_digest:
                raise PackageError(
                    f"ASUS updater engine member {member} changed: {digest}; review required"
                )

        payload = _extract_7z_member(seven_zip, sfx_path, profile.payload_filename)
        payload_digest = hashlib.sha256(payload).hexdigest()
        if payload_digest != profile.payload_sha256:
            raise PackageError(
                f"payload SHA-256 is {payload_digest}, expected {profile.payload_sha256}"
            )

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / profile.payload_filename
    reused = False
    if destination.exists():
        if sha256_file(destination) != profile.payload_sha256:
            raise PackageError(f"existing payload has the wrong SHA-256: {destination}")
        reused = True
    else:
        temporary_payload = destination.with_name(destination.name + ".part")
        temporary_payload.unlink(missing_ok=True)
        try:
            temporary_payload.write_bytes(payload)
            os.replace(temporary_payload, destination)
        finally:
            temporary_payload.unlink(missing_ok=True)

    firmware = analyze_firmware(destination)
    if not firmware.valid:
        raise PackageError("extracted payload failed profile validation: " + "; ".join(firmware.errors))
    return PackageReport(
        package_path=str(package),
        package_sha256=package_digest,
        sfx_member=sfx_member,
        engine_sha256=engine_digests,
        firmware=firmware,
        reused_payload=reused,
    )
