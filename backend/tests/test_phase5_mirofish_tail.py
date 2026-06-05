import importlib
import sys
import types
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def install_external_stubs(monkeypatch):
    zep_cloud_module = types.ModuleType("zep_cloud")
    zep_cloud_client_module = types.ModuleType("zep_cloud.client")

    class DummyZep:
        pass

    zep_cloud_module.InternalServerError = Exception
    zep_cloud_module.EpisodeData = object
    zep_cloud_module.EntityEdgeSourceTarget = object
    zep_cloud_client_module.Zep = DummyZep
    monkeypatch.setitem(sys.modules, "zep_cloud", zep_cloud_module)
    monkeypatch.setitem(sys.modules, "zep_cloud.client", zep_cloud_client_module)


class TestConfig:
    SECRET_KEY = "test-secret"
    DEBUG = False
    TESTING = False
    JSON_AS_ASCII = False
    DATA_ROOT = ""
    CORS_ORIGINS = ["https://allowed.example"]

    @classmethod
    def ensure_storage_dirs(cls):
        return None


def build_test_app(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)
    TestConfig.DATA_ROOT = str(tmp_path)

    import app as app_package

    importlib.reload(app_package)
    flask_app = app_package.create_app(TestConfig)
    monkeypatch.setenv("MIROFISH_API_KEY", "phase5-test-key")
    return flask_app


def test_splitter_rejects_non_progressing_chunk_overlap():
    from app.utils.file_parser import split_text_into_chunks

    with pytest.raises(ValueError, match="overlap must be less than chunk_size"):
        split_text_into_chunks("abcdef", chunk_size=3, overlap=3)

    assert split_text_into_chunks("abcdef", chunk_size=3, overlap=1) == ["abc", "cde", "ef"]


def test_graph_build_rejects_invalid_chunk_config_before_task_creation(monkeypatch, tmp_path):
    flask_app = build_test_app(monkeypatch, tmp_path)

    import app.api.graph as graph_api
    from app.models.project import ProjectManager, ProjectStatus
    from app.models.task import TaskManager

    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "dummy-zep-key", raising=False)
    monkeypatch.setattr(graph_api.Config, "LLM_RATE_LIMIT_DB", str(tmp_path / "rate.sqlite3"), raising=False)
    ProjectManager.reset_for_tests(tmp_path / "projects")
    TaskManager.reset_for_tests(tmp_path / "tasks")

    project = ProjectManager.create_project(name="phase5 graph")
    project.status = ProjectStatus.ONTOLOGY_GENERATED
    project.ontology = {"entity_types": [], "edge_types": []}
    ProjectManager.save_project(project)
    ProjectManager.save_extracted_text(project.project_id, "x" * 1000)

    response = flask_app.test_client().post(
        "/api/graph/build",
        headers={"X-API-Key": "phase5-test-key"},
        json={
            "project_id": project.project_id,
            "chunk_size": 10,
            "chunk_overlap": 10,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "chunk_overlap must be less than chunk_size"
    assert TaskManager().list_tasks() == []
    restored = ProjectManager.get_project(project.project_id)
    assert restored.graph_build_task_id is None
    assert restored.chunk_size == 500
    assert restored.chunk_overlap == 50


def test_manager_reset_hooks_provide_isolated_test_storage(tmp_path):
    from app.models.project import ProjectManager
    from app.models import task as task_manager_module

    first_tasks = tmp_path / "tasks-1"
    second_tasks = tmp_path / "tasks-2"
    task_manager_module.TaskManager.reset_for_tests(first_tasks)
    first_manager = task_manager_module.TaskManager()
    task_id = first_manager.create_task("phase5")

    task_manager_module.TaskManager.reset_for_tests(second_tasks)
    second_manager = task_manager_module.TaskManager()
    assert second_manager.get_task(task_id) is None
    assert second_manager.TASKS_DIR == str(second_tasks)

    first_projects = tmp_path / "projects-1"
    second_projects = tmp_path / "projects-2"
    ProjectManager.reset_for_tests(first_projects)
    project = ProjectManager.create_project(name="isolated")

    ProjectManager.reset_for_tests(second_projects)
    assert ProjectManager.get_project(project.project_id) is None
    assert ProjectManager.PROJECTS_DIR == str(second_projects)
