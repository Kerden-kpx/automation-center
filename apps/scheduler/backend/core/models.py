from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class TaskStatus(str, Enum):
    idle = "idle"
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    stopped = "stopped"


class TaskRunMode(str, Enum):
    oneshot = "oneshot"
    daemon = "daemon"


class TaskRestartPolicy(str, Enum):
    never = "never"
    on_failure = "on-failure"
    always = "always"


class TaskScheduleType(str, Enum):
    none = "none"
    daily = "daily"


@dataclass
class TaskDefinition:
    task_id: str
    name: str
    pipeline: List[dict] = field(default_factory=list)
    cwd: Optional[str] = None
    enabled: bool = True
    timeout_sec: int = 0
    max_retries: int = 0
    retry_delay_sec: int = 5
    singleton: bool = True
    run_mode: TaskRunMode = TaskRunMode.oneshot
    restart_policy: TaskRestartPolicy = TaskRestartPolicy.on_failure
    max_stale_sec: int = 120
    schedule_type: TaskScheduleType = TaskScheduleType.none
    schedule_time: str = "00:00"
    priority: int = 100
    resource_group: Optional[str] = None


@dataclass
class TaskRun:
    run_id: str
    task_id: str
    status: TaskStatus = TaskStatus.idle
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    return_code: Optional[int] = None
    log_tail: List[str] = field(default_factory=list)
    attempt: int = 1
    max_retries: int = 0
    trigger_type: str = "manual"
    error_message: Optional[str] = None
    last_heartbeat_at: Optional[datetime] = None
