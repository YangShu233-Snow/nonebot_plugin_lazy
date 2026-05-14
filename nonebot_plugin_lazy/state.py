"""多用户会话管理与轮询状态追踪。

UserManager 维护所有已注册用户的内存状态：
- .env 账号（qq_id=-1）
- 私聊注册的普通用户

RuntimeConfig 管理白名单群和用户路由，持久化到 config.json。
首次启动时 seen_*_ids 为空 set，自然跳过第一轮通知。"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from nonebot.log import logger


DATA_DIR = Path("data") / "lazy_monitor"
DATA_FILE = DATA_DIR / "users.json"
CONFIG_FILE = DATA_DIR / "config.json"


@dataclass
class MonitorState:
    """每个用户独立的轮询状态，记录已通知过的 ID 以避免重复推送。"""

    seen_rollcall_ids: set[int] = field(default_factory=set)
    seen_todo_ids: set[int] = field(default_factory=set)


@dataclass
class UserSession:
    """单个用户的完整会话信息。"""

    qq_id: int
    studentid: str
    password: str
    token: str
    server_url: str
    state: MonitorState = field(default_factory=MonitorState)
    consecutive_failures: int = 0


class UserManager:
    """管理所有注册用户，提供增删查遍历操作。
    
    add_user / remove_user 会自动持久化到磁盘。
    """

    def __init__(self):
        self.users: dict[int, UserSession] = {}
        self._load()

    def add_user(
        self, qq_id: int, studentid: str,
        password: str, token: str, server_url: str,
    ) -> UserSession:
        session = UserSession(
            qq_id=qq_id,
            studentid=studentid,
            password=password,
            token=token,
            server_url=server_url,
        )
        self.users[qq_id] = session
        self._save()
        return session

    def remove_user(self, qq_id: int):
        self.users.pop(qq_id, None)
        self._save()

    def get_user(self, qq_id: int) -> UserSession | None:
        return self.users.get(qq_id)

    def all_users(self) -> list[UserSession]:
        return list(self.users.values())

    def flush(self):
        self._save()

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "qq_id": u.qq_id,
                "studentid": u.studentid,
                "password": u.password,
                "token": u.token,
                "server_url": u.server_url,
            }
            for u in self.users.values()
            if u.qq_id > 0
        ]
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self):
        if not DATA_FILE.exists():
            return
        try:
            raw = json.loads(DATA_FILE.read_text())
            for item in raw:
                qq_id = item["qq_id"]
                self.users[qq_id] = UserSession(
                    qq_id=qq_id,
                    studentid=item["studentid"],
                    password=item["password"],
                    token=item["token"],
                    server_url=item["server_url"],
                )
            if raw:
                logger.info(f"已从 {DATA_FILE} 恢复 {len(raw)} 个用户")
        except Exception as e:
            logger.error(f"加载持久化用户数据失败: {e}")


user_mgr = UserManager()


@dataclass
class RuntimeConfig:
    """运行时通知路由配置，持久化到 config.json。"""

    allowed_groups: list[int] = field(default_factory=list)
    per_user_routes: dict[int, list[int]] = field(default_factory=dict)

    def target_groups(self, qq_id: int) -> list[int]:
        """获取指定用户的通知目标群列表。"""
        allowed = set(self.allowed_groups)
        user_groups = self.per_user_routes.get(qq_id)
        if user_groups:
            return [g for g in user_groups if g in allowed]
        return list(allowed)


def save_config(cfg: RuntimeConfig):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "allowed_groups": cfg.allowed_groups,
        "per_user_routes": {str(k): v for k, v in cfg.per_user_routes.items()},
    }
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def load_config() -> RuntimeConfig:
    if not CONFIG_FILE.exists():
        return RuntimeConfig()
    try:
        raw = json.loads(CONFIG_FILE.read_text())
        per_user = {int(k): v for k, v in raw.get("per_user_routes", {}).items()}
        cfg = RuntimeConfig(
            allowed_groups=raw.get("allowed_groups", []),
            per_user_routes=per_user,
        )
        if raw:
            logger.info(f"已从 {CONFIG_FILE} 加载通知路由配置")
        return cfg
    except Exception as e:
        logger.error(f"加载通知路由配置失败: {e}")
        return RuntimeConfig()


runtime_config = load_config()
