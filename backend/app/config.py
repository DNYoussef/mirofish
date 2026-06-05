"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


def env_flag(name, default=False):
    """Parse common boolean env formats safely."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def resolve_data_root():
    """Resolve the persistent application data directory."""
    explicit_root = os.environ.get('MIROFISH_DATA_DIR')
    if explicit_root:
        return os.path.abspath(explicit_root)

    volume_root = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
    if volume_root:
        return os.path.abspath(volume_root)

    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../uploads'))


DEFAULT_SECRET_KEY = 'mirofish-secret-key'
DEFAULT_CORS_ORIGINS = (
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'https://mirofish-production-bbd6.up.railway.app',
)
PRODUCTION_CORS_ORIGINS = (
    'https://mirofish-production-bbd6.up.railway.app',
)


def is_production_environment():
    """Return True for Railway or explicit production-like environments."""
    environment = (
        os.environ.get('APP_ENV')
        or os.environ.get('FLASK_ENV')
        or os.environ.get('ENVIRONMENT')
        or ''
    ).strip().lower()
    railway_markers = (
        'RAILWAY_ENVIRONMENT_ID',
        'RAILWAY_ENVIRONMENT_NAME',
        'RAILWAY_ENVIRONMENT',
        'RAILWAY_PROJECT_ID',
        'RAILWAY_SERVICE_ID',
        'RAILWAY_PUBLIC_DOMAIN',
    )
    return environment in {'production', 'prod'} or any(os.environ.get(name) for name in railway_markers)


def resolve_secret_key():
    """Use an explicit secret in production and a fallback only for local dev."""
    secret_key = os.environ.get('SECRET_KEY')
    if secret_key:
        return secret_key
    return None if is_production_environment() else DEFAULT_SECRET_KEY


def parse_cors_origins(raw_origins=None):
    """Parse configured CORS origins and prevent wildcard production CORS."""
    is_production = is_production_environment()
    if raw_origins is None:
        raw_origins = os.environ.get('MIROFISH_CORS_ORIGINS') or os.environ.get('CORS_ORIGINS')

    if raw_origins:
        origins = [origin.strip().rstrip('/') for origin in raw_origins.split(',') if origin.strip()]
    else:
        origins = list(PRODUCTION_CORS_ORIGINS if is_production else DEFAULT_CORS_ORIGINS)

    if is_production:
        origins = [origin for origin in origins if origin != '*']

    return origins or list(PRODUCTION_CORS_ORIGINS if is_production else DEFAULT_CORS_ORIGINS)


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = resolve_secret_key()
    DEBUG = env_flag('FLASK_DEBUG', False)
    IS_PRODUCTION = is_production_environment()
    CORS_ORIGINS = parse_cors_origins()
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    DATA_ROOT = resolve_data_root()
    UPLOAD_FOLDER = DATA_ROOT
    PROJECTS_DIR = os.path.join(DATA_ROOT, 'projects')
    REPORTS_DIR = os.path.join(DATA_ROOT, 'reports')
    TASKS_DIR = os.path.join(DATA_ROOT, 'tasks')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(DATA_ROOT, 'simulations')
    LLM_RATE_LIMIT_REQUESTS = int(os.environ.get('MIROFISH_LLM_RATE_LIMIT_REQUESTS', '5'))
    LLM_RATE_LIMIT_WINDOW = int(os.environ.get('MIROFISH_LLM_RATE_LIMIT_WINDOW', '600'))
    LLM_RATE_LIMIT_DB = os.environ.get(
        'MIROFISH_LLM_RATE_LIMIT_DB',
        os.path.join(DATA_ROOT, 'security', 'llm_rate_limits.sqlite3')
    )
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls):
        """验证必要配置"""
        errors = []
        if cls.IS_PRODUCTION and (not cls.SECRET_KEY or cls.SECRET_KEY == DEFAULT_SECRET_KEY):
            errors.append("SECRET_KEY must be configured for production")
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        return errors

    @classmethod
    def ensure_storage_dirs(cls):
        """Ensure persistent storage directories exist before serving traffic."""
        for path in (
            cls.UPLOAD_FOLDER,
            cls.PROJECTS_DIR,
            cls.REPORTS_DIR,
            cls.TASKS_DIR,
            cls.OASIS_SIMULATION_DATA_DIR,
        ):
            os.makedirs(path, exist_ok=True)

