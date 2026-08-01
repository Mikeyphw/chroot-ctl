# Phase 26 - UX and release readiness polish

Phase 26 adds a native release readiness card to Home and a `release.readiness` bridge query so the app can surface post-WebUI release state without opening the retired browser UI.

## Polish gates

- Home shows a Release readiness card.
- The bridge exposes `release.readiness`.
- SDK remains pinned to 36.
- Smoke suite contracts from Phase 25 remain wired.
- Known Android/Devtool guardrails remain sealed.
