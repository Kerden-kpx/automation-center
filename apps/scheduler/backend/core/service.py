from __future__ import annotations

import os
import logging
import threading
import time
from datetime import datetime
from typing import List, Optional

from .models import (
    TaskDefinition,
    TaskRun,
    TaskRunMode,
    TaskScheduleType,
)
from .registry import TaskRegistry
from .runner import TaskRunner
from ..persistence.store import SchedulerStore

logger = logging.getLogger(__name__)


class SchedulerCenterService:
    def __init__(self) -> None:
        self.store = SchedulerStore(auto_init_schema=True)
        self.registry = TaskRegistry(store=self.store)
        self.runner = TaskRunner(
            store=self.store,
            max_concurrent_runs=max(1, int(os.getenv("SCHEDULER_MAX_CONCURRENT_RUNS", "4"))),
        )
        self._watchdog_interval_sec = max(2, int(os.getenv("SCHEDULER_WATCHDOG_INTERVAL", "5")))
        self._watchdog_enabled = os.getenv("SCHEDULER_ENABLE_WATCHDOG", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._schedule_interval_sec = max(10, int(os.getenv("SCHEDULER_SCHEDULE_INTERVAL", "20")))
        self._stale_recovery_sec = max(10, int(os.getenv("SCHEDULER_STALE_RECOVERY_SEC", "120")))
        self._scheduled_fired_day: dict[str, str] = {}
        recovered = self.store.finalize_stale_runs(max_stale_sec=self._stale_recovery_sec)
        if recovered > 0:
            logger.warning(
                "Recovered stale runs count=%s heartbeat_timeout=%ss",
                recovered,
                self._stale_recovery_sec,
            )
        if self._watchdog_enabled:
            threading.Thread(target=self._watchdog_loop, daemon=True).start()
        threading.Thread(target=self._schedule_loop, daemon=True).start()
        logger.info(
            "Scheduler service started watchdog=%s watchdog_interval=%ss schedule_interval=%ss",
            self._watchdog_enabled,
            self._watchdog_interval_sec,
            self._schedule_interval_sec,
        )

    def register_task(self, task: TaskDefinition) -> None:
        self.registry.register(task)

    def update_task(self, task: TaskDefinition) -> TaskDefinition:
        self.registry.register(task)
        return task

    def remove_task(self, task_id: str) -> None:
        self.registry.remove(task_id)

    def list_tasks(self) -> List[TaskDefinition]:
        return self.registry.list()

    def set_task_enabled(self, task_id: str, enabled: bool) -> TaskDefinition:
        task = self.registry.get(task_id)
        task.enabled = bool(enabled)
        self.registry.register(task)
        return task

    def start_task(self, task_id: str, *, trigger_type: str = "manual") -> TaskRun:
        task = self.registry.get(task_id)
        if not task.enabled:
            raise RuntimeError(f"Task is disabled: {task_id}")
        logger.info("Start task requested task_id=%s trigger=%s", task_id, trigger_type)
        return self.runner.start(task, trigger_type=trigger_type)

    def stop_run(self, run_id: str) -> None:
        logger.info("Stop run requested run_id=%s", run_id)
        self.runner.stop(run_id)

    def get_run(self, run_id: str) -> Optional[TaskRun]:
        return self.runner.get_run(run_id)

    def list_runs(self) -> List[TaskRun]:
        return self.runner.list_runs()

    def _watchdog_loop(self) -> None:
        while True:
            try:
                tasks = self.list_tasks()
                for task in tasks:
                    if not task.enabled or task.run_mode != TaskRunMode.daemon:
                        continue
                    if self.store.has_running_task(task.task_id, max_stale_sec=max(10, int(task.max_stale_sec))):
                        continue
                    try:
                        self.runner.start(task, trigger_type="watchdog")
                        logger.warning("Watchdog restarted task task_id=%s", task.task_id)
                    except RuntimeError:
                        continue
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(self._watchdog_interval_sec)

    def _schedule_loop(self) -> None:
        while True:
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                now_hhmm = now.strftime("%H:%M")
                tasks = self.list_tasks()
                for task in tasks:
                    if not task.enabled or task.schedule_type != TaskScheduleType.daily:
                        continue
                    if self._scheduled_fired_day.get(task.task_id) == today:
                        continue
                    if not self._is_due_daily(task.schedule_time, now_hhmm):
                        continue
                    try:
                        self.runner.start(task, trigger_type="schedule")
                        self._scheduled_fired_day[task.task_id] = today
                        logger.info("Schedule fired task_id=%s schedule_time=%s", task.task_id, task.schedule_time)
                    except RuntimeError:
                        continue
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(self._schedule_interval_sec)

    @staticmethod
    def _is_due_daily(schedule_time: str, now_hhmm: str) -> bool:
        if len(schedule_time) != 5 or schedule_time[2] != ":":
            return False
        return now_hhmm == schedule_time

    def stats(self) -> dict:
        tasks = self.list_tasks()
        runs = self.list_runs()
        now = datetime.now()
        status_counts: dict[str, int] = {}
        success_24h = 0
        total_24h = 0
        recent_failures: list[dict] = []

        for run in runs:
            key = run.status.value if hasattr(run.status, "value") else str(run.status)
            status_counts[key] = status_counts.get(key, 0) + 1
            if run.started_at and (now - run.started_at).total_seconds() <= 86400:
                total_24h += 1
                if key == "success":
                    success_24h += 1
            if key == "failed" and len(recent_failures) < 5:
                recent_failures.append(
                    {
                        "run_id": run.run_id,
                        "task_id": run.task_id,
                        "started_at": run.started_at,
                        "error_message": run.error_message,
                    }
                )

        success_rate_24h = round((success_24h * 100.0 / total_24h), 2) if total_24h else 0.0
        return {
            "task_count": len(tasks),
            "run_count": len(runs),
            "status_counts": status_counts,
            "window_24h": {
                "total_runs": total_24h,
                "success_runs": success_24h,
                "success_rate": success_rate_24h,
            },
            "recent_failures": recent_failures,
        }
