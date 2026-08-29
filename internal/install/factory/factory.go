package factory

import (
	"fmt"

	"chrootctl/internal/install"
	archinstall "chrootctl/internal/install/arch"
	ubuntuinstall "chrootctl/internal/install/ubuntu"
)

func Build(distro string, base *install.Base) (install.DistroInstaller, error) {
	switch distro {
	case "ubuntu":
		return ubuntuinstall.New(base), nil
	case "arch":
		return archinstall.New(base), nil
	default:
		return nil, fmt.Errorf("unsupported distro: %s", distro)
	}
}
