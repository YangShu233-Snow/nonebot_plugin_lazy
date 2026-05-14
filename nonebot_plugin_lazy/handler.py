"""用户交互命令处理器。

包含两大功能：
1. `/register` — 私聊四步骤注册 / 群聊拒绝引导
2. `/task` — 任务管理（list / enable / disable / interval / reset）

所有命令使用 Nonebot2 标准 Matcher.got() 实现多步骤对话。"""

import httpx
from nonebot import on_command
from nonebot.rule import is_type, to_me
from nonebot.adapters.onebot.v11 import (
    Bot,
    MessageEvent,
    PrivateMessageEvent,
    GroupMessageEvent,
    MessageSegment,
    Message,
)
from nonebot.params import ArgPlainText, CommandArg
from nonebot.log import logger

from .config import config
from .state import user_mgr
from .auth import TokenManager


# ── 注册 ──────────────────────────────────────────

register = on_command(
    "register",
    rule=to_me() & is_type(PrivateMessageEvent),
)

@register.handle()
async def _(event: PrivateMessageEvent):
    if user_mgr.get_user(event.user_id):
        await register.finish(
            "您已经注册过了。如需重新注册，请联系管理员。"
        )

@register.got(
    "confirm",
    prompt=(
        "⚠️ 安全提示：\n"
        "您的学号和密码将存储在服务器上，"
        "Bot管理员可以查看这些信息。\n\n"
        "是否继续注册？（回复 是/否）"
    ),
)
async def _(event: PrivateMessageEvent, confirm: str = ArgPlainText()):
    if confirm.strip() not in ("是", "y", "yes", "Y", "Yes"):
        await register.finish(
            "注册已取消。如需重新注册，请再次发送 /register。"
        )

@register.got("studentid", prompt="请输入您的学号：")
async def _(studentid: str = ArgPlainText()):
    if not studentid.strip().isdigit():
        await register.reject("学号格式不正确，请输入纯数字学号：")

@register.got(
    "password",
    prompt="请输入密码（密码仅用于验证，验证后加密存储）：",
)
async def _(
    event: PrivateMessageEvent,
    studentid: str = ArgPlainText("studentid"),
    password: str = ArgPlainText(),
):
    """最终步骤：验证凭据 → 存入 UserManager → 完成注册。"""
    sid = studentid.strip()
    pwd = password.strip()
    tm = TokenManager(config.server_url, sid, pwd)
    try:
        token = await tm.login()
    except RuntimeError as e:
        await register.reject(
            f"验证失败：{e}\n请检查后重新输入密码"
            "（或发送 取消 中止）："
        )
    except Exception as e:
        logger.error(f"注册验证异常: {e}")
        await register.reject("验证失败：服务器异常，请稍后重试。")
        return

    user_mgr.add_user(
        event.user_id, sid, pwd, token, config.server_url,
    )
    await register.finish(
        f"✅ 注册成功！\n"
        f"学号：{sid}\n"
        f"您将会收到点名和待办的通知。"
    )


register_group = on_command(
    "register",
    rule=is_type(GroupMessageEvent),
)

@register_group.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    """群聊中发送 /register 时 @ 用户并引导至私聊。"""
    await bot.send(
        event=event,
        message=(
            MessageSegment.at(event.user_id)
            + " 请在私聊中使用 /register 进行注册"
        ),
    )


# ── 任务管理 ───────────────────────────────────────

task = on_command("task", rule=to_me())

@task.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    """解析 /task 子命令并分发到对应处理函数。"""
    user = user_mgr.get_user(event.user_id)
    if not user:
        await task.finish(
            "您还没有注册。请在私聊中使用 /register 注册。"
        )

    text = args.extract_plain_text().strip().split()
    cmd = text[0] if text else "list"

    if cmd == "list":
        await _task_list(user)
    elif cmd in ("enable", "disable") and len(text) >= 2:
        enabled = cmd == "enable"
        await _task_update(user, text[1], {"enabled": enabled})
    elif cmd == "interval" and len(text) >= 3:
        try:
            interval = int(text[2])
        except ValueError:
            await task.finish("间隔必须为数字（秒）。")
            return
        await _task_update(user, text[1], {"interval": interval})
    elif cmd == "reset" and len(text) >= 2:
        await _task_reset(user, text[1])
    else:
        await task.finish(
            "可用命令：\n"
            "/task list                     列出所有任务\n"
            "/task enable <task_id>         启用任务\n"
            "/task disable <task_id>        停用任务\n"
            "/task interval <task_id> <秒>  修改轮询间隔\n"
            "/task reset <task_id>          恢复默认"
        )


async def _task_list(user):
    """发送 GET /api/tasks 并格式化输出。"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{config.server_url}/api/tasks",
                params={"token": user.token},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"获取任务列表失败: {e}")
            await task.finish(f"获取任务列表失败：{e}")
            return

    tasks = data.get("tasks", [])
    if not tasks:
        await task.finish("暂无可用任务。")
        return

    lines = ["📋 任务列表"]
    for t in tasks:
        status = "✅" if t.get("enabled") else "⏹"
        override = " (已覆写)" if t.get("has_override") else ""
        lines.append(
            f"{status} {t['task_id']} — {t.get('description', '')}"
        )
        lines.append(
            f"   间隔: {t.get('interval')}s"
            f" | 状态: {t.get('cache_status')}{override}"
        )
    await task.finish("\n".join(lines))


async def _task_update(user, task_id: str, body: dict):
    """发送 PUT /api/tasks/{id} 修改任务配置。"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.put(
                f"{config.server_url}/api/tasks/{task_id}",
                params={"token": user.token},
                json=body,
                timeout=10,
            )
            if resp.status_code == 401:
                await task.finish(
                    "Token 已失效，请在私聊中重新注册。"
                )
                return
            if resp.status_code == 404:
                await task.finish(f"任务 {task_id} 不存在。")
                return
            resp.raise_for_status()
            await task.finish(f"✅ 任务 {task_id} 已更新。")
        except Exception as e:
            logger.error(f"更新任务失败: {e}")
            await task.finish(f"更新任务失败：{e}")


async def _task_reset(user, task_id: str):
    """发送 DELETE /api/tasks/{id} 重置为系统默认。"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.delete(
                f"{config.server_url}/api/tasks/{task_id}",
                params={"token": user.token},
                timeout=10,
            )
            if resp.status_code == 401:
                await task.finish(
                    "Token 已失效，请在私聊中重新注册。"
                )
                return
            resp.raise_for_status()
            msg = resp.json().get("message", "已重置")
            await task.finish(f"✅ 任务 {task_id} {msg}。")
        except Exception as e:
            logger.error(f"重置任务失败: {e}")
            await task.finish(f"重置任务失败：{e}")
