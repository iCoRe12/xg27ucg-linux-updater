# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from dataclasses import asdict, dataclass


EXPECTED_MODEL = "XG27UCG"
_VERSION_PATTERN = re.compile(r"^MCM([0-9]{3})$")


@dataclass(frozen=True)
class FirmwareProfile:
    model: str
    version: str
    version_number: int
    payload_size: int
    payload_sha256: str
    payload_checksum16: int
    outer_filename: str
    outer_sha256: str
    release_date: str
    allowed_source_versions: tuple[int, ...]
    hardware_verified_source_versions: tuple[int, ...]
    flash_supported: bool
    evidence: str

    @property
    def payload_filename(self) -> str:
        return f"ASUS_{self.model}_{self.version}.BIN"

    @property
    def confirmation_token(self) -> str:
        return f"{self.model}-{self.version}-{self.payload_sha256[:8]}"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["payload_checksum16_hex"] = f"0x{self.payload_checksum16:04x}"
        data["confirmation_token"] = self.confirmation_token
        return data


# MCM103 and MCM104 ship byte-identical updater executables and transport
# libraries. MCM103 remains catalogued for package inspection and provenance,
# but the updater never selects an obsolete target when MCM104 is available.
MCM103 = FirmwareProfile(
    model=EXPECTED_MODEL,
    version="MCM103",
    version_number=103,
    payload_size=2_027_558,
    payload_sha256="65372be71080904ae57395c91aa8c7fd2a0d6d67a6e470a568201734ba77b0e1",
    payload_checksum16=0x3F6B,
    outer_filename="ASUS_XG27UCG_MCM103.zip",
    outer_sha256="fc9d4cb71db500d2a89beff9aece8d83ae5b0b40edf39a40b96a0e59351e3e2b",
    release_date="2025-01-06",
    allowed_source_versions=(102,),
    hardware_verified_source_versions=(),
    flash_supported=False,
    evidence="official package inspected; obsolete target; no live Linux flash",
)

MCM104 = FirmwareProfile(
    model=EXPECTED_MODEL,
    version="MCM104",
    version_number=104,
    payload_size=2_027_558,
    payload_sha256="b73131c26c48cb03e990170c50fb5363cad4e211af900ec146757164a30ebd9a",
    payload_checksum16=0x79F2,
    outer_filename="ASUS_XG27UCG_MCM104.zip",
    outer_sha256="413114148964542de4580c642008fd43093398dc65008eba7564d938cb46b432",
    release_date="2025-05-12",
    allowed_source_versions=(102, 103),
    hardware_verified_source_versions=(102,),
    flash_supported=True,
    evidence=(
        "MCM102 to MCM104 live-verified; MCM103 source support inferred from "
        "the identical ASUS updater engine and full-image package"
    ),
)

MCM106 = FirmwareProfile(
    model=EXPECTED_MODEL,
    version="MCM106",
    version_number=106,
    payload_size=2_027_558,
    payload_sha256="02f3c88fdc9d45f1d4174cd428b2a874b5ea23c75a1154c4501549612d4f311c",
    payload_checksum16=0x54B7,
    outer_filename="ASUS_XG27UCG_MCM106.zip",
    outer_sha256="5c6b6fc19fa1d7675b279ff0155e55198611687bf7f2bcab0e1614eb7e4592c7",
    release_date="2026-08-18",
    allowed_source_versions=(),
    hardware_verified_source_versions=(),
    flash_supported=False,
    evidence=(
        "official package independently inspected; identical MCM103/MCM104 engine; "
        "inspection only, no source versions approved and no live Linux flash"
    ),
)

PROFILES = (MCM103, MCM104, MCM106)
PROFILE_BY_VERSION_NUMBER = {profile.version_number: profile for profile in PROFILES}
PROFILE_BY_OUTER_SHA256 = {profile.outer_sha256: profile for profile in PROFILES}


# These three files are byte-identical inside the official MCM103 and MCM104
# self-extracting packages. A changed future engine requires review before its
# transport can be considered compatible.
KNOWN_UPDATER_ENGINE_SHA256 = {
    "FirmwareOneKeyUpdate.exe": (
        "68708a7f44b43b19b8ffecff625b16f708accabfb8afe2a064fa3c460afaf2ba"
    ),
    "FirmwareOneKeyUpdateLibrary.dll": (
        "add611d5d41e2ddd702215ccc7f506461901ab424b6a308e494ffdd3e02aee06"
    ),
    "MAPI/CLIBMTKUSB.dll": (
        "d1499cc7fdf746ebf513d988c8159aa6184f1d49539eb49d53aada3048cee9b3"
    ),
}


def parse_version_number(version: str) -> int:
    match = _VERSION_PATTERN.fullmatch(version.upper())
    if not match:
        raise ValueError(f"invalid firmware version {version!r}; expected MCM followed by 3 digits")
    return int(match.group(1))


def profile_for_version(version: str | int) -> FirmwareProfile | None:
    number = parse_version_number(version) if isinstance(version, str) else version
    return PROFILE_BY_VERSION_NUMBER.get(number)


def profile_for_outer_sha256(digest: str) -> FirmwareProfile | None:
    return PROFILE_BY_OUTER_SHA256.get(digest.lower())


def latest_flash_profile() -> FirmwareProfile:
    return max(
        (profile for profile in PROFILES if profile.flash_supported),
        key=lambda profile: profile.version_number,
    )
