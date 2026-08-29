package install

import "fmt"

func SupportedDistro(name string) error {
	switch name {
	case "ubuntu", "arch":
		return nil
	default:
		return fmt.Errorf("unsupported distro: %s", name)
	}
}
