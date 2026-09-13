package services

import "context"

type operationProvenanceKey struct{}

type OperationProvenance struct {
	ID   string
	Kind string
}

func WithOperationProvenance(ctx context.Context, id, kind string) context.Context {
	if ctx == nil || (id == "" && kind == "") {
		return ctx
	}
	return context.WithValue(ctx, operationProvenanceKey{}, OperationProvenance{ID: id, Kind: kind})
}

func OperationProvenanceFromContext(ctx context.Context) OperationProvenance {
	if ctx == nil {
		return OperationProvenance{}
	}
	if v, ok := ctx.Value(operationProvenanceKey{}).(OperationProvenance); ok {
		return v
	}
	return OperationProvenance{}
}
