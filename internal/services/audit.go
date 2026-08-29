package services

import (
	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	"context"
)

type AuditService struct{ C *Container }

func (s *AuditService) Record(ctx context.Context, eventType, target, result, message, actor string, metadata map[string]string) (model.AuditEvent, error) {
	if actor == "" {
		actor = s.C.BaseConfig.Username
		if actor == "" {
			actor = "unknown"
		}
	}
	if result == "" {
		result = "ok"
	}
	e, err := s.C.Registry.AddEvent(ctx, registry.EventInput{EventType: eventType, Actor: actor, Target: target, Result: result, Message: message, Metadata: func() map[string]any {
		out := map[string]any{}
		for k, v := range metadata {
			out[k] = v
		}
		return out
	}()})
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
	return model.AuditEvent{EventId: int(e.EventID), EventType: e.EventType, Actor: e.Actor, Target: e.Target, Result: e.Result, Message: e.Message, CreatedAt: e.CreatedAt, Metadata: e.Metadata}
}
