"""LAZY 监控插件配置模型。

通过 Nonebot2 的 get_plugin_config 自动绑定 .env 中
LAZY_MONITOR__* 前缀的环境变量到 Pydantic 模型。
"""

from pydantic import BaseModel
from nonebot import get_plugin_config


class LazyMonitorConfig(BaseModel):
    """插件核心配置，所有字段均可通过 .env 覆盖。"""

    server_url: str = "http://127.0.0.1:8765"
    studentid: str = ""
    password: str = ""
    owner_qq: int = 0
    poll_interval: int = 30
    notify_groups: list[int] = []
    notify_users: list[int] = []
    enable_rollcall: bool = True
    enable_todo: bool = True
    max_retries: int = 3
    retry_delay: int = 5


class Config(BaseModel):
    """Nonebot2 需要顶层模型来解析嵌套的 LAZY_MONITOR__* 配置。"""

    lazy_monitor: LazyMonitorConfig


config = get_plugin_config(Config).lazy_monitor
