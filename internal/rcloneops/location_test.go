package rcloneops

import "testing"

func TestLocationNormalizationAndJoining(t *testing.T) {
	got, err := NormalizeLocation("rclone://drive/folder/safe")
	if err != nil || got != "drive:folder/safe" {
		t.Fatalf("got=%q err=%v", got, err)
	}
	uri, err := JoinURI("rclone://drive/chroots", "Phone backup.tar.zst")
	if err != nil || uri != "rclone://drive/chroots/Phone%20backup.tar.zst" {
		t.Fatalf("uri=%q err=%v", uri, err)
	}
	for _, bad := range []string{
		"s3://bucket/x",
		"rclone://user:secret@drive/x",
		"rclone://drive/x?token=secret",
		"rclone://drive/x#frag",
		"rclone://bad name/x",
	} {
		if _, err := NormalizeLocation(bad); err == nil {
			t.Fatalf("unsafe location accepted: %s", bad)
		}
	}
}

func TestRcloneLocationRejectsTraversalSegments(t *testing.T) {
	for _, value := range []string{
		"rclone://drive/../escape",
		"rclone://drive/folder/%2e%2e/escape",
	} {
		if _, err := NormalizeLocation(value); err == nil {
			t.Fatalf("expected traversal rejection for %q", value)
		}
	}
	if _, err := JoinURI("rclone://drive/chroots/", "../escape"); err == nil {
		t.Fatal("expected JoinURI traversal rejection")
	}
}
