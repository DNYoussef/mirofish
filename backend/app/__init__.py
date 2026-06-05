"""
MiroFish Backend - Flask应用工厂
"""

import os
import warnings
from pathlib import Path

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .utils.logger import setup_logger, get_logger


SENSITIVE_ERROR_KEYS = {'traceback', 'stack', 'stacktrace', 'exc_info'}


def _strip_sensitive_error_fields(value):
    if isinstance(value, dict):
        return {
            key: _strip_sensitive_error_fields(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_ERROR_KEYS
        }
    if isinstance(value, list):
        return [_strip_sensitive_error_fields(item) for item in value]
    return value


def _sanitize_json_error_response(app, response):
    if not response.is_json:
        return response

    payload = response.get_json(silent=True)
    if payload is None:
        return response

    sanitized = _strip_sensitive_error_fields(payload)
    if sanitized == payload:
        return response

    response.set_data(app.json.dumps(sanitized))
    response.mimetype = 'application/json'
    return response


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    frontend_dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    app = Flask(
        __name__,
        static_folder=str(frontend_dist) if frontend_dist.exists() else None,
        static_url_path='',
    )
    app.config.from_object(config_class)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
    
    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    # Flask >= 2.3 使用 app.json.ensure_ascii，旧版本使用 JSON_AS_ASCII 配置
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # 设置日志
    logger = setup_logger('mirofish')
    config_class.ensure_storage_dirs()
    
    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend 启动中...")
        logger.info("=" * 50)
        logger.info(f"Data root: {config_class.DATA_ROOT}")
    
    # 启用CORS
    CORS(app, resources={r"/api/*": {"origins": app.config['CORS_ORIGINS']}})
    
    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")
    
    # 请求日志中间件
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"请求体: {request.get_json(silent=True)}")
    
        if request.method == 'OPTIONS' or not request.path.startswith('/api/'):
            return None

        expected_api_key = os.environ.get('MIROFISH_API_KEY')
        if not expected_api_key:
            return {'error': 'API authentication is not configured'}, 503

        bearer = request.headers.get('Authorization', '')
        supplied_api_key = request.headers.get('X-API-Key', '')
        if bearer.startswith('Bearer '):
            supplied_api_key = bearer.removeprefix('Bearer ').strip()

        if supplied_api_key != expected_api_key:
            return {'error': 'Authentication required'}, 401

        return None

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        response = _sanitize_json_error_response(app, response)
        logger.debug(f"响应: {response.status_code}")
        return response
    
    # Sanitize exception responses before route registration.
    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return jsonify({
                "success": False,
                "error": error.description,
            }), error.code

        logger.exception("Unhandled API error")
        return jsonify({
            "success": False,
            "error": "Internal server error",
        }), 500

    # Register API blueprints.
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    
    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def frontend(path):
        if path.startswith('api/') or path == 'api':
            return {'error': 'Not found'}, 404

        if frontend_dist.exists():
            requested = frontend_dist / path if path else frontend_dist / 'index.html'
            if path and requested.is_file():
                return send_from_directory(str(frontend_dist), path)
            return send_from_directory(str(frontend_dist), 'index.html')

        return {'error': 'Frontend build missing'}, 503
    
    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")
    
    return app

