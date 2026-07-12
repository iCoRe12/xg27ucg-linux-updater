# Security policy

This tool writes monitor firmware through raw SCSI commands. Treat any bug that
could select the wrong device, accept the wrong image, bypass a safety gate, or
misreport transfer completion as a security and hardware-safety issue.

Please report such findings privately through GitHub's **Security** tab using a
private vulnerability report. Do not include proprietary firmware, credentials,
or unredacted hardware serial numbers. For non-sensitive defects, use a normal
GitHub issue.

Only the latest tagged release is supported. Until a report has been assessed,
do not run the affected write path on hardware.
