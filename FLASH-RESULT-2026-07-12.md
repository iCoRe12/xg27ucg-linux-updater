# XG27UCG MCM104 Linux flash result

## Outcome

Successful and post-boot verified on 2026-07-12 at approximately 23:01 CEST.

- Monitor: ASUS XG27UCG (serial intentionally omitted)
- Source: MCM102
- Target: MCM104
- Connection: DisplayPort plus USB data cable
- Linux update endpoint: USB `0b05:1b9c`, SCSI vendor `GCREADER`, `/dev/sg2`
- Firmware payload size: 2,027,558 bytes
- Firmware payload SHA-256:
  `b73131c26c48cb03e990170c50fb5363cad4e211af900ec146757164a30ebd9a`
- Additive checksum: `0x79f2`

The monitor acknowledged every 2,048-byte transfer block. The final device
counter was 2,028,032 bytes because the final 38 firmware bytes were padded to
one 512-byte sector, exactly as in the ASUS updater.

## Post-update verification

- Manufacturer VCP `0xFF`: maximum value 104 (`0x0068`), proving MCM104 booted
- GCREADER bootloader disconnected after the monitor's automatic restart
- No relevant USB/SCSI I/O errors in the kernel log
- KDE output remained `3840x2160@159.98`
- HDR remained disabled, VRR remained `Never`, and scale remained `1.7`

## Linux transport finding

ASUS's Windows DLL submits 4- and 5-byte vendor CDBs. Linux `sg` rejects CDBs
shorter than six bytes. The first attempt was therefore rejected in the kernel
with `EMSGSIZE` before any device command or data transfer; a read-only status
query confirmed zero programmed bytes. Padding those CDBs with zero
control/reserved bytes preserved their fields and enabled the successful
transfer.

## Remaining manual step

Use the monitor OSD to run `All Reset`, as required by ASUS after updating.
Then observe the original KDE/Claude flicker behavior during normal use.
