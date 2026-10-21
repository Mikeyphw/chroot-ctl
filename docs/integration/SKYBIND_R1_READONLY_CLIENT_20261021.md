# chrootctl native R1 Skybind metadata client

This module-root-only source addition is opt-in: `chrootctl skybind-read --operation rclone.lsjson --remote REMOTE --path RELATIVE`. Only R1 metadata operations are accepted. It does **not** alter chrootctl's sealed bundled rclone binary, config selection, chroot/archive path or backup semantics, and there is no automatic provider fallback/switch.

The client process requests no grant scope: it waits for an authorized root operator to approve the exact *running* chrootctl PID, installed module seal, SELinux context, remote/prefix/operation and TTL in the Skybind gateway. The grant token is returned through a kernel-peer-bound abstract local socket, is held only in process RAM, and is used once for read-only metadata over the consumer endpoint. No token is printed or saved. It exits nonzero on denial/timeouts; no native-rclone operation runs as fallback.

**Qualification:** Source-only adapter tests. The installed chrootctl 1.3.7 module remains unchanged until explicitly rebuilt and installed. After a new build the module manifest SHA256 and executable bytes will change; review and re-approve against installed source and independent signed artifacts. Validate true `/proc/PID/exe` identity and SELinux before operator issues an offer. Never use a generic root shell as a chrootctl identity.

Live Android SELinux admission, real abstract socket metadata, revocation and independent release gates remain pending. The Skybind producer must be activated manually with an approved policy, trusted app principal and production metadata backend; without it this command fails closed.
