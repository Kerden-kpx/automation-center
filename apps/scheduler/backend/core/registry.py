from __future__ import annotations

from typing import Dict, List

from .models import TaskDefinition
from ..persistence.store import SchedulerStore


class TaskRegistry:
    def __init__(self, store: SchedulerStore) -> None:
        self._store = store
        self._tasks: Dict[str, TaskDefinition] = {}
        self._reload_cache()

    def _reload_cache(self) -> None:
        self._tasks = {task.task_id: task for task in self._store.list_tasks()}

    def register(self, task: TaskDefinition) -> None:
        self._store.upsert_task(task)
        self._tasks[task.task_id] = task

    def get(self, task_id: str) -> TaskDefinition:
        task = self._tasks.get(task_id)
        if task is None:
            task = self._store.get_task(task_id)
            if task is not None:
                self._tasks[task.task_id] = task
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        return task

    def list(self) -> List[TaskDefinition]:
        self._reload_cache()
        return list(self._tasks.values())

    def remove(self, task_id: str) -> None:
        self._store.remove_task(task_id)
        self._tasks.pop(task_id, None)
