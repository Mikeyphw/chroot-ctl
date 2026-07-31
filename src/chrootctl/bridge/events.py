from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TextIO

EventSink = Callable[[dict[str, Any]], None]


def ndjson_sink(stream: TextIO) -> EventSink:
    def emit(event: dict[str, Any]) -> None:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        stream.write("\n")
        stream.flush()

    return emit
