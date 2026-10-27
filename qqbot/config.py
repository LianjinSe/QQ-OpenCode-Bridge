from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"


class ConfigError(ValueError):
    pass


def qq_ids(value: str, name: str) -> frozenset[int]:
    parts = [s.strip() for s in value.split(",") if s.strip()]
    if any(not s.isascii() or not s.isdecimal() or int(s) <= 0 for s in parts):
        raise ConfigError(f"{name} 必须是用逗号分隔的正整数 QQ 号")
    return frozenset(int(s) for s in parts)


def positive(value: str, name: str, *, floating: bool = False) -> float | int:
    try:
        number = float(value) if floating else int(value)
        if number <= 0 or not float(number) < float("inf"):
            raise ValueError
        return number
    except ValueError as exc:
        raise ConfigError(f"{name} 必须为有限正数") from exc


@dataclass(frozen=True)
class Config:
    napcat_url: str
    napcat_token: str = field(repr=False)
    allowed_users: frozenset[int]
    allowed_groups: frozenset[int] = frozenset()
    superadmin_user_id: int | None = None
    group_readonly_mcp_actions: frozenset[str] = frozenset()
    excluded_prefixes: tuple[str, ...] = ("ww", "mm", "codex", "core")
    env_file: Path = PROJECT_ROOT / ".env"
    workdir: Path = Path.home() / "qq-agent-workspace"
    service_file: Path = Path.home() / ".local/state/opencode/service.json"
    opencode_binary: str = "opencode"
    autostart: bool = True
    opencode_url: str = ""
    opencode_password: str = field(default="", repr=False)
    opencode_username: str = "opencode"
    model: str = ""
    image_generation_enabled: bool = False
    image_provider: str = "custom"
    image_model: str = "your-image-model"
    image_opencode_config: Path = Path.home() / ".config/opencode/opencode.json"
    image_timeout: float = 600
    state_db: Path = DATA_ROOT / "bridge.sqlite3"
    execution_timeout: float = 3600
    interaction_timeout: float = 600
    staging_ttl: float = 600
    max_attachments: int = 50
    max_attachment_bytes: int = 100 * 1024 * 1024
    delivery_immediate: bool = False
    download_timeout: float = 120
    poll_interval: float = 1
    reply_chunk_size: int = 1800
    text_typing_chars_per_second: float = 20
    text_typing_min_delay: float = 0.5
    text_typing_max_delay: float = 3
    typing_status_enabled: bool = True
    typing_refresh_interval: float = 5
    max_queued_per_context: int = 10
    log_level: str = "INFO"
    group_background_ttl_seconds: int = 86400
    group_background_max_messages: int = 200
    group_background_max_chars: int = 20000
    diagnostic_ttl_seconds: int = 604800
    diagnostic_max_events: int = 100000
    memory_enabled: bool = False
    memory_owner_user_id: int | None = None
    memory_api_key: str = field(default="", repr=False)
    memory_database_url: str = field(default="", repr=False)
    memory_db: Path = DATA_ROOT / "memory.sqlite3"
    memory_base_url: str = "https://api.siliconflow.cn/v1"
    memory_model: str = "deepseek-ai/DeepSeek-V3.2"
    memory_embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    memory_rerank_model: str = "Qwen/Qwen3-Reranker-8B"
    memory_dimensions: int = 1024
    memory_timeout: float = 90
    memory_search_timeout: float = 8
    memory_rerank_enabled: bool = True
    webui_enabled: bool = False
    webui_host: str = "127.0.0.1"
    webui_port: int = 8093
    webui_public_url: str = ""
    knowledge_enabled: bool = False
    napcat_tools_enabled: bool = False

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> Config:
        load_dotenv(env_file, override=False)
        env = os.environ
        numeric = {
            "execution_timeout": ("EXECUTION_TIMEOUT", "3600", True),
            "interaction_timeout": ("INTERACTION_TIMEOUT", "600", True),
            "staging_ttl": ("STAGING_TTL", "600", True),
            "max_attachments": ("MAX_ATTACHMENTS", "50", False),
            "max_attachment_bytes": ("MAX_ATTACHMENT_BYTES", "104857600", False),
            "download_timeout": ("DOWNLOAD_TIMEOUT", "120", True),
            "poll_interval": ("POLL_INTERVAL", "1", True),
            "reply_chunk_size": ("REPLY_CHUNK_SIZE", "1800", False),
            "text_typing_chars_per_second": ("TEXT_TYPING_CHARS_PER_SECOND", "20", True),
            "text_typing_min_delay": ("TEXT_TYPING_MIN_DELAY", "0.5", True),
            "text_typing_max_delay": ("TEXT_TYPING_MAX_DELAY", "3", True),
            "max_queued_per_context": ("MAX_QUEUED_PER_CONTEXT", "10", False),
            "typing_refresh_interval": ("TYPING_REFRESH_INTERVAL", "5", True),
            "image_timeout": ("IMAGE_TIMEOUT", "600", True),
        }
        numeric.update(
            {
                "group_background_ttl_seconds": ("GROUP_BACKGROUND_TTL_SECONDS", "86400", False),
                "group_background_max_messages": ("GROUP_BACKGROUND_MAX_MESSAGES", "200", False),
                "group_background_max_chars": ("GROUP_BACKGROUND_MAX_CHARS", "20000", False),
                "diagnostic_ttl_seconds": ("DIAGNOSTIC_TTL_SECONDS", "604800", False),
                "diagnostic_max_events": ("DIAGNOSTIC_MAX_EVENTS", "100000", False),
            }
        )
        auto = env.get("OPENCODE_AUTOSTART", "true").lower()
        if auto not in {"true", "false", "1", "0"}:
            raise ConfigError("OPENCODE_AUTOSTART 必须为 true 或 false")
        image_enabled = env.get("IMAGE_GENERATION_ENABLED", "false").lower()
        if image_enabled not in {"true", "false", "1", "0"}:
            raise ConfigError("IMAGE_GENERATION_ENABLED 必须为 true 或 false")
        typing_enabled = env.get("TYPING_STATUS_ENABLED", "true").lower()
        if typing_enabled not in {"true", "false", "1", "0"}:
            raise ConfigError("TYPING_STATUS_ENABLED 必须为 true 或 false")
        memory_enabled = env.get("MEMORY_ENABLED", "false").lower()
        memory_rerank = env.get("MEMORY_RERANK_ENABLED", "true").lower()
        webui_enabled = env.get("WEBUI_ENABLED", "false").lower()
        knowledge_enabled = env.get("KNOWLEDGE_ENABLED", "false").lower()
        napcat_tools_enabled = env.get("NAPCAT_TOOLS_ENABLED", "false").lower()
        if napcat_tools_enabled not in {"true", "false", "1", "0"}:
            raise ConfigError("NAPCAT_TOOLS_ENABLED 必须为 true 或 false")
        if knowledge_enabled not in {"true", "false", "1", "0"}:
            raise ConfigError("KNOWLEDGE_ENABLED 必须为 true 或 false")
        if webui_enabled not in {"true", "false", "1", "0"}:
            raise ConfigError("WEBUI_ENABLED 必须为 true 或 false")
        if any(v not in {"true", "false", "1", "0"} for v in (memory_enabled, memory_rerank)):
            raise ConfigError("MEMORY_ENABLED 与 MEMORY_RERANK_ENABLED 必须为 true 或 false")
        superadmins = qq_ids(env.get("SUPERADMIN_USER_ID", ""), "SUPERADMIN_USER_ID")
        memory_owners = qq_ids(
            env.get("MEMORY_OWNER_USER_ID") or env.get("SUPERADMIN_USER_ID", ""),
            "MEMORY_OWNER_USER_ID",
        )
        if len(memory_owners) > 1:
            raise ConfigError("MEMORY_OWNER_USER_ID 只能配置一个 QQ 号")
        if len(superadmins) > 1:
            raise ConfigError("SUPERADMIN_USER_ID 只能配置一个 QQ 号")
        cfg = cls(
            env_file=Path(env_file).expanduser().resolve(),
            napcat_url=env.get("NAPCAT_WS_URL", "ws://127.0.0.1:3001"),
            napcat_token=env.get("NAPCAT_TOKEN", ""),
            allowed_users=qq_ids(env.get("ALLOWED_USERS", ""), "ALLOWED_USERS"),
            allowed_groups=qq_ids(env.get("ALLOWED_GROUPS", ""), "ALLOWED_GROUPS"),
            superadmin_user_id=next(iter(superadmins), None),
            group_readonly_mcp_actions=frozenset(
                action.strip()
                for action in env.get("GROUP_READONLY_MCP_ACTIONS", "").split(",")
                if action.strip()
            ),
            excluded_prefixes=tuple(
                p.strip().casefold()
                for p in env.get("EXCLUDED_PREFIXES", "ww,mm,codex,core").split(",")
                if p.strip()
            ),
            workdir=Path(env.get("OPENCODE_WORKDIR", "~/qq-agent-workspace")).expanduser(),
            service_file=Path(
                env.get("OPENCODE_SERVICE_FILE", "~/.local/state/opencode/service.json")
            ).expanduser(),
            opencode_binary=env.get("OPENCODE_BINARY", "opencode"),
            autostart=auto in {"true", "1"},
            opencode_url=env.get("OPENCODE_URL", "").rstrip("/"),
            opencode_password=env.get("OPENCODE_PASSWORD", ""),
            opencode_username=env.get("OPENCODE_USERNAME", "opencode"),
            model=env.get("OPENCODE_MODEL", ""),
            image_generation_enabled=image_enabled in {"true", "1"},
            typing_status_enabled=typing_enabled in {"true", "1"},
            image_provider=env.get("IMAGE_PROVIDER", "custom"),
            image_model=env.get("IMAGE_MODEL", "your-image-model"),
            image_opencode_config=Path(
                env.get("IMAGE_OPENCODE_CONFIG", "~/.config/opencode/opencode.json")
            ).expanduser(),
            state_db=Path(env.get("STATE_DB", str(DATA_ROOT / "bridge.sqlite3"))).expanduser(),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            memory_enabled=memory_enabled in {"true", "1"},
            memory_owner_user_id=next(iter(memory_owners), None),
            memory_api_key=env.get("SILICONFLOW_API_KEY", ""),
            memory_database_url=env.get("MEMORY_DATABASE_URL", ""),
            memory_db=Path(env.get("MEMORY_DB", str(DATA_ROOT / "memory.sqlite3"))).expanduser(),
            memory_base_url=env.get("MEMORY_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/"),
            memory_model=env.get("MEMORY_MODEL", "deepseek-ai/DeepSeek-V3.2"),
            memory_embedding_model=env.get("MEMORY_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            memory_rerank_model=env.get("MEMORY_RERANK_MODEL", "Qwen/Qwen3-Reranker-8B"),
            memory_dimensions=int(
                positive(env.get("MEMORY_DIMENSIONS", "1024"), "MEMORY_DIMENSIONS")
            ),
            memory_timeout=float(
                positive(env.get("MEMORY_TIMEOUT", "90"), "MEMORY_TIMEOUT", floating=True)
            ),
            memory_search_timeout=float(
                positive(
                    env.get("MEMORY_SEARCH_TIMEOUT", "8"), "MEMORY_SEARCH_TIMEOUT", floating=True
                )
            ),
            memory_rerank_enabled=memory_rerank in {"true", "1"},
            webui_enabled=webui_enabled in {"true", "1"},
            knowledge_enabled=knowledge_enabled in {"true", "1"},
            napcat_tools_enabled=napcat_tools_enabled in {"true", "1"},
            delivery_immediate=env.get("DELIVERY_IMMEDIATE", "false").lower() in {"true", "1"},
            webui_host=env.get("WEBUI_HOST", "127.0.0.1"),
            webui_port=int(positive(env.get("WEBUI_PORT", "8093"), "WEBUI_PORT")),
            webui_public_url=env.get("WEBUI_PUBLIC_URL", "").rstrip("/"),
            **{
                key: positive(env.get(name, default), name, floating=floating)
                for key, (name, default, floating) in numeric.items()
            },
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not self.webui_host or not 1 <= self.webui_port <= 65535:
            raise ConfigError("WEBUI_HOST 不能为空；WEBUI_PORT 需在 1–65535 之间")
        if self.webui_public_url:
            public = urlsplit(self.webui_public_url)
            if (
                public.scheme not in {"http", "https"}
                or not public.hostname
                or public.username
                or public.password
                or public.query
                or public.fragment
                or public.path not in {"", "/"}
            ):
                raise ConfigError("WEBUI_PUBLIC_URL 必须是无凭据和路径的 HTTP(S) 地址")
        if self.memory_enabled or self.knowledge_enabled:
            if self.memory_enabled and self.memory_owner_user_id not in self.allowed_users:
                raise ConfigError("MEMORY_OWNER_USER_ID 必须属于 ALLOWED_USERS")
            if self.knowledge_enabled and self.superadmin_user_id not in self.allowed_users:
                raise ConfigError("知识库需要配置 SUPERADMIN_USER_ID")
            if not self.memory_api_key or not self.memory_database_url:
                raise ConfigError("启用记忆需要 SILICONFLOW_API_KEY 和 MEMORY_DATABASE_URL")
            endpoint = urlsplit(self.memory_base_url)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ConfigError("MEMORY_BASE_URL 必须为不含凭据的 HTTPS 地址")
            if not self.memory_db.is_absolute() or not 32 <= self.memory_dimensions <= 2000:
                raise ConfigError("MEMORY_DB 需为绝对路径；MEMORY_DIMENSIONS 需在 32–2000 之间")
        if self.napcat_tools_enabled and self.superadmin_user_id not in self.allowed_users:
            raise ConfigError("NapCat 能力工具需要配置 SUPERADMIN_USER_ID")
        positive(str(self.typing_refresh_interval), "TYPING_REFRESH_INTERVAL", floating=True)
        for name in (
            "text_typing_chars_per_second",
            "text_typing_min_delay",
            "text_typing_max_delay",
        ):
            positive(str(getattr(self, name)), name.upper(), floating=True)
        if self.text_typing_max_delay < self.text_typing_min_delay:
            raise ConfigError("TEXT_TYPING_MAX_DELAY 不能小于 TEXT_TYPING_MIN_DELAY")
        for name in (
            "group_background_ttl_seconds",
            "group_background_max_messages",
            "group_background_max_chars",
            "diagnostic_ttl_seconds",
            "diagnostic_max_events",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(f"{name.upper()} 必须为正整数")
        if not self.allowed_users:
            raise ConfigError("ALLOWED_USERS 不能为空；请先配置授权 QQ 号")
        if self.superadmin_user_id is not None and (
            isinstance(self.superadmin_user_id, bool)
            or self.superadmin_user_id not in self.allowed_users
        ):
            raise ConfigError("SUPERADMIN_USER_ID 必须是 ALLOWED_USERS 中的一个 QQ 号")
        for action in self.group_readonly_mcp_actions:
            if (
                "_" not in action
                or not action.replace("_", "").isascii()
                or not action.replace("_", "").isalnum()
                or action in {"external_directory", "apply_patch"}
                or any(
                    part
                    in {
                        "write",
                        "edit",
                        "delete",
                        "remove",
                        "patch",
                        "move",
                        "rename",
                        "create",
                        "append",
                        "save",
                        "copy",
                        "chmod",
                        "chown",
                    }
                    for part in action.lower().split("_")
                )
            ):
                raise ConfigError("GROUP_READONLY_MCP_ACTIONS 只能填写已确认只读的完整 MCP 动作名")
        if not self.napcat_token:
            raise ConfigError("NAPCAT_TOKEN 不能为空；请填写 OneBot WebSocket Token")
        for value, name, schemes in [
            (self.napcat_url, "NAPCAT_WS_URL", {"ws", "wss"}),
            (self.opencode_url, "OPENCODE_URL", {"http", "https"}),
        ]:
            if not value and name == "OPENCODE_URL":
                continue
            parsed = urlsplit(value)
            if (
                parsed.scheme not in schemes
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ConfigError(f"{name} 必须是无凭据、查询参数或 fragment 的有效地址")
        if not self.workdir.is_absolute() or not self.state_db.is_absolute():
            raise ConfigError("OPENCODE_WORKDIR 与 STATE_DB 必须使用绝对路径")
        if self.model and ("/" not in self.model or not all(self.model.split("/", 1))):
            raise ConfigError("OPENCODE_MODEL 必须为 provider/model")
        if self.image_generation_enabled:
            if not self.image_provider.strip() or not self.image_model.strip():
                raise ConfigError("IMAGE_PROVIDER 与 IMAGE_MODEL 不能为空")
            if not self.image_opencode_config.is_absolute():
                raise ConfigError("IMAGE_OPENCODE_CONFIG 必须使用绝对路径")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("LOG_LEVEL 无效")
