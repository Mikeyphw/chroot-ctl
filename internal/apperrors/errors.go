package apperrors

import (
	"fmt"
	"strings"
)

type ErrorAction struct {
	Label   string  `json:"label"`
	Href    *string `json:"href"`
	Command *string `json:"command"`
}

type ErrorResponse struct {
	Code       string         `json:"code"`
	Title      string         `json:"title"`
	Message    string         `json:"message"`
	Details    map[string]any `json:"details"`
	Hints      []string       `json:"hints"`
	Actions    []ErrorAction  `json:"actions"`
	Retryable  bool           `json:"retryable"`
	StatusCode int            `json:"status_code"`
}

func (response ErrorResponse) HTTPPayload() map[string]any {
	actions := make([]map[string]any, 0, len(response.Actions))
	for _, action := range response.Actions {
		item := map[string]any{"label": action.Label, "href": nil, "command": nil}
		if action.Href != nil {
			item["href"] = *action.Href
		}
		if action.Command != nil {
			item["command"] = *action.Command
		}
		actions = append(actions, item)
	}
	return map[string]any{
		"code":      response.Code,
		"title":     response.Title,
		"message":   response.Message,
		"details":   cloneMap(response.Details),
		"hints":     append(make([]string, 0, len(response.Hints)), response.Hints...),
		"actions":   actions,
		"retryable": response.Retryable,
	}
}

type AppError struct {
	Code       string
	Title      string
	Message    string
	Details    map[string]any
	Hints      []string
	Actions    []ErrorAction
	Retryable  bool
	StatusCode int
}

func (err AppError) Error() string {
	if strings.TrimSpace(err.Message) != "" {
		return err.Message
	}
	if strings.TrimSpace(err.Title) != "" {
		return err.Title
	}
	return err.Code
}

func (err AppError) ToResponse() ErrorResponse {
	status := err.StatusCode
	if status == 0 {
		status = 400
	}
	return ErrorResponse{
		Code:       err.Code,
		Title:      err.Title,
		Message:    err.Message,
		Details:    cloneMap(err.Details),
		Hints:      append([]string(nil), err.Hints...),
		Actions:    append([]ErrorAction(nil), err.Actions...),
		Retryable:  err.Retryable,
		StatusCode: status,
	}
}

func FromHTTPException(statusCode int, detail any) ErrorResponse {
	switch typed := detail.(type) {
	case ErrorResponse:
		typed.StatusCode = statusCode
		return normalizeResponse(typed)
	case *ErrorResponse:
		if typed != nil {
			copy := *typed
			copy.StatusCode = statusCode
			return normalizeResponse(copy)
		}
	case map[string]any:
		return responseFromMap(statusCode, typed)
	}
	message := DefaultMessage(statusCode)
	if detail != nil {
		text := fmt.Sprint(detail)
		if text != "" {
			message = text
		}
	}
	return normalizeResponse(ErrorResponse{
		Code:       fmt.Sprintf("http_%d", statusCode),
		Title:      DefaultTitle(statusCode),
		Message:    message,
		StatusCode: statusCode,
	})
}

func responseFromMap(statusCode int, detail map[string]any) ErrorResponse {
	code := stringValue(detail["code"])
	if code == "" {
		code = fmt.Sprintf("http_%d", statusCode)
	}
	title := stringValue(detail["title"])
	if title == "" {
		title = DefaultTitle(statusCode)
	}
	message := stringValue(detail["message"])
	if message == "" {
		message = stringValue(detail["detail"])
	}
	if message == "" {
		message = DefaultMessage(statusCode)
	}

	details := map[string]any{}
	if raw, ok := detail["details"].(map[string]any); ok {
		details = cloneMap(raw)
	}

	hints := stringSlice(detail["hints"])
	actions := actionSlice(detail["actions"])
	retryable, _ := detail["retryable"].(bool)
	return ErrorResponse{
		Code:       code,
		Title:      title,
		Message:    message,
		Details:    details,
		Hints:      hints,
		Actions:    actions,
		Retryable:  retryable,
		StatusCode: statusCode,
	}
}

func normalizeResponse(response ErrorResponse) ErrorResponse {
	if response.Details == nil {
		response.Details = map[string]any{}
	}
	if response.Hints == nil {
		response.Hints = []string{}
	}
	if response.Actions == nil {
		response.Actions = []ErrorAction{}
	}
	return response
}

func DefaultTitle(statusCode int) string {
	switch {
	case statusCode == 404:
		return "Not found"
	case statusCode == 403:
		return "Forbidden"
	case statusCode == 422:
		return "Validation error"
	case statusCode >= 500:
		return "Internal error"
	default:
		return "Request error"
	}
}

func DefaultMessage(statusCode int) string {
	switch {
	case statusCode == 404:
		return "The requested resource was not found."
	case statusCode == 403:
		return "The request is not allowed."
	case statusCode == 422:
		return "The request payload is invalid."
	case statusCode >= 500:
		return "The request failed because of an internal error."
	default:
		return "The request could not be completed."
	}
}

func stringValue(value any) string {
	if value == nil {
		return ""
	}
	return fmt.Sprint(value)
}

func stringSlice(value any) []string {
	items, ok := value.([]any)
	if !ok {
		if stringsValue, ok := value.([]string); ok {
			return append([]string(nil), stringsValue...)
		}
		return []string{}
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		result = append(result, fmt.Sprint(item))
	}
	return result
}

func actionSlice(value any) []ErrorAction {
	items, ok := value.([]any)
	if !ok {
		return []ErrorAction{}
	}
	result := make([]ErrorAction, 0, len(items))
	for _, item := range items {
		mapping, ok := item.(map[string]any)
		if !ok {
			continue
		}
		action := ErrorAction{Label: stringValue(mapping["label"])}
		if href := stringValue(mapping["href"]); href != "" {
			action.Href = &href
		}
		if command := stringValue(mapping["command"]); command != "" {
			action.Command = &command
		}
		result = append(result, action)
	}
	return result
}

func cloneMap(value map[string]any) map[string]any {
	if value == nil {
		return map[string]any{}
	}
	result := make(map[string]any, len(value))
	for key, item := range value {
		result[key] = item
	}
	return result
}
