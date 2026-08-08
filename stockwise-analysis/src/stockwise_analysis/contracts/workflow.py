"""动态工作流契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TaskStatus = Literal["PENDING", "RUNNING", "COMPLETED", "SKIPPED", "FAILED"]


class TaskSpec(BaseModel):
    """Query Graph 生成的单个动态任务及其依赖关系。"""

    task_id: str
    task_type: str
    depends_on: list[str] = Field(default_factory=list)
    status: TaskStatus = "PENDING"
    input_ref: list[str] = Field(default_factory=list)
    output_ref: list[str] = Field(default_factory=list)
    optional: bool = False


class WorkflowPlan(BaseModel):
    """可序列化、可 Checkpoint 的动态任务计划。"""

    plan_id: str
    analysis_type: str = "market_snapshot"
    tasks: list[TaskSpec] = Field(default_factory=list)
    current_task_id: str | None = None
    revision: int = 0

    def next_pending(self) -> TaskSpec | None:
        """返回依赖全部完成的下一个待执行任务。"""
        completed = {task.task_id for task in self.tasks if task.status == "COMPLETED"}
        for task in self.tasks:
            if task.status != "PENDING":
                continue
            if all(dependency in completed for dependency in task.depends_on):
                return task
        return None

    def mark(self, task_id: str, status: TaskStatus) -> "WorkflowPlan":
        """以不可变方式更新任务状态，避免并行节点修改共享对象。"""
        tasks = [
            task.model_copy(update={"status": status}) if task.task_id == task_id else task
            for task in self.tasks
        ]
        return self.model_copy(
            update={"tasks": tasks, "current_task_id": task_id, "revision": self.revision + 1}
        )
