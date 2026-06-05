import json
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

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


def load_runner(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)
    import app.services.simulation_runner as runner_module

    runner = runner_module.SimulationRunner
    monkeypatch.setattr(runner, "RUN_STATE_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(runner, "SCRIPTS_DIR", str(tmp_path / "scripts"))
    monkeypatch.setattr(runner, "_monitor_simulation", staticmethod(lambda simulation_id: None))
    runner._run_states.clear()
    runner._processes.clear()
    runner._action_queues.clear()
    runner._monitor_threads.clear()
    runner._stdout_files.clear()
    runner._stderr_files.clear()
    runner._graph_memory_enabled.clear()
    runner._starting_simulations.clear()
    Path(runner.RUN_STATE_DIR).mkdir(parents=True, exist_ok=True)
    Path(runner.SCRIPTS_DIR).mkdir(parents=True, exist_ok=True)
    (Path(runner.SCRIPTS_DIR) / "run_parallel_simulation.py").write_text("# test script\n", encoding="utf-8")
    return runner_module, runner


def write_simulation_config(runner, simulation_id, time_config):
    sim_dir = Path(runner.RUN_STATE_DIR) / simulation_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "simulation_config.json").write_text(
        json.dumps({"time_config": time_config}),
        encoding="utf-8",
    )


def install_fake_popen(monkeypatch, runner_module, delay=0.0):
    calls = []

    class DummyProcess:
        def __init__(self):
            self.pid = 1000 + len(calls)

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        if delay:
            time.sleep(delay)
        return DummyProcess()

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    return calls


def close_runner_files(runner):
    for file_handle in list(runner._stdout_files.values()):
        file_handle.close()


def test_start_simulation_validates_round_minutes_and_uses_sixty_minute_default(monkeypatch, tmp_path):
    runner_module, runner = load_runner(monkeypatch, tmp_path)
    popen_calls = install_fake_popen(monkeypatch, runner_module)

    write_simulation_config(runner, "sim_default", {"total_simulation_hours": 2})
    state = runner.start_simulation("sim_default")

    assert state.total_rounds == 2
    assert len(popen_calls) == 1

    write_simulation_config(runner, "sim_zero", {"total_simulation_hours": 2, "minutes_per_round": 0})
    with pytest.raises(ValueError, match="minutes_per_round"):
        runner.start_simulation("sim_zero")

    close_runner_files(runner)


def test_start_simulation_allows_only_one_concurrent_process(monkeypatch, tmp_path):
    runner_module, runner = load_runner(monkeypatch, tmp_path)
    popen_calls = install_fake_popen(monkeypatch, runner_module, delay=0.05)
    write_simulation_config(runner, "sim_race", {"total_simulation_hours": 1, "minutes_per_round": 60})

    barrier = threading.Barrier(2)

    def start_once():
        barrier.wait(timeout=2)
        try:
            return ("ok", runner.start_simulation("sim_race").runner_status.value)
        except Exception as exc:
            return ("error", str(exc))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start_once(), range(2)))

    assert [status for status, _ in results].count("ok") == 1
    assert [status for status, _ in results].count("error") == 1
    assert len(popen_calls) == 1

    close_runner_files(runner)


def test_loaded_running_state_without_owned_process_fails_closed(monkeypatch, tmp_path):
    _, runner = load_runner(monkeypatch, tmp_path)
    sim_dir = Path(runner.RUN_STATE_DIR) / "sim_stale"
    sim_dir.mkdir(parents=True)
    (sim_dir / "run_state.json").write_text(
        json.dumps({
            "runner_status": "running",
            "current_round": 3,
            "total_rounds": 10,
            "twitter_running": True,
            "reddit_running": True,
            "process_pid": 4242,
        }),
        encoding="utf-8",
    )

    state = runner.get_run_state("sim_stale")

    assert state.runner_status.value == "failed"
    assert state.twitter_running is False
    assert state.reddit_running is False
    assert "ownership was lost" in state.error
    persisted = json.loads((sim_dir / "run_state.json").read_text(encoding="utf-8"))
    assert persisted["runner_status"] == "failed"


def test_progress_and_summaries_do_not_overstate_or_truncate(monkeypatch, tmp_path):
    _, runner = load_runner(monkeypatch, tmp_path)

    from app.services.simulation_runner import AgentAction, SimulationRunState

    state = SimulationRunState(
        simulation_id="sim_progress",
        current_round=12,
        total_rounds=10,
    )
    assert state.to_dict()["progress_percent"] == 100.0

    actions = [
        AgentAction(
            round_num=1,
            timestamp=f"2026-06-03T00:00:{i % 60:02d}",
            platform="twitter",
            agent_id=7,
            agent_name="agent-seven",
            action_type="POST",
        )
        for i in range(10005)
    ]

    monkeypatch.setattr(
        runner,
        "get_all_actions",
        classmethod(lambda cls, simulation_id, platform=None, agent_id=None, round_num=None: actions),
    )

    timeline = runner.get_timeline("sim_many")
    stats = runner.get_agent_stats("sim_many")

    assert timeline[0]["total_actions"] == 10005
    assert stats[0]["total_actions"] == 10005


def test_simulation_manager_read_does_not_create_missing_dir_and_cache_survives_new_instance(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)
    from app.services.simulation_manager import SimulationManager, SimulationState

    data_root = tmp_path / "simulations"
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(data_root))

    manager = SimulationManager()
    assert manager.get_simulation("missing") is None
    assert not (data_root / "missing").exists()

    state = SimulationState(simulation_id="sim_cached", project_id="project-1", graph_id="graph-1")
    manager._save_simulation_state(state)
    (data_root / "sim_cached" / "state.json").unlink()

    second_manager = SimulationManager()
    assert second_manager._simulations is manager._simulations
    assert second_manager.get_simulation("sim_cached") is state


def test_report_download_temp_file_is_removed_on_response_close(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)
    from flask import Flask, Response
    import app.api.report as report_api

    captured = {}
    monkeypatch.setattr(
        report_api.ReportManager,
        "get_report",
        staticmethod(lambda report_id: SimpleNamespace(markdown_content="# generated\n")),
    )
    monkeypatch.setattr(
        report_api.ReportManager,
        "_get_report_markdown_path",
        staticmethod(lambda report_id: str(tmp_path / "missing-report.md")),
    )

    def fake_send_file(path, **kwargs):
        captured["path"] = Path(path)
        return Response("ok")

    monkeypatch.setattr(report_api, "send_file", fake_send_file)

    app = Flask(__name__)
    with app.test_request_context("/report-1/download"):
        response = report_api.download_report("report-1")

    assert captured["path"].exists()
    response.close()
    assert not captured["path"].exists()


def test_prepared_check_reports_ready_without_mutating_state_json(monkeypatch, tmp_path):
    install_external_stubs(monkeypatch)
    import app.api.simulation as simulation_api

    monkeypatch.setattr(
        simulation_api.Config,
        "OASIS_SIMULATION_DATA_DIR",
        str(tmp_path / "simulations"),
    )
    sim_dir = Path(simulation_api.Config.OASIS_SIMULATION_DATA_DIR) / "sim_preparing"
    sim_dir.mkdir(parents=True)
    state_path = sim_dir / "state.json"
    state_path.write_text(
        json.dumps({
            "status": "preparing",
            "config_generated": True,
            "updated_at": "unchanged",
            "entities_count": 2,
            "entity_types": ["Person"],
        }),
        encoding="utf-8",
    )
    (sim_dir / "simulation_config.json").write_text("{}", encoding="utf-8")
    (sim_dir / "reddit_profiles.json").write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")
    (sim_dir / "twitter_profiles.csv").write_text("id,name\n1,A\n", encoding="utf-8")
    before = state_path.read_text(encoding="utf-8")

    is_prepared, info = simulation_api._check_simulation_prepared("sim_preparing")

    assert is_prepared is True
    assert info["status"] == "ready"
    assert info["state_status"] == "preparing"
    assert info["profiles_count"] == 2
    assert state_path.read_text(encoding="utf-8") == before


def test_simulation_runner_centralizes_run_state_paths(monkeypatch, tmp_path):
    _, runner = load_runner(monkeypatch, tmp_path)
    source = (BACKEND_ROOT / "app" / "services" / "simulation_runner.py").read_text(encoding="utf-8")

    assert runner._simulation_dir("sim_path") == str(Path(runner.RUN_STATE_DIR) / "sim_path")
    assert runner._run_state_path("sim_path") == str(
        Path(runner.RUN_STATE_DIR) / "sim_path" / "run_state.json"
    )
    assert source.count("os.path.join(cls.RUN_STATE_DIR") == 1
    assert "def _simulation_dir" in source
    assert "def _run_state_path" in source
