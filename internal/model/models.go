package model

import "strings"

// This file mirrors the Python dataclasses in src/chrootctl/models.py.
// JSON tags intentionally keep Python snake_case naming during the migration.

type OperationResult struct {
	Success int      `json:"success"`
	Failed  int      `json:"failed"`
	Skipped int      `json:"skipped"`
	Errors  []string `json:"errors"`
}

type ChrootRemovalResult struct {
	Name             string `json:"name"`
	Removed          bool   `json:"removed"`
	UnmountedSuccess int    `json:"unmounted_success"`
	UnmountedFailed  int    `json:"unmounted_failed"`
}

type ChrootRenameResult struct {
	OldName string `json:"old_name"`
	NewName string `json:"new_name"`
	Renamed bool   `json:"renamed"`
}

type ChrootExportResult struct {
	Name         string  `json:"name"`
	Archive      string  `json:"archive"`
	Arch         string  `json:"arch"`
	Checksum     *string `json:"checksum"`
	ChecksumPath *string `json:"checksum_path"`
	Encrypted    bool    `json:"encrypted"`
}

type ChrootImportResult struct {
	Name              string  `json:"name"`
	Archive           string  `json:"archive"`
	Arch              string  `json:"arch"`
	Path              string  `json:"path"`
	ChecksumVerified  *bool   `json:"checksum_verified"`
	ChecksumPath      *string `json:"checksum_path"`
	ConflictStrategy  string  `json:"conflict_strategy"`
	Encrypted         bool    `json:"encrypted"`
	ValidationOk      *bool   `json:"validation_ok"`
	ValidationSummary string  `json:"validation_summary"`
	PostImportAction  string  `json:"post_import_action"`
}

type PackageInventoryResult struct {
	Name      string   `json:"name"`
	Count     int      `json:"count"`
	Packages  []string `json:"packages"`
	Limit     int      `json:"limit"`
	Truncated bool     `json:"truncated"`
}

type PackageDiffResult struct {
	Left        string   `json:"left"`
	Right       string   `json:"right"`
	LeftCount   int      `json:"left_count"`
	RightCount  int      `json:"right_count"`
	OnlyLeft    []string `json:"only_left"`
	OnlyRight   []string `json:"only_right"`
	CommonCount int      `json:"common_count"`
}

type ChrootArchiveInspection struct {
	Archive                 string            `json:"archive"`
	SourceName              string            `json:"source_name"`
	SuggestedName           string            `json:"suggested_name"`
	PathName                string            `json:"path_name"`
	Distro                  string            `json:"distro"`
	Arch                    string            `json:"arch"`
	ReleaseName             string            `json:"release_name"`
	Version                 string            `json:"version"`
	Phase                   string            `json:"phase"`
	Installed               bool              `json:"installed"`
	Metadata                map[string]string `json:"metadata"`
	SizeBytes               int               `json:"size_bytes"`
	ExtractedSizeBytes      int               `json:"extracted_size_bytes"`
	CreatedAt               string            `json:"created_at"`
	Checksum                *string           `json:"checksum"`
	ChecksumPath            *string           `json:"checksum_path"`
	ChecksumVerified        *bool             `json:"checksum_verified"`
	Encrypted               bool              `json:"encrypted"`
	TargetExists            bool              `json:"target_exists"`
	ConflictStrategyOptions []string          `json:"conflict_strategy_options"`
}

type SnapshotRecord struct {
	SnapshotId int               `json:"snapshot_id"`
	Name       string            `json:"name"`
	ChrootName string            `json:"chroot_name"`
	Path       string            `json:"path"`
	Kind       string            `json:"kind"`
	CreatedAt  string            `json:"created_at"`
	Note       string            `json:"note"`
	SizeBytes  int               `json:"size_bytes"`
	Metadata   map[string]string `json:"metadata"`
}

type SnapshotActionResult struct {
	ChrootName      string   `json:"chroot_name"`
	SnapshotName    string   `json:"snapshot_name"`
	Path            string   `json:"path"`
	Action          string   `json:"action"`
	CreatedAt       string   `json:"created_at"`
	ExportedArchive *string  `json:"exported_archive"`
	NextSteps       []string `json:"next_steps"`
}

type RegistryRepairResult struct {
	ScannedPaths    int      `json:"scanned_paths"`
	MissingRecords  []string `json:"missing_records"`
	MissingPaths    []string `json:"missing_paths"`
	MismatchedPaths []string `json:"mismatched_paths"`
	RepairedRecords []string `json:"repaired_records"`
	RemovedRecords  []string `json:"removed_records"`
	Preview         bool     `json:"preview"`
	NextSteps       []string `json:"next_steps"`
}

type AuditEvent struct {
	EventId   int               `json:"event_id"`
	EventType string            `json:"event_type"`
	Actor     string            `json:"actor"`
	Target    string            `json:"target"`
	Result    string            `json:"result"`
	Message   string            `json:"message"`
	CreatedAt string            `json:"created_at"`
	Metadata  map[string]string `json:"metadata"`
}

type SupportBundleResult struct {
	Archive    string   `json:"archive"`
	Included   []string `json:"included"`
	ArtifactID string   `json:"artifact_id,omitempty"`
}

type ChrootUserDetails struct {
	Username      string   `json:"username"`
	Uid           string   `json:"uid"`
	Gid           string   `json:"gid"`
	Home          string   `json:"home"`
	Shell         string   `json:"shell"`
	Sudo          bool     `json:"sudo"`
	SudoRule      bool     `json:"sudo_rule"`
	SudoGroup     bool     `json:"sudo_group"`
	Protected     bool     `json:"protected"`
	System        bool     `json:"system"`
	Login         bool     `json:"login"`
	Mutable       bool     `json:"mutable"`
	PolicyReasons []string `json:"policy_reasons"`
}

type ChrootUserCreateResult struct {
	Username       string `json:"username"`
	Shell          string `json:"shell"`
	Sudo           bool   `json:"sudo"`
	Created        bool   `json:"created"`
	AlreadyExisted bool   `json:"already_existed"`
}

type ChrootUserRemoveResult struct {
	Username    string `json:"username"`
	HomeDeleted bool   `json:"home_deleted"`
	Removed     bool   `json:"removed"`
}

type ChrootUserPasswordResult struct {
	Username string `json:"username"`
	Updated  bool   `json:"updated"`
}

type ChrootUserShellResult struct {
	Username string `json:"username"`
	Shell    string `json:"shell"`
	Updated  bool   `json:"updated"`
}

type ChrootUserSudoResult struct {
	Username     string `json:"username"`
	Enabled      bool   `json:"enabled"`
	Passwordless bool   `json:"passwordless"`
	SudoRule     bool   `json:"sudo_rule"`
	SudoGroup    bool   `json:"sudo_group"`
}

type CatalogApplyResult struct {
	Kind         string   `json:"kind"`
	Name         string   `json:"name"`
	Distro       string   `json:"distro"`
	Categories   []string `json:"categories"`
	Version      string   `json:"version"`
	ScriptSHA256 string   `json:"script_sha256"`
	RiskLevel    string   `json:"risk_level"`
	Rollback     string   `json:"rollback"`
	Applied      bool     `json:"applied"`
}

type InstallExtractResult struct {
	Version string `json:"version"`
	Release string `json:"release"`
	Tarball string `json:"tarball"`
	Phase   string `json:"phase"`
}

type InstallBootstrapResult struct {
	Username string `json:"username"`
	Profile  string `json:"profile"`
	Phase    string `json:"phase"`
}

type InstallDesktopResult struct {
	Desktop  string `json:"desktop"`
	Snapshot string `json:"snapshot"`
	Profile  string `json:"profile"`
	Phase    string `json:"phase"`
}

type InstallFinalizeResult struct {
	Installed bool    `json:"installed"`
	UidSync   bool    `json:"uid_sync"`
	Snapshot  string  `json:"snapshot"`
	Status    *string `json:"status"`
	Phase     string  `json:"phase"`
}

type InstallAlreadyCompleteResult struct {
	Installed bool   `json:"installed"`
	Status    string `json:"status"`
	Phase     string `json:"phase"`
}

type UpgradeResult struct {
	Status    string   `json:"status"`
	Snapshot  string   `json:"snapshot"`
	NextSteps []string `json:"next_steps"`
}

type UserIdStatus struct {
	Username      string   `json:"username"`
	HostUid       int      `json:"host_uid"`
	HostGid       int      `json:"host_gid"`
	ChrootUid     string   `json:"chroot_uid"`
	ChrootGid     string   `json:"chroot_gid"`
	PasswdExists  bool     `json:"passwd_exists"`
	GroupExists   bool     `json:"group_exists"`
	Protected     bool     `json:"protected"`
	System        bool     `json:"system"`
	Mutable       bool     `json:"mutable"`
	PolicyReasons []string `json:"policy_reasons"`
}

type UserIdSyncResult struct {
	Username       string `json:"username"`
	Uid            int    `json:"uid"`
	Gid            int    `json:"gid"`
	OwnershipFixed bool   `json:"ownership_fixed"`
	Transactional  bool   `json:"transactional"`
}

type ChrootRecord struct {
	Name        string            `json:"name"`
	Distro      string            `json:"distro"`
	Path        string            `json:"path"`
	Arch        string            `json:"arch"`
	ReleaseName string            `json:"release_name"`
	Version     string            `json:"version"`
	Phase       string            `json:"phase"`
	Installed   bool              `json:"installed"`
	CreatedAt   string            `json:"created_at"`
	UpdatedAt   string            `json:"updated_at"`
	Metadata    map[string]string `json:"metadata"`
}

type ChrootDetails struct {
	Name             string            `json:"name"`
	Distro           string            `json:"distro"`
	Path             string            `json:"path"`
	ReleaseName      string            `json:"release_name"`
	Version          string            `json:"version"`
	Phase            string            `json:"phase"`
	Installed        bool              `json:"installed"`
	Arch             string            `json:"arch"`
	CreatedAt        string            `json:"created_at"`
	UpdatedAt        string            `json:"updated_at"`
	ConfiguredMounts string            `json:"configured_mounts"`
	ExtraPackages    string            `json:"extra_packages"`
	Locale           string            `json:"locale"`
	Metadata         map[string]string `json:"metadata"`
}

type CheckRow struct {
	Check  string `json:"check"`
	Result string `json:"result"`
	Detail string `json:"detail"`
	Next   string `json:"next"`
}

type LogLink struct {
	Label string `json:"label"`
	Href  string `json:"href"`
}

type LogEntry struct {
	Line  string    `json:"line"`
	Level *string   `json:"level"`
	Links []LogLink `json:"links"`
}

type LogSnapshot struct {
	LogFile      string     `json:"log_file"`
	Level        *string    `json:"level"`
	Lines        []string   `json:"lines"`
	Follow       bool       `json:"follow"`
	TargetName   *string    `json:"target_name"`
	Entries      []LogEntry `json:"entries"`
	RelatedLinks []LogLink  `json:"related_links"`
}

type DashboardSummary struct {
	TargetName   *string        `json:"target_name"`
	Chroots      []ChrootRecord `json:"chroots"`
	StatusChecks []CheckRow     `json:"status_checks"`
	DoctorChecks []CheckRow     `json:"doctor_checks"`
	Logs         *LogSnapshot   `json:"logs"`
}

type InstallWizardDefaults struct {
	Distro   *string  `json:"distro"`
	Name     *string  `json:"name"`
	Username *string  `json:"username"`
	Preset   *string  `json:"preset"`
	Profile  *string  `json:"profile"`
	Desktop  *string  `json:"desktop"`
	Release  *string  `json:"release"`
	Version  *string  `json:"version"`
	Tools    []string `json:"tools"`
	Addons   []string `json:"addons"`
}

type InstallRequest struct {
	Distro            string   `json:"distro"`
	Name              string   `json:"name"`
	Username          string   `json:"username"`
	Arch              string   `json:"arch"`
	Preset            *string  `json:"preset"`
	Profile           *string  `json:"profile"`
	Desktop           *string  `json:"desktop"`
	Release           *string  `json:"release"`
	Version           *string  `json:"version"`
	Mirror            *string  `json:"mirror"`
	Phase             *string  `json:"phase"`
	ForcePhase        bool     `json:"force_phase"`
	Resume            bool     `json:"resume"`
	Repair            bool     `json:"repair"`
	OverwriteExisting bool     `json:"overwrite_existing"`
	Tools             []string `json:"tools"`
	Addons            []string `json:"addons"`
}

type InstallRunResult struct {
	ChrootName   string               `json:"chroot_name"`
	Distro       string               `json:"distro"`
	Phases       []InstallerResult    `json:"phases"`
	ToolResults  []CatalogApplyResult `json:"tool_results"`
	AddonResults []CatalogApplyResult `json:"addon_results"`
	NextSteps    []string             `json:"next_steps"`
}

type SessionActionResult struct {
	Action    string   `json:"action"`
	Target    string   `json:"target"`
	ExitCode  int      `json:"exit_code"`
	NextSteps []string `json:"next_steps"`
}

type DashboardChrootCard struct {
	Name           string `json:"name"`
	Distro         string `json:"distro"`
	Phase          string `json:"phase"`
	Installed      bool   `json:"installed"`
	Running        bool   `json:"running"`
	UserCount      int    `json:"user_count"`
	DoctorWarnings int    `json:"doctor_warnings"`
	DoctorFailures int    `json:"doctor_failures"`
}

type AppBuildResult struct {
	ArtifactName   string   `json:"artifact_name"`
	ArtifactPath   string   `json:"artifact_path"`
	OutputDir      string   `json:"output_dir"`
	StartupTargets []string `json:"startup_targets"`
}

// InstallerResult is the common model surface for the five Python installer
// result variants. The phase method keeps accidental unrelated structs out.
type InstallerResult interface {
	installerResult()
}

func (InstallExtractResult) installerResult()         {}
func (InstallBootstrapResult) installerResult()       {}
func (InstallDesktopResult) installerResult()         {}
func (InstallFinalizeResult) installerResult()        {}
func (InstallAlreadyCompleteResult) installerResult() {}

func (result *OperationResult) AddSuccess() {
	result.Success++
}

func (result *OperationResult) AddFailure(message string) {
	result.Failed++
	result.Errors = append(result.Errors, message)
}

func (result *OperationResult) AddSkipped() {
	result.Skipped++
}

func (result SessionActionResult) SuccessValue() bool {
	return result.ExitCode == 0
}

func (snapshot LogSnapshot) Text() string {
	if len(snapshot.Entries) != 0 {
		lines := make([]string, 0, len(snapshot.Entries))
		for _, entry := range snapshot.Entries {
			lines = append(lines, entry.Line)
		}
		return strings.Join(lines, "\n")
	}
	return strings.Join(snapshot.Lines, "\n")
}

func (result AppBuildResult) NextSteps() []string {
	return []string{"Download artifact: " + result.ArtifactName}
}

func NewChrootImportResult() ChrootImportResult {
	return ChrootImportResult{ConflictStrategy: "rename", PostImportAction: "register"}
}

func NewChrootArchiveInspection() ChrootArchiveInspection {
	return ChrootArchiveInspection{ConflictStrategyOptions: []string{"rename", "overwrite"}}
}

func NewInstallExtractResult() InstallExtractResult {
	return InstallExtractResult{Phase: "extract"}
}

func NewInstallBootstrapResult() InstallBootstrapResult {
	return InstallBootstrapResult{Phase: "bootstrap"}
}

func NewInstallDesktopResult() InstallDesktopResult {
	return InstallDesktopResult{Phase: "desktop"}
}

func NewInstallFinalizeResult() InstallFinalizeResult {
	return InstallFinalizeResult{Phase: "finalize"}
}

func NewInstallAlreadyCompleteResult() InstallAlreadyCompleteResult {
	return InstallAlreadyCompleteResult{Installed: true, Status: "already_complete", Phase: "finalize"}
}

func NewInstallRequest() InstallRequest {
	return InstallRequest{Arch: "arm64"}
}
