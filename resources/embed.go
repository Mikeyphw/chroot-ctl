package resources

import "embed"

// FS contains the Go backend's built-in catalog scripts/manifests. CLI shell
// completion is generated directly from the compiled CLI contract so it cannot
// drift from parser/help metadata.
//
//go:embed tools/*.yaml tool-scripts/* addons/*.yaml addon-scripts/*
var FS embed.FS
