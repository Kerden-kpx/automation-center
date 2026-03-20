from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import List


def _parse_modules(raw: str) -> List[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _run_module(module: str) -> int:
    cmd = [sys.executable, "-m", module]
    print(f"[composite] start module={module}", flush=True)
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{module}] {line.rstrip()}", flush=True)
    code = proc.wait()
    print(f"[composite] end module={module} code={code}", flush=True)
    return int(code)


def _state_file(run_id: str) -> Path:
    root = Path(tempfile.gettempdir()) / "automation-center" / "scheduler-composite-state"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{run_id}.json"


def _load_state(run_id: str, modules: List[str]) -> int:
    path = _state_file(run_id)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if payload.get("modules") != modules:
        return 0
    completed_count = int(payload.get("completed_count") or 0)
    if completed_count < 0:
        return 0
    if completed_count > len(modules):
        return len(modules)
    return completed_count


def _save_state(run_id: str, modules: List[str], completed_count: int) -> None:
    path = _state_file(run_id)
    payload = {
        "run_id": run_id,
        "modules": modules,
        "completed_count": max(0, int(completed_count)),
    }
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _clear_state(run_id: str) -> None:
    path = _state_file(run_id)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multiple python modules in sequence.")
    parser.add_argument("--modules", required=True, help="Comma-separated modules.")
    args = parser.parse_args()

    modules = _parse_modules(args.modules)
    if not modules:
        print("[composite] no modules provided", flush=True)
        return 2

    run_id = str(os.getenv("SCHEDULER_RUN_ID") or "").strip()
    completed_count = _load_state(run_id, modules) if run_id else 0
    if completed_count > 0:
        print(
            f"[composite] resume run_id={run_id} from step {completed_count + 1}/{len(modules)}",
            flush=True,
        )

    for idx, module in enumerate(modules, start=1):
        if idx <= completed_count:
            print(f"[composite] skip module={module} (already completed)", flush=True)
            continue
        code = _run_module(module)
        if code != 0:
            return code
        completed_count = idx
        if run_id:
            _save_state(run_id, modules, completed_count)
    if run_id:
        _clear_state(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
