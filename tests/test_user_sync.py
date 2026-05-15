import logging
from pathlib import Path

from chrootctl.config import ChrootConfig
from chrootctl.system import SystemRunner
from chrootctl.user_sync import UserSyncManager

def test_show_id_reads_paths(tmp_path: Path) -> None:
    cfg = ChrootConfig(chroot_root=tmp_path, termux_home=tmp_path, distro_name="ubuntu")
    (cfg.chroot_base / "etc").mkdir(parents=True)
    (cfg.chroot_base / "etc/passwd").write_text("mike:x:1000:1000::/home/mike:/bin/bash\n", encoding="utf-8")
    mgr = UserSyncManager(cfg, SystemRunner(logging.getLogger("test"), dry_run=True), logging.getLogger("test"))
    data = mgr.show_id("mike")
    assert data["username"] == "mike"
