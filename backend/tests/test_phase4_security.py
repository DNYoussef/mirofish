import importlib
import json
import sys
import types
from pathlib import Path


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
    monkeypatch.setenv("MIROFISH_API_KEY", "phase4-test-key")
    return flask_app


def assert_no_traceback_leak(response):
    body = response.get_data(as_text=True)
    assert "traceback" not in body.lower()
    assert "Traceback (most recent call last)" not in body
    assert "File " not in body


def test_caught_simulation_errors_do_not_return_tracebacks(monkeypatch, tmp_path):
    flask_app = build_test_app(monkeypatch, tmp_path)

    import app.api.simulation as simulation_api

    def fail_project_lookup(project_id):
        raise RuntimeError("phase4 simulated lookup failure")

    monkeypatch.setattr(simulation_api.ProjectManager, "get_project", staticmethod(fail_project_lookup))

    response = flask_app.test_client().post(
        "/api/simulation/create",
        headers={"X-API-Key": "phase4-test-key"},
        json={"project_id": "project-1"},
    )

    assert response.status_code == 500
    assert response.get_json()["error"] == "phase4 simulated lookup failure"
    assert_no_traceback_leak(response)


def test_uncaught_api_errors_fail_closed_without_stack_body(monkeypatch, tmp_path):
    flask_app = build_test_app(monkeypatch, tmp_path)

    @flask_app.route("/api/phase4-boom")
    def phase4_boom():
        raise RuntimeError("phase4 stack sentinel should not be exposed")

    response = flask_app.test_client().get(
        "/api/phase4-boom",
        headers={"X-API-Key": "phase4-test-key"},
    )

    assert response.status_code == 500
    assert response.get_json() == {"success": False, "error": "Internal server error"}
    assert "phase4 stack sentinel" not in response.get_data(as_text=True)
    assert_no_traceback_leak(response)


def test_llm_graph_endpoints_are_rate_limited_before_expensive_work(monkeypatch, tmp_path):
    flask_app = build_test_app(monkeypatch, tmp_path)

    import app.api.graph as graph_api

    monkeypatch.setattr(graph_api.Config, "LLM_RATE_LIMIT_DB", str(tmp_path / "llm-rate.sqlite3"), raising=False)
    monkeypatch.setattr(graph_api.Config, "LLM_RATE_LIMIT_REQUESTS", 1, raising=False)
    monkeypatch.setattr(graph_api.Config, "LLM_RATE_LIMIT_WINDOW", 60, raising=False)

    client = flask_app.test_client()
    headers = {"X-API-Key": "phase4-test-key"}

    ontology_first = client.post(
        "/api/graph/ontology/generate",
        headers=headers,
        data={"simulation_requirement": "model this document"},
    )
    ontology_second = client.post(
        "/api/graph/ontology/generate",
        headers=headers,
        data={"simulation_requirement": "model this document again"},
    )
    build_first = client.post("/api/graph/build", headers=headers, json={})
    build_second = client.post("/api/graph/build", headers=headers, json={})

    assert ontology_first.status_code != 429
    assert ontology_second.status_code == 429
    assert ontology_second.get_json()["error"] == "LLM endpoint rate limit exceeded"
    assert build_first.status_code != 429
    assert build_second.status_code == 429
    assert build_second.get_json()["retry_after"] > 0


def test_ipc_rejects_unauthenticated_filesystem_commands(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)

    from app.services.simulation_ipc import CommandType, SimulationIPCServer

    server = SimulationIPCServer(str(tmp_path))
    attack_file = Path(server.commands_dir) / "attack.json"
    legit_file = Path(server.commands_dir) / "legit.json"

    attack_file.write_text(
        json.dumps({
            "command_id": "attack",
            "command_type": CommandType.CLOSE_ENV.value,
            "args": {},
        }),
        encoding="utf-8",
    )
    legit_file.write_text(
        json.dumps({
            "command_id": "legit",
            "command_type": CommandType.CLOSE_ENV.value,
            "args": {},
            "auth_token": server.auth_token,
        }),
        encoding="utf-8",
    )

    command = server.poll_commands()

    assert command.command_id == "legit"
    assert command.auth_token == server.auth_token
    assert not attack_file.exists()
