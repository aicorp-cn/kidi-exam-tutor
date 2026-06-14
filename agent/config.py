"""Configuration loader with validation gates and two-level LLM overrides.

Usage:
  from config import config       # Singleton, validates at import time
  params = config.llm_for("stage1")  # → {"model": "deepseek-chat", "temperature": 0.0, ...}

CLI mode:
  python3 -c "from config import validate; validate()"
  → exit 0 if valid, exit 1 with stderr on failure
"""

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

# ═══════════════════════════════════════════════════════════════
# Path resolution
# ═══════════════════════════════════════════════════════════════

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parent


def _find_config() -> Path:
    """Search for config.yaml: env var → agent/ → project root → cwd."""
    env_path = os.getenv("EXAM_TUTOR_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    for base in [_PROJECT_ROOT, _AGENT_DIR, Path.cwd()]:
        candidate = base / "config.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "config.yaml not found. "
        "Set EXAM_TUTOR_CONFIG=/path/to/config.yaml or place it in the project root."
    )


# ═══════════════════════════════════════════════════════════════
# Validation gates
# ═══════════════════════════════════════════════════════════════

class ConfigError(Exception):
    """Fatal configuration error — blocks startup."""
    pass


def _resolve_path(p: str) -> Path:
    """Resolve a path string: absolute stays, relative → from project root."""
    path = Path(p)
    if not path.is_absolute():
        path = (_PROJECT_ROOT / path).resolve()
    return path


def _check(condition: bool, message: str, fatal: bool = True):
    if not condition:
        if fatal:
            raise ConfigError(message)
        else:
            print(f"[config] WARNING: {message}", file=sys.stderr)


def _validate_url(url: str, label: str):
    """Validate that a URL has http/https scheme and a host."""
    parsed = urlparse(url)
    _check(parsed.scheme in ("http", "https"),
           f"{label} must start with http:// or https://, got '{url}'")
    _check(bool(parsed.netloc),
           f"{label} has no hostname, got '{url}'")


_MODEL_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9.\-_]+$')


def _validate_model_name(name: str, label: str):
    """Validate model name format — does NOT verify model exists in API."""
    _check(_MODEL_RE.match(name),
           f"{label} '{name}' is not a valid model name (expected e.g. 'deepseek-chat')")


def _validate(raw: dict) -> list[str]:
    """Run all validation gates. Returns list of non-fatal warnings."""
    warnings = []

    # ── Load .env FIRST, before any env-dependent check ──
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        _load_dotenv(env_path)

    # ── Server ──
    srv = raw.get("server", {})
    port = srv.get("port", 8080)
    _check(isinstance(port, int) and 1024 <= port <= 65535,
           f"server.port must be int in [1024, 65535], got {port}")
    _check(isinstance(srv.get("host", ""), str),
           "server.host must be a string")

    cors = srv.get("cors_origins", ["*"])
    _check(isinstance(cors, list) and len(cors) > 0,
           "server.cors_origins must be a non-empty list of strings")
    if cors == ["*"]:
        warnings.append("server.cors_origins is '*' — all origins allowed. "
                        "Set specific origins for production.")

    api_pfx = srv.get("api_prefix", "")
    _check(isinstance(api_pfx, str), "server.api_prefix must be a string")
    if api_pfx:
        warnings.append(
            f"server.api_prefix is set to '{api_pfx}'. "
            "This requires a reverse proxy (nginx/Caddy) to strip the prefix "
            "before forwarding to the backend. Without a reverse proxy, "
            "API requests will fail with 404."
        )

    # ── Upload ──
    up = raw.get("upload", {})
    _check(isinstance(up.get("max_file_size_mb", 0), (int, float)) and up["max_file_size_mb"] > 0,
           f"upload.max_file_size_mb must be > 0, got {up.get('max_file_size_mb')}")
    types = up.get("allowed_types", [])
    _check(isinstance(types, list) and len(types) > 0,
           "upload.allowed_types must be a non-empty list")
    _check(isinstance(up.get("image_cleanup", True), bool),
           "upload.image_cleanup must be a boolean")

    # ── LLM ──
    llm = raw.get("llm", {})
    _check(isinstance(llm.get("model", ""), str) and len(llm["model"]) > 0,
           "llm.model must be a non-empty string")
    _validate_model_name(llm["model"], "llm.model")
    _check(isinstance(llm.get("api_key_env", ""), str) and len(llm["api_key_env"]) > 0,
           "llm.api_key_env must be a non-empty string")

    # API key
    key = os.getenv(llm["api_key_env"], "")
    _check(bool(key), f"Environment variable '{llm['api_key_env']}' is not set. "
           f"Copy .env.example to .env and fill in your API key.")

    _check(isinstance(llm.get("base_url", ""), str) and len(llm["base_url"]) > 0,
           "llm.base_url must be a non-empty string")
    _validate_url(llm["base_url"], "llm.base_url")
    if llm.get("fallback_url"):
        _validate_url(llm["fallback_url"], "llm.fallback_url")
    _check(isinstance(llm.get("timeout_s", 0), (int, float)) and llm["timeout_s"] > 0,
           f"llm.timeout_s must be > 0, got {llm.get('timeout_s')}")
    _check(isinstance(llm.get("retry_attempts", 0), int) and llm["retry_attempts"] > 0,
           f"llm.retry_attempts must be > 0, got {llm.get('retry_attempts')}")
    _check(isinstance(llm.get("retry_delay_s", 0), (int, float)) and llm["retry_delay_s"] > 0,
           f"llm.retry_delay_s must be > 0, got {llm.get('retry_delay_s')}")

    for st, st_name in [(llm.get("stage1", {}), "stage1"), (llm.get("stage2", {}), "stage2")]:
        if "model" in st:
            _validate_model_name(st["model"], f"llm.{st_name}.model")
        if "temperature" in st:
            t = st["temperature"]
            _check(isinstance(t, (int, float)) and 0.0 <= t <= 2.0,
                   f"llm.{st_name}.temperature must be in [0.0, 2.0], got {t}")
        if "max_tokens" in st:
            mt = st["max_tokens"]
            _check(isinstance(mt, int) and mt > 0,
                   f"llm.{st_name}.max_tokens must be > 0, got {mt}")

    st2 = llm.get("stage2", {})
    if "truncation_batch_size" in st2:
        _check(st2["truncation_batch_size"] > 0,
               f"llm.stage2.truncation_batch_size must be > 0")
    if "heartbeat_interval_s" in st2:
        _check(st2["heartbeat_interval_s"] > 0,
               f"llm.stage2.heartbeat_interval_s must be > 0")

    # ── SSE ──
    sse = raw.get("sse", {})
    _check(isinstance(sse.get("heartbeat_timeout", 0), (int, float)) and sse["heartbeat_timeout"] > 0,
           f"sse.heartbeat_timeout must be > 0, got {sse.get('heartbeat_timeout')}")

    # ── History ──
    hist = raw.get("history", {})
    _check(isinstance(hist.get("page_size", 0), int) and hist["page_size"] > 0,
           f"history.page_size must be > 0, got {hist.get('page_size')}")

    # ── Paths ──
    pp = raw.get("paths", {})
    data_dir = pp.get("data_dir", "./data")
    webui_dir = pp.get("webui_dir", "./webui")

    # Resolve relative to project root
    data_path = _resolve_path(data_dir)
    webui_path = _resolve_path(webui_dir)

    # data_dir parent must exist and be writable
    parent = data_path.parent if data_path.exists() else data_path
    while not parent.exists():
        parent = parent.parent
    _check(os.access(str(parent), os.W_OK),
           f"data_dir parent is not writable: {parent}")

    # webui_dir must contain index.html
    _check(webui_path.exists(),
           f"webui_dir does not exist: {webui_path}")
    _check((webui_path / "index.html").exists(),
           f"webui_dir missing index.html: {webui_path}")

    return warnings


def _load_dotenv(path: Path):
    """Minimal .env loader — no python-dotenv dependency."""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


# ═══════════════════════════════════════════════════════════════
# Config class
# ═══════════════════════════════════════════════════════════════

class Config:
    """Singleton configuration loaded from config.yaml."""

    def __init__(self):
        self._config_path = _find_config()
        with open(self._config_path) as f:
            self._raw = yaml.safe_load(f)

        self._warnings = _validate(self._raw)
        self._resolve()

    def _resolve(self):
        """Flatten config into attributes for direct access."""
        raw = self._raw

        # Server
        srv = raw["server"]
        self.server_host = srv["host"]
        self.server_port = srv["port"]
        self.cors_origins = srv["cors_origins"]
        self.api_prefix = srv.get("api_prefix", "")

        # SSL (optional, disabled by default)
        ssl_raw = srv.get("ssl", {})
        self.ssl_enabled = ssl_raw.get("enabled", False)
        if self.ssl_enabled:
            self.ssl_cert_file = _resolve_path(ssl_raw["cert_file"])
            self.ssl_key_file = _resolve_path(ssl_raw["key_file"])
            _check(self.ssl_cert_file.exists(),
                   f"SSL cert file not found: {self.ssl_cert_file}")
            _check(self.ssl_key_file.exists(),
                   f"SSL key file not found: {self.ssl_key_file}")

        # Upload
        up = raw["upload"]
        self.upload_max_file_size = up["max_file_size_mb"] * 1024 * 1024
        self.upload_allowed_types = set(up["allowed_types"])
        self.upload_image_cleanup = up.get("image_cleanup", True)

        # SSE
        sse = raw["sse"]
        self.sse_heartbeat_timeout = sse["heartbeat_timeout"]

        # History
        hist = raw["history"]
        self.history_page_size = hist["page_size"]

        # Paths — resolve relative to project root
        pp = raw["paths"]
        self.data_dir = _resolve_path(pp["data_dir"])
        self.webui_dir = _resolve_path(pp["webui_dir"])
        (self.data_dir / "images").mkdir(parents=True, exist_ok=True)

        # LLM — store raw for llm_for()
        self._llm = raw["llm"]

        self.project_root = _PROJECT_ROOT

    # ── LLM: two-level override ──

    def llm_for(self, stage: str) -> dict:
        """Return flat dict of LLM params for a given stage.

        Merge order: global → pipeline defaults → stage override.
        """
        llm = self._llm

        # Start with global
        params = {
            "model": llm["model"],
            "base_url": llm["base_url"],
            "fallback_url": llm.get("fallback_url", llm["base_url"].replace("/beta", "")),
            "timeout": llm["timeout_s"],
            "max_retries": llm["max_retries"],
        }

        # Add pipeline defaults
        for key in ("retry_attempts", "retry_delay_s"):
            if key in llm:
                params[key] = llm[key]

        # Stage override
        stage_raw = llm.get(stage, {})
        for key in ("model", "temperature", "max_tokens", "retry_attempts",
                     "retry_delay_s", "truncation_batch_size", "heartbeat_interval_s"):
            if key in stage_raw:
                params[key] = stage_raw[key]

        # extra_body — model-specific API parameters (e.g. thinking mode)
        if "extra_body" in stage_raw:
            params["extra_body"] = stage_raw["extra_body"]

        return params

    def llm_api_key(self) -> str:
        return os.getenv(self._llm["api_key_env"], "")

    # ── Health / Frontend config ──

    def health(self) -> dict:
        """Generate /health endpoint response."""
        status = "ok" if not self._warnings else "degraded"
        return {
            "status": status,
            "checks": {
                "config_valid": True,
                "api_key_set": bool(self.llm_api_key()),
                "data_dir_writable": os.access(str(self.data_dir), os.W_OK),
                "webui_present": (self.webui_dir / "index.html").exists(),
                "llm_configured": bool(self._llm.get("model")),
            },
            "version": "6.1.0",
            "warnings": self._warnings,
        }

    def frontend_config(self) -> dict:
        """Generate /api/config endpoint response for frontend."""
        return {
            "upload_max_mb": self._raw["upload"]["max_file_size_mb"],
            "allowed_types": sorted(self.upload_allowed_types),
            "page_size": self.history_page_size,
            "api_base": self.api_prefix,
        }


# ═══════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════

_config_instance = None


def _init_config():
    global _config_instance
    if _config_instance is None:
        try:
            _config_instance = Config()
            for w in _config_instance._warnings:
                print(f"[config] WARNING: {w}", file=sys.stderr)
            print(f"[config] Loaded: {_config_instance._config_path}", file=sys.stderr)
        except (ConfigError, FileNotFoundError) as e:
            print(f"[config] FATAL: {e}", file=sys.stderr)
            sys.exit(1)
    return _config_instance


def validate(deep: bool = False):
    """Entry point for pre-flight check.

    Args:
        deep: If True, also ping each configured model via 1-token inference.
    """
    cfg = _init_config()
    print(f"✅ 配置验证通过")
    print(f"   配置文件: {cfg._config_path}")
    print(f"   模型: {cfg._llm['model']}")
    print(f"   端口: {cfg.server_port}")
    print(f"   数据目录: {cfg.data_dir}")
    print(f"   前端目录: {cfg.webui_dir}")
    print(f"   上传上限: {cfg._raw['upload']['max_file_size_mb']} MB")

    if deep:
        import asyncio
        from openai import AsyncOpenAI

        async def _ping_model(model: str, client) -> tuple[bool, str]:
            """1-token inference ping. Returns (ok, detail)."""
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    temperature=0.0,
                )
                return True, f"ok (finish={resp.choices[0].finish_reason})"
            except Exception as ex:
                return False, str(ex)[:200]

        async def _run():
            api_key = cfg.llm_api_key()
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=cfg.llm_for("stage1")["base_url"],
                timeout=30,
            )
            for stage in ("stage1", "stage2"):
                model = cfg.llm_for(stage)["model"]
                print(f"   {stage} model '{model}' ... ", end="", flush=True)
                ok, detail = await _ping_model(model, client)
                print("✅ 可达" if ok else f"❌ {detail}")

        asyncio.run(_run())

    return cfg


# Lazy init — validates at first access, not at import time
# (allows importing config module for check_config without side effects)

def get_config() -> Config:
    return _init_config()


# Convenience: config = get_config()
# Usage: from config import config
class _ConfigProxy:
    def __getattr__(self, name):
        return getattr(get_config(), name)


config = _ConfigProxy()
