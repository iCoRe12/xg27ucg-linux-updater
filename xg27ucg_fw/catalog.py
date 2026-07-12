# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

from . import __version__
from .profiles import EXPECTED_MODEL, FirmwareProfile, parse_version_number, profile_for_version


CATALOG_ENDPOINT = "https://www.asus.com/support/webapi/ProductV2/GetPDBIOS"
SUPPORT_PAGE = "https://www.asus.com/us/supportonly/xg27ucg/helpdesk_bios/"
CDN_ORIGIN = "https://dlcdnets.asus.com"
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class AsusRelease:
    model: str
    title: str
    version: str
    version_number: int
    release_date: str
    file_size_text: str
    sha256: str
    download_path: str
    description: str

    @property
    def filename(self) -> str:
        return PurePosixPath(unquote(self.download_path)).name

    @property
    def download_url(self) -> str:
        return CDN_ORIGIN + quote(unquote(self.download_path), safe="/._-")

    @property
    def profile(self) -> FirmwareProfile | None:
        profile = profile_for_version(self.version_number)
        if profile is None:
            return None
        if profile.outer_sha256 != self.sha256 or profile.outer_filename != self.filename:
            return None
        return profile

    @property
    def reviewed_for_flash(self) -> bool:
        return bool(self.profile and self.profile.flash_supported)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["filename"] = self.filename
        data["download_url"] = self.download_url
        data["support_page"] = SUPPORT_PAGE
        data["reviewed_for_flash"] = self.reviewed_for_flash
        data["profile"] = self.profile.to_dict() if self.profile else None
        return data


Opener = Callable[..., BinaryIO]


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"xg27ucg-linux-updater/{__version__}",
        },
    )


def _read_limited(response: BinaryIO, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise CatalogError(f"response exceeds the {limit}-byte safety limit")
    return data


def _validate_download_path(model: str, version: str, path: object) -> str:
    if not isinstance(path, str):
        raise CatalogError(f"ASUS catalog entry {version} has no global download path")
    decoded = unquote(path)
    pure = PurePosixPath(decoded)
    expected_prefix = f"/pub/ASUS/LCD Monitors/{model}/"
    expected_filename = f"ASUS_{model}_{version}.zip"
    if not decoded.startswith(expected_prefix):
        raise CatalogError(f"ASUS catalog path leaves the expected model directory: {decoded!r}")
    if any(part in ("", ".", "..") for part in pure.parts[1:]) or pure.name != expected_filename:
        raise CatalogError(f"unexpected ASUS catalog filename/path: {decoded!r}")
    return decoded


def parse_catalog_document(document: object, expected_model: str = EXPECTED_MODEL) -> list[AsusRelease]:
    if not isinstance(document, dict) or document.get("Status") != "SUCCESS":
        raise CatalogError("ASUS catalog did not return SUCCESS")
    result = document.get("Result")
    if not isinstance(result, dict) or result.get("Model") != expected_model:
        raise CatalogError("ASUS catalog model does not match the connected updater model")
    groups = result.get("Obj")
    if not isinstance(groups, list):
        raise CatalogError("ASUS catalog has no firmware groups")

    releases: list[AsusRelease] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        files = group.get("Files")
        if not isinstance(files, list):
            continue
        for item in files:
            if not isinstance(item, dict):
                continue
            version = item.get("Version")
            title = item.get("Title")
            digest = item.get("sha256")
            if not isinstance(version, str) or not isinstance(title, str):
                continue
            try:
                version_number = parse_version_number(version)
            except ValueError:
                continue
            expected_title = f"ASUS_{expected_model}_{version.upper()}"
            if title != expected_title:
                raise CatalogError(f"unexpected ASUS firmware title {title!r}")
            if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
                raise CatalogError(f"ASUS catalog entry {version} has no valid SHA-256")
            download_urls = item.get("DownloadUrl")
            if not isinstance(download_urls, dict):
                raise CatalogError(f"ASUS catalog entry {version} has no download URL object")
            path = _validate_download_path(
                expected_model,
                version.upper(),
                download_urls.get("Global"),
            )
            release_date = item.get("ReleaseDate")
            try:
                normalized_date = date.fromisoformat(str(release_date).replace("/", "-")).isoformat()
            except ValueError as error:
                raise CatalogError(f"invalid release date for {version}: {release_date!r}") from error
            releases.append(
                AsusRelease(
                    model=expected_model,
                    title=title,
                    version=version.upper(),
                    version_number=version_number,
                    release_date=normalized_date,
                    file_size_text=str(item.get("FileSize") or ""),
                    sha256=digest.lower(),
                    download_path=path,
                    description=str(item.get("Description") or ""),
                )
            )
    if not releases:
        raise CatalogError(f"ASUS catalog returned no firmware for {expected_model}")
    unique = {(release.version, release.sha256): release for release in releases}
    return sorted(
        unique.values(),
        key=lambda release: (release.release_date, release.version_number),
        reverse=True,
    )


def fetch_releases(
    model: str = EXPECTED_MODEL,
    website: str = "en-us",
    *,
    timeout: int = 20,
    opener: Opener = urlopen,
) -> list[AsusRelease]:
    query = urlencode(
        {
            "website": website,
            "model": model,
            "pdhashedid": "",
            "cpu": "",
            "pdid": "",
        }
    )
    try:
        with opener(_request(f"{CATALOG_ENDPOINT}?{query}"), timeout=timeout) as response:
            raw = _read_limited(response, MAX_CATALOG_BYTES)
    except (HTTPError, URLError, OSError) as error:
        raise CatalogError(f"cannot query ASUS firmware catalog: {error}") from error
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"ASUS catalog returned invalid JSON: {error}") from error
    return parse_catalog_document(document, expected_model=model)


def latest_release(releases: list[AsusRelease]) -> AsusRelease:
    if not releases:
        raise CatalogError("release list is empty")
    return max(releases, key=lambda release: (release.release_date, release.version_number))


def select_release(releases: list[AsusRelease], version: str) -> AsusRelease:
    if version.lower() == "latest":
        return latest_release(releases)
    number = parse_version_number(version)
    matches = [release for release in releases if release.version_number == number]
    if len(matches) != 1:
        raise CatalogError(f"ASUS catalog has no unique release for MCM{number:03d}")
    return matches[0]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_release(
    release: AsusRelease,
    output_directory: str | Path,
    *,
    timeout: int = 60,
    opener: Opener = urlopen,
) -> tuple[Path, bool]:
    directory = Path(output_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / release.filename
    if destination.exists():
        if sha256_file(destination) != release.sha256:
            raise CatalogError(f"existing download has the wrong SHA-256: {destination}")
        return destination, True

    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    total = 0
    request = Request(
        release.download_url,
        headers={"User-Agent": f"xg27ucg-linux-updater/{__version__}"},
    )
    try:
        with opener(request, timeout=timeout) as response, temporary.open("xb") as output:
            final_url = response.geturl() if hasattr(response, "geturl") else release.download_url
            parsed = urlsplit(final_url)
            if parsed.scheme != "https" or parsed.hostname != "dlcdnets.asus.com":
                raise CatalogError(f"ASUS download redirected to an untrusted host: {final_url}")
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_PACKAGE_BYTES:
                    raise CatalogError("ASUS package exceeds the 64 MiB safety limit")
                digest.update(block)
                output.write(block)
        if digest.hexdigest() != release.sha256:
            raise CatalogError(
                f"downloaded package SHA-256 is {digest.hexdigest()}, expected {release.sha256}"
            )
        os.replace(temporary, destination)
    except (HTTPError, URLError, OSError) as error:
        temporary.unlink(missing_ok=True)
        raise CatalogError(f"cannot download ASUS firmware package: {error}") from error
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination, False
