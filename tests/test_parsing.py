# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import ctypes
import unittest

from xg27ucg_fw.ddc import _RAW_VALUE_PATTERN
from xg27ucg_fw.scsi import _SgIoHdr, linux_cdb


class ParsingTests(unittest.TestCase):
    def test_ddc_raw_value_parser(self) -> None:
        text = (
            "Raw value: opcode=0xff, mh=0x00, ml=0x66, "
            "sh=0x00, sl=0x00, max_val=102 (0x0066), cur_val=0 (0x0000)"
        )
        match = _RAW_VALUE_PATTERN.search(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.groups(), ("ff", "00", "66", "00", "00"))

    def test_sg_io_header_layout_on_x86_64(self) -> None:
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            self.skipTest("layout assertion is for the target x86-64 host")
        self.assertEqual(ctypes.sizeof(_SgIoHdr), 88)
        self.assertEqual(_SgIoHdr.dxferp.offset, 16)
        self.assertEqual(_SgIoHdr.cmdp.offset, 24)
        self.assertEqual(_SgIoHdr.status.offset, 64)
        self.assertEqual(_SgIoHdr.info.offset, 80)

    def test_windows_short_cdbs_are_padded_for_linux(self) -> None:
        self.assertEqual(
            linux_cdb(bytes.fromhex("e8 08 1e f0 26")),
            bytes.fromhex("e8 08 1e f0 26 00"),
        )
        self.assertEqual(
            linux_cdb(bytes.fromhex("e8 0a 79 f2")),
            bytes.fromhex("e8 0a 79 f2 00 00"),
        )
        self.assertEqual(
            linux_cdb(bytes.fromhex("e8 27 00 00 00 00 00 00 00 04")),
            bytes.fromhex("e8 27 00 00 00 00 00 00 00 04"),
        )


if __name__ == "__main__":
    unittest.main()
