from __future__ import annotations

import os
import platform
import sys


def main() -> None:
    print(f"python={sys.version.split()[0]}")
    print(f"platform={platform.platform()}")
    for key in ("CHROOTCTL_NAME", "CHROOTCTL_DISTRO", "CHROOTCTL_USERNAME"):
        print(f"{key}={os.environ.get(key, '')}")


if __name__ == "__main__":
    main()
