from chrootctl.config import ChrootConfig

def test_chroot_base_uses_name() -> None:
    cfg = ChrootConfig(distro_name="noble")
    assert str(cfg.chroot_base).endswith("/noble")
