from __future__ import annotations

import os
import subprocess
import logging
import threading
import time
import uuid
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from .alerting import SchedulerAlertNotifier
from .models import TaskDefinition, TaskRestartPolicy, TaskRun, TaskRunMode, TaskStatus
from ..persistence.store import SchedulerStore

logger = logging.getLogger(__name__)
COMPOSITE_RUNNER_MODULE = "apps.scheduler.backend.composite_task_runner"

@dataclass
class _RunState:
    task: TaskDefinition
    run: TaskRun
    process: subprocess.Popen | None = None
    log_thread: threading.Thread | None = None
    stop_requested: bool = False
    timed_out: bool = False


class TaskRunner:
    def __init__(
        self,
        store: SchedulerStore,
        log_tail_size: int = 200,
        heartbeat_interval_sec: int = 5,
        poll_interval_sec: float = 0.5,
        max_concurrent_runs: int = 4,
        dispatch_interval_sec: float = 0.5,
    ) -> None:
        self._store = store
        self._states: Dict[str, _RunState] = {}
        self._task_running_run: Dict[str, str] = {}
        self._pending_run_ids: list[str] = []
        self._active_resources: Dict[str, str] = {}
        self._log_tail_size = max(20, int(log_tail_size))
        self._heartbeat_interval_sec = max(2, int(heartbeat_interval_sec))
        self._poll_interval_sec = max(0.2, float(poll_interval_sec))
        self._max_concurrent_runs = max(1, int(max_concurrent_runs))
        self._dispatch_interval_sec = max(0.1, float(dispatch_interval_sec))
        self._echo_task_logs = (os.getenv("SCHEDULER_ECHO_TASK_LOGS", "1") or "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._alert_notifier = SchedulerAlertNotifier.from_env()
        self._lock = threading.Lock()
        threading.Thread(target=self._dispatch_loop, daemon=True).start()

    def start(self, task: TaskDefinition, *, trigger_type: str = "manual") -> TaskRun:
        with self._lock:
            running_run_id = self._task_running_run.get(task.task_id)
            if task.singleton and running_run_id:
                state = self._states.get(running_run_id)
                if state and state.run.status in {TaskStatus.running, TaskStatus.queued}:
                    raise RuntimeError(f"Task is already running: {task.task_id}")
            if task.singleton and self._store.has_running_task(task.task_id):
                raise RuntimeError(f"Task is already running (persisted): {task.task_id}")

            run = TaskRun(
                run_id=uuid.uuid4().hex[:12],
                task_id=task.task_id,
                status=TaskStatus.queued,
                started_at=datetime.now(),
                attempt=1,
                max_retries=max(0, int(task.max_retries)),
                trigger_type=trigger_type,
                last_heartbeat_at=datetime.now(),
            )
            self._store.create_run(run)
            state = _RunState(task=task, run=run)
            self._states[run.run_id] = state
            self._task_running_run[task.task_id] = run.run_id
            self._enqueue_locked(run.run_id)
            self._store.update_run(run)
            self._dispatch_locked()
            logger.info(
                "Run queued run_id=%s task_id=%s trigger=%s priority=%s",
                run.run_id,
                run.task_id,
                trigger_type,
                task.priority,
            )
            return run

    def stop(self, run_id: str) -> None:
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return
            state.stop_requested = True
            process = state.process
            if process is None:
                self._pending_run_ids = [rid for rid in self._pending_run_ids if rid != run_id]
                self._release_resource_locked(state)
                state.run.status = TaskStatus.stopped
                state.run.error_message = "Stopped by user"
                state.run.ended_at = datetime.now()
                state.run.last_heartbeat_at = state.run.ended_at
                self._store.update_run(state.run)
                self._task_running_run.pop(state.task.task_id, None)
                self._states.pop(run_id, None)
                return
            state.run.status = TaskStatus.stopped
            state.run.error_message = "Stopped by user"
            state.run.last_heartbeat_at = datetime.now()
            self._store.update_run(state.run)
            logger.info("Run stop requested run_id=%s task_id=%s", run_id, state.task.task_id)
        try:
            process.terminate()
        except Exception:
            pass

    def get_run(self, run_id: str) -> Optional[TaskRun]:
        with self._lock:
            state = self._states.get(run_id)
            if state is not None:
                return state.run
        return self._store.get_run(run_id, with_log_tail=self._log_tail_size)

    def list_runs(self) -> list[TaskRun]:
        runs = self._store.list_runs(limit=200, with_log_tail=self._log_tail_size)
        by_id = {run.run_id: run for run in runs}
        with self._lock:
            for run_id, state in self._states.items():
                by_id[run_id] = state.run
        return sorted(
            by_id.values(),
            key=lambda item: item.started_at or datetime.min,
            reverse=True,
        )

    def _enqueue_locked(self, run_id: str) -> None:
        if run_id in self._pending_run_ids:
            return
        self._pending_run_ids.append(run_id)
        self._pending_run_ids.sort(
            key=lambda rid: (
                -(self._states.get(rid).task.priority if self._states.get(rid) else 0),
                self._states.get(rid).run.started_at if self._states.get(rid) else datetime.now(),
            )
        )

    def _dispatch_loop(self) -> None:
        while True:
            try:
                with self._lock:
                    self._dispatch_locked()
            except Exception:
                pass
            time.sleep(self._dispatch_interval_sec)

    def _dispatch_locked(self) -> None:
        progressed = True
        while progressed:
            progressed = False
            if self._running_count_locked() >= self._max_concurrent_runs:
                return
            for run_id in list(self._pending_run_ids):
                state = self._states.get(run_id)
                if state is None:
                    self._pending_run_ids.remove(run_id)
                    continue
                if not self._can_start_locked(state):
                    continue
                self._pending_run_ids.remove(run_id)
                try:
                    self._start_attempt_locked(state)
                except Exception as exc:
                    state.run.status = TaskStatus.failed
                    state.run.error_message = f"Launch failed: {exc}"
                    state.run.ended_at = datetime.now()
                    state.run.last_heartbeat_at = state.run.ended_at
                    self._store.update_run(state.run)
                    self._notify_failure(state)
                    self._release_resource_locked(state)
                    self._task_running_run.pop(state.task.task_id, None)
                    self._states.pop(run_id, None)
                    progressed = True
                    break
                self._start_watcher(state.run.run_id)
                progressed = True
                break

    def _running_count_locked(self) -> int:
        count = 0
        for state in self._states.values():
            if state.process is not None and state.run.status == TaskStatus.running:
                count += 1
        return count

    def _can_start_locked(self, state: _RunState) -> bool:
        if state.stop_requested:
            return False
        if self._running_count_locked() >= self._max_concurrent_runs:
            return False
        resource_group = (state.task.resource_group or "").strip()
        if resource_group and resource_group in self._active_resources:
            return False
        return True

    def _start_watcher(self, run_id: str) -> None:
        threading.Thread(target=self._watch_run, args=(run_id,), daemon=True).start()

    def _start_attempt_locked(self, state: _RunState) -> None:
        run = state.run
        task = state.task

        resource_group = (task.resource_group or "").strip()
        if resource_group:
            self._active_resources[resource_group] = run.run_id

        try:
            command = self._build_command_for_task(task)
            child_env = os.environ.copy()
            child_env["PYTHONUNBUFFERED"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["SCHEDULER_RUN_ID"] = run.run_id
            child_env["SCHEDULER_TASK_ID"] = task.task_id
            process = subprocess.Popen(
                command,
                cwd=task.cwd or None,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception:
            if resource_group:
                self._active_resources.pop(resource_group, None)
            raise

        state.process = process
        state.timed_out = False
        run.status = TaskStatus.running
        run.ended_at = None
        run.return_code = None
        run.error_message = None
        run.last_heartbeat_at = datetime.now()
        self._store.update_run(run)
        state.log_thread = threading.Thread(target=self._stream_logs, args=(state,), daemon=True)
        state.log_thread.start()
        logger.info("Run started run_id=%s task_id=%s attempt=%s", run.run_id, task.task_id, run.attempt)

    def _build_command_for_task(self, task: TaskDefinition) -> list[str]:
        steps = [step for step in sorted(task.pipeline or [], key=lambda item: int(item.get("order") or 0)) if bool(step.get("enabled", True))]
        if not steps:
            raise RuntimeError(f"Task pipeline is empty: {task.task_id}")
        app_rows = self._store.list_apps()
        app_map = {str(row.get("app_id") or ""): str(row.get("module") or "") for row in app_rows}
        modules: list[str] = []
        for step in steps:
            app_id = str(step.get("app_id") or "").strip()
            module = app_map.get(app_id, "").strip()
            if not module:
                raise RuntimeError(f"Invalid app_id in pipeline: {app_id}")
            modules.append(module)
        if len(modules) == 1:
            return [sys.executable, "-u", "-m", modules[0]]
        return [sys.executable, "-u", "-m", COMPOSITE_RUNNER_MODULE, "--modules", ",".join(modules)]

    def _stream_logs(self, state: _RunState) -> None:
        process = state.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._append_log(state.run.run_id, line)

    def _append_log(self, run_id: str, line: str) -> None:
        text = str(line or "").rstrip("\n")
        if not text:
            return
        if self._echo_task_logs:
            logger.info("[task-log][%s] %s", run_id, text)
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return
            run = state.run
            run.log_tail.append(text)
            if len(run.log_tail) > self._log_tail_size:
                run.log_tail[:] = run.log_tail[-self._log_tail_size :]
            run.last_heartbeat_at = datetime.now()
            self._store.update_run(run)
        self._store.append_logs(run_id, [text])

    def _watch_run(self, run_id: str) -> None:
        while True:
            with self._lock:
                state = self._states.get(run_id)
                if state is None:
                    return
                process = state.process
                run = state.run
                task = state.task

            if process is None:
                self._fail_run(run_id, "Missing process handle.")
                return

            code = process.poll()
            now = datetime.now()
            if code is None:
                self._heartbeat(run_id, now)
                time.sleep(self._poll_interval_sec)
                continue

            self._finalize_attempt(run_id, code)
            with self._lock:
                state = self._states.get(run_id)
                if state is None:
                    return
                should_retry = self._should_retry(state)
                retry_delay = max(0, int(task.retry_delay_sec))
            if not should_retry:
                with self._lock:
                    current = self._states.get(run_id)
                    if current:
                        self._task_running_run.pop(current.task.task_id, None)
                        self._states.pop(run_id, None)
                return

            with self._lock:
                current = self._states.get(run_id)
                if current is None:
                    return
                if current.task.run_mode == TaskRunMode.daemon:
                    retry_desc = f"attempt {current.run.attempt + 1}"
                else:
                    retry_desc = f"attempt {current.run.attempt + 1}/{current.run.max_retries + 1}"
            self._append_log(run_id, f"[runner] retry {retry_desc}")
            if retry_delay > 0:
                time.sleep(retry_delay)
            with self._lock:
                current = self._states.get(run_id)
                if current is None:
                    return
                current.run.attempt += 1
                current.run.status = TaskStatus.queued
                current.run.return_code = None
                current.run.error_message = None
                current.run.ended_at = None
                current.run.last_heartbeat_at = datetime.now()
                current.process = None
                current.log_thread = None
                current.timed_out = False
                self._store.update_run(current.run)
                self._enqueue_locked(run_id)
                self._dispatch_locked()
                return

    def _heartbeat(self, run_id: str, now: datetime) -> None:
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return
            run = state.run
            if run.last_heartbeat_at and (now - run.last_heartbeat_at).total_seconds() < self._heartbeat_interval_sec:
                return
            run.last_heartbeat_at = now
            self._store.update_run(run)

    @staticmethod
    def _should_retry(state: _RunState) -> bool:
        if state.stop_requested:
            return False
        if state.task.run_mode == TaskRunMode.daemon:
            if state.task.restart_policy == TaskRestartPolicy.never:
                return False
            if state.task.restart_policy == TaskRestartPolicy.always:
                return True
            return state.run.status == TaskStatus.failed
        return state.run.status == TaskStatus.failed and state.run.attempt <= state.run.max_retries

    def _timeout_process(self, run_id: str) -> None:
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return
            if state.timed_out:
                return
            state.timed_out = True
            process = state.process
            timeout_sec = int(state.task.timeout_sec)
        self._append_log(run_id, f"[runner] timeout exceeded ({timeout_sec}s), terminating process.")
        logger.warning("Run timeout run_id=%s timeout_sec=%s", run_id, timeout_sec)
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _release_resource_locked(self, state: _RunState) -> None:
        resource_group = (state.task.resource_group or "").strip()
        if not resource_group:
            return
        owner = self._active_resources.get(resource_group)
        if owner == state.run.run_id:
            self._active_resources.pop(resource_group, None)

    def _finalize_attempt(self, run_id: str, return_code: int) -> None:
        should_notify = False
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return
            log_thread = state.log_thread
            run = state.run
            if state.stop_requested:
                run.status = TaskStatus.stopped
            elif state.timed_out:
                run.status = TaskStatus.failed
                run.error_message = f"Timeout exceeded: {int(state.task.timeout_sec)}s"
            else:
                run.status = TaskStatus.success if return_code == 0 else TaskStatus.failed
                if return_code != 0:
                    run.error_message = f"Process exited with code {return_code}"
            run.return_code = int(return_code)
            run.ended_at = datetime.now()
            run.last_heartbeat_at = run.ended_at
            state.process = None
            state.log_thread = None
            self._release_resource_locked(state)
            self._store.update_run(run)
            should_notify = run.status == TaskStatus.failed
        if log_thread is not None and log_thread.is_alive():
            log_thread.join(timeout=2)
        if should_notify:
            self._notify_failure(state)
        logger.info(
            "Run finalized run_id=%s task_id=%s status=%s return_code=%s attempt=%s",
            run.run_id,
            state.task.task_id,
            run.status.value if hasattr(run.status, "value") else run.status,
            return_code,
            run.attempt,
        )

    def _fail_run(self, run_id: str, message: str) -> None:
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return
            state.run.status = TaskStatus.failed
            state.run.error_message = message
            state.run.ended_at = datetime.now()
            state.run.last_heartbeat_at = state.run.ended_at
            self._release_resource_locked(state)
            self._store.update_run(state.run)
            self._notify_failure(state)
            self._task_running_run.pop(state.task.task_id, None)
            self._states.pop(run_id, None)
        logger.error("Run failed run_id=%s task_id=%s error=%s", run_id, state.task.task_id, message)

    def _notify_failure(self, state: _RunState) -> None:
        try:
            self._alert_notifier.notify_failure(
                task_id=state.task.task_id,
                run_id=state.run.run_id,
                status=str(state.run.status.value if hasattr(state.run.status, "value") else state.run.status),
                error_message=str(state.run.error_message or ""),
                trigger_type=str(state.run.trigger_type or "unknown"),
                attempt=int(state.run.attempt or 1),
            )
        except Exception:
            return
