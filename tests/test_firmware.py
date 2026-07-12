# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from xg27ucg_fw.firmware import (
    EXPECTED_CHECKSUM16,
    EXPECTED_SHA256,
    EXPECTED_SIZE,
    analyze_firmware,
    checksum_cdb,
    filesize_cdb,
    iter_transfer_blocks,
    progress_cdb,
)
from xg27ucg_fw.profiles import MCM103, MCM104, latest_flash_profile, profile_for_version
from xg27ucg_fw.updater import FlashError, flash_firmware


OFFICIAL_FIRMWARE = Path(
    os.environ.get(
        "XG27UCG_TEST_FIRMWARE",
        Path(__file__).resolve().parents[1] / "ASUS_XG27UCG_MCM104.BIN",
    )
)
OFFICIAL_FIRMWARE_103 = Path(os.environ.get("XG27UCG_TEST_FIRMWARE_103", "missing-mcm103.bin"))


class ProtocolTests(unittest.TestCase):
    def test_reviewed_profile_matrix(self) -> None:
        self.assertEqual(MCM104.allowed_source_versions, (102, 103))
        self.assertEqual(MCM104.hardware_verified_source_versions, (102,))
        self.assertTrue(MCM104.flash_supported)
        self.assertFalse(MCM103.flash_supported)
        self.assertIs(latest_flash_profile(), MCM104)
        self.assertIs(profile_for_version("mcm104"), MCM104)
        self.assertIsNone(profile_for_version(105))

    def test_protocol_vectors(self) -> None:
        self.assertEqual(filesize_cdb(EXPECTED_SIZE), bytes.fromhex("e8 08 1e f0 26"))
        self.assertEqual(checksum_cdb(EXPECTED_CHECKSUM16), bytes.fromhex("e8 0a 79 f2"))
        self.assertEqual(
            progress_cdb(),
            bytes.fromhex("e8 27 00 00 00 00 00 00 00 04"),
        )

    def test_synthetic_transfer_blocks_match_vendor_algorithm(self) -> None:
        data = bytes((index % 251 for index in range(2048 + 38)))
        blocks = list(iter_transfer_blocks(data))
        self.assertEqual(len(blocks), 2)
        self.assertFalse(blocks[0].final)
        self.assertEqual(blocks[0].cdb, bytes.fromhex("e8 01 00 00 00 00 00 00 08 00"))
        self.assertEqual(len(blocks[0].transfer), 2048)
        self.assertTrue(blocks[-1].final)
        self.assertEqual(blocks[-1].offset, 2048)
        self.assertEqual(len(blocks[-1].payload), 38)
        self.assertEqual(len(blocks[-1].transfer), 512)
        self.assertEqual(blocks[-1].cdb, bytes.fromhex("e8 04 00 00 00 00 00 00 02 00"))
        self.assertEqual(blocks[-1].transfer[:38], data[-38:])
        self.assertEqual(blocks[-1].transfer[38:], bytes(512 - 38))

    def test_empty_firmware_has_no_transfer_blocks(self) -> None:
        with self.assertRaisesRegex(ValueError, "firmware is empty"):
            list(iter_transfer_blocks(b""))


class OfficialFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not OFFICIAL_FIRMWARE.exists():
            raise unittest.SkipTest("official test firmware is not present")
        cls.data = OFFICIAL_FIRMWARE.read_bytes()

    def test_official_firmware_identity(self) -> None:
        report = analyze_firmware(OFFICIAL_FIRMWARE)
        self.assertTrue(report.valid, report.errors)
        self.assertEqual(report.size, EXPECTED_SIZE)
        self.assertEqual(report.sha256, EXPECTED_SHA256)
        self.assertEqual(report.checksum16, EXPECTED_CHECKSUM16)
        self.assertEqual(report.model, "XG27UCG")
        self.assertEqual(report.version, "MCM104")
        self.assertEqual(report.version_number, 104)
        self.assertEqual(report.normal_blocks, 990)
        self.assertEqual(report.final_payload_bytes, 38)
        self.assertEqual(report.final_transfer_bytes, 512)
        self.assertEqual(report.total_transfer_bytes, 2_028_032)
        self.assertEqual(report.confirmation_token, "XG27UCG-MCM104-b73131c2")
        self.assertIs(report.profile, MCM104)

    def test_transfer_blocks_match_vendor_algorithm(self) -> None:
        blocks = list(iter_transfer_blocks(self.data))
        self.assertEqual(len(blocks), 991)
        self.assertFalse(blocks[0].final)
        self.assertEqual(blocks[0].cdb, bytes.fromhex("e8 01 00 00 00 00 00 00 08 00"))
        self.assertEqual(len(blocks[0].transfer), 2048)
        self.assertTrue(blocks[-1].final)
        self.assertEqual(blocks[-1].offset, 990 * 2048)
        self.assertEqual(len(blocks[-1].payload), 38)
        self.assertEqual(len(blocks[-1].transfer), 512)
        self.assertEqual(blocks[-1].cdb, bytes.fromhex("e8 04 00 00 00 00 00 00 02 00"))
        self.assertEqual(blocks[-1].transfer[:38], self.data[-38:])
        self.assertEqual(blocks[-1].transfer[38:], bytes(512 - 38))

    def test_one_byte_change_is_rejected(self) -> None:
        changed = bytearray(self.data)
        changed[0] ^= 1
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "changed.bin"
            path.write_bytes(changed)
            report = analyze_firmware(path)
        self.assertFalse(report.valid)
        self.assertTrue(any("SHA-256" in error for error in report.errors))
        self.assertTrue(any("checksum" in error for error in report.errors))


class OfficialMCM103FirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not OFFICIAL_FIRMWARE_103.exists():
            raise unittest.SkipTest("official MCM103 test firmware is not present")

    def test_official_mcm103_is_recognized_but_not_flash_enabled(self) -> None:
        report = analyze_firmware(OFFICIAL_FIRMWARE_103)
        self.assertTrue(report.valid, report.errors)
        self.assertEqual(report.version, "MCM103")
        self.assertEqual(report.sha256, MCM103.payload_sha256)
        self.assertEqual(report.checksum16, MCM103.payload_checksum16)
        self.assertIs(report.profile, MCM103)
        self.assertFalse(report.profile.flash_supported)
        with self.assertRaisesRegex(FlashError, "not enabled for writing"):
            flash_firmware("/dev/null", OFFICIAL_FIRMWARE_103)


if __name__ == "__main__":
    unittest.main()
