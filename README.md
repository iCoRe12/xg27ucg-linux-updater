# xg27ucg-linux-updater

[![Tests](https://github.com/iCoRe12/xg27ucg-linux-updater/actions/workflows/tests.yml/badge.svg)](https://github.com/iCoRe12/xg27ucg-linux-updater/actions/workflows/tests.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)

A native Linux firmware catalog, package verifier, and update engine for the
ASUS ROG Strix XG27UCG. It detects the installed monitor firmware, queries
ASUS's official catalog for the newest release, downloads and verifies the
vendor package, safely extracts its payload, and writes reviewed targets
through Linux DDC/CI and `SG_IO`.

No Wine, Windows installation, or virtual machine is needed.

The first physical update, MCM102 to MCM104, completed successfully on
2026-07-12. The monitor rebooted normally, reported MCM104 through DDC/CI, and
retained 3840x2160 at 159.98 Hz.

> [!CAUTION]
> Firmware updates can permanently damage hardware if interrupted or used on
> the wrong device. This project is independent, unofficial, and provided
> without warranty. ASUS's Windows package remains the vendor-supported path.

## What is generic and what is reviewed

The transport engine is not intrinsically limited to one source/target pair.
ASUS ships byte-identical updater executables and transport libraries in the
official MCM103 and MCM104 packages; only the full firmware image changes.

Writing is nevertheless profile-locked. Online discovery must not turn a new,
unreviewed vendor package into an immediate hardware experiment.

| Target | Reviewed sources | Evidence | Write status |
| --- | --- | --- | --- |
| MCM103 | MCM102 | Official package and engine inspected; no Linux hardware flash | Obsolete target, blocked |
| MCM104 | MCM102 | Successfully flashed and post-reboot verified on hardware | Enabled |
| MCM104 | MCM103 | Same full-image package and byte-identical ASUS update engine | Enabled, vendor-inferred |

A future MCM105 will be visible and downloadable immediately through the ASUS
catalog command. Flashing remains blocked until its package, embedded updater
engine, firmware layout, and upgrade sources have a reviewed profile. Adding a
reviewed release is data-driven in `xg27ucg_fw/profiles.py`; the SCSI engine does
not need to be rewritten when ASUS keeps the protocol unchanged.

Show the locally reviewed matrix at any time:

```bash
./xg27ucg-fw profiles
```

## Current/latest version check

Connect the normal display cable. The following command performs no writes:

```bash
./xg27ucg-fw check
```

Example on an updated monitor:

```text
Installed: XG27UCG MCM104
ASUS latest: MCM104 (2025-05-12), outer SHA-256 41311414...
State: UP TO DATE
Linux profile: reviewed for flashing
```

The result can also be consumed as JSON:

```bash
./xg27ucg-fw check --json
```

## Download and prepare the newest official package

The tool queries ASUS's official firmware API, downloads only from ASUS's
HTTPS CDN, checks the catalog-provided outer SHA-256, verifies the known updater
engine inside the self-extracting EXE, extracts only the expected BIN, and then
applies the reviewed payload hash, checksum, model, version, size, and footer
checks:

```bash
./xg27ucg-fw download \
  --version latest \
  --prepare \
  --output ./firmware
```

This repository never redistributes ASUS firmware. The downloaded ZIP and BIN
remain local to the user and are excluded by `.gitignore` and the source-package
manifest.

The equivalent offline preparation command is:

```bash
./xg27ucg-fw prepare \
  --package /path/to/ASUS_XG27UCG_MCM104.zip \
  --output ./firmware
```

## Requirements

- Linux on x86-64 with Python 3.11 or newer
- `ddcutil`, `7z`, and the standard Linux `sg` kernel module
- DisplayPort or HDMI plus the monitor's separate USB data cable
- Network access for `check` and `download`, or a manually downloaded package
- Root access for raw SCSI probing and the actual flash

On Arch Linux and derivatives:

```bash
sudo pacman -S --needed python ddcutil 7zip sg3_utils
sudo modprobe sg
```

Clone the project and run the included launcher directly:

```bash
git clone https://github.com/iCoRe12/xg27ucg-linux-updater.git
cd xg27ucg-linux-updater
./xg27ucg-fw --version
```

An optional isolated install can be made with `pipx install .`.

## Firmware update procedure

First check the connected monitor and prepare the latest reviewed release:

```bash
./xg27ucg-fw check
./xg27ucg-fw download --version latest --prepare --output ./firmware
```

Probe the monitor, payload, USB VID/PID, and SCSI identity. Before USB update
mode is enabled, a missing updater endpoint is expected:

```bash
./xg27ucg-fw probe \
  --firmware ./firmware/ASUS_XG27UCG_MCM104.BIN
```

Enable the XG27UCG's update-only USB interface through DDC/CI. The command
checks that the installed source version is reviewed for the selected target:

```bash
./xg27ucg-fw usb-on \
  --target MCM104 \
  --confirm XG27UCG-USB-ON
```

Load `sg` and probe again as root. The tool discovers the matching `/dev/sgX`
node itself; never guess a disk or SCSI-generic path.

```bash
sudo modprobe sg
sudo ./xg27ucg-fw probe \
  --firmware ./firmware/ASUS_XG27UCG_MCM104.BIN
```

Continue only when the final line is `Flash readiness: READY`. Prevent sleep
and shutdown while transferring the image:

```bash
sudo systemd-inhibit \
  --what=sleep:shutdown:idle \
  --why='ASUS XG27UCG firmware update' \
  ./xg27ucg-fw flash \
  --firmware ./firmware/ASUS_XG27UCG_MCM104.BIN \
  --allow-device-write \
  --confirm XG27UCG-MCM104-b73131c2
```

Do not power off the monitor, reboot or suspend the PC, disconnect either
cable, or interrupt the process. Wait for the monitor to restart itself.

Verify the installed target from Linux:

```bash
./xg27ucg-fw verify --target MCM104
```

Finally open the monitor OSD and select:

`System Setup` -> `All Reset` -> `Yes`

If update mode was enabled but no flash was started, disable it again:

```bash
./xg27ucg-fw usb-off --confirm XG27UCG-USB-OFF
```

## Trust and safety chain

The automatic path requires all applicable checks to agree:

1. EDID/DDC identifies exactly `AUS:XG27UCG`.
2. ASUS's official API returns the exact model, release date, version, CDN path,
   and outer-package SHA-256.
3. The download stays on `https://dlcdnets.asus.com` and matches that hash.
4. The outer ZIP contains exactly one expected ASUS self-extracting updater.
5. Three inner updater-engine files match the reviewed MCM103/MCM104 engine.
6. The BIN matches a reviewed target profile: model, version, size, payload
   SHA-256, additive checksum, and exact footer.
7. The installed source version is allowed, the operation is an upgrade, and
   the target is not already installed.
8. USB `0b05:1b9c`, SCSI vendor `GCREADER`, mount state, exclusive access,
   root privileges, and two destructive-write confirmations all pass.
9. The device acknowledges the exact padded transfer boundary after every
   block.

The catalog and CDN are both operated by ASUS, so the online hash protects
against corruption and mismatched downloads but is not independent protection
against a compromise of ASUS's distribution infrastructure. Reviewed local
profiles provide an additional pinned identity for write-enabled releases.

## How the ASUS Windows package differs

ASUS does not currently ship one permanent XG27UCG updater that independently
downloads the newest release. Each support-page ZIP bundles the same generic
Windows updater with one target BIN. The EXE reads `Current Version` from the
monitor and `New Version` from that bundled BIN.

This project combines both layers under Linux: online newest-release discovery
from ASUS plus the model-locked update engine.

## Protocol documentation

The monitor exposes an update-only USB interface after a DDC/CI VCP `0xDD`
command. It accepts vendor SCSI commands through Linux `SG_IO`. The engine
submits the true payload size and additive checksum, transfers 2 KiB blocks,
and validates the programmed-byte counter after every block.

See [PROTOCOL.md](PROTOCOL.md) for the command sequence and
[FLASH-RESULT-2026-07-12.md](FLASH-RESULT-2026-07-12.md) for the first live
validation record.

## Related ecosystem and independent prior art

These projects are references, not dependencies. No source code from them is
included in this updater.

| Project | Why it is mentioned | Used to implement this updater? |
| --- | --- | --- |
| [fwupd](https://github.com/fwupd/fwupd) | The standard long-term Linux firmware ecosystem and a possible future integration target | No |
| [kiyo-xhci-fix](https://github.com/jphein/kiyo-xhci-fix) | Independently documents `SG_IO` for another `GCREADER`/SigmaStar-family device; external corroboration that this device family appears elsewhere | No; discovered after this updater worked |
| [OpenRGB](https://github.com/CalcProgrammer1/OpenRGB) | Supports the XG27UCG's normal Aura lighting interface, illustrating a separate USB function | No; it does not flash monitor firmware |

No exact open-source XG27UCG firmware updater was found in searches made on
2026-07-12. If one exists, please open an issue so it can be linked here.

## Development and provenance

The protocol was reconstructed from observable behavior and static analysis of
ASUS's publicly distributed update package. The implementation contains no
ASUS firmware or ASUS source code. It was developed collaboratively by Marc
Sattelberger and OpenAI Codex, with Marc authorizing and validating the live
hardware update.

Contributions are welcome, but a new online release does not automatically
become a write-enabled profile. See [CONTRIBUTING.md](CONTRIBUTING.md),
[SECURITY.md](SECURITY.md), and [NOTICE.md](NOTICE.md).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
