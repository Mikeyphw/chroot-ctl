# GO06 — controller and distro installers

GO06 ports the low-level chroot controller and the installation state machine into Go.
It preserves the Python phase order (`extract`, `bootstrap`, `desktop`, `finalize`),
resume context fail-closed behavior, filesystem promotion journal, rootfs integrity
verification, foreign-architecture QEMU/binfmt guard, mount/session command generation,
and Ubuntu/Arch package/bootstrap command shapes.

The concrete UID/GID synchronizer remains an interface in GO06. GO07 provides it.
Python remains production-authoritative until the later service/bridge cutover phases.
