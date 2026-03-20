from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import List

from fastapi import Body, FastAPI, HTTPException, Request
from core.settings import load_env_files

from ..core.models import (
    TaskDefinition,
    TaskRestartPolicy,
    TaskRun,
    TaskRunMode,
    TaskScheduleType,
)
from ..core.service import SchedulerCenterService
from .schemas import (
    DomainAppOut,
    DomainAppUpdateIn,
    RunLogsQueryIn,
    StartTaskIn,
    TaskDefinitionIn,
    TaskDefinitionOut,
    TaskEnabledIn,
    TaskRunOut,
)

def _load_scheduler_env() -> None:
    """Load scheduler env files without overriding existing environment variables."""
    explicit = os.getenv("SCHEDULER_ENV_FILE", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(__file__).resolve().parents[1] / ".env")
    candidates.append(Path(__file__).resolve().parents[4] / ".env")
    candidates.append(Path.cwd() / ".env")
    load_env_files(candidates, override=False)


def _task_to_out(task: TaskDefinition) -> TaskDefinitionOut:
    return TaskDefinitionOut(
        task_id=task.task_id,
        name=task.name,
        pipeline=[dict(step) for step in (task.pipeline or [])],
        cwd=task.cwd,
        enabled=bool(task.enabled),
        timeout_sec=int(task.timeout_sec),
        max_retries=int(task.max_retries),
        retry_delay_sec=int(task.retry_delay_sec),
        singleton=bool(task.singleton),
        run_mode=task.run_mode.value,
        restart_policy=task.restart_policy.value,
        max_stale_sec=int(task.max_stale_sec),
        schedule_type=task.schedule_type.value,
        schedule_time=task.schedule_time,
        priority=int(task.priority),
        resource_group=task.resource_group,
    )


def _normalize_pipeline(payload_steps: list | None) -> list[dict]:
    steps = payload_steps or []
    sorted_steps = sorted(steps, key=lambda item: int(getattr(item, "order", 0) or 0))
    normalized = []
    for index, step in enumerate(sorted_steps, start=1):
        app_id = str(getattr(step, "app_id", "")).strip()
        if not app_id:
            continue
        enabled = bool(getattr(step, "enabled", True))
        normalized.append({"app_id": app_id, "order": index, "enabled": enabled})
    return normalized


def _validate_pipeline_and_get_resource_group(service: SchedulerCenterService, pipeline: list[dict]) -> str | None:
    active_steps = [step for step in sorted(pipeline, key=lambda item: int(item.get("order") or 0)) if bool(step.get("enabled", True))]
    if not active_steps:
        raise HTTPException(status_code=422, detail="Pipeline has no enabled steps")
    app_rows = service.store.list_apps()
    app_map = {str(row.get("app_id") or ""): str(row.get("module") or "") for row in app_rows}
    step_app_ids: list[str] = []
    for step in active_steps:
        app_id = str(step.get("app_id") or "")
        module = app_map.get(app_id, "").strip()
        if not module:
            raise HTTPException(status_code=422, detail=f"Invalid app_id in pipeline: {app_id}")
        step_app_ids.append(app_id)
    if len(step_app_ids) == 1:
        return step_app_ids[0]
    return None


def _run_to_out(run: TaskRun) -> TaskRunOut:
    return TaskRunOut(
        run_id=run.run_id,
        task_id=run.task_id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        started_at=run.started_at,
        ended_at=run.ended_at,
        return_code=run.return_code,
        log_tail=list(run.log_tail or []),
        attempt=int(run.attempt),
        max_retries=int(run.max_retries),
        trigger_type=run.trigger_type,
        error_message=run.error_message,
        last_heartbeat_at=run.last_heartbeat_at,
    )


def _scan_domain_apps() -> list[DomainAppOut]:
    root_override = os.getenv("SCHEDULER_WORKSPACE_ROOT", "").strip()
    workspace_root = Path(root_override) if root_override else Path(__file__).resolve().parents[4]
    domains_root = workspace_root / "domains"
    if not domains_root.exists():
        return []

    items: list[DomainAppOut] = []
    for py_file in sorted(domains_root.glob("*/flows/*.py")):
        if py_file.name.startswith("_"):
            continue
        relative = py_file.relative_to(workspace_root).as_posix()
        module = relative[:-3].replace("/", ".")
        app_id = uuid.uuid5(uuid.NAMESPACE_URL, module).hex
        app_name = py_file.stem
        items.append(
            DomainAppOut(
                app_id=app_id,
                app_name=app_name,
                module=module,
                cwd=".",
                enabled=True,
            )
        )
    return items


def create_app() -> FastAPI:
    _load_scheduler_env()
    app = FastAPI(title="Web Scheduler Center", version="0.1.0")
    service = SchedulerCenterService()

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/tasks", response_model=List[TaskDefinitionOut])
    def list_tasks() -> List[TaskDefinitionOut]:
        return [_task_to_out(task) for task in service.list_tasks()]

    @app.get("/apps", response_model=List[DomainAppOut])
    def list_apps() -> List[DomainAppOut]:
        auto_sync = os.getenv("SCHEDULER_APPS_AUTO_SYNC", "1").strip().lower() in {"1", "true", "yes", "on"}
        if auto_sync:
            scanned = _scan_domain_apps()
            service.store.upsert_apps(
                [
                    {
                        "app_id": item.app_id,
                        "app_name": item.app_name,
                        "module": item.module,
                        "cwd": item.cwd,
                        "enabled": item.enabled,
                    }
                    for item in scanned
                ]
            )
        rows = service.store.list_apps()
        if not rows:
            # Fallback for first bootstrap when table is empty and auto sync is disabled.
            return _scan_domain_apps()
        return [
            DomainAppOut(
                app_id=str(row.get("app_id") or ""),
                app_name=str(row.get("app_name") or ""),
                module=str(row.get("module") or ""),
                cwd=str(row.get("cwd") or "."),
                enabled=bool(row.get("enabled", 1)),
            )
            for row in rows
        ]

    @app.patch("/apps/{app_id}", response_model=DomainAppOut)
    def update_app(app_id: str, payload: DomainAppUpdateIn) -> DomainAppOut:
        updated = service.store.update_app(
            app_id=app_id,
            app_name=payload.app_name.strip(),
            enabled=payload.enabled,
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"App not found: {app_id}")
        return DomainAppOut(
            app_id=str(updated.get("app_id") or ""),
            app_name=str(updated.get("app_name") or ""),
            module=str(updated.get("module") or ""),
            cwd=str(updated.get("cwd") or "."),
            enabled=bool(updated.get("enabled", 1)),
        )

    @app.post("/tasks", response_model=TaskDefinitionOut)
    def upsert_task(payload: TaskDefinitionIn) -> TaskDefinitionOut:
        try:
            run_mode = TaskRunMode(payload.run_mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid run_mode: {payload.run_mode}") from exc
        try:
            restart_policy = TaskRestartPolicy(payload.restart_policy)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid restart_policy: {payload.restart_policy}") from exc
        try:
            schedule_type = TaskScheduleType(payload.schedule_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid schedule_type: {payload.schedule_type}") from exc
        pipeline = _normalize_pipeline(payload.pipeline)
        resource_group = _validate_pipeline_and_get_resource_group(service, pipeline)
        task_id = uuid.uuid4().hex
        task = TaskDefinition(
            task_id=task_id,
            name=payload.name.strip(),
            pipeline=pipeline,
            cwd=payload.cwd,
            enabled=payload.enabled,
            timeout_sec=payload.timeout_sec,
            max_retries=payload.max_retries,
            retry_delay_sec=payload.retry_delay_sec,
            singleton=payload.singleton,
            run_mode=run_mode,
            restart_policy=restart_policy,
            max_stale_sec=payload.max_stale_sec,
            schedule_type=schedule_type,
            schedule_time=payload.schedule_time,
            priority=payload.priority,
            resource_group=resource_group,
        )
        service.register_task(task)
        return _task_to_out(task)

    @app.put("/tasks/{task_id}", response_model=TaskDefinitionOut)
    def update_task(task_id: str, payload: TaskDefinitionIn) -> TaskDefinitionOut:
        try:
            old = service.registry.get(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            run_mode = TaskRunMode(payload.run_mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid run_mode: {payload.run_mode}") from exc
        try:
            restart_policy = TaskRestartPolicy(payload.restart_policy)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid restart_policy: {payload.restart_policy}") from exc
        try:
            schedule_type = TaskScheduleType(payload.schedule_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid schedule_type: {payload.schedule_type}") from exc
        pipeline = _normalize_pipeline(payload.pipeline)
        resource_group = _validate_pipeline_and_get_resource_group(service, pipeline)
        task = TaskDefinition(
            task_id=task_id,
            name=payload.name.strip(),
            pipeline=pipeline,
            cwd=payload.cwd,
            enabled=payload.enabled,
            timeout_sec=payload.timeout_sec,
            max_retries=payload.max_retries,
            retry_delay_sec=payload.retry_delay_sec,
            singleton=payload.singleton,
            run_mode=run_mode,
            restart_policy=restart_policy,
            max_stale_sec=payload.max_stale_sec,
            schedule_type=schedule_type,
            schedule_time=payload.schedule_time,
            priority=payload.priority,
            resource_group=resource_group,
        )
        if old.task_id != task.task_id:
            raise HTTPException(status_code=400, detail="Task ID mismatch")
        service.update_task(task)
        return _task_to_out(task)

    @app.delete("/tasks/{task_id}")
    def delete_task(task_id: str) -> dict:
        try:
            _ = service.registry.get(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        service.remove_task(task_id)
        return {"ok": True, "task_id": task_id}

    @app.patch("/tasks/{task_id}/enabled", response_model=TaskDefinitionOut)
    def set_task_enabled(task_id: str, payload: TaskEnabledIn) -> TaskDefinitionOut:
        try:
            task = service.set_task_enabled(task_id, payload.enabled)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _task_to_out(task)

    @app.post("/tasks/{task_id}/start", response_model=TaskRunOut)
    def start_task(task_id: str, payload: StartTaskIn = Body(default_factory=StartTaskIn)) -> TaskRunOut:
        try:
            run = service.start_task(task_id, trigger_type=payload.trigger_type)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _run_to_out(run)

    @app.post("/runs/{run_id}/stop")
    def stop_run(run_id: str) -> dict:
        service.stop_run(run_id)
        return {"ok": True, "run_id": run_id}

    @app.get("/runs", response_model=List[TaskRunOut])
    def list_runs() -> List[TaskRunOut]:
        return [_run_to_out(run) for run in service.list_runs()]

    @app.get("/runs/{run_id}", response_model=TaskRunOut)
    def get_run(run_id: str) -> TaskRunOut:
        run = service.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return _run_to_out(run)

    @app.post("/runs/{run_id}/logs/query")
    def query_run_logs(run_id: str, payload: RunLogsQueryIn = Body(default_factory=RunLogsQueryIn)) -> dict:
        logs = service.store.list_run_logs(run_id, limit=payload.limit, offset=payload.offset)
        return {"run_id": run_id, "count": len(logs), "items": logs}

    @app.get("/stats")
    def stats() -> dict:
        return service.stats()

    @app.post("/integrations/dingtalk/callback")
    async def dingtalk_callback(
        request: Request,
        payload: dict = Body(default={}),
    ) -> dict:
        try:
            from core.integrations.dingtalk_client import record_command_from_callback
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"dingtalk client unavailable: {exc}") from exc

        command_key = (request.query_params.get("command_key") or "xiyou_login").strip() or "xiyou_login"
        accepted = record_command_from_callback(
            payload if isinstance(payload, dict) else {},
            command_key=command_key,
            keywords=["已登录"],
        )
        return {"ok": True, "accepted": bool(accepted), "command_key": command_key}

    @app.post("/integrations/dingtalk/commands/consume")
    async def consume_dingtalk_command(payload: dict = Body(default={})) -> dict:
        try:
            from core.integrations.dingtalk_client import consume_command
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"dingtalk client unavailable: {exc}") from exc

        command_key = str((payload or {}).get("command_key") or "xiyou_login").strip() or "xiyou_login"
        since_ts_raw = (payload or {}).get("since_ts")
        since_ts = None
        if since_ts_raw is not None:
            try:
                since_ts = float(since_ts_raw)
            except (TypeError, ValueError):
                since_ts = None
        matched = consume_command(command_key=command_key, keywords=["已登录"], since_ts=since_ts)
        return {"ok": True, "matched": bool(matched), "command": matched}

    return app


app = create_app()
