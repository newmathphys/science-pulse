from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

LEAN_FILE = "formal/Invariants.lean"


@dataclass
class FormalResult:
    available: bool
    ok: bool
    file: str
    stdout: str = ""
    stderr: str = ""
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "ok": self.ok,
            "file": self.file,
            "error": self.error,
            "stderr": self.stderr,
        }


def lean_available() -> bool:
    return shutil.which("lean") is not None


def check_lean(root: Optional[Path] = None, timeout: int = 180) -> FormalResult:
    """Компилирует Lean-доказательства инвариантов (см. docs/FORMAL.md).

    `ok=True` — файл скомпилирован без ошибок и без `sorry`.
    """
    base = Path(root) if root else Path.cwd()
    path = base / LEAN_FILE
    if not path.exists():
        return FormalResult(available=lean_available(), ok=False, file=str(path), error="файл не найден")
    if not lean_available():
        return FormalResult(available=False, ok=False, file=str(path), error="lean не установлен")
    try:
        proc = subprocess.run(
            ["lean", str(path)],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover - защита от таймаута/сбоя процесса
        return FormalResult(available=True, ok=False, file=str(path), error=str(exc)[:200])
    stdout = (proc.stdout or "")[-4000:]
    stderr = (proc.stderr or "")[-4000:]
    ok = proc.returncode == 0 and "sorry" not in stdout and "sorry" not in stderr
    return FormalResult(available=True, ok=ok, file=str(path), stdout=stdout, stderr=stderr)
