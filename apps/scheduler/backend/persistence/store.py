from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Iterable, List, Optional

import pymysql
from core.data.client import execute, fetch_all

from ..core.models import (
    TaskScheduleType,
    TaskDefinition,
    TaskRestartPolicy,
    TaskRun,
    TaskRunMode,
    TaskStatus,
)


_RUNNING_STATUSES = {TaskStatus.running.value, TaskStatus.queued.value}


class SchedulerStore:
    def __init__(self, *, auto_init_schema: bool = True) -> None:
        if auto_init_schema:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        execute(
            """
            CREATE TABLE IF NOT EXISTS dim_auto_scheduler_app (
                app_id VARCHAR(255) PRIMARY KEY,
                app_name VARCHAR(255) NOT NULL,
                module VARCHAR(255) NOT NULL,
                cwd TEXT NOT NULL,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                createtime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updatetime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )
        self._dedupe_apps_by_module()
        self._normalize_apps_uuid_ids()
        execute(
            """
            CREATE TABLE IF NOT EXISTS dim_auto_scheduler_task (
                task_id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                pipeline_json LONGTEXT NULL,
                cwd TEXT NULL,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                timeout_sec INT NOT NULL DEFAULT 0,
                max_retries INT NOT NULL DEFAULT 0,
                retry_delay_sec INT NOT NULL DEFAULT 5,
                singleton_task TINYINT(1) NOT NULL DEFAULT 1,
                run_mode VARCHAR(16) NOT NULL DEFAULT 'oneshot',
                restart_policy VARCHAR(16) NOT NULL DEFAULT 'on-failure',
                max_stale_sec INT NOT NULL DEFAULT 120,
                schedule_type VARCHAR(16) NOT NULL DEFAULT 'none',
                schedule_time VARCHAR(5) NOT NULL DEFAULT '00:00',
                priority INT NOT NULL DEFAULT 100,
                resource_group VARCHAR(64) NULL,
                createtime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updatetime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_legacy_command_json_nullable()
        self._ensure_task_schedule_columns()
        execute(
            """
            CREATE TABLE IF NOT EXISTS fact_auto_scheduler_run (
                run_id VARCHAR(32) PRIMARY KEY,
                task_id VARCHAR(64) NOT NULL,
                status VARCHAR(16) NOT NULL,
                attempt INT NOT NULL DEFAULT 1,
                max_retries INT NOT NULL DEFAULT 0,
                trigger_type VARCHAR(32) NOT NULL DEFAULT 'manual',
                started_at DATETIME NULL,
                ended_at DATETIME NULL,
                return_code INT NULL,
                error_message TEXT NULL,
                last_heartbeat_at DATETIME NULL,
                createtime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updatetime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_web_scheduler_run_task_status (task_id, status),
                INDEX idx_web_scheduler_run_started_at (started_at)
            )
            """
        )
        execute(
            """
            CREATE TABLE IF NOT EXISTS fact_auto_scheduler_log (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                run_id VARCHAR(32) NOT NULL,
                ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                line LONGTEXT NOT NULL,
                UNIQUE KEY uk_auto_scheduler_log_run_id (run_id),
                INDEX idx_web_scheduler_log_run_id (run_id)
            )
            """
        )
        self._migrate_logs_to_single_row_per_run()

    def _ensure_legacy_command_json_nullable(self) -> None:
        rows = fetch_all(
            """
            SELECT COUNT(*) AS c
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'dim_auto_scheduler_task'
              AND column_name = 'command_json'
            """
        )
        exists = int((rows[0] or {}).get("c") or 0) > 0 if rows else False
        if not exists:
            return
        execute("ALTER TABLE dim_auto_scheduler_task MODIFY COLUMN command_json TEXT NULL")

    def _ensure_task_schedule_columns(self) -> None:
        expected_columns = {
            "run_mode": "ALTER TABLE dim_auto_scheduler_task ADD COLUMN run_mode VARCHAR(16) NOT NULL DEFAULT 'oneshot' AFTER singleton_task",
            "restart_policy": "ALTER TABLE dim_auto_scheduler_task ADD COLUMN restart_policy VARCHAR(16) NOT NULL DEFAULT 'on-failure' AFTER run_mode",
            "max_stale_sec": "ALTER TABLE dim_auto_scheduler_task ADD COLUMN max_stale_sec INT NOT NULL DEFAULT 120 AFTER restart_policy",
            "schedule_type": "ALTER TABLE dim_auto_scheduler_task ADD COLUMN schedule_type VARCHAR(16) NOT NULL DEFAULT 'none' AFTER max_stale_sec",
            "schedule_time": "ALTER TABLE dim_auto_scheduler_task ADD COLUMN schedule_time VARCHAR(5) NOT NULL DEFAULT '00:00' AFTER schedule_type",
            "priority": "ALTER TABLE dim_auto_scheduler_task ADD COLUMN priority INT NOT NULL DEFAULT 100 AFTER schedule_time",
            "resource_group": "ALTER TABLE dim_auto_scheduler_task ADD COLUMN resource_group VARCHAR(64) NULL AFTER priority",
        }
        rows = fetch_all(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'dim_auto_scheduler_task'
            """
        )
        existing = {str(row.get("column_name") or "").strip() for row in rows}
        for column_name, ddl in expected_columns.items():
            if column_name in existing:
                continue
            try:
                execute(ddl)
            except pymysql.err.OperationalError as exc:
                if int(getattr(exc, "args", [None])[0] or 0) == 1060:
                    continue
                raise

    def _migrate_logs_to_single_row_per_run(self) -> None:
        execute("ALTER TABLE fact_auto_scheduler_log MODIFY COLUMN line LONGTEXT NOT NULL")
        dup_runs = fetch_all(
            """
            SELECT run_id
            FROM fact_auto_scheduler_log
            GROUP BY run_id
            HAVING COUNT(*) > 1
            """
        )
        for item in dup_runs:
            run_id = str(item.get("run_id") or "").strip()
            if not run_id:
                continue
            rows = fetch_all(
                """
                SELECT id, line
                FROM fact_auto_scheduler_log
                WHERE run_id = %s
                ORDER BY id ASC
                """,
                (run_id,),
            )
            if not rows:
                continue
            keep_id = int(rows[0].get("id") or 0)
            if keep_id <= 0:
                continue
            merged = "\n".join(str(row.get("line") or "").rstrip("\n") for row in rows if str(row.get("line") or "").strip())
            execute(
                """
                UPDATE fact_auto_scheduler_log
                SET line = %s, ts = NOW()
                WHERE id = %s
                """,
                (merged, keep_id),
            )
            execute(
                """
                DELETE FROM fact_auto_scheduler_log
                WHERE run_id = %s AND id <> %s
                """,
                (run_id, keep_id),
            )
        unique_idx = fetch_all(
            """
            SELECT COUNT(*) AS c
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'fact_auto_scheduler_log'
              AND index_name = 'uk_auto_scheduler_log_run_id'
            """
        )
        has_unique = int((unique_idx[0] or {}).get("c") or 0) > 0 if unique_idx else False
        if not has_unique:
            execute("ALTER TABLE fact_auto_scheduler_log ADD UNIQUE KEY uk_auto_scheduler_log_run_id (run_id)")

    @staticmethod
    def _module_to_uuid(module: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, module).hex

    def _dedupe_apps_by_module(self) -> None:
        dup_modules = fetch_all(
            """
            SELECT module
            FROM dim_auto_scheduler_app
            GROUP BY module
            HAVING COUNT(*) > 1
            """
        )
        for item in dup_modules:
            module = str(item.get("module") or "").strip()
            if not module:
                continue
            rows = fetch_all(
                """
                SELECT app_id
                FROM dim_auto_scheduler_app
                WHERE module = %s
                ORDER BY updatetime DESC, createtime DESC, app_id ASC
                """,
                (module,),
            )
            keep = str(rows[0].get("app_id") or "") if rows else ""
            for row in rows[1:]:
                app_id = str(row.get("app_id") or "")
                if app_id and app_id != keep:
                    execute("DELETE FROM dim_auto_scheduler_app WHERE app_id = %s", (app_id,))

    def _normalize_apps_uuid_ids(self) -> None:
        rows = fetch_all("SELECT app_id, module FROM dim_auto_scheduler_app")
        for row in rows:
            module = str(row.get("module") or "").strip()
            old_app_id = str(row.get("app_id") or "").strip()
            if not module:
                continue
            target_app_id = self._module_to_uuid(module)
            if old_app_id == target_app_id:
                continue
            execute(
                "UPDATE dim_auto_scheduler_app SET app_id = %s WHERE app_id = %s",
                (target_app_id, old_app_id),
            )

    def upsert_apps(self, apps: Iterable[dict]) -> None:
        for app in apps:
            module = str(app.get("module") or "").strip()
            if not module:
                continue
            app_name = str(app.get("app_name") or module).strip() or module
            cwd = str(app.get("cwd") or ".").strip() or "."
            target_app_id = self._module_to_uuid(module)
            exists = fetch_all(
                """
                SELECT app_id
                FROM dim_auto_scheduler_app
                WHERE module = %s
                LIMIT 1
                """,
                (module,),
            )
            if exists:
                execute(
                    """
                    UPDATE dim_auto_scheduler_app
                    SET app_id = %s, cwd = %s
                    WHERE module = %s
                    """,
                    (target_app_id, cwd, module),
                )
                continue
            execute(
                """
                INSERT INTO dim_auto_scheduler_app (app_id, app_name, module, cwd)
                VALUES (%s, %s, %s, %s)
                """,
                (target_app_id, app_name, module, cwd),
            )

    def list_apps(self) -> List[dict]:
        rows = fetch_all(
            """
            SELECT app_id, app_name, module, cwd, enabled
            FROM dim_auto_scheduler_app
            ORDER BY app_name ASC, app_id ASC
            """
        )
        return rows

    def update_app(self, app_id: str, *, app_name: str, enabled: bool) -> Optional[dict]:
        execute(
            """
            UPDATE dim_auto_scheduler_app
            SET app_name = %s, enabled = %s
            WHERE app_id = %s
            """,
            (app_name, 1 if enabled else 0, app_id),
        )
        rows = fetch_all(
            """
            SELECT app_id, app_name, module, cwd, enabled
            FROM dim_auto_scheduler_app
            WHERE app_id = %s
            LIMIT 1
            """,
            (app_id,),
        )
        return rows[0] if rows else None

    def upsert_task(self, task: TaskDefinition) -> None:
        execute(
            """
            INSERT INTO dim_auto_scheduler_task (
                task_id, name, pipeline_json, cwd, enabled, timeout_sec, max_retries, retry_delay_sec, singleton_task,
                run_mode, restart_policy, max_stale_sec, schedule_type, schedule_time, priority, resource_group
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                pipeline_json = VALUES(pipeline_json),
                cwd = VALUES(cwd),
                enabled = VALUES(enabled),
                timeout_sec = VALUES(timeout_sec),
                max_retries = VALUES(max_retries),
                retry_delay_sec = VALUES(retry_delay_sec),
                singleton_task = VALUES(singleton_task),
                run_mode = VALUES(run_mode),
                restart_policy = VALUES(restart_policy),
                max_stale_sec = VALUES(max_stale_sec),
                schedule_type = VALUES(schedule_type),
                schedule_time = VALUES(schedule_time),
                priority = VALUES(priority),
                resource_group = VALUES(resource_group)
            """,
            (
                task.task_id,
                task.name,
                json.dumps(task.pipeline or [], ensure_ascii=False),
                task.cwd,
                1 if task.enabled else 0,
                int(task.timeout_sec),
                int(task.max_retries),
                int(task.retry_delay_sec),
                1 if task.singleton else 0,
                task.run_mode.value,
                task.restart_policy.value,
                int(task.max_stale_sec),
                task.schedule_type.value,
                task.schedule_time,
                int(task.priority),
                task.resource_group,
            ),
        )

    def list_tasks(self) -> List[TaskDefinition]:
        rows = fetch_all(
            """
            SELECT task_id, name, pipeline_json, cwd, enabled, timeout_sec, max_retries, retry_delay_sec, singleton_task,
                   run_mode, restart_policy, max_stale_sec, schedule_type, schedule_time, priority, resource_group
            FROM dim_auto_scheduler_task
            ORDER BY task_id
            """
        )
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: str) -> Optional[TaskDefinition]:
        rows = fetch_all(
            """
            SELECT task_id, name, pipeline_json, cwd, enabled, timeout_sec, max_retries, retry_delay_sec, singleton_task,
                   run_mode, restart_policy, max_stale_sec, schedule_type, schedule_time, priority, resource_group
            FROM dim_auto_scheduler_task
            WHERE task_id = %s
            LIMIT 1
            """,
            (task_id,),
        )
        if not rows:
            return None
        return self._task_from_row(rows[0])

    def remove_task(self, task_id: str) -> None:
        execute(
            """
            DELETE l
            FROM fact_auto_scheduler_log l
            INNER JOIN fact_auto_scheduler_run r ON r.run_id = l.run_id
            WHERE r.task_id = %s
            """,
            (task_id,),
        )
        execute("DELETE FROM fact_auto_scheduler_run WHERE task_id = %s", (task_id,))
        execute("DELETE FROM dim_auto_scheduler_task WHERE task_id = %s", (task_id,))

    def has_running_task(self, task_id: str, *, max_stale_sec: int = 120) -> bool:
        rows = fetch_all(
            """
            SELECT run_id
            FROM fact_auto_scheduler_run
            WHERE task_id = %s
              AND status IN (%s, %s)
              AND (
                    last_heartbeat_at IS NULL
                    OR last_heartbeat_at >= DATE_SUB(NOW(), INTERVAL %s SECOND)
                  )
            LIMIT 1
            """,
            (task_id, TaskStatus.running.value, TaskStatus.queued.value, max(10, int(max_stale_sec))),
        )
        return bool(rows)

    def finalize_stale_runs(self, *, max_stale_sec: int = 120) -> int:
        stale_sec = max(10, int(max_stale_sec))
        sql = """
        UPDATE fact_auto_scheduler_run
        SET
            status = %s,
            error_message = CASE
                WHEN error_message IS NULL OR error_message = ''
                    THEN %s
                ELSE error_message
            END,
            ended_at = COALESCE(ended_at, NOW()),
            last_heartbeat_at = NOW()
        WHERE status IN (%s, %s)
          AND (
                last_heartbeat_at IS NULL
                OR last_heartbeat_at < DATE_SUB(NOW(), INTERVAL %s SECOND)
              )
        """
        return int(
            execute(
                sql,
                (
                    TaskStatus.failed.value,
                    f"Recovered stale run as failed after heartbeat timeout ({stale_sec}s)",
                    TaskStatus.running.value,
                    TaskStatus.queued.value,
                    stale_sec,
                ),
            )
            or 0
        )

    def create_run(self, run: TaskRun) -> None:
        execute(
            """
            INSERT INTO fact_auto_scheduler_run (
                run_id, task_id, status, attempt, max_retries, trigger_type, started_at, ended_at, return_code, error_message, last_heartbeat_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run.run_id,
                run.task_id,
                run.status.value if isinstance(run.status, TaskStatus) else str(run.status),
                int(run.attempt),
                int(run.max_retries),
                run.trigger_type,
                run.started_at,
                run.ended_at,
                run.return_code,
                run.error_message,
                run.last_heartbeat_at,
            ),
        )

    def update_run(self, run: TaskRun) -> None:
        execute(
            """
            UPDATE fact_auto_scheduler_run
            SET
                status = %s,
                attempt = %s,
                max_retries = %s,
                trigger_type = %s,
                started_at = %s,
                ended_at = %s,
                return_code = %s,
                error_message = %s,
                last_heartbeat_at = %s
            WHERE run_id = %s
            """,
            (
                run.status.value if isinstance(run.status, TaskStatus) else str(run.status),
                int(run.attempt),
                int(run.max_retries),
                run.trigger_type,
                run.started_at,
                run.ended_at,
                run.return_code,
                run.error_message,
                run.last_heartbeat_at,
                run.run_id,
            ),
        )

    def append_logs(self, run_id: str, lines: Iterable[str]) -> None:
        chunks: list[str] = []
        for line in lines:
            text = str(line or "").rstrip("\n")
            if not text:
                continue
            chunks.append(text)
        if not chunks:
            return
        joined = "\n".join(chunks)
        now = datetime.now()
        execute(
            """
            INSERT INTO fact_auto_scheduler_log (run_id, ts, line)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                ts = VALUES(ts),
                line = CASE
                    WHEN line IS NULL OR line = '' THEN VALUES(line)
                    ELSE CONCAT(line, '\n', VALUES(line))
                END
            """,
            (run_id, now, joined),
        )

    def list_run_logs(self, run_id: str, *, limit: int = 200, offset: int = 0) -> List[dict]:
        rows = fetch_all(
            """
            SELECT id, run_id, ts, line
            FROM fact_auto_scheduler_log
            WHERE run_id = %s
            LIMIT 1
            """,
            (run_id,),
        )
        if not rows:
            return []
        row = rows[0]
        blob = str(row.get("line") or "")
        if not blob:
            return []
        all_lines = [item for item in blob.splitlines() if item.strip()]
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        sliced = all_lines[start:end]
        return [
            {"id": idx + 1, "run_id": run_id, "ts": row.get("ts"), "line": text}
            for idx, text in enumerate(sliced, start=start)
        ]

    def get_run(self, run_id: str, *, with_log_tail: int = 200) -> Optional[TaskRun]:
        rows = fetch_all(
            """
            SELECT run_id, task_id, status, attempt, max_retries, trigger_type, started_at, ended_at, return_code, error_message, last_heartbeat_at
            FROM fact_auto_scheduler_run
            WHERE run_id = %s
            LIMIT 1
            """,
            (run_id,),
        )
        if not rows:
            return None
        run = self._run_from_row(rows[0])
        if with_log_tail > 0:
            logs = fetch_all(
                """
                SELECT line
                FROM fact_auto_scheduler_log
                WHERE run_id = %s
                LIMIT 1
                """,
                (run_id,),
            )
            blob = str((logs[0] or {}).get("line") or "").strip() if logs else ""
            lines = [item for item in blob.splitlines() if item.strip()]
            run.log_tail = lines[-int(with_log_tail) :] if with_log_tail > 0 else lines
        return run

    def list_runs(self, *, limit: int = 200, with_log_tail: int = 0) -> List[TaskRun]:
        rows = fetch_all(
            """
            SELECT run_id, task_id, status, attempt, max_retries, trigger_type, started_at, ended_at, return_code, error_message, last_heartbeat_at
            FROM fact_auto_scheduler_run
            ORDER BY started_at DESC, createtime DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        runs = [self._run_from_row(row) for row in rows]
        if with_log_tail <= 0:
            return runs
        for run in runs:
            loaded = self.get_run(run.run_id, with_log_tail=with_log_tail)
            if loaded:
                run.log_tail = loaded.log_tail
        return runs

    @staticmethod
    def _task_from_row(row: dict) -> TaskDefinition:
        pipeline_json = row.get("pipeline_json") or "[]"
        try:
            pipeline = json.loads(pipeline_json)
        except Exception:
            pipeline = []
        if not isinstance(pipeline, list):
            pipeline = []
        return TaskDefinition(
            task_id=str(row.get("task_id") or "").strip(),
            name=str(row.get("name") or "").strip(),
            pipeline=[item for item in pipeline if isinstance(item, dict)],
            cwd=row.get("cwd"),
            enabled=bool(row.get("enabled")),
            timeout_sec=max(0, int(row.get("timeout_sec") or 0)),
            max_retries=max(0, int(row.get("max_retries") or 0)),
            retry_delay_sec=max(0, int(row.get("retry_delay_sec") or 5)),
            singleton=bool(row.get("singleton_task")),
            run_mode=TaskRunMode(str(row.get("run_mode") or TaskRunMode.oneshot.value)),
            restart_policy=TaskRestartPolicy(str(row.get("restart_policy") or TaskRestartPolicy.on_failure.value)),
            max_stale_sec=max(10, int(row.get("max_stale_sec") or 120)),
            schedule_type=TaskScheduleType(str(row.get("schedule_type") or TaskScheduleType.none.value)),
            schedule_time=str(row.get("schedule_time") or "00:00"),
            priority=max(1, int(row.get("priority") or 100)),
            resource_group=str(row.get("resource_group") or "").strip() or None,
        )

    @staticmethod
    def _run_from_row(row: dict) -> TaskRun:
        raw_status = str(row.get("status") or TaskStatus.idle.value)
        try:
            status = TaskStatus(raw_status)
        except ValueError:
            status = TaskStatus.failed if raw_status not in _RUNNING_STATUSES else TaskStatus.running
        return TaskRun(
            run_id=str(row.get("run_id") or "").strip(),
            task_id=str(row.get("task_id") or "").strip(),
            status=status,
            started_at=row.get("started_at"),
            ended_at=row.get("ended_at"),
            return_code=row.get("return_code"),
            attempt=max(1, int(row.get("attempt") or 1)),
            max_retries=max(0, int(row.get("max_retries") or 0)),
            trigger_type=str(row.get("trigger_type") or "manual"),
            error_message=row.get("error_message"),
            last_heartbeat_at=row.get("last_heartbeat_at"),
        )
