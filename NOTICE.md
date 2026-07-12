# Notices and provenance

`xg27ucg-linux-updater` is an independent community project. It is not
affiliated with, authorized by, endorsed by, or supported by ASUSTeK Computer
Inc. ASUS and ROG product names are used only to identify interoperable
hardware.

The repository does not contain ASUS firmware or ASUS source code. Users must
obtain the firmware package from ASUS and the updater accepts only the exact
verified MCM104 payload described in the documentation.

The Linux implementation was derived from observable device behavior and
static analysis of the publicly distributed Windows update package. It was
written collaboratively by Marc Sattelberger and OpenAI Codex and validated by
Marc on his own hardware.

The related `kiyo-xhci-fix` project by jphein documents a different Linux
`SG_IO` implementation for another device in the broader GCREADER/SigmaStar
family. It was discovered after this updater had been implemented; no source
code was copied from it. See its GPL-3.0 repository at
<https://github.com/jphein/kiyo-xhci-fix>.
