package rcloneops

import (
	"fmt"
	"net/url"
	"path"
	"path/filepath"
	"regexp"
	"strings"
)

const Scheme = "rclone"

var safeRemoteName = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)

type location struct {
	remote string
	path   string
}

func IsLocation(value string) bool {
	_, err := parseLocation(value)
	return err == nil
}

func parseLocation(value string) (location, error) {
	raw := strings.TrimSpace(value)
	u, err := url.Parse(raw)
	if err != nil || !strings.EqualFold(u.Scheme, Scheme) || u.Host == "" {
		return location{}, fmt.Errorf("invalid rclone location %q; expected rclone://remote/path", value)
	}
	if u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return location{}, fmt.Errorf("rclone location must not contain credentials, query parameters, or fragments")
	}
	remote, err := url.PathUnescape(u.Host)
	if err != nil || !safeRemoteName.MatchString(remote) {
		return location{}, fmt.Errorf("invalid rclone remote name; use letters, numbers, dot, underscore, or dash")
	}
	remotePath, err := url.PathUnescape(strings.TrimPrefix(u.EscapedPath(), "/"))
	if err != nil || strings.ContainsRune(remotePath, '\x00') || hasTraversalSegment(remotePath) {
		return location{}, fmt.Errorf("invalid rclone remote path")
	}
	clean := path.Clean("/" + remotePath)
	if clean == "/" {
		remotePath = ""
	} else {
		remotePath = strings.TrimPrefix(clean, "/")
	}
	return location{remote: remote, path: remotePath}, nil
}

func hasTraversalSegment(value string) bool {
	for _, segment := range strings.Split(strings.ReplaceAll(value, "\\", "/"), "/") {
		if segment == ".." {
			return true
		}
	}
	return false
}

func NormalizeLocation(value string) (string, error) {
	parsed, err := parseLocation(value)
	if err != nil {
		return "", err
	}
	if parsed.path == "" {
		return parsed.remote + ":", nil
	}
	return parsed.remote + ":" + parsed.path, nil
}

func CanonicalURI(value string) (string, error) {
	parsed, err := parseLocation(value)
	if err != nil {
		return "", err
	}
	u := &url.URL{Scheme: Scheme, Host: parsed.remote}
	if parsed.path == "" {
		u.Path = "/"
	} else {
		u.Path = "/" + parsed.path
	}
	return u.String(), nil
}

func JoinURI(base, relative string) (string, error) {
	parsed, err := parseLocation(base)
	if err != nil {
		return "", err
	}
	rel := strings.TrimSpace(relative)
	if rel == "" || strings.ContainsRune(rel, '\x00') || strings.HasPrefix(rel, "/") || hasTraversalSegment(rel) {
		return "", fmt.Errorf("invalid rclone child path")
	}
	clean := path.Clean("/" + rel)
	if clean == "/" {
		return "", fmt.Errorf("invalid rclone child path")
	}
	joined := path.Join("/", parsed.path, strings.TrimPrefix(clean, "/"))
	u := &url.URL{Scheme: Scheme, Host: parsed.remote, Path: joined}
	return u.String(), nil
}

func BaseName(value string) string {
	if parsed, err := parseLocation(value); err == nil {
		if parsed.path == "" {
			return parsed.remote
		}
		return path.Base(parsed.path)
	}
	return filepath.Base(strings.TrimRight(value, string(filepath.Separator)))
}

func commandLocation(value string) (string, error) {
	if IsLocation(value) {
		return NormalizeLocation(value)
	}
	if strings.Contains(value, "://") {
		return "", fmt.Errorf("unsupported remote location %q; use rclone://remote/path", value)
	}
	return filepath.Abs(value)
}

func joinDestination(destination, child string) (string, error) {
	if IsLocation(destination) {
		uri, err := JoinURI(destination, child)
		if err != nil {
			return "", err
		}
		return commandLocation(uri)
	}
	absolute, err := filepath.Abs(destination)
	if err != nil {
		return "", err
	}
	return filepath.Join(absolute, child), nil
}
