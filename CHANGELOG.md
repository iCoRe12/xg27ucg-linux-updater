# Changelog

All notable project changes are documented here.

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
