# Native runtime update and final seal

OV07 adds staged native runtime update validation:

- validate the source runtime before replacement
- copy through a temporary staging directory
- reject symlink sources and destinations
- refuse non-directory destinations

OV08 adds the final release seal command:

```bash
PYTHONPATH=src python3 scripts/final-native-runtime-release-check.py --repo-root .
```

The supported module runtime remains the sealed standalone runtime. The Nuitka onefile path remains an opt-in experiment only.
