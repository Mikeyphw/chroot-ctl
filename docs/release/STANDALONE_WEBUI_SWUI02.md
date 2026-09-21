# SWUI-02 — typed HTTP backend mapping

SWUI-02 maps the standalone loopback transport onto the same `bridge.Dispatcher` and `services.Container` used by the structured `chrootctl app` protocol. It does not add a second business-logic implementation.

Authenticated endpoints provide capabilities/state, typed query and preview dispatch, operation execution with collected structured events, and operation journal get/cancel/reconcile. Operation names and payloads are still resolved by the frozen bridge contract, including the complete session/tmux surface.

Every non-GET request remains protected by the SWUI-01 session, CSRF and Origin checks. There is no shell, exec, arbitrary argv, generic root RPC, permissive CORS, or direct tmux HTTP endpoint.
