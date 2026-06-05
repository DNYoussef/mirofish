import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def reset_task_manager(task_manager_module, tmp_path):
    task_manager_module.TaskManager.reset_for_tests(tmp_path)
    return task_manager_module.TaskManager()


def test_task_manager_persists_tasks(monkeypatch, tmp_path):
    from app.models import task as task_manager_module

    manager = reset_task_manager(task_manager_module, tmp_path)
    task_id = manager.create_task("build-graph", {"project_id": "project-1"})
    manager.update_task(task_id, progress=75, message="almost done")

    task_manager_module.TaskManager.reset_for_tests()
    restored = task_manager_module.TaskManager()

    task = restored.get_task(task_id)

    assert task is not None
    assert task.task_id == task_id
    assert task.progress == 75
    assert task.message == "almost done"
    assert task.metadata == {"project_id": "project-1"}


def test_task_manager_rejects_path_traversal_ids(tmp_path):
    from app.models import task as task_manager_module

    manager = reset_task_manager(task_manager_module, tmp_path)

    assert manager.get_task("../outside") is None
    assert manager.get_task("..\\outside") is None
