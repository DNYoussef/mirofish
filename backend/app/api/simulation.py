"""
Simulation API compatibility facade.

The route implementations live in concern-specific modules so routing, runtime
state mutation, and file/database reads are not owned by one god file. Importing
this module registers the same `simulation_bp` routes as the legacy module.
"""

from ..config import Config
from ..models.project import ProjectManager
from .simulation_prepare_routes import _check_simulation_prepared
from . import simulation_entity_routes as _simulation_entity_routes  # noqa: F401,E402
from . import simulation_prepare_routes as _simulation_prepare_routes  # noqa: F401,E402
from . import simulation_read_routes as _simulation_read_routes  # noqa: F401,E402
from . import simulation_run_routes as _simulation_run_routes  # noqa: F401,E402
from . import simulation_interview_routes as _simulation_interview_routes  # noqa: F401,E402

__all__ = ["Config", "ProjectManager", "_check_simulation_prepared"]
