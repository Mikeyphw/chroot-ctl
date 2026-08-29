package model

import (
	"fmt"
	"strings"
)

func DisplayBool(value bool) string {
	if value {
		return "yes"
	}
	return "no"
}

func DisplayStrings(values []string) string { return strings.Join(values, ",") }

func (result OperationResult) DisplayMap() map[string]string {
	return map[string]string{
		"success": fmt.Sprint(result.Success),
		"failed":  fmt.Sprint(result.Failed),
		"skipped": fmt.Sprint(result.Skipped),
	}
}

func (result SessionActionResult) DisplayMap() map[string]string {
	return map[string]string{
		"action":     result.Action,
		"target":     result.Target,
		"exit_code":  fmt.Sprint(result.ExitCode),
		"success":    DisplayBool(result.SuccessValue()),
		"next_steps": DisplayStrings(result.NextSteps),
	}
}

func (link LogLink) DisplayMap() map[string]string {
	return map[string]string{"label": link.Label, "href": link.Href}
}

func (entry LogEntry) DisplayMap() map[string]string {
	level := ""
	if entry.Level != nil {
		level = *entry.Level
	}
	return map[string]string{
		"line":  entry.Line,
		"level": level,
		"links": displayLogLinks(entry.Links),
	}
}

func (snapshot LogSnapshot) DisplayMap() map[string]string {
	level := ""
	if snapshot.Level != nil {
		level = *snapshot.Level
	}
	target := ""
	if snapshot.TargetName != nil {
		target = *snapshot.TargetName
	}
	entries := make([]string, 0, len(snapshot.Entries))
	for _, entry := range snapshot.Entries {
		entries = append(entries, logEntryDict(entry))
	}
	links := make([]string, 0, len(snapshot.RelatedLinks))
	for _, link := range snapshot.RelatedLinks {
		links = append(links, logLinkDict(link))
	}
	return map[string]string{
		"log_file":      snapshot.LogFile,
		"level":         level,
		"lines":         DisplayStrings(snapshot.Lines),
		"follow":        DisplayBool(snapshot.Follow),
		"target_name":   target,
		"entries":       strings.Join(entries, ","),
		"related_links": strings.Join(links, ","),
	}
}

func (result AppBuildResult) DisplayMap() map[string]string {
	return map[string]string{
		"artifact_name":   result.ArtifactName,
		"artifact_path":   result.ArtifactPath,
		"output_dir":      result.OutputDir,
		"startup_targets": DisplayStrings(result.StartupTargets),
	}
}

func displayLogLinks(values []LogLink) string {
	parts := make([]string, 0, len(values))
	for _, value := range values {
		parts = append(parts, logLinkDict(value))
	}
	return strings.Join(parts, ",")
}

func logLinkDict(link LogLink) string {
	return "{'label': " + reprString(link.Label) + ", 'href': " + reprString(link.Href) + "}"
}

func logEntryDict(entry LogEntry) string {
	level := ""
	if entry.Level != nil {
		level = *entry.Level
	}
	return "{'line': " + reprString(entry.Line) + ", 'level': " + reprString(level) + ", 'links': " + reprString(displayLogLinks(entry.Links)) + "}"
}

func reprString(value string) string {
	value = strings.ReplaceAll(value, `\`, `\\`)
	value = strings.ReplaceAll(value, `'`, `\'`)
	value = strings.ReplaceAll(value, "\n", `\n`)
	value = strings.ReplaceAll(value, "\r", `\r`)
	return "'" + value + "'"
}
