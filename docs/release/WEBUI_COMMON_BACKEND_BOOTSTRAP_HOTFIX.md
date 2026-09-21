# WebUI common backend bootstrap hotfix

Real-device evidence showed both the KernelSU-hosted and standalone-browser WebUI could remain on the static "Checking backend" state. The common frontend never reached backend probing because its ES modules did not parse: accumulated roadmap merges left duplicate imported/exported/function bindings. The page also contained duplicate DOM IDs across the Diagnostics and Readiness workspaces.

This hotfix makes the shared frontend parseable, makes those DOM IDs unique, restores all section discriminators, installs startup error reporting before backend bootstrap, and bounds standalone HTTP requests so a backend request cannot leave the UI checking indefinitely.
