import json
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
    service_source = (
        BACKEND_ROOT / "app" / "services" / "simulation_read_service.py"
    ).read_text(encoding="utf-8")

    assert len(api_source.splitlines()) < 2450
    assert "from ..services.simulation_read_service import" in api_source
    assert "load_simulation_profiles_realtime(simulation_id, platform)" in api_source
    assert "load_simulation_config_realtime(simulation_id)" in api_source
    assert "csv.DictReader" not in api_source
    assert "datetime.fromtimestamp" not in api_source
    assert "def load_simulation_profiles_realtime" in service_source
    assert "def load_simulation_config_realtime" in service_source


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
