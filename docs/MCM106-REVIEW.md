# MCM106 package inspection — 2026-10-29

Issue [#3](https://github.com/iCoRe12/xg27ucg-linux-updater/issues/3) supplied
MCM106 package fingerprints and requested diagnostics for MCM101. The package
claims were independently reproduced from ASUS's live catalog and CDN.
This record covers static package inspection only; no vendor executable was
run and no monitor was accessed.

## Official source and results

- Catalog: `https://www.asus.com/support/webapi/ProductV2/GetPDBIOS?website=en-us&model=XG27UCG&pdhashedid=&cpu=&pdid=`
- [Official ZIP](https://dlcdnets.asus.com/pub/ASUS/LCD%20Monitors/XG27UCG/ASUS_XG27UCG_MCM106.zip)
- ASUS release date: `2026-08-18`
- Outer SHA-256: `5c6b6fc19fa1d7675b279ff0155e55198611687bf7f2bcab0e1614eb7e4592c7`
- Payload size: `2,027,558` bytes
- Payload SHA-256: `02f3c88fdc9d45f1d4174cd428b2a874b5ea23c75a1154c4501549612d4f311c`
- Additive checksum: `0x54b7`
- Model footer at `0x1ef000`: `XG27UCG`
- Exact final version footer at `0x1ef020`: `MCM106`

All three embedded updater files match the existing reviewed engine pins:

| Member | SHA-256 |
| --- | --- |
| `FirmwareOneKeyUpdate.exe` | `68708a7f44b43b19b8ffecff625b16f708accabfb8afe2a064fa3c460afaf2ba` |
| `FirmwareOneKeyUpdateLibrary.dll` | `add611d5d41e2ddd702215ccc7f506461901ab424b6a308e494ffdd3e02aee06` |
| `MAPI/CLIBMTKUSB.dll` | `d1499cc7fdf746ebf513d988c8159aa6184f1d49539eb49d53aada3048cee9b3` |

## Reproduce without monitor access

Run from the project root with Python and `7z` installed:

```bash
./xg27ucg-fw download --version MCM106 --prepare --output ./firmware-review
./xg27ucg-fw firmware --firmware ./firmware-review/ASUS_XG27UCG_MCM106.BIN --json
XG27UCG_TEST_PACKAGE_106="$PWD/firmware-review/ASUS_XG27UCG_MCM106.zip" \
XG27UCG_TEST_FIRMWARE_106="$PWD/firmware-review/ASUS_XG27UCG_MCM106.BIN" \
  python -m unittest discover -s tests -v
```

Package preparation requires the pinned outer hash, all three engine hashes,
and payload hash. Firmware analysis then checks the size, checksum, model,
version and exact footer. The official-file tests also verify that the lower
level flash function refuses MCM106 before opening a device.

## Approval boundary

MCM106 is an **inspection-only** profile: `flash_supported=False`, no allowed
source versions and no hardware-verified source versions. MCM104 remains the
latest flash-enabled target. Identical updater bytes do not demonstrate
MCM101's update-mode behavior or a physical MCM106 update.

The MCM101 handshake, permitted MCM106 source versions, physical transfer,
reboot and post-update display behavior remain open. Issue #3 must remain
open until its hardware and write-support requests have been assessed.
