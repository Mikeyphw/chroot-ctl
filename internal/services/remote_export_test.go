package services

import "testing"

func TestNormalizeRemoteExportDestinationPreservesEncryptionIdentity(t *testing.T) {
	plain, sidecar, err := normalizeRemoteExportDestination("rclone://drive/chroots/androidos.tar.zst", "")
	if err != nil {
		t.Fatal(err)
	}
	if plain != "rclone://drive/chroots/androidos.tar.zst" || sidecar != plain+".sha256" {
		t.Fatalf("plain=%q sidecar=%q", plain, sidecar)
	}

	encrypted, encryptedSidecar, err := normalizeRemoteExportDestination("rclone://drive/chroots/androidos.tar.zst", "secret")
	if err != nil {
		t.Fatal(err)
	}
	if encrypted != "rclone://drive/chroots/androidos.tar.zst.enc" || encryptedSidecar != encrypted+".sha256" {
		t.Fatalf("encrypted=%q sidecar=%q", encrypted, encryptedSidecar)
	}

	alreadyEncrypted, _, err := normalizeRemoteExportDestination("rclone://drive/chroots/androidos.tar.zst.enc", "secret")
	if err != nil || alreadyEncrypted != "rclone://drive/chroots/androidos.tar.zst.enc" {
		t.Fatalf("already encrypted=%q err=%v", alreadyEncrypted, err)
	}
}
