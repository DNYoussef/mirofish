import json
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


def test_simulation_routes_delegate_realtime_file_io_to_read_service():
    api_source = (BACKEND_ROOT / "app" / "api" / "simulation.py").read_text(encoding="utf-8")
    read_routes_source = (
        BACKEND_ROOT / "app" / "api" / "simulation_read_routes.py"
    ).read_text(encoding="utf-8")
    service_source = (
        BACKEND_ROOT / "app" / "services" / "simulation_read_service.py"
    ).read_text(encoding="utf-8")

    assert len(api_source.splitlines()) < 80
    assert "simulation_read_routes" in api_source
    assert "from ..services.simulation_read_service import" in read_routes_source
    assert "load_simulation_profiles_realtime(simulation_id, platform)" in read_routes_source
    assert "load_simulation_config_realtime(simulation_id)" in read_routes_source
    assert "csv.DictReader" not in read_routes_source
    assert "datetime.fromtimestamp" not in read_routes_source
    assert "def load_simulation_profiles_realtime" in service_source
    assert "def load_simulation_config_realtime" in service_source


def test_simulation_api_is_split_into_concern_route_modules():
    facade_source = (BACKEND_ROOT / "app" / "api" / "simulation.py").read_text(encoding="utf-8")
    module_limits = {
        "simulation_entity_routes.py": 260,
        "simulation_prepare_routes.py": 680,
        "simulation_read_routes.py": 380,
        "simulation_run_routes.py": 820,
        "simulation_interview_routes.py": 700,
    }
    modules = {
        name: (BACKEND_ROOT / "app" / "api" / name).read_text(encoding="utf-8")
        for name in module_limits
    }

    assert len(facade_source.splitlines()) < 80
    assert "@simulation_bp.route" not in facade_source
    assert "traceback.format_exc" not in facade_source
    assert "_check_simulation_prepared" in facade_source
    for module_name in module_limits:
        assert module_name.removesuffix(".py") in facade_source

    for module_name, limit in module_limits.items():
        source = modules[module_name]
        assert len(source.splitlines()) < limit
        assert "@simulation_bp.route" in source

    assert "def start_simulation" in modules["simulation_run_routes.py"]
    assert "def get_simulation_posts" in modules["simulation_run_routes.py"]
    assert "def interview_agent" in modules["simulation_interview_routes.py"]
    assert "def close_simulation_env" in modules["simulation_interview_routes.py"]
    assert "def _check_simulation_prepared" in modules["simulation_prepare_routes.py"]
    assert "def get_simulation_config" in modules["simulation_read_routes.py"]
    assert "def get_graph_entities" in modules["simulation_entity_routes.py"]
    assert sum(source.count("@simulation_bp.route") for source in modules.values()) == 31


def test_simulation_read_service_preserves_realtime_profiles_and_config(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)

    from app.config import Config
    from app.services.simulation_read_service import (
        SimulationReadNotFound,
        load_simulation_config_realtime,
        load_simulation_profiles_realtime,
    )

    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    sim_dir = Path(Config.OASIS_SIMULATION_DATA_DIR) / "sim_read"
    sim_dir.mkdir(parents=True)
    (sim_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "preparing",
                "entities_count": 2,
                "profiles_generated": True,
                "config_generated": True,
            }
        ),
        encoding="utf-8",
    )
    (sim_dir / "reddit_profiles.json").write_text(
        json.dumps([{"id": "r1"}, {"id": "r2"}]),
        encoding="utf-8",
    )
    (sim_dir / "simulation_config.json").write_text(
        json.dumps(
            {
                "agent_configs": [{"id": "a1"}, {"id": "a2"}],
                "time_config": {"total_simulation_hours": 3},
                "event_config": {"initial_posts": ["p1"], "hot_topics": ["h1", "h2"]},
                "twitter_config": {},
                "generated_at": "2026-06-05T00:00:00",
                "llm_model": "test-model",
            }
        ),
        encoding="utf-8",
    )

    profiles = load_simulation_profiles_realtime("sim_read", "reddit")
    assert profiles["count"] == 2
    assert profiles["total_expected"] == 2
    assert profiles["is_generating"] is True
    assert profiles["file_exists"] is True

    config = load_simulation_config_realtime("sim_read")
    assert config["generation_stage"] == "generating_config"
    assert config["config_generated"] is True
    assert config["summary"]["total_agents"] == 2
    assert config["summary"]["simulation_hours"] == 3
    assert config["summary"]["initial_posts_count"] == 1
    assert config["summary"]["hot_topics_count"] == 2
    assert config["summary"]["has_twitter_config"] is True
    assert config["summary"]["has_reddit_config"] is False

    with pytest.raises(SimulationReadNotFound):
        load_simulation_profiles_realtime("missing", "reddit")


class RouteMapConfig:
    SECRET_KEY = "test-secret"
    DEBUG = False
    TESTING = False
    JSON_AS_ASCII = False
    DATA_ROOT = ""
    CORS_ORIGINS = ["https://allowed.example"]

    @classmethod
    def ensure_storage_dirs(cls):
        return None


def test_simulation_route_map_is_preserved_across_module_split(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)
    RouteMapConfig.DATA_ROOT = str(tmp_path)

    import app as app_package

    importlib.reload(app_package)
    flask_app = app_package.create_app(RouteMapConfig)

    routes = {
        rule.rule.removeprefix("/api/simulation"): sorted(
            method for method in rule.methods if method not in {"HEAD", "OPTIONS"}
        )
        for rule in flask_app.url_map.iter_rules()
        if rule.rule.startswith("/api/simulation")
    }

    assert routes == {
        "/entities/<graph_id>": ["GET"],
        "/entities/<graph_id>/<entity_uuid>": ["GET"],
        "/entities/<graph_id>/by-type/<entity_type>": ["GET"],
        "/create": ["POST"],
        "/prepare": ["POST"],
        "/prepare/status": ["POST"],
        "/<simulation_id>": ["GET"],
        "/list": ["GET"],
        "/history": ["GET"],
        "/<simulation_id>/profiles": ["GET"],
        "/<simulation_id>/profiles/realtime": ["GET"],
        "/<simulation_id>/config/realtime": ["GET"],
        "/<simulation_id>/config": ["GET"],
        "/<simulation_id>/config/download": ["GET"],
        "/script/<script_name>/download": ["GET"],
        "/generate-profiles": ["POST"],
        "/start": ["POST"],
        "/stop": ["POST"],
        "/<simulation_id>/run-status": ["GET"],
        "/<simulation_id>/run-status/detail": ["GET"],
        "/<simulation_id>/actions": ["GET"],
        "/<simulation_id>/timeline": ["GET"],
        "/<simulation_id>/agent-stats": ["GET"],
        "/<simulation_id>/posts": ["GET"],
        "/<simulation_id>/comments": ["GET"],
        "/interview": ["POST"],
        "/interview/batch": ["POST"],
        "/interview/all": ["POST"],
        "/interview/history": ["POST"],
        "/env-status": ["POST"],
        "/close-env": ["POST"],
    }
