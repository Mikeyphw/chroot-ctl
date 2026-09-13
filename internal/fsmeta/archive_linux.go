//go:build linux || android

package fsmeta

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const xattrPAXPrefix = "CHROOTCTL.xattr."

type CopyControl struct {
	Check    func(context.Context) error
	Progress func(int64) error
}

func (c CopyControl) check(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if c.Check != nil {
		return c.Check(ctx)
	}
	return nil
}
func (c CopyControl) add(n int64) error {
	if c.Progress != nil && n > 0 {
		return c.Progress(n)
	}
	return nil
}

type inodeKey struct{ Dev, Ino uint64 }

func ArchiveTreeGzip(ctx context.Context, source, target string, control CopyControl) error {
	source = filepath.Clean(source)
	st, err := os.Lstat(source)
	if err != nil {
		return err
	}
	if !st.IsDir() {
		return fmt.Errorf("rootfs source is not a directory: %s", source)
	}
	f, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = f.Close()
		if !ok {
			_ = os.Remove(target)
		}
	}()
	gz := gzip.NewWriter(f)
	tw := tar.NewWriter(gz)
	links := map[inodeKey]string{}
	walkErr := filepath.Walk(source, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if err := control.check(ctx); err != nil {
			return err
		}
		rel, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		if rel == "." {
			rel = "."
		}
		rel = filepath.ToSlash(rel)
		var link string
		if info.Mode()&os.ModeSymlink != 0 {
			link, err = os.Readlink(path)
			if err != nil {
				return err
			}
		}
		if info.Mode()&os.ModeSocket != 0 {
			return fmt.Errorf("rootfs contains live socket; quiesce/remove it before snapshot: %s", path)
		}
		h, err := tar.FileInfoHeader(info, link)
		if err != nil {
			return err
		}
		h.Name = rel
		h.Format = tar.FormatPAX
		if stat, ok := info.Sys().(*syscall.Stat_t); ok {
			h.Uid, h.Gid = int(stat.Uid), int(stat.Gid)
			h.Mode = int64(stat.Mode & 0o7777)
			h.AccessTime = timespecTime(stat.Atim)
			h.ModTime = timespecTime(stat.Mtim)
			switch info.Mode() & os.ModeType {
			case os.ModeDevice:
				h.Typeflag = tar.TypeBlock
				h.Devmajor, h.Devminor = linuxMajorMinor(uint64(stat.Rdev))
			case os.ModeDevice | os.ModeCharDevice:
				h.Typeflag = tar.TypeChar
				h.Devmajor, h.Devminor = linuxMajorMinor(uint64(stat.Rdev))
			case os.ModeNamedPipe:
				h.Typeflag = tar.TypeFifo
			}
			if info.Mode().IsRegular() && stat.Nlink > 1 {
				key := inodeKey{Dev: uint64(stat.Dev), Ino: stat.Ino}
				if first, found := links[key]; found {
					h.Typeflag = tar.TypeLink
					h.Linkname = first
					h.Size = 0
				} else {
					links[key] = rel
				}
			}
		}
		attrs, err := readXattrs(path, info.Mode()&os.ModeSymlink != 0)
		if err != nil {
			return fmt.Errorf("read xattrs for %s: %w", path, err)
		}
		if len(attrs) != 0 {
			if h.PAXRecords == nil {
				h.PAXRecords = map[string]string{}
			}
			keys := make([]string, 0, len(attrs))
			for k := range attrs {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				ek := base64.RawURLEncoding.EncodeToString([]byte(k))
				h.PAXRecords[xattrPAXPrefix+ek] = base64.StdEncoding.EncodeToString(attrs[k])
			}
		}
		if err := tw.WriteHeader(h); err != nil {
			return err
		}
		if info.Mode().IsRegular() && h.Typeflag != tar.TypeLink {
			in, err := os.Open(path)
			if err != nil {
				return err
			}
			n, copyErr := copyChecked(ctx, control, tw, in)
			closeErr := in.Close()
			if copyErr != nil {
				return copyErr
			}
			if closeErr != nil {
				return closeErr
			}
			if n != info.Size() {
				return fmt.Errorf("short snapshot read for %s: %d != %d", path, n, info.Size())
			}
		}
		return nil
	})
	closeTar := tw.Close()
	closeGz := gz.Close()
	syncErr := f.Sync()
	closeFile := f.Close()
	if walkErr != nil {
		return walkErr
	}
	if closeTar != nil {
		return closeTar
	}
	if closeGz != nil {
		return closeGz
	}
	if syncErr != nil {
		return syncErr
	}
	if closeFile != nil {
		return closeFile
	}
	ok = true
	return nil
}

func ExtractTarGzip(ctx context.Context, archive, dest string, control CopyControl) error {
	f, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	return extractTar(ctx, tar.NewReader(gz), filepath.Clean(dest), "", control)
}

// ExtractTarRoot extracts one top-level archive root into dest, stripping that root.
func ExtractTarRoot(ctx context.Context, r io.Reader, dest, archiveRoot string, control CopyControl) error {
	if archiveRoot == "" || filepath.Base(archiveRoot) != archiveRoot {
		return fmt.Errorf("invalid archive root name: %q", archiveRoot)
	}
	return extractTar(ctx, tar.NewReader(r), filepath.Clean(dest), archiveRoot, control)
}

type deferredMeta struct {
	path string
	h    tar.Header
}

func extractTar(ctx context.Context, tr *tar.Reader, dest, stripRoot string, control CopyControl) error {
	if err := os.MkdirAll(dest, 0o700); err != nil {
		return err
	}
	var dirs []deferredMeta
	extractedRegular := map[string]bool{}
	prefix := ""
	if stripRoot != "" {
		prefix = stripRoot + "/"
	}
	for {
		if err := control.check(ctx); err != nil {
			return err
		}
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		raw := filepath.ToSlash(filepath.Clean(h.Name))
		if raw == "." && stripRoot == "" {
			dirs = append(dirs, deferredMeta{dest, *h})
			continue
		}
		if stripRoot != "" {
			if raw == stripRoot {
				dirs = append(dirs, deferredMeta{dest, *h})
				continue
			}
			if !strings.HasPrefix(raw, prefix) {
				return fmt.Errorf("unexpected archive member outside root %s: %s", stripRoot, h.Name)
			}
			raw = strings.TrimPrefix(raw, prefix)
		}
		if raw == "" || raw == "." || filepath.IsAbs(raw) || raw == ".." || strings.HasPrefix(raw, "../") {
			return fmt.Errorf("unsafe archive member: %s", h.Name)
		}
		target, err := safeTarget(dest, filepath.FromSlash(raw))
		if err != nil {
			return err
		}
		if err := ensureRealParents(dest, target); err != nil {
			return err
		}
		switch h.Typeflag {
		case tar.TypeDir:
			if err := ensureDirectory(target); err != nil {
				return err
			}
			dirs = append(dirs, deferredMeta{target, *h})
		case tar.TypeReg, tar.TypeRegA:
			if err := ensureAbsentOrRegular(target); err != nil {
				return err
			}
			out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
			if err != nil {
				return err
			}
			copyErr := sparseCopy(ctx, control, out, tr, h.Size)
			syncErr := out.Sync()
			closeErr := out.Close()
			if copyErr != nil {
				return copyErr
			}
			if syncErr != nil {
				return syncErr
			}
			if closeErr != nil {
				return closeErr
			}
			if err := applyMeta(target, *h, false); err != nil {
				return err
			}
			extractedRegular[raw] = true
		case tar.TypeSymlink:
			if _, err := os.Lstat(target); err == nil {
				return fmt.Errorf("duplicate archive member: %s", raw)
			} else if !os.IsNotExist(err) {
				return err
			}
			if err := os.Symlink(h.Linkname, target); err != nil {
				return err
			}
			if err := applyMeta(target, *h, true); err != nil {
				return err
			}
		case tar.TypeLink:
			linkRaw := filepath.ToSlash(filepath.Clean(h.Linkname))
			if stripRoot != "" {
				if !strings.HasPrefix(linkRaw, prefix) {
					return fmt.Errorf("unsafe hardlink target: %s", h.Linkname)
				}
				linkRaw = strings.TrimPrefix(linkRaw, prefix)
			}
			if !extractedRegular[linkRaw] {
				return fmt.Errorf("hardlink target is not a previously extracted regular file: %s", h.Linkname)
			}
			linkTarget, err := safeTarget(dest, filepath.FromSlash(linkRaw))
			if err != nil {
				return err
			}
			if err := os.Link(linkTarget, target); err != nil {
				return err
			}
			if err := applyMeta(target, *h, false); err != nil {
				return err
			}
			extractedRegular[raw] = true
		case tar.TypeFifo:
			if _, err := os.Lstat(target); !os.IsNotExist(err) {
				if err == nil {
					return fmt.Errorf("duplicate archive member: %s", raw)
				}
				return err
			}
			if err := syscall.Mkfifo(target, uint32(h.Mode&0o7777)); err != nil {
				return err
			}
			if err := applyMeta(target, *h, false); err != nil {
				return err
			}
		case tar.TypeChar, tar.TypeBlock:
			if _, err := os.Lstat(target); !os.IsNotExist(err) {
				if err == nil {
					return fmt.Errorf("duplicate archive member: %s", raw)
				}
				return err
			}
			mode := uint32(h.Mode & 0o7777)
			if h.Typeflag == tar.TypeChar {
				mode |= syscall.S_IFCHR
			} else {
				mode |= syscall.S_IFBLK
			}
			if err := syscall.Mknod(target, mode, linuxMkdev(uint64(h.Devmajor), uint64(h.Devminor))); err != nil {
				return err
			}
			if err := applyMeta(target, *h, false); err != nil {
				return err
			}
		case tar.TypeXGlobalHeader, tar.TypeXHeader:
			continue
		default:
			return fmt.Errorf("unsupported rootfs archive entry type %d for %s", h.Typeflag, h.Name)
		}
	}
	for i := len(dirs) - 1; i >= 0; i-- {
		if err := applyMeta(dirs[i].path, dirs[i].h, false); err != nil {
			return err
		}
	}
	return syncTreeRoot(dest)
}

func copyChecked(ctx context.Context, control CopyControl, dst io.Writer, src io.Reader) (int64, error) {
	buf := make([]byte, 128*1024)
	var total int64
	for {
		if err := control.check(ctx); err != nil {
			return total, err
		}
		n, er := src.Read(buf)
		if n > 0 {
			w, ew := dst.Write(buf[:n])
			total += int64(w)
			if ew != nil {
				return total, ew
			}
			if w != n {
				return total, io.ErrShortWrite
			}
			if e := control.add(int64(w)); e != nil {
				return total, e
			}
		}
		if er == io.EOF {
			return total, nil
		}
		if er != nil {
			return total, er
		}
	}
}

func sparseCopy(ctx context.Context, control CopyControl, out *os.File, src io.Reader, size int64) error {
	buf := make([]byte, 128*1024)
	var written int64
	for written < size {
		if err := control.check(ctx); err != nil {
			return err
		}
		want := len(buf)
		if left := size - written; int64(want) > left {
			want = int(left)
		}
		n, er := io.ReadFull(src, buf[:want])
		if er != nil && er != io.ErrUnexpectedEOF {
			return er
		}
		if n == 0 {
			break
		}
		chunk := buf[:n]
		if allZero(chunk) {
			if _, err := out.Seek(int64(n), io.SeekCurrent); err != nil {
				return err
			}
		} else {
			if _, err := out.Write(chunk); err != nil {
				return err
			}
		}
		written += int64(n)
		if err := control.add(int64(n)); err != nil {
			return err
		}
		if er == io.ErrUnexpectedEOF {
			break
		}
	}
	if written != size {
		return fmt.Errorf("short archive member: %d != %d", written, size)
	}
	return out.Truncate(size)
}
func allZero(b []byte) bool {
	for _, v := range b {
		if v != 0 {
			return false
		}
	}
	return true
}

func applyMeta(path string, h tar.Header, symlink bool) error {
	if symlink {
		if err := os.Lchown(path, h.Uid, h.Gid); err != nil {
			return err
		}
	} else {
		if err := os.Chown(path, h.Uid, h.Gid); err != nil {
			return err
		}
		if err := os.Chmod(path, fileMode(h.Mode)); err != nil {
			return err
		}
	}
	if err := restoreXattrs(path, h, symlink); err != nil {
		return err
	}
	if err := setTimes(path, h.AccessTime, h.ModTime, symlink); err != nil {
		return err
	}
	return nil
}
func fileMode(m int64) os.FileMode {
	v := os.FileMode(m & 0o777)
	if m&0o4000 != 0 {
		v |= os.ModeSetuid
	}
	if m&0o2000 != 0 {
		v |= os.ModeSetgid
	}
	if m&0o1000 != 0 {
		v |= os.ModeSticky
	}
	return v
}

func readXattrs(path string, symlink bool) (map[string][]byte, error) {
	var n int
	var err error
	if symlink {
		n, err = llistxattr(path, nil)
	} else {
		n, err = syscall.Listxattr(path, nil)
	}
	if err != nil {
		if errors.Is(err, syscall.ENOTSUP) || errors.Is(err, syscall.EOPNOTSUPP) {
			return nil, nil
		}
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	buf := make([]byte, n)
	if symlink {
		n, err = llistxattr(path, buf)
	} else {
		n, err = syscall.Listxattr(path, buf)
	}
	if err != nil {
		return nil, err
	}
	out := map[string][]byte{}
	for _, part := range strings.Split(string(buf[:n]), "\x00") {
		if part == "" {
			continue
		}
		var sz int
		var e error
		if symlink {
			sz, e = lgetxattr(path, part, nil)
		} else {
			sz, e = syscall.Getxattr(path, part, nil)
		}
		if e != nil {
			return nil, e
		}
		val := make([]byte, sz)
		if sz > 0 {
			var got int
			if symlink {
				got, e = lgetxattr(path, part, val)
			} else {
				got, e = syscall.Getxattr(path, part, val)
			}
			if e != nil {
				return nil, e
			}
			val = val[:got]
		}
		out[part] = val
	}
	return out, nil
}
func restoreXattrs(path string, h tar.Header, symlink bool) error {
	attrs := map[string][]byte{}
	for k, v := range h.Xattrs {
		attrs[k] = []byte(v)
	}
	for k, v := range h.PAXRecords {
		if strings.HasPrefix(k, "SCHILY.xattr.") {
			attrs[strings.TrimPrefix(k, "SCHILY.xattr.")] = []byte(v)
		}
		if strings.HasPrefix(k, xattrPAXPrefix) {
			nk := strings.TrimPrefix(k, xattrPAXPrefix)
			nb, e := base64.RawURLEncoding.DecodeString(nk)
			if e != nil {
				return fmt.Errorf("invalid xattr name encoding: %w", e)
			}
			vb, e := base64.StdEncoding.DecodeString(v)
			if e != nil {
				return fmt.Errorf("invalid xattr value encoding: %w", e)
			}
			attrs[string(nb)] = vb
		}
	}
	keys := make([]string, 0, len(attrs))
	for k := range attrs {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		var err error
		if symlink {
			err = lsetxattr(path, k, attrs[k], 0)
		} else {
			err = syscall.Setxattr(path, k, attrs[k], 0)
		}
		if err != nil {
			return fmt.Errorf("restore xattr %s on %s: %w", k, path, err)
		}
	}
	return nil
}

func llistxattr(path string, dest []byte) (int, error) {
	p, err := syscall.BytePtrFromString(path)
	if err != nil {
		return 0, err
	}
	var ptr uintptr
	if len(dest) > 0 {
		ptr = uintptr(unsafe.Pointer(&dest[0]))
	}
	r0, _, errno := syscall.Syscall(syscall.SYS_LLISTXATTR, uintptr(unsafe.Pointer(p)), ptr, uintptr(len(dest)))
	if errno != 0 {
		return int(r0), errno
	}
	return int(r0), nil
}
func lgetxattr(path, name string, dest []byte) (int, error) {
	p, err := syscall.BytePtrFromString(path)
	if err != nil {
		return 0, err
	}
	n, err := syscall.BytePtrFromString(name)
	if err != nil {
		return 0, err
	}
	var ptr uintptr
	if len(dest) > 0 {
		ptr = uintptr(unsafe.Pointer(&dest[0]))
	}
	r0, _, errno := syscall.Syscall6(syscall.SYS_LGETXATTR, uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(n)), ptr, uintptr(len(dest)), 0, 0)
	if errno != 0 {
		return int(r0), errno
	}
	return int(r0), nil
}
func lsetxattr(path, name string, data []byte, flags int) error {
	p, err := syscall.BytePtrFromString(path)
	if err != nil {
		return err
	}
	n, err := syscall.BytePtrFromString(name)
	if err != nil {
		return err
	}
	var ptr uintptr
	if len(data) > 0 {
		ptr = uintptr(unsafe.Pointer(&data[0]))
	}
	_, _, errno := syscall.Syscall6(syscall.SYS_LSETXATTR, uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(n)), ptr, uintptr(len(data)), uintptr(flags), 0)
	if errno != 0 {
		return errno
	}
	return nil
}

func safeTarget(root, rel string) (string, error) {
	clean := filepath.Clean(rel)
	if filepath.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("archive member escapes target: %s", rel)
	}
	target := filepath.Join(root, clean)
	r, e := filepath.Rel(root, target)
	if e != nil || r == ".." || strings.HasPrefix(r, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("archive member escapes target: %s", rel)
	}
	return target, nil
}
func ensureRealParents(root, path string) error {
	rel, e := filepath.Rel(root, filepath.Dir(path))
	if e != nil {
		return e
	}
	cur := root
	if rel == "." {
		return nil
	}
	for _, part := range strings.Split(rel, string(filepath.Separator)) {
		cur = filepath.Join(cur, part)
		st, e := os.Lstat(cur)
		if os.IsNotExist(e) {
			if e = os.Mkdir(cur, 0o700); e != nil {
				return e
			}
			continue
		}
		if e != nil {
			return e
		}
		if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
			return fmt.Errorf("archive parent is not a real directory: %s", cur)
		}
	}
	return nil
}
func ensureDirectory(path string) error {
	st, e := os.Lstat(path)
	if os.IsNotExist(e) {
		return os.Mkdir(path, 0o700)
	}
	if e != nil {
		return e
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("archive directory collides with unsafe entry: %s", path)
	}
	return nil
}
func ensureAbsentOrRegular(path string) error {
	st, e := os.Lstat(path)
	if os.IsNotExist(e) {
		return nil
	}
	if e != nil {
		return e
	}
	if !st.Mode().IsRegular() {
		return fmt.Errorf("archive file collides with non-regular entry: %s", path)
	}
	return nil
}
func syncTreeRoot(root string) error {
	f, e := os.Open(root)
	if e != nil {
		return e
	}
	defer f.Close()
	return f.Sync()
}
func timespecTime(ts syscall.Timespec) time.Time { return time.Unix(ts.Sec, ts.Nsec) }
func linuxMajorMinor(dev uint64) (int64, int64) {
	major := ((dev >> 8) & 0xfff) | ((dev >> 32) & 0xfffff000)
	minor := (dev & 0xff) | ((dev >> 12) & 0xffffff00)
	return int64(major), int64(minor)
}
func linuxMkdev(major, minor uint64) int {
	return int((minor & 0xff) | ((major & 0xfff) << 8) | ((minor & 0xffffff00) << 12) | ((major & 0xfffff000) << 32))
}

func setTimes(path string, atime, mtime time.Time, noFollow bool) error {
	if atime.IsZero() {
		atime = mtime
	}
	if mtime.IsZero() {
		return nil
	}
	ts := []syscall.Timespec{syscall.NsecToTimespec(atime.UnixNano()), syscall.NsecToTimespec(mtime.UnixNano())}
	if !noFollow {
		return syscall.UtimesNano(path, ts)
	}
	p, err := syscall.BytePtrFromString(path)
	if err != nil {
		return err
	}
	const atFDCWD = ^uintptr(99) // -100
	const atSymlinkNoFollow = 0x100
	_, _, errno := syscall.Syscall6(syscall.SYS_UTIMENSAT, atFDCWD, uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(&ts[0])), atSymlinkNoFollow, 0, 0)
	if errno != 0 {
		return errno
	}
	return nil
}
