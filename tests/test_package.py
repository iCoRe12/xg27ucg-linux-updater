# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from xg27ucg_fw.package import prepare_package
from xg27ucg_fw.profiles import MCM103, MCM104


PACKAGE_104 = Path(os.environ.get("XG27UCG_TEST_PACKAGE", "missing-mcm104.zip"))
PACKAGE_103 = Path(os.environ.get("XG27UCG_TEST_PACKAGE_103", "missing-mcm103.zip"))


class OfficialPackageTests(unittest.TestCase):
    def _verify_package(self, path: Path, expected_profile: object) -> None:
        if not path.exists():
            self.skipTest(f"official package is not present: {path}")
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = prepare_package(path, temporary_directory)
            self.assertTrue(report.firmware.valid, report.firmware.errors)
            self.assertIs(report.firmware.profile, expected_profile)
            self.assertEqual(len(report.engine_sha256), 3)
            self.assertTrue(Path(report.firmware.path).is_file())

    def test_mcm104_package(self) -> None:
        self._verify_package(PACKAGE_104, MCM104)

    def test_mcm103_package_uses_the_same_reviewed_engine(self) -> None:
        self._verify_package(PACKAGE_103, MCM103)


if __name__ == "__main__":
    unittest.main()
