#!/usr/bin/env python3
"""Root-only opt-in chrootctl metadata client regression (no socket required)."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
cli=(ROOT/'cmd/chrootctl/main.go').read_text()
client=(ROOT/'internal/skybindr1/client.go').read_text()
checks={
    'REAL_CHROOTCTL_COMMAND':'if len(args) > 0 && args[0] == "skybind-read"' in cli,
    'ROOT_PROCESS_REQUIRED':'os.Geteuid() != 0' in cli,
    'APPROVAL_WINDOW':'context.WithTimeout(context.Background(), 120*time.Second)' in cli,
    'READONLY_CLIENT':'skybindr1.Read(ctx, *op, *remote, *path)' in cli,
    'ABSTRACT_HANDoFF':'\x00skybind-r1-grant-handoff-v1' in client or '\\x00skybind-r1-grant-handoff-v1' in client,
    'NO_NATIVE_FALLBACK':'exec.Command("rclone"' not in client,
}
for k,v in checks.items(): print(('PASS_' if v else 'FAIL_')+k)
raise SystemExit(0 if all(checks.values()) else 2)
