# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import stat
from dataclasses import dataclass
from pathlib import Path


TARGET_USB_VID = 0x0B05
TARGET_USB_PID = 0x1B9C
TARGET_PRODUCT = "GCREADER"

SG_IO = 0x2285
SG_DXFER_NONE = -1
SG_DXFER_TO_DEV = -2
SG_DXFER_FROM_DEV = -3
SG_INFO_OK_MASK = 0x1


class ScsiError(RuntimeError):
    pass


class _SgIoHdr(ctypes.Structure):
    _fields_ = [
        ("interface_id", ctypes.c_int),
        ("dxfer_direction", ctypes.c_int),
        ("cmd_len", ctypes.c_ubyte),
        ("mx_sb_len", ctypes.c_ubyte),
        ("iovec_count", ctypes.c_ushort),
        ("dxfer_len", ctypes.c_uint),
        ("dxferp", ctypes.c_void_p),
        ("cmdp", ctypes.c_void_p),
        ("sbp", ctypes.c_void_p),
        ("timeout", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("pack_id", ctypes.c_int),
        ("usr_ptr", ctypes.c_void_p),
        ("status", ctypes.c_ubyte),
        ("masked_status", ctypes.c_ubyte),
        ("msg_status", ctypes.c_ubyte),
        ("sb_len_wr", ctypes.c_ubyte),
        ("host_status", ctypes.c_ushort),
        ("driver_status", ctypes.c_ushort),
        ("resid", ctypes.c_int),
        ("duration", ctypes.c_uint),
        ("info", ctypes.c_uint),
    ]


@dataclass(frozen=True)
class UsbIdentity:
    vid: int
    pid: int
    manufacturer: str
    product: str
    serial: str
    sysfs_path: str

    @property
    def matches_target(self) -> bool:
        return self.vid == TARGET_USB_VID and self.pid == TARGET_USB_PID

    def to_dict(self) -> dict[str, object]:
        return {
            "vid": f"{self.vid:04x}",
            "pid": f"{self.pid:04x}",
            "manufacturer": self.manufacturer,
            "product": self.product,
            "serial": self.serial,
            "sysfs_path": self.sysfs_path,
            "matches_target": self.matches_target,
        }


@dataclass(frozen=True)
class InquiryData:
    peripheral_type: int
    removable: bool
    vendor: str
    product: str
    revision: str
    raw: bytes

    @property
    def is_gcreader(self) -> bool:
        # The official helper compares bytes 8..15 of the INQUIRY response,
        # i.e. the standard vendor-identification field, with "GCREADER".
        return self.vendor == TARGET_PRODUCT

    def to_dict(self) -> dict[str, object]:
        return {
            "peripheral_type": self.peripheral_type,
            "removable": self.removable,
            "vendor": self.vendor,
            "product": self.product,
            "revision": self.revision,
            "is_gcreader": self.is_gcreader,
            "raw_hex": self.raw.hex(),
        }


@dataclass(frozen=True)
class ScsiResponse:
    data: bytes
    duration_ms: int
    residual: int


def linux_cdb(cdb: bytes) -> bytes:
    """Adapt the Windows helper's short vendor CDBs to Linux SG_IO.

    ASUS sends 4- and 5-byte CDBs through Windows SCSI_PASS_THROUGH. Linux's
    sg driver rejects CDBs shorter than six bytes with EMSGSIZE. Zero-padding
    to the standard minimum preserves every vendor field and only adds the
    otherwise implicit control/reserved bytes.
    """
    if not 1 <= len(cdb) <= 16:
        raise ValueError("SG_IO command length must be between 1 and 16 bytes")
    return cdb.ljust(6, b"\0")


def _read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _sysfs_for_device(device: str | Path) -> Path:
    device_path = Path(device).resolve()
    try:
        device_stat = device_path.stat()
    except OSError as error:
        raise ScsiError(f"cannot stat {device_path}: {error}") from error
    if not (stat.S_ISBLK(device_stat.st_mode) or stat.S_ISCHR(device_stat.st_mode)):
        raise ScsiError(f"{device_path} is not a block or SCSI character device")
    sysfs_link = Path("/sys/dev/block" if stat.S_ISBLK(device_stat.st_mode) else "/sys/dev/char")
    sysfs_link /= f"{os.major(device_stat.st_rdev)}:{os.minor(device_stat.st_rdev)}"
    if not sysfs_link.exists():
        raise ScsiError(f"no sysfs entry for {device_path}")
    return sysfs_link.resolve()


def usb_identity_for_device(device: str | Path) -> UsbIdentity:
    sysfs = _sysfs_for_device(device)
    if (sysfs / "partition").exists():
        raise ScsiError(f"{device} is a partition; pass the whole device")
    for ancestor in (sysfs, *sysfs.parents):
        vendor_path = ancestor / "idVendor"
        product_path = ancestor / "idProduct"
        if not (vendor_path.exists() and product_path.exists()):
            continue
        try:
            vid = int(_read_optional(vendor_path), 16)
            pid = int(_read_optional(product_path), 16)
        except ValueError as error:
            raise ScsiError(f"invalid USB identity below {ancestor}") from error
        return UsbIdentity(
            vid=vid,
            pid=pid,
            manufacturer=_read_optional(ancestor / "manufacturer"),
            product=_read_optional(ancestor / "product"),
            serial=_read_optional(ancestor / "serial"),
            sysfs_path=str(ancestor),
        )
    raise ScsiError(f"{device} is not below a USB device in sysfs")


def discover_target_devices() -> list[str]:
    # GCREADER intentionally reports zero media capacity. Linux therefore
    # rejects opening its /dev/sdX node with ENOMEDIUM. Prefer the node from
    # the standard `sg` kernel module, which exposes raw SG_IO directly.
    generic_devices: list[str] = []
    for entry in sorted(Path("/sys/class/scsi_generic").glob("sg*")):
        device = Path("/dev") / entry.name
        if not device.exists():
            continue
        try:
            identity = usb_identity_for_device(device)
        except ScsiError:
            continue
        if identity.matches_target:
            generic_devices.append(str(device))
    if generic_devices:
        return generic_devices

    block_devices: list[str] = []
    for entry in sorted(Path("/sys/class/block").glob("*")):
        if (entry / "partition").exists():
            continue
        device = Path("/dev") / entry.name
        if not device.exists():
            continue
        try:
            identity = usb_identity_for_device(device)
        except ScsiError:
            continue
        if identity.matches_target:
            block_devices.append(str(device))
    return block_devices


def device_is_mounted(device: str | Path) -> bool:
    sysfs = _sysfs_for_device(device)
    devts = {_read_optional(sysfs / "dev")}

    # A /dev/sgX node is a character device, while mountinfo records the
    # related block device's major:minor number. Walk only as far as the USB
    # parent and include any sibling block node and its partitions.
    for ancestor in (sysfs, *sysfs.parents):
        block_directory = ancestor / "block"
        if block_directory.is_dir():
            for block in block_directory.iterdir():
                devts.add(_read_optional(block / "dev"))
                for child in block.iterdir():
                    if (child / "partition").exists():
                        devts.add(_read_optional(child / "dev"))
        if (ancestor / "idVendor").exists() and (ancestor / "idProduct").exists():
            break

    devts.discard("")
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError as error:
        raise ScsiError(f"cannot inspect mount table: {error}") from error
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) > 2 and fields[2] in devts:
            return True
    return False


class ScsiDevice:
    def __init__(self, path: str | Path, writable: bool = False, exclusive: bool = False):
        self.path = str(Path(path).resolve())
        flags = os.O_CLOEXEC | (os.O_RDWR if writable else os.O_RDONLY)
        if exclusive:
            flags |= os.O_EXCL
        try:
            self.fd = os.open(self.path, flags)
        except OSError as error:
            message = f"cannot open {self.path}: {error.strerror}"
            if error.errno in (errno.EACCES, errno.EPERM):
                message += " (root privileges are normally required)"
            elif error.errno == errno.ENOMEDIUM:
                message += " (load the sg module and use the matching /dev/sgX node)"
            raise ScsiError(message) from error
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(self.fd)
            raise ScsiError(f"cannot lock {self.path}: {error}") from error

    def close(self) -> None:
        if getattr(self, "fd", -1) >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "ScsiDevice":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def command(
        self,
        cdb: bytes,
        *,
        data_out: bytes | None = None,
        data_in_length: int = 0,
        timeout_seconds: int = 20,
    ) -> ScsiResponse:
        cdb = linux_cdb(cdb)
        if data_out is not None and data_in_length:
            raise ValueError("bidirectional transfers are not used by this protocol")

        command_buffer = ctypes.create_string_buffer(cdb, len(cdb))
        sense_buffer = ctypes.create_string_buffer(64)
        data_buffer: ctypes.Array[ctypes.c_char] | None
        if data_out is not None:
            data_buffer = ctypes.create_string_buffer(data_out, len(data_out))
            direction = SG_DXFER_TO_DEV
            transfer_length = len(data_out)
        elif data_in_length:
            data_buffer = ctypes.create_string_buffer(data_in_length)
            direction = SG_DXFER_FROM_DEV
            transfer_length = data_in_length
        else:
            data_buffer = None
            direction = SG_DXFER_NONE
            transfer_length = 0

        header = _SgIoHdr()
        header.interface_id = ord("S")
        header.dxfer_direction = direction
        header.cmd_len = len(cdb)
        header.mx_sb_len = len(sense_buffer)
        header.dxfer_len = transfer_length
        header.dxferp = ctypes.addressof(data_buffer) if data_buffer is not None else None
        header.cmdp = ctypes.addressof(command_buffer)
        header.sbp = ctypes.addressof(sense_buffer)
        header.timeout = timeout_seconds * 1000

        libc = ctypes.CDLL(None, use_errno=True)
        ioctl = libc.ioctl
        ioctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)
        ioctl.restype = ctypes.c_int
        result = ioctl(self.fd, SG_IO, ctypes.byref(header))
        if result < 0:
            error_number = ctypes.get_errno()
            raise ScsiError(
                f"SG_IO failed for CDB {cdb.hex(' ')}: "
                f"{os.strerror(error_number)} (errno {error_number})"
            )

        sense = bytes(sense_buffer.raw[: header.sb_len_wr])
        if (
            header.status != 0
            or header.host_status != 0
            or header.driver_status != 0
            or (header.info & SG_INFO_OK_MASK) != 0
        ):
            raise ScsiError(
                f"SCSI command {cdb.hex(' ')} failed: status=0x{header.status:02x}, "
                f"host=0x{header.host_status:04x}, driver=0x{header.driver_status:04x}, "
                f"residual={header.resid}, sense={sense.hex(' ')}"
            )

        actual_length = max(0, transfer_length - max(header.resid, 0))
        data = bytes(data_buffer.raw[:actual_length]) if data_buffer is not None else b""
        return ScsiResponse(data=data, duration_ms=header.duration, residual=header.resid)

    def inquiry(self) -> InquiryData:
        # Standard six-byte INQUIRY. The Windows helper sets CdbLength=5 but
        # leaves the sixth control byte at zero, which is equivalent on wire.
        response = self.command(bytes((0x12, 0x00, 0x00, 0x00, 0x24, 0x00)), data_in_length=36)
        if len(response.data) < 36:
            raise ScsiError(f"short INQUIRY response: {len(response.data)} bytes")
        data = response.data
        return InquiryData(
            peripheral_type=data[0] & 0x1F,
            removable=bool(data[1] & 0x80),
            vendor=data[8:16].decode("ascii", errors="replace").strip(" \0"),
            product=data[16:32].decode("ascii", errors="replace").strip(" \0"),
            revision=data[32:36].decode("ascii", errors="replace").strip(" \0"),
            raw=data,
        )
