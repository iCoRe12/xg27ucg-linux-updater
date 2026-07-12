# xg27ucg-linux-updater

[![Tests](https://github.com/iCoRe12/xg27ucg-linux-updater/actions/workflows/tests.yml/badge.svg)](https://github.com/iCoRe12/xg27ucg-linux-updater/actions/workflows/tests.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)

A model-locked native Linux firmware updater for the ASUS ROG Strix
XG27UCG. It reimplements the update transport used by ASUS's official MCM104
Windows package without Wine, a Windows installation, or a virtual machine.

The updater was successfully used on one physical XG27UCG to update MCM102 to
MCM104 on 2026-07-12. The monitor rebooted normally, reported MCM104 through
DDC/CI, and retained 3840x2160 at 159.98 Hz.

> [!CAUTION]
> Firmware updates can permanently damage hardware if interrupted or used on
> the wrong device. This project is independent, unofficial, and provided
> without warranty. It has been validated on one monitor. ASUS's Windows tool
> remains the vendor-supported update path.

## Supported update

| Gate | Required value |
| --- | --- |
| Monitor EDID | `AUS:XG27UCG` |
| Installed firmware | `MCM102` |
| Target firmware | `MCM104` |
| Firmware payload SHA-256 | `b73131c26c48cb03e990170c50fb5363cad4e211af900ec146757164a30ebd9a` |
| Update-mode USB ID | `0b05:1b9c` |
| SCSI INQUIRY vendor | `GCREADER` |

Every value is checked again immediately before writing. Other ASUS models,
other source versions, modified firmware, multiple matching devices, mounted
media, and reflashing an already updated MCM104 monitor are refused.

## Requirements

- Linux on x86-64 with Python 3.11 or newer
- `ddcutil`, `7z`, and the standard Linux `sg` kernel module
- DisplayPort or HDMI plus the monitor's separate USB data cable
- The unmodified MCM104 package from the
  [official ASUS XG27UCG support page](https://www.asus.com/us/supportonly/xg27ucg/helpdesk_bios/)
- Root access for raw SCSI probing and the actual flash

On Arch Linux and derivatives:

```bash
sudo pacman -S --needed python ddcutil p7zip sg3_utils
sudo modprobe sg
```

The updater itself has no third-party Python dependencies. Clone it and run
the included launcher directly:

```bash
git clone https://github.com/iCoRe12/xg27ucg-linux-updater.git
cd xg27ucg-linux-updater
./xg27ucg-fw --version
```

An optional isolated install can be made with `pipx install .`.

## Obtain the firmware payload

This repository intentionally does **not** redistribute ASUS firmware. Download
the MCM104 ZIP from ASUS and verify the outer archive before extracting it:

```bash
sha256sum ASUS_XG27UCG_MCM104.zip
# Expected:
# 413114148964542de4580c642008fd43093398dc65008eba7564d938cb46b432

7z x ASUS_XG27UCG_MCM104.zip
7z x OneKeyUpdate/ASUSFirmwareOneKeyUpdate.exe -oasus-mcm104
```

The required payload is then
`asus-mcm104/ASUS_XG27UCG_MCM104.BIN`. Let the updater perform its independent
size, hash, checksum, model-footer, and version-footer validation:

```bash
./xg27ucg-fw firmware \
  --firmware asus-mcm104/ASUS_XG27UCG_MCM104.BIN
```

Do not continue unless it prints `Firmware: VALID`.

## Update procedure

First record the current monitor and firmware state. Replace `4` with the DDC
bus shown by `ddcutil detect`; omit `--bus` if exactly one XG27UCG is connected.

```bash
./xg27ucg-fw probe \
  --bus 4 \
  --firmware asus-mcm104/ASUS_XG27UCG_MCM104.BIN
```

At this point the USB updater normally is not present yet, so `NOT READY` is
expected. Enable it through the monitor's model-specific DDC switch:

```bash
./xg27ucg-fw usb-on \
  --bus 4 \
  --confirm XG27UCG-USB-ON
```

Load `sg` and probe again as root. The tool discovers the matching `/dev/sgX`
node itself; do not guess a disk or SCSI-generic path.

```bash
sudo modprobe sg
sudo ./xg27ucg-fw probe \
  --bus 4 \
  --firmware asus-mcm104/ASUS_XG27UCG_MCM104.BIN
```

Only continue when the final line is `Flash readiness: READY`. Prevent sleep
and shutdown while transferring the image:

```bash
sudo systemd-inhibit \
  --what=sleep:shutdown:idle \
  --why='ASUS XG27UCG firmware update' \
  ./xg27ucg-fw flash \
  --bus 4 \
  --firmware asus-mcm104/ASUS_XG27UCG_MCM104.BIN \
  --allow-device-write \
  --confirm XG27UCG-MCM104-b73131c2
```

Do not power off the monitor, reboot or suspend the PC, disconnect either
cable, or interrupt the process. Wait for the monitor to restart by itself.

After the restart, verify MCM104 from Linux:

```bash
./xg27ucg-fw verify --bus 4
```

Finally open the monitor OSD and select:

`System Setup` -> `All Reset` -> `Yes`

This is the reset ASUS requests after a firmware update; it resets monitor OSD
settings, so note any custom settings beforehand.

If update mode was enabled but no flash was started, it can be disabled again:

```bash
./xg27ucg-fw usb-off \
  --bus 4 \
  --confirm XG27UCG-USB-OFF
```

## How it works

The monitor exposes an update-only USB interface after a DDC/CI VCP `0xDD`
command. That interface accepts vendor SCSI commands through Linux `SG_IO`.
The updater validates the exact image, submits the true size and additive
checksum, transfers 2 KiB blocks, and checks the monitor's programmed-byte
counter after every block. See [PROTOCOL.md](PROTOCOL.md) for the reconstructed
command sequence and [FLASH-RESULT-2026-07-12.md](FLASH-RESULT-2026-07-12.md)
for the first live validation record.

## Related work

- [fwupd](https://github.com/fwupd/fwupd) is the standard Linux firmware-update
  ecosystem. No XG27UCG plugin or LVFS payload was found while researching this
  updater; long-term integration would be preferable to a model-specific tool.
- [kiyo-xhci-fix](https://github.com/jphein/kiyo-xhci-fix) independently
  documents Linux `SG_IO` commands for another `GCREADER`/SigmaStar-family
  device. Its device, boot path, packet size, and protocol differ. This project
  was implemented before that repository was discovered and contains no code
  copied from it.
- [OpenRGB](https://github.com/CalcProgrammer1/OpenRGB) supports the XG27UCG's
  normal Aura lighting interface, not monitor firmware flashing.

No exact open-source XG27UCG updater was found in GitHub and web searches made
on 2026-07-12. If one exists, please open an issue so it can be linked here.

## Development and provenance

The protocol was reconstructed from observable behavior and static analysis of
ASUS's official package. The implementation contains no ASUS firmware or ASUS
source code. It was developed collaboratively by Marc Sattelberger and OpenAI
Codex, with Marc authorizing and validating the live hardware update.

Contributions are welcome, but safety gates for unverified hardware will not be
removed based only on a model-name guess. See [CONTRIBUTING.md](CONTRIBUTING.md),
[SECURITY.md](SECURITY.md), and [NOTICE.md](NOTICE.md).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
