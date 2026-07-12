# Notices and provenance

`xg27ucg-linux-updater` is an independent community project. It is not
affiliated with, authorized by, endorsed by, or supported by ASUSTeK Computer
Inc. ASUS and ROG product names are used only to identify interoperable
hardware.

The repository does not contain ASUS firmware or ASUS source code. Its optional
network client queries ASUS's public support API and downloads packages from
ASUS's public CDN. Write operations accept only reviewed profiles pinned in the
repository.

The Linux implementation was derived from observable device behavior and
static analysis of the publicly distributed Windows update package. It was
written collaboratively by Marc Sattelberger and OpenAI Codex and validated by
Marc on his own hardware.

The related `kiyo-xhci-fix` project by jphein documents a different Linux
`SG_IO` implementation for another device in the broader GCREADER/SigmaStar
family. It was discovered after this updater had been implemented; no source
code was copied from it. See its GPL-3.0 repository at
<https://github.com/jphein/kiyo-xhci-fix>.

Neither `fwupd`, `kiyo-xhci-fix`, nor OpenRGB is a runtime, build, or source-code
dependency of this project. They are linked only as ecosystem context and
independent prior art.
