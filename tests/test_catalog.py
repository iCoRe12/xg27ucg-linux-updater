# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from xg27ucg_fw.catalog import (
    CatalogError,
    download_release,
    fetch_releases,
    latest_release,
    parse_catalog_document,
    select_release,
)


FIXTURE = Path(__file__).parent / "fixtures" / "asus_catalog_xg27ucg.json"


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self._url = url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def geturl(self) -> str:
        return self._url


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.releases = parse_catalog_document(self.document)

    def test_catalog_parsing_and_latest_selection(self) -> None:
        self.assertEqual([release.version for release in self.releases], ["MCM104", "MCM103"])
        newest = latest_release(self.releases)
        self.assertEqual(newest.version, "MCM104")
        self.assertTrue(newest.reviewed_for_flash)
        self.assertEqual(
            newest.download_url,
            "https://dlcdnets.asus.com/pub/ASUS/LCD%20Monitors/XG27UCG/"
            "ASUS_XG27UCG_MCM104.zip",
        )
        self.assertEqual(select_release(self.releases, "mcm103").version_number, 103)

    def test_fetch_uses_official_api_shape(self) -> None:
        raw = FIXTURE.read_bytes()
        seen_urls: list[str] = []

        def opener(request: object, *, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 4)
            url = request.full_url  # type: ignore[attr-defined]
            seen_urls.append(url)
            return FakeResponse(raw, url)

        releases = fetch_releases(timeout=4, opener=opener)
        self.assertEqual(releases[0].version, "MCM104")
        self.assertIn("model=XG27UCG", seen_urls[0])
        self.assertIn("website=en-us", seen_urls[0])

    def test_catalog_rejects_wrong_model_path_and_hash(self) -> None:
        wrong_model = copy.deepcopy(self.document)
        wrong_model["Result"]["Model"] = "OTHER"
        with self.assertRaisesRegex(CatalogError, "model"):
            parse_catalog_document(wrong_model)

        wrong_path = copy.deepcopy(self.document)
        wrong_path["Result"]["Obj"][0]["Files"][0]["DownloadUrl"]["Global"] = (
            "/pub/ASUS/LCD Monitors/OTHER/ASUS_XG27UCG_MCM104.zip"
        )
        with self.assertRaisesRegex(CatalogError, "model directory"):
            parse_catalog_document(wrong_path)

        wrong_hash = copy.deepcopy(self.document)
        wrong_hash["Result"]["Obj"][0]["Files"][0]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(CatalogError, "SHA-256"):
            parse_catalog_document(wrong_hash)

    def test_download_hash_verification_and_reuse(self) -> None:
        payload = b"official package fixture"
        release = replace(self.releases[0], sha256=hashlib.sha256(payload).hexdigest())

        def opener(_request: object, *, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 5)
            return FakeResponse(payload, release.download_url)

        with tempfile.TemporaryDirectory() as temporary_directory:
            path, reused = download_release(
                release,
                temporary_directory,
                timeout=5,
                opener=opener,
            )
            self.assertFalse(reused)
            self.assertEqual(path.read_bytes(), payload)
            second_path, reused = download_release(release, temporary_directory, opener=opener)
            self.assertTrue(reused)
            self.assertEqual(second_path, path)

    def test_download_rejects_untrusted_redirect(self) -> None:
        payload = b"package"
        release = replace(self.releases[0], sha256=hashlib.sha256(payload).hexdigest())

        def opener(_request: object, *, timeout: int) -> FakeResponse:
            return FakeResponse(payload, "https://example.invalid/package.zip")

        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(CatalogError, "untrusted host"):
                download_release(release, temporary_directory, opener=opener)
            self.assertFalse(any(Path(temporary_directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
