import importlib
import sys
import types
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def reload_config(monkeypatch, **env):
    import dotenv

    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: None)

    for name in (
        'APP_ENV',
        'FLASK_ENV',
        'ENVIRONMENT',
        'RAILWAY_ENVIRONMENT_ID',
        'RAILWAY_ENVIRONMENT_NAME',
        'RAILWAY_ENVIRONMENT',
        'RAILWAY_PROJECT_ID',
        'RAILWAY_SERVICE_ID',
        'RAILWAY_PUBLIC_DOMAIN',
        'SECRET_KEY',
        'MIROFISH_CORS_ORIGINS',
        'CORS_ORIGINS',
    ):
        monkeypatch.delenv(name, raising=False)

    for name, value in env.items():
        monkeypatch.setenv(name, value)

    sys.modules.pop('app.config', None)
    import app.config as config

    return config


def test_local_dev_keeps_secret_fallback(monkeypatch):
    config = reload_config(monkeypatch)

    assert config.Config.SECRET_KEY == config.DEFAULT_SECRET_KEY
    assert config.Config.IS_PRODUCTION is False


def test_production_requires_explicit_secret(monkeypatch):
    config = reload_config(monkeypatch, RAILWAY_ENVIRONMENT='production')

    assert config.Config.SECRET_KEY is None
    assert "SECRET_KEY must be configured for production" in config.Config.validate()


def test_production_accepts_explicit_secret(monkeypatch):
    config = reload_config(
        monkeypatch,
        RAILWAY_ENVIRONMENT='production',
        SECRET_KEY='a-production-secret',
    )

    assert config.Config.SECRET_KEY == 'a-production-secret'
    assert "SECRET_KEY must be configured for production" not in config.Config.validate()


def test_production_cors_filters_wildcards(monkeypatch):
    config = reload_config(
        monkeypatch,
        RAILWAY_ENVIRONMENT='production',
        MIROFISH_CORS_ORIGINS='*, https://app.example.com/',
    )

    assert config.Config.CORS_ORIGINS == ['https://app.example.com']


def test_production_cors_wildcard_only_falls_back_to_public_domain(monkeypatch):
    config = reload_config(
        monkeypatch,
        RAILWAY_ENVIRONMENT='production',
        MIROFISH_CORS_ORIGINS='*',
    )

    assert config.Config.CORS_ORIGINS == ['https://mirofish-production-bbd6.up.railway.app']


def test_default_cors_includes_local_and_railway(monkeypatch):
    config = reload_config(monkeypatch)

    assert 'http://localhost:5173' in config.Config.CORS_ORIGINS
    assert 'https://mirofish-production-bbd6.up.railway.app' in config.Config.CORS_ORIGINS


def test_app_factory_health_and_api_cors(monkeypatch, tmp_path):
    reload_config(monkeypatch)

    services_module = types.ModuleType('app.services')
    services_module.__path__ = []

    simulation_runner_module = types.ModuleType('app.services.simulation_runner')

    class DummySimulationRunner:
        @staticmethod
        def register_cleanup():
            return None

    simulation_runner_module.SimulationRunner = DummySimulationRunner

    api_module = types.ModuleType('app.api')
    from flask import Blueprint

    api_module.graph_bp = Blueprint('graph_test', __name__)
    api_module.simulation_bp = Blueprint('simulation_test', __name__)
    api_module.report_bp = Blueprint('report_test', __name__)

    monkeypatch.setitem(sys.modules, 'app.services', services_module)
    monkeypatch.setitem(sys.modules, 'app.services.simulation_runner', simulation_runner_module)
    monkeypatch.setitem(sys.modules, 'app.api', api_module)

    import app as app_package
    importlib.reload(app_package)

    class TestConfig:
        SECRET_KEY = 'test-secret'
        DEBUG = False
        JSON_AS_ASCII = False
        DATA_ROOT = str(tmp_path)
        CORS_ORIGINS = ['https://allowed.example']

        @classmethod
        def ensure_storage_dirs(cls):
            return None

    flask_app = app_package.create_app(TestConfig)
    client = flask_app.test_client()

    assert client.get('/health').json == {'status': 'ok', 'service': 'MiroFish Backend'}

    allowed = client.options(
        '/api/graph/project/list',
        headers={
            'Origin': 'https://allowed.example',
            'Access-Control-Request-Method': 'GET',
        },
    )
    denied = client.options(
        '/api/graph/project/list',
        headers={
            'Origin': 'https://denied.example',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert allowed.headers.get('Access-Control-Allow-Origin') == 'https://allowed.example'
    assert denied.headers.get('Access-Control-Allow-Origin') is None
