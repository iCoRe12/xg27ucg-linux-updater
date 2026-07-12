# Contributing

Contributions that improve diagnostics, documentation, tests, or the verified
XG27UCG MCM102-to-MCM104 path are welcome.

## Safety boundary

Do not weaken or bypass model, source-version, firmware-hash, USB-identity,
SCSI-INQUIRY, mount, exclusivity, privilege, or confirmation gates. Support for
another model or firmware pair requires independently reproducible protocol
evidence and validation on real hardware; a similar product name is not enough.

Never submit ASUS firmware, updater binaries, personal monitor serial numbers,
logs containing credentials, or code copied from proprietary software.

## Development

Use Python 3.11 or newer. The test suite intentionally separates synthetic
protocol tests from tests that use the locally extracted official payload:

```bash
python -m compileall -q xg27ucg_fw tests
python -m unittest discover -s tests -v
```

The official-payload tests are skipped when that file is absent. This is the
expected state in public CI because the firmware is not redistributed.
Developers who obtained the payload from ASUS can run those tests explicitly:

```bash
XG27UCG_TEST_FIRMWARE=/path/to/ASUS_XG27UCG_MCM104.BIN \
  python -m unittest discover -s tests -v
```

Open an issue before attempting a new hardware-writing path. Include read-only
identity data and redact device serial numbers. Do not ask another user to run
an unreviewed destructive test.
