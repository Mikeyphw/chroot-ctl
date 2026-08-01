# Phase 08-10 Backup Rules Hotfix

Adds the legacy `res/xml/backup_rules.xml` resource referenced by `AndroidManifest.xml` via `android:fullBackupContent`.

The app still disables backup with `android:allowBackup="false"`; this file exists so AAPT can resolve the manifest reference on SDK 36 builds and so Android 11-and-lower backup metadata remains explicit.
