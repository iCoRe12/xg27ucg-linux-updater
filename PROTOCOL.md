# Reconstructed XG27UCG MCM104 protocol

This is an independent interoperability record. It contains no ASUS firmware
or ASUS source code. All multi-byte values below are shown exactly as submitted
by the verified updater implementation.

This document records the exact behavior recovered from ASUS's official
Windows updater. It is specific to `XG27UCG`, source firmware `MCM102`, and
target firmware `MCM104`.

## Identity gates

- Monitor EDID/DDC identity: `AUS:XG27UCG`
- Current firmware: manufacturer VCP `0xFF`, maximum-value bytes = decimal 102
- USB update-mode switch: `SetVCPFeature(0xDD, 1)`; disable with value `0`
- USB identity in ASUS's model/PID table: `0b05:1b9c`
- SCSI INQUIRY bytes 8 through 15: ASCII `GCREADER`
- Firmware size: `2,027,558` bytes (`0x1ef026`)
- Firmware SHA-256:
  `b73131c26c48cb03e990170c50fb5363cad4e211af900ec146757164a30ebd9a`
- Firmware footer at `0x1ef000`: `XG27UCG`
- Firmware footer at `0x1ef020`: `MCM104`

## Transport

The Windows helper sends `IOCTL_SCSI_PASS_THROUGH` (`0x4d004`) to the logical
drive exposed by the monitor. Linux uses the equivalent `SG_IO` ioctl. Because
GCREADER reports zero capacity, the Linux block node returns `ENOMEDIUM`; the
SCSI-generic node created by `modprobe sg` is the correct transport. The
Windows structure has a 20-second timeout, 32 bytes of sense space, and treats
the operation as successful only when both `DeviceIoControl` succeeds and
`ScsiStatus` is zero.

## Command sequence

1. Send the true firmware size as a 24-bit big-endian value:

   `e8 08 1e f0 26`

   Windows submits this as a 5-byte CDB. Linux `sg` requires at least six
   bytes, so the Linux transport appends one zero control byte.

2. Sum every firmware byte modulo 65536 and send it big-endian. For the
   official image the sum is `0x79f2`:

   `e8 0a 79 f2`

   Windows submits this as a 4-byte CDB. Linux appends two zero
   control/reserved bytes.

3. Transfer normal 2,048-byte chunks with this 10-byte CDB:

   `e8 01 00 00 00 00 00 00 08 00`

4. The final payload contains 38 real bytes and is padded with zeroes to one
   512-byte sector. Its CDB changes subcommand `01` to `04` and declares the
   padded transfer size:

   `e8 04 00 00 00 00 00 00 02 00`

5. After every block, request four progress bytes:

   `e8 27 00 00 00 00 00 00 00 04`

   Interpret the four returned bytes as an unsigned big-endian programmed-byte
   counter. This implementation requires it to equal the exact padded transfer
   boundary after every block before continuing.

The official updater retries block writes after 200 ms and progress reads
after 50 ms. This implementation caps either operation at seven attempts.

## Live validation

The first Linux submission of ASUS's original 5-byte size CDB was rejected by
the local `sg` driver with `EMSGSIZE` before reaching the monitor. A read-only
progress query returned zero programmed bytes. After applying the documented
six-byte zero-padding transport adaptation, the complete MCM104 payload was
accepted. Every returned progress counter matched the host offset; the final
counter was 2,028,032 bytes, consisting of 2,027,558 firmware bytes plus the
required zero-padding of the final 512-byte sector. The monitor rebooted and
VCP `0xFF` subsequently reported decimal 104.

## Safety deviations

The official tool broadcasts VCP `0xDD` to every physical monitor. This Linux
implementation targets only the one DDC bus whose EDID is exactly
`AUS:XG27UCG`. It also refuses modified firmware, a different source firmware,
a different USB VID/PID, a non-`GCREADER` SCSI device, mounted media, multiple
matching devices, or a flash command without two explicit destructive-write
gates.
