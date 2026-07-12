# Changelog

All notable project changes are documented here.

## 0.3.0 - Unreleased

- Added live installed-versus-latest checks against ASUS's official firmware
  API.
- Added HTTPS download with catalog SHA-256 verification and strict CDN-host
  validation.
- Added safe extraction of the expected BIN from ASUS's self-extracting
  package without running vendor Windows code.
- Added pinned verification of the three byte-identical updater-engine files
  found in the official MCM103 and MCM104 packages.
- Split the reusable USB/SCSI transport from data-driven firmware profiles.
- Added a reviewed MCM103 package profile and enabled MCM103 as a source for
  the current MCM104 target; MCM102-to-MCM104 remains the hardware-verified
  Linux path.
- Added offline catalog, download, redirect, profile, and package tests.

## 0.2.0 - 2026-07-12

- Added a native Linux DDC/CI and `SG_IO` update path for the exact XG27UCG
  MCM102-to-MCM104 firmware transition.
- Added strict monitor, source-version, payload hash, checksum, USB VID/PID,
  SCSI vendor, mount-state, privilege, and confirmation gates.
- Adapted the Windows helper's four- and five-byte vendor CDBs to Linux's
  six-byte minimum with zero padding.
- Completed and post-reboot verified the first physical MCM104 update.
- Added installed-version verification, JSON diagnostics, protocol notes,
  public packaging, CI, and contributor/security documentation.
