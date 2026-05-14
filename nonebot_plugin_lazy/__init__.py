"""nonebot_plugin_lazy — Nonebot2 插件入口。

启动时自动加载 APScheduler，可选注册 .env 账号，然后启动定时轮询。

消息处理器在 handler.py 中通过 import 副效应注册到 Nonebot2。"""

from nonebot.plugin import require
from nonebot import get_driver
from nonebot.log import logger

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .config import config
from .state import user_mgr, runtime_config, save_config
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

    for user in list(user_mgr.all_users()):
        if user.qq_id <= 0:
            continue
        tm = TokenManager(user.server_url, user.studentid, user.password)
        tm.token = user.token
        try:
            await tm.ensure_token()
            user.token = tm.token
            user_mgr.flush()
            logger.success(f"用户 {user.studentid} 凭证恢复成功")
        except Exception as e:
            logger.warning(
                f"用户 {user.studentid} 凭证恢复失败，将在轮询中重试: {e}"
            )

    if not runtime_config.allowed_groups and config.notify_groups:
        runtime_config.allowed_groups = list(config.notify_groups)
        save_config(runtime_config)
        logger.info(
            f"已将 .env notify_groups 导入运行时配置: {config.notify_groups}"
        )

    scheduler.add_job(
        poller.run,
        "interval",
        seconds=config.poll_interval,
        id="lazy_poll",
    )
