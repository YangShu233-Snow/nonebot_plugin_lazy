"""通知格式化与消息发送。

检测到新项目时将当前所有任务渲染为 HTML 表格图片，
发送到白名单群（含 @用户）和私聊。

发送异常不会阻塞后续通知。
图片渲染失败时降级为纯文本。"""

import base64
from datetime import datetime

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from nonebot.log import logger

from .config import config
from .state import runtime_config

try:
    from nonebot_plugin_htmlrender import html_to_pic
except ImportError:
    html_to_pic = None


_ROLLCALL_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{style}</head><body>{body}</body></html>"""

_STYLE = """<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#f0f2f5;padding:16px;font-family:'Microsoft YaHei','PingFang SC',sans-serif;font-size:14px;color:#1a1a1a}}
.card{{background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
.header{{padding:14px 16px 8px;font-size:17px;font-weight:600}}
table{{width:100%;border-collapse:collapse}}
th{{padding:10px 12px;text-align:left;color:#666;font-weight:500;font-size:13px;border-bottom:1px solid #eee;background:#f8f9fc}}
td{{padding:10px 12px;border-bottom:1px solid #f0f0f0;font-size:14px}}
tr:last-child td{{border-bottom:none}}
.time{{color:#999;font-size:13px}}
.footer{{padding:10px 16px;color:#999;font-size:12px;border-top:1px solid #f0f0f0}}
</style>"""


class Notifier:
    """将点名/待办数据渲染为图片并通过 OneBot API 发送。"""

    @staticmethod
    def _format_time(iso_str: str | None) -> str:
        if not iso_str:
            return "未知"
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            return str(iso_str)

    @staticmethod
    def _build_rollcall_html(items: list[dict]) -> str:
        sorted_items = sorted(
            items,
            key=lambda x: x.get("start_time", "") or "",
        )
        rows = []
        for item in sorted_items:
            at = "雷达点名" if item.get("is_radar") else "数字点名"
            rows.append(
                f"<tr><td>{item.get('course_title','')}</td>"
                f"<td>{item.get('created_by_name','')}</td>"
                f"<td>{at}</td>"
                f'<td class="time">'
                f'{Notifier._format_time(item.get("start_time"))}</td></tr>'
            )
        body = (
            f'<div class="card">'
            f'<div class="header">🔔 当前进行中点名</div>'
            f"<table><thead><tr>"
            f"<th>课程</th><th>发起人</th><th>类型</th><th>时间</th>"
            f"</tr></thead><tbody>"
            f'{"".join(rows)}'
            f"</tbody></table>"
            f'<div class="footer">共 {len(sorted_items)} 条点名</div>'
            f"</div>"
        )
        return _ROLLCALL_HTML.format(style=_STYLE, body=body)

    @staticmethod
    def _build_todo_html(items: list[dict]) -> str:
        sorted_items = sorted(
            items,
            key=lambda x: x.get("end_time", "") or "",
        )
        rows = []
        for item in sorted_items:
            rows.append(
                f"<tr><td>{item.get('title','')}</td>"
                f"<td>{item.get('course_name','')}</td>"
                f'<td class="time">'
                f'{Notifier._format_time(item.get("end_time"))}</td></tr>'
            )
        body = (
            f'<div class="card">'
            f'<div class="header">📋 当前待办任务</div>'
            f"<table><thead><tr>"
            f"<th>标题</th><th>课程</th><th>截止时间</th>"
            f"</tr></thead><tbody>"
            f'{"".join(rows)}'
            f"</tbody></table>"
            f'<div class="footer">共 {len(sorted_items)} 条待办</div>'
            f"</div>"
        )
        return _ROLLCALL_HTML.format(style=_STYLE, body=body)

    async def _render_image(self, html: str) -> bytes | None:
        if html_to_pic is None:
            logger.error("html_to_pic 不可用（nonebot_plugin_htmlrender 未安装）")
            return None
        try:
            return await html_to_pic(html, viewport={"width": 560})
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")
            return None

    def _resolve_at_qq(self, qq_id: int) -> int:
        if qq_id > 0:
            return qq_id
        if config.owner_qq > 0:
            return config.owner_qq
        return -1

    def _target_groups(self, qq_id: int) -> list[int]:
        return runtime_config.target_groups(qq_id)

    async def _send_image(self, qq_id: int, pic_bytes: bytes, groups: list[int]):
        bot = get_bot()
        b64 = base64.b64encode(pic_bytes).decode()
        img = MessageSegment.image(f"base64://{b64}")
        at_qq = self._resolve_at_qq(qq_id)

        for gid in groups:
            try:
                msg = (
                    Message(MessageSegment.at(at_qq)).append(img)
                    if at_qq > 0 else Message(img)
                )
                await bot.send_group_msg(group_id=gid, message=msg)
            except Exception as e:
                logger.error(f"发送群通知失败 ({gid}): {e}")

        if qq_id > 0:
            try:
                await bot.send_private_msg(user_id=qq_id, message=img)
            except Exception as e:
                logger.error(f"发送私聊通知失败 ({qq_id}): {e}")

    async def _send_text_fallback(self, qq_id: int, text: str, groups: list[int]):
        bot = get_bot()
        at_qq = self._resolve_at_qq(qq_id)
        for gid in groups:
            try:
                msg = Message(MessageSegment.at(at_qq) + f"\n{text}") if at_qq > 0 else Message(text)
                await bot.send_group_msg(group_id=gid, message=msg)
            except Exception as e:
                logger.error(f"发送群通知失败 ({gid}): {e}")
        if qq_id > 0:
            try:
                await bot.send_private_msg(user_id=qq_id, message=text)
            except Exception as e:
                logger.error(f"发送私聊通知失败 ({qq_id}): {e}")

    async def notify_rollcalls(self, qq_id: int, items: list[dict]):
        try:
            bot = get_bot()
        except ValueError:
            logger.error("没有可用的 Bot 实例")
            return
        groups = self._target_groups(qq_id)
        html = self._build_rollcall_html(items)
        pic = await self._render_image(html)
        if pic:
            await self._send_image(qq_id, pic, groups)
        else:
            text = "\n\n".join(
                f"🔔 点名\n课程：{i.get('course_title','')}\n"
                f"发起人：{i.get('created_by_name','')}"
                for i in items
            )
            await self._send_text_fallback(qq_id, text, groups)

    async def notify_todos(self, qq_id: int, items: list[dict]):
        try:
            bot = get_bot()
        except ValueError:
            logger.error("没有可用的 Bot 实例")
            return
        groups = self._target_groups(qq_id)
        html = self._build_todo_html(items)
        pic = await self._render_image(html)
        if pic:
            await self._send_image(qq_id, pic, groups)
        else:
            text = "\n\n".join(
                f"📋 待办\n标题：{i.get('title','')}\n"
                f"截止：{self._format_time(i.get('end_time'))}"
                for i in items
            )
            await self._send_text_fallback(qq_id, text, groups)

    async def alert_superusers(self, msg: str):
        try:
            bot = get_bot()
            for sid in bot.config.superusers:
                try:
                    await bot.send_private_msg(user_id=int(sid), message=msg)
                except Exception:
                    pass
        except Exception:
            logger.error(f"无法发送告警消息: {msg}")


notifier = Notifier()
