> **Superseded for current KernelSU Manager:** root module 1.3.7 / versionCode 22 uses a single shell-quoted command with empty native argv because the Android WebView bridge concatenates native `spawn` argv without shell escaping. This document is retained as historical context.

# WebUI KSU transport compatibility hotfix

Comparison with SAN v2.2.2 found a concrete ABI difference in the KernelSU `spawn` adapter. SAN passes argv as `JSON.stringify(args)`, while chrootctl pre-shell-quoted every argv element before JSON encoding. KernelSU/KsuWebUIStandalone owns argv conversion, so those quotes can become literal argument bytes and break structured backend requests.

The adapter now follows the proven host ABI exactly for `spawn`: command, verbatim JSON argv, JSON options, callback object name. `exec` remains a command-string API and retains shell quoting there.

Startup reporting is also staged. The UI now distinguishes bridge discovery, root-shell probing, and backend capability probing, and surfaces JavaScript/unhandled-promise startup failures instead of remaining indefinitely on the static `Checking backend` label.


## Legacy transport regression migration
The pre-existing Node transport test is migrated from the old shell-prequoted spawn ABI to verbatim JSON argv. Exec remains shell-quoted because exec accepts a command string.
