"""通知格式化与消息发送。

支持两种通道：
- 群通知：根据 RuntimeConfig 路由表决定发送目标
- 私聊通知：直接发送给数据触发者

发送异常不会阻塞后续通知。"""

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from nonebot.log import logger

from .config import config
from .state import runtime_config


class Notifier:
    """格式化点名/待办消息并通过 OneBot API 发送。"""

    @staticmethod
    def _format_rollcall(item: dict) -> str:
        rollcall_type = "雷达点名" if item.get("is_radar") else "数字点名"
        return (
            f"🔔 新点名通知\n"
            f"————————\n"
            f"课程：{item.get('course_title', '未知')}\n"
            f"发起人：{item.get('created_by_name', '未知')}\n"
            f"类型：{rollcall_type}"
        )

    @staticmethod
    def _format_todo(item: dict) -> str:
        return (
            f"📋 新待办通知\n"
            f"————————\n"
            f"标题：{item.get('title', '未知')}\n"
            f"课程：{item.get('course_name', '未知')}\n"
            f"截止时间：{item.get('end_time', '未知')}"
        )

    def _resolve_at_qq(self, qq_id: int) -> int:
        """确定群通知中 @ 的 QQ 号。DM 注册用户 @ 自己，.env 账号 @ owner_qq。"""
        if qq_id > 0:
            return qq_id
        if config.owner_qq > 0:
            return config.owner_qq
        return -1

    def _target_groups(self, qq_id: int) -> list[int]:
        """根据运行时路由表决定当前用户的通知目标群。"""
        return runtime_config.target_groups(qq_id)

    async def notify_rollcalls(self, items: list[dict], qq_id: int):
        """批量发送点名通知。"""
        try:
            bot = get_bot()
        except ValueError:
            logger.error("没有可用的 Bot 实例")
            return

        at_qq = self._resolve_at_qq(qq_id)
        groups = self._target_groups(qq_id)

        for item in items:
            msg = self._format_rollcall(item)
            for group in groups:
                try:
                    if at_qq > 0:
                        full_msg = Message(
                            MessageSegment.at(at_qq) + f"\n{msg}"
                        )
                    else:
                        full_msg = Message(msg)
                    await bot.send_group_msg(
                        group_id=group, message=full_msg,
                    )
                except Exception as e:
                    logger.error(f"发送点名群通知失败 ({group}): {e}")

            if qq_id > 0:
                try:
                    await bot.send_private_msg(user_id=qq_id, message=msg)
                except Exception as e:
                    logger.error(
                        f"发送点名私聊通知失败 ({qq_id}): {e}"
                    )

    async def notify_todos(self, items: list[dict], qq_id: int):
        """批量发送待办通知。"""
        try:
            bot = get_bot()
        except ValueError:
            logger.error("没有可用的 Bot 实例")
            return

        at_qq = self._resolve_at_qq(qq_id)
        groups = self._target_groups(qq_id)

        for item in items:
            msg = self._format_todo(item)
            for group in groups:
                try:
                    if at_qq > 0:
                        full_msg = Message(
                            MessageSegment.at(at_qq) + f"\n{msg}"
                        )
                    else:
                        full_msg = Message(msg)
                    await bot.send_group_msg(
                        group_id=group, message=full_msg,
                    )
                except Exception as e:
                    logger.error(f"发送待办群通知失败 ({group}): {e}")

            if qq_id > 0:
                try:
                    await bot.send_private_msg(user_id=qq_id, message=msg)
                except Exception as e:
                    logger.error(
                        f"发送待办私聊通知失败 ({qq_id}): {e}"
                    )

    async def alert_superusers(self, msg: str):
        """给所有 SUPERUSERS 发送告警（用于连续失败场景）。"""
        try:
            bot = get_bot()
            for sid in bot.config.superusers:
                try:
                    await bot.send_private_msg(
                        user_id=int(sid), message=msg,
                    )
                except Exception:
                    pass
        except Exception:
            logger.error(f"无法发送告警消息: {msg}")


notifier = Notifier()
