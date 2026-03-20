from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TaskPipelineStepIn(BaseModel):
    app_id: str = Field(min_length=1, max_length=255)
    order: int = Field(default=1, ge=1, le=10000)
    enabled: bool = True


class TaskDefinitionIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    pipeline: List[TaskPipelineStepIn] = Field(min_length=1)
    cwd: Optional[str] = None
    enabled: bool = True
    timeout_sec: int = Field(default=0, ge=0, le=86400)
    max_retries: int = Field(default=0, ge=0, le=50)
    retry_delay_sec: int = Field(default=5, ge=0, le=3600)
    singleton: bool = True
    run_mode: str = Field(default="oneshot", pattern="^(oneshot|daemon)$")
    restart_policy: str = Field(default="on-failure", pattern="^(never|on-failure|always)$")
    max_stale_sec: int = Field(default=120, ge=10, le=3600)
    schedule_type: str = Field(default="none", pattern="^(none|daily)$")
    schedule_time: str = Field(default="00:00", pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    priority: int = Field(default=100, ge=1, le=1000)
    resource_group: Optional[str] = Field(default=None, max_length=64)


class TaskDefinitionOut(BaseModel):
    task_id: str
    name: str
    pipeline: List[TaskPipelineStepIn] = Field(default_factory=list)
    cwd: Optional[str] = None
    enabled: bool
    timeout_sec: int
    max_retries: int
    retry_delay_sec: int
    singleton: bool
    run_mode: str
    restart_policy: str
    max_stale_sec: int
    schedule_type: str
    schedule_time: str
    priority: int
    resource_group: Optional[str] = None


class TaskRunOut(BaseModel):
    run_id: str
    task_id: str
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    return_code: Optional[int] = None
    log_tail: List[str] = Field(default_factory=list)
    attempt: int
    max_retries: int
    trigger_type: str
    error_message: Optional[str] = None
    last_heartbeat_at: Optional[datetime] = None


class StartTaskIn(BaseModel):
    trigger_type: str = Field(default="manual", max_length=32)


class TaskEnabledIn(BaseModel):
    enabled: bool


class DomainAppOut(BaseModel):
    app_id: str
    app_name: str
    module: str
    cwd: str
    enabled: bool = True


class DomainAppUpdateIn(BaseModel):
    app_name: str = Field(min_length=1, max_length=255)
    enabled: bool = True


class RunLogsQueryIn(BaseModel):
    limit: int = Field(default=200, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)
