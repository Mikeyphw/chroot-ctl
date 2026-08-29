package resources

import "embed"

// FS contains the Go backend's built-in catalog scripts/manifests and the
// generated shell completion asset. Keeping them embedded lets the final
// module runtime remain a single native executable.
//
//go:embed tools/*.yaml tool-scripts/* addons/*.yaml addon-scripts/* completion/*
var FS embed.FS
