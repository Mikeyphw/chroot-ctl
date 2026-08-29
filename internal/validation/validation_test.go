package validation

import "testing"

func TestPythonValidationEdgeCases(t *testing.T) {
	if got, err := RelativeChrootPath("a/./b"); err != nil || got != "a/./b" {
		t.Fatalf("RelativeChrootPath normalized input = %q, %v", got, err)
	}
	if got, err := RelativeChrootPath("a//b"); err != nil || got != "a//b" {
		t.Fatalf("RelativeChrootPath repeated slash = %q, %v", got, err)
	}
	if got, err := RelativeChrootPath("."); err != nil || got != "." {
		t.Fatalf("RelativeChrootPath dot = %q, %v", got, err)
	}
	if _, err := RelativeChrootPath("a/../b"); err == nil || err.Error() != "path must not contain empty, current, or parent path segments" {
		t.Fatalf("parent traversal error = %v", err)
	}
	if _, err := ChrootName("../bad"); err == nil || err.Error() != "chroot name must be a safe basename" {
		t.Fatalf("unsafe basename error = %v", err)
	}
	if _, err := Username("Mike"); err == nil || err.Error() != "invalid username: 'Mike'" {
		t.Fatalf("username error = %v", err)
	}
}
