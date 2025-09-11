from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
import threading


class OpsLogger:
    """Append-only JSONL logger for operational metrics.

    - Writes one JSON object per line to a file (UTF-8, newline-delimited)
    - Thread-safe (coarse lock)
    - Best-effort: never raises to caller
    """

    def __init__(self, file_path: Path, also_stdout: bool = False) -> None:
        self.file_path = Path(file_path)
        self.also_stdout = bool(also_stdout)
        self._lock = threading.Lock()
        # Ensure parent exists
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def emit(self, record: Dict[str, Any]) -> None:
        try:
            line = json.dumps(record, ensure_ascii=False)
        except Exception:
            # Last resort: stringify
            try:
                line = json.dumps({"egc_ops": 1, "_serialization_error": True, "record_str": str(record)})
            except Exception:
                return
        try:
            with self._lock:
                with self.file_path.open("a", encoding="utf-8") as f:
                    f.write(line)
                    f.write("\n")
        except Exception:
            # Never propagate logging errors
            pass
        if self.also_stdout:
            try:
                print(line)
            except Exception:
                pass
