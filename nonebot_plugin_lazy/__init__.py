"""nonebot_plugin_lazy — Nonebot2 插件入口。

启动时自动加载 APScheduler，可选注册 .env 账号，然后启动定时轮询。

消息处理器在 handler.py 中通过 import 副效应注册到 Nonebot2。"""

from nonebot.plugin import require
from nonebot import get_driver
from nonebot.log import logger

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .config import config
from .state import user_mgr
from .auth import TokenManager
from .monitor import Poller

from . import handler  # noqa: F401 — 注册消息处理器

driver = get_driver()

poller = Poller()


@driver.on_startup
async def startup():
    if config.studentid and config.password:
        tm = TokenManager(
            config.server_url, config.studentid, config.password,
        )
        try:
            token = await tm.login()
            qq_id = config.owner_qq if config.owner_qq > 0 else -1
            user_mgr.add_user(
                qq_id,
                config.studentid,
                config.password,
                token,
                config.server_url,
            )
            logger.success(
                f".env 账号 {config.studentid} 自动注册成功"
            )
        except Exception as e:
            logger.error(f".env 账号注册失败: {e}")

    scheduler.add_job(
        poller.run,
        "interval",
        seconds=config.poll_interval,
        id="lazy_poll",
    )
