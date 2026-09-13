package services

import (
	"context"
	"os"
	"os/user"
	"strings"

	"chrootctl/internal/model"
	"chrootctl/internal/redaction"
	"chrootctl/internal/registry"
)

type AuditService struct{ C *Container }

func defaultAuditActor(fallback string) string {
	if u, err := user.Current(); err == nil && strings.TrimSpace(u.Username) != "" {
		return u.Username
	}
	for _, key := range []string{"USER", "LOGNAME"} {
		if v := strings.TrimSpace(os.Getenv(key)); v != "" {
			return v
		}
	}
	if fallback != "" {
		return fallback
	}
	return "unknown"
}

func (s *AuditService) Record(ctx context.Context, eventType, target, result, message, actor string, metadata map[string]string) (model.AuditEvent, error) {
	if actor == "" {
		actor = defaultAuditActor(s.C.BaseConfig.Username)
	}
	if result == "" {
		result = "ok"
	}
	cleanMeta := map[string]any{}
	for k, v := range metadata {
		cleanMeta[k] = v
	}
	e, err := s.C.Registry.AddEvent(ctx, registry.EventInput{EventType: redaction.String(eventType), Actor: actor, Target: target, Result: redaction.String(result), Message: message, Metadata: cleanMeta})
	return eventModel(e), err
}
func (s *AuditService) Recent(ctx context.Context, limit int) ([]model.AuditEvent, error) {
	rows, e := s.C.Registry.ListEvents(ctx, limit)
	out := make([]model.AuditEvent, 0, len(rows))
	for _, r := range rows {
		out = append(out, eventModel(r))
	}
	return out, e
}
func eventModel(e registry.Event) model.AuditEvent {
	return model.AuditEvent{EventId: int(e.EventID), EventType: redaction.String(e.EventType), Actor: redaction.String(e.Actor), Target: redaction.String(e.Target), Result: redaction.String(e.Result), Message: redaction.String(e.Message), CreatedAt: e.CreatedAt, Metadata: redactedStringMap(e.Metadata)}
}
func redactedStringMap(in map[string]string) map[string]string {
	out := make(map[string]string, len(in))
	for k, v := range in {
		if redaction.Value(map[string]any{k: v}).(map[string]any)[k] == "<redacted>" {
			out[k] = "<redacted>"
		} else {
			out[k] = redaction.String(v)
		}
	}
	return out
}
