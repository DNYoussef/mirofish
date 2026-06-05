"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import json
import os
import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from ..config import Config


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0              # 总进度百分比 0-100
    message: str = ""              # 状态消息
    result: Optional[Dict] = None  # 任务结果
    error: Optional[str] = None    # 错误信息
    metadata: Dict = field(default_factory=dict)  # 额外元数据
    progress_detail: Dict = field(default_factory=dict)  # 详细进度信息
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从字典恢复任务对象。"""
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            status=TaskStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            progress=data.get("progress", 0),
            message=data.get("message", ""),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
            progress_detail=data.get("progress_detail", {}),
        )


class TaskManager:
    """
    任务管理器
    线程安全的任务状态管理
    """
    
    _instance = None
    _lock = threading.Lock()
    TASKS_DIR = Config.TASKS_DIR
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
                    cls._instance._ensure_tasks_dir()
        return cls._instance

    @classmethod
    def reset_for_tests(cls, tasks_dir: Optional[str] = None) -> None:
        """Reset singleton state and optionally point tests at an isolated task dir."""
        with cls._lock:
            if tasks_dir is not None:
                cls.TASKS_DIR = str(tasks_dir)
            cls._instance = None

    def _ensure_tasks_dir(self):
        os.makedirs(self.TASKS_DIR, exist_ok=True)

    def _task_path(self, task_id: str) -> str:
        if not task_id or "/" in task_id or "\\" in task_id or os.path.basename(task_id) != task_id:
            raise ValueError("Invalid task id")
        return os.path.join(self.TASKS_DIR, f"{task_id}.json")

    def _save_task(self, task: Task):
        self._ensure_tasks_dir()
        with open(self._task_path(task.task_id), "w", encoding="utf-8") as f:
            json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)

    def _load_task_from_disk(self, task_id: str) -> Optional[Task]:
        try:
            task_path = self._task_path(task_id)
        except ValueError:
            return None
        if not os.path.exists(task_path):
            return None

        with open(task_path, "r", encoding="utf-8") as f:
            task_data = json.load(f)
        return Task.from_dict(task_data)
    
    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        """
        创建新任务
        
        Args:
            task_type: 任务类型
            metadata: 额外元数据
            
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        now = datetime.now()
        
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {}
        )
        
        with self._task_lock:
            self._tasks[task_id] = task
            self._save_task(task)
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task is not None:
                return task

            task = self._load_task_from_disk(task_id)
            if task is not None:
                self._tasks[task_id] = task
            return task
    
    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None
    ):
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            progress: 进度
            message: 消息
            result: 结果
            error: 错误信息
            progress_detail: 详细进度信息
        """
        with self._task_lock:
            task = self._tasks.get(task_id) or self._load_task_from_disk(task_id)
            if task:
                task.updated_at = datetime.now()
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                if progress_detail is not None:
                    task.progress_detail = progress_detail
                self._tasks[task_id] = task
                self._save_task(task)
    
    def complete_task(self, task_id: str, result: Dict):
        """标记任务完成"""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="任务完成",
            result=result
        )
    
    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message="任务失败",
            error=error
        )
    
    def list_tasks(self, task_type: Optional[str] = None) -> list:
        """列出任务"""
        with self._task_lock:
            self._ensure_tasks_dir()
            tasks_by_id: Dict[str, Task] = dict(self._tasks)
            for file_name in os.listdir(self.TASKS_DIR):
                if not file_name.endswith(".json"):
                    continue
                try:
                    task = self._load_task_from_disk(file_name[:-5])
                except (json.JSONDecodeError, OSError, ValueError):
                    continue
                if task is not None:
                    tasks_by_id[task.task_id] = task
                    self._tasks[task.task_id] = task

            tasks = list(tasks_by_id.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]
                try:
                    os.remove(self._task_path(tid))
                except OSError:
                    pass

