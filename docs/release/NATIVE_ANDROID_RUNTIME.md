# Native Android runtime

This overlay adds only the native Android runtime build pipeline. It does **not** change module packaging, `/data/adb` state handling, Android bridge behavior, or the Android companion app.

The runtime is built from the normal `chrootctl` Python source with Nuitka standalone mode. The build is intentionally restricted to native Termux on Android: compiling inside a glibc Linux chroot would produce an artifact that cannot be treated as an Android/Bionic runtime.

Build prerequisites on Termux include Nuitka and the native toolchain packages:

```sh
pkg install clang patchelf ccache binutils ldd termux-elf-cleaner
python3 -m pip install Nuitka
```

Build the runtime from the repository root with:

```sh
PYTHONPATH=src python3 scripts/build-native-android-runtime.py --jobs 2
```

The default output is below `out/native-runtime`, which is already part of the repository's generated-output area:

```text
out/native-runtime/arm64-v8a/
├── runtime-manifest.json
└── chrootctl.dist/
    ├── chrootctl
    └── ... bundled Python/runtime shared objects ...
```

`runtime-manifest.json` is a release seal for the standalone directory. It records the runtime kind, Android ABI, chrootctl package version, bridge protocol version, Nuitka version, and the SHA-256/size/executable bit for every bundled file. Module packaging should validate this manifest before copying a native runtime.

The initial supported host ABI is `arm64-v8a`. Guest chroot architectures such as `amd64` are unrelated to the Android host ABI and remain handled by the existing chroot runtime code.
