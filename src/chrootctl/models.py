from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(slots=True)
class OperationResult:
    success: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def add_success(self) -> None:
        self.success += 1

    def add_failure(self, message: str) -> None:
        self.failed += 1
        self.errors.append(message)

    def add_skipped(self) -> None:
        self.skipped += 1
