# KernelSU WebUI reference-transport hotfix

Compared chrootctl's adapter with the supplied `ssh-ksu 1.1.0` WebUI.

The reference module calls KernelSU as:

`ksu.spawn(command, JSON.stringify(args), JSON.stringify(options), callbackName)`

chrootctl was incorrectly shell-quoting the executable and every argv element
before passing them to `ksu.spawn`. That can prevent KernelSU from launching the
backend at all, which matches the observed absence of WebUI invocations in
`transport.log`.

This hotfix passes the command and argv to KernelSU verbatim at the JavaScript
bridge boundary. Shell quoting remains limited to the legacy `ksu.exec` fallback,
where a single shell command string is actually required.

The exec fallback also now emits an error instead of an exit-success-like
completion ordering for non-zero results.
