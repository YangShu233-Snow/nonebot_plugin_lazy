"""多用户会话管理与轮询状态追踪。

UserManager 维护所有已注册用户的内存状态：
- .env 账号（qq_id=-1）
- 私聊注册的普通用户

首次启动时 seen_*_ids 为空 set，自然跳过第一轮通知。
"""

from dataclasses import dataclass, field


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
    """管理所有注册用户，提供增删查遍历操作。"""

    def __init__(self):
        self.users: dict[int, UserSession] = {}

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
        return session

    def remove_user(self, qq_id: int):
        self.users.pop(qq_id, None)

    def get_user(self, qq_id: int) -> UserSession | None:
        return self.users.get(qq_id)

    def all_users(self) -> list[UserSession]:
        return list(self.users.values())


user_mgr = UserManager()
