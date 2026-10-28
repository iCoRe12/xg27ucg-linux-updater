# Contributing

Contributions that improve diagnostics, documentation, tests, or the verified
XG27UCG update engine are welcome.

## Safety boundary

Do not weaken or bypass catalog, model, source-version, package/payload hash,
updater-engine identity, USB-identity, SCSI-INQUIRY, mount, exclusivity,
privilege, or confirmation gates. Support for another model or firmware pair
requires independently reproducible protocol evidence; a similar product name
or a newly appearing download is not enough.

Never submit ASUS firmware, updater binaries, personal monitor serial numbers,
logs containing credentials, or code copied from proprietary software.

## Adding a firmware profile

The ASUS catalog can discover a new release without a code change, but writing
remains blocked until `xg27ucg_fw/profiles.py` contains a reviewed profile.
A profile submission should include:

- the official API response fields and outer-package SHA-256;
- hashes of the embedded Windows updater, update library, and USB library;
- payload model, version, size, SHA-256, additive checksum, and exact footer;
- evidence for permitted source versions and whether each path was physically
  tested or inferred from an identical full-image vendor engine;
- updated fixtures, tests, protocol notes, and user-facing safety wording.

If the embedded updater-engine hashes change, treat the transport as unknown
until the new behavior has been independently analyzed. Do not simply copy the
new hashes into the profile.

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
XG27UCG_TEST_FIRMWARE_103=/path/to/ASUS_XG27UCG_MCM103.BIN \
XG27UCG_TEST_PACKAGE=/path/to/ASUS_XG27UCG_MCM104.zip \
XG27UCG_TEST_PACKAGE_103=/path/to/ASUS_XG27UCG_MCM103.zip \
XG27UCG_TEST_FIRMWARE_106=/path/to/ASUS_XG27UCG_MCM106.BIN \
XG27UCG_TEST_PACKAGE_106=/path/to/ASUS_XG27UCG_MCM106.zip \
  python -m unittest discover -s tests -v
```

Open an issue before attempting a new hardware-writing path. Include read-only
identity data and redact device serial numbers. Do not ask another user to run
an unreviewed destructive test.
