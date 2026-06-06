"""Read-only simulation presentation helpers.

This module owns file-backed read models for simulation routes so the Flask
route module can stay focused on HTTP adaptation.
"""

import csv
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import Config
from ..models.project import ProjectManager
from ..utils.logger import get_logger
from .simulation_manager import SimulationManager
from .simulation_runner import SimulationRunner


logger = get_logger("mirofish.services.simulation_read")


class SimulationReadNotFound(ValueError):
    """Raised when a requested simulation read model has no backing directory."""


def _simulation_dir(simulation_id: str) -> str:
    return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)


def resolve_report_id_for_simulation(simulation_id: str) -> Optional[str]:
    reports_dir = Config.REPORTS_DIR
    if not os.path.exists(reports_dir):
        return None

    matching_reports = []

    try:
        for report_folder in os.listdir(reports_dir):
            report_path = os.path.join(reports_dir, report_folder)
            if not os.path.isdir(report_path):
                continue

            meta_file = os.path.join(report_path, "meta.json")
            if not os.path.exists(meta_file):
                continue

            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)

                if meta.get("simulation_id") == simulation_id:
                    matching_reports.append(
                        {
                            "report_id": meta.get("report_id"),
                            "created_at": meta.get("created_at", ""),
                            "status": meta.get("status", ""),
                        }
                    )
            except Exception:
                continue

        if not matching_reports:
            return None

        matching_reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return matching_reports[0].get("report_id")

    except Exception as exc:
        logger.warning("Failed to resolve report for simulation %s: %s", simulation_id, exc)
        return None


def build_simulation_history(limit: int = 20) -> List[Dict[str, Any]]:
    manager = SimulationManager()
    simulations = manager.list_simulations()[:limit]

    enriched_simulations = []
    for sim in simulations:
        sim_dict = sim.to_dict()

        config = manager.get_simulation_config(sim.simulation_id)
        if config:
            sim_dict["simulation_requirement"] = config.get("simulation_requirement", "")
            time_config = config.get("time_config", {})
            sim_dict["total_simulation_hours"] = time_config.get("total_simulation_hours", 0)
            recommended_rounds = int(
                time_config.get("total_simulation_hours", 0)
                * 60
                / max(time_config.get("minutes_per_round", 60), 1)
            )
        else:
            sim_dict["simulation_requirement"] = ""
            sim_dict["total_simulation_hours"] = 0
            recommended_rounds = 0

        run_state = SimulationRunner.get_run_state(sim.simulation_id)
        if run_state:
            sim_dict["current_round"] = run_state.current_round
            sim_dict["runner_status"] = run_state.runner_status.value
            sim_dict["total_rounds"] = (
                run_state.total_rounds if run_state.total_rounds > 0 else recommended_rounds
            )
        else:
            sim_dict["current_round"] = 0
            sim_dict["runner_status"] = "idle"
            sim_dict["total_rounds"] = recommended_rounds

        project = ProjectManager.get_project(sim.project_id)
        if project and hasattr(project, "files") and project.files:
            sim_dict["files"] = [
                {"filename": f.get("filename", "\u672a\u77e5\u6587\u4ef6")}
                for f in project.files[:3]
            ]
        else:
            sim_dict["files"] = []

        sim_dict["report_id"] = resolve_report_id_for_simulation(sim.simulation_id)
        sim_dict["version"] = "v1.0.2"
        sim_dict["created_date"] = sim_dict.get("created_at", "")[:10]

        enriched_simulations.append(sim_dict)

    return enriched_simulations


def load_simulation_profiles_realtime(simulation_id: str, platform: str) -> Dict[str, Any]:
    sim_dir = _simulation_dir(simulation_id)
    if not os.path.exists(sim_dir):
        raise SimulationReadNotFound(f"\u6a21\u62df\u4e0d\u5b58\u5728: {simulation_id}")

    profiles_file = (
        os.path.join(sim_dir, "reddit_profiles.json")
        if platform == "reddit"
        else os.path.join(sim_dir, "twitter_profiles.csv")
    )

    file_exists = os.path.exists(profiles_file)
    profiles = []
    file_modified_at = None

    if file_exists:
        file_stat = os.stat(profiles_file)
        file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()

        try:
            if platform == "reddit":
                with open(profiles_file, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            else:
                with open(profiles_file, "r", encoding="utf-8") as f:
                    profiles = list(csv.DictReader(f))
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to read profiles file, possibly mid-write: %s", exc)
            profiles = []

    is_generating = False
    total_expected = None
    state_file = os.path.join(sim_dir, "state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            is_generating = state_data.get("status", "") == "preparing"
            total_expected = state_data.get("entities_count")
        except Exception:
            pass

    return {
        "simulation_id": simulation_id,
        "platform": platform,
        "count": len(profiles),
        "total_expected": total_expected,
        "is_generating": is_generating,
        "file_exists": file_exists,
        "file_modified_at": file_modified_at,
        "profiles": profiles,
    }


def load_simulation_config_realtime(simulation_id: str) -> Dict[str, Any]:
    sim_dir = _simulation_dir(simulation_id)
    if not os.path.exists(sim_dir):
        raise SimulationReadNotFound(f"\u6a21\u62df\u4e0d\u5b58\u5728: {simulation_id}")

    config_file = os.path.join(sim_dir, "simulation_config.json")
    file_exists = os.path.exists(config_file)
    config = None
    file_modified_at = None

    if file_exists:
        file_stat = os.stat(config_file)
        file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to read config file, possibly mid-write: %s", exc)
            config = None

    is_generating = False
    generation_stage = None
    config_generated = False

    state_file = os.path.join(sim_dir, "state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            status = state_data.get("status", "")
            is_generating = status == "preparing"
            config_generated = state_data.get("config_generated", False)

            if is_generating:
                generation_stage = (
                    "generating_config"
                    if state_data.get("profiles_generated", False)
                    else "generating_profiles"
                )
            elif status == "ready":
                generation_stage = "completed"
        except Exception:
            pass

    response_data: Dict[str, Any] = {
        "simulation_id": simulation_id,
        "file_exists": file_exists,
        "file_modified_at": file_modified_at,
        "is_generating": is_generating,
        "generation_stage": generation_stage,
        "config_generated": config_generated,
        "config": config,
    }

    if config:
        response_data["summary"] = {
            "total_agents": len(config.get("agent_configs", [])),
            "simulation_hours": config.get("time_config", {}).get("total_simulation_hours"),
            "initial_posts_count": len(config.get("event_config", {}).get("initial_posts", [])),
            "hot_topics_count": len(config.get("event_config", {}).get("hot_topics", [])),
            "has_twitter_config": "twitter_config" in config,
            "has_reddit_config": "reddit_config" in config,
            "generated_at": config.get("generated_at"),
            "llm_model": config.get("llm_model"),
        }

    return response_data
