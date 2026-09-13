package factory

import (
	"context"
	"fmt"
	"strings"

	sys "chrootctl/internal/system"

	"chrootctl/internal/install"
	archinstall "chrootctl/internal/install/arch"
	ubuntuinstall "chrootctl/internal/install/ubuntu"
)

func Build(distro string, base *install.Base) (install.DistroInstaller, error) {
	if base == nil || base.Runner == nil {
		return nil, fmt.Errorf("installer runner is not configured")
	}
	fetchText := func(url string) (string, error) {
		res, err := base.Runner.Run(context.Background(), []string{"curl", "--fail", "--location", "--silent", "--show-error", url}, sys.RunOptions{MaxCaptureBytes: 8 * 1024 * 1024})
		if err != nil {
			return "", err
		}
		if res.ReturnCode != 0 {
			return "", fmt.Errorf("fetch %s failed: %s", url, strings.TrimSpace(res.Stderr))
		}
		return res.Stdout, nil
	}
	download := func(url, destination string) error {
		res, err := base.Runner.Run(context.Background(), []string{"curl", "--fail", "--location", "--retry", "3", "--output", destination, url}, sys.RunOptions{NoCapture: true})
		if err != nil {
			return err
		}
		if res.ReturnCode != 0 {
			return fmt.Errorf("download %s failed with exit %d", url, res.ReturnCode)
		}
		return nil
	}
	switch distro {
	case "ubuntu":
		i := ubuntuinstall.New(base)
		i.FetchText = fetchText
		i.Download = download
		return i, nil
	case "arch":
		i := archinstall.New(base)
		i.Download = download
		return i, nil
	default:
		return nil, fmt.Errorf("unsupported distro: %s", distro)
	}
}
