"""用户交互命令处理器。

包含四大功能：
1. `/help` — 显示可用命令列表
2. `/register` — 群聊发起 → 私聊完成注册（自动绑定通知群）
3. `/task` — 任务管理（list / enable / disable / interval / reset）
4. `/lazy` — 管理员配置白名单群和用户路由（仅 SUPERUSERS）

所有命令使用 Nonebot2 标准 Matcher.got() 实现多步骤对话。"""

import httpx
from nonebot import on_command
from nonebot.rule import is_type, to_me
from nonebot.permission import SUPERUSER
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
from .state import user_mgr, runtime_config, save_config
from .auth import TokenManager


# 群聊 → 私聊注册接力暂存
_pending_group: dict[int, int] = {}


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
    """最终步骤：验证凭据 → 存入 UserManager → 检查群接力 → 完成。"""
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

    qq_id = event.user_id
    reply = f"✅ 注册成功！\n学号：{sid}"

    group_id = _pending_group.pop(qq_id, None)
    if group_id and group_id in runtime_config.allowed_groups:
        routes = runtime_config.per_user_routes.setdefault(qq_id, [])
        if group_id not in routes:
            routes.append(group_id)
            save_config(runtime_config)
        reply += f"\n通知将发送到群 {group_id}"
    else:
        reply += "\n您尚未绑定通知群，请联系管理员配置。"
    reply += "\n您将会收到点名和待办的通知。"

    await register.finish(reply)


register_group = on_command(
    "register",
    rule=is_type(GroupMessageEvent),
)

@register_group.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    """群聊中发送 /register 时记录群号，引导到私聊接力注册。"""
    gid = event.group_id
    uid = event.user_id
    if gid not in runtime_config.allowed_groups:
        await bot.send(
            event=event,
            message=MessageSegment.at(uid)
            + " 本群未在白名单中，请管理员使用 /lazy group add 添加。",
        )
        return
    if user_mgr.get_user(uid):
        await bot.send(
            event=event,
            message=MessageSegment.at(uid) + " 您已注册。",
        )
        return
    _pending_group[uid] = gid
    await bot.send(
        event=event,
        message=MessageSegment.at(uid)
        + " 已收到注册申请，请查看私聊消息完成注册。",
    )


# ── 帮助 ───────────────────────────────────────────

help_cmd = on_command("help", rule=to_me())

@help_cmd.handle()
async def _():
    await help_cmd.finish(
        "📋 可用命令：\n\n"
        "/register — 绑定学号密码（仅私聊）\n"
        "/task list — 查看监控任务列表\n"
        "/task enable <id> — 启用任务\n"
        "/task disable <id> — 停用任务\n"
        "/task interval <id> <秒> — 修改轮询间隔\n"
        "/task reset <id> — 恢复默认设置"
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


# ── 管理员配置 ────────────────────────────────────

lazy_cmd = on_command("lazy", rule=to_me(), permission=SUPERUSER)

@lazy_cmd.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    text = args.extract_plain_text().strip().split()
    if not text:
        await _lazy_help()
        return
    cmd = text[0]

    if cmd == "group" and len(text) >= 3:
        action, gid_str = text[1], text[2]
        if not gid_str.isdigit():
            await lazy_cmd.finish("群号必须为数字。")
            return
        gid = int(gid_str)

        if action == "add":
            if gid not in runtime_config.allowed_groups:
                runtime_config.allowed_groups.append(gid)
                save_config(runtime_config)
            await lazy_cmd.finish(f"✅ 群 {gid} 已加入白名单。")
        elif action == "remove":
            if gid in runtime_config.allowed_groups:
                runtime_config.allowed_groups.remove(gid)
                save_config(runtime_config)
            await lazy_cmd.finish(f"✅ 群 {gid} 已移出白名单。")
        else:
            await _lazy_help()

    elif cmd == "group" and text[1] == "list":
        await _lazy_group_list()

    elif cmd == "user" and len(text) >= 3:
        target_qq = int(text[1]) if text[1].isdigit() else None
        if not target_qq:
            await lazy_cmd.finish("QQ 号格式不正确。")
            return
        action = text[2]

        if action in ("bind", "unbind") and len(text) >= 4:
            gid = int(text[3]) if text[3].isdigit() else None
            if not gid:
                await lazy_cmd.finish("群号格式不正确。")
                return
            routes = runtime_config.per_user_routes.setdefault(target_qq, [])
            if action == "bind":
                if gid not in routes:
                    routes.append(gid)
                save_config(runtime_config)
                await lazy_cmd.finish(f"✅ 用户 {target_qq} 已绑定群 {gid}。")
            else:
                if gid in routes:
                    routes.remove(gid)
                save_config(runtime_config)
                await lazy_cmd.finish(f"✅ 用户 {target_qq} 已解绑群 {gid}。")

        elif action == "info":
            await _lazy_user_info(target_qq)
        else:
            await _lazy_help()

    elif cmd == "status":
        await _lazy_status()
    else:
        await _lazy_help()


async def _lazy_help():
    await lazy_cmd.finish(
        "📋 管理员命令（仅 SUPERUSERS）：\n\n"
        "/lazy group add <群号>          加入白名单\n"
        "/lazy group remove <群号>       移出白名单\n"
        "/lazy group list               查看白名单与路由\n"
        "/lazy user <QQ> bind <群号>     绑定用户通知路由\n"
        "/lazy user <QQ> unbind <群号>   解绑用户通知路由\n"
        "/lazy user <QQ> info           查看用户信息\n"
        "/lazy status                   查看全局状态"
    )


async def _lazy_group_list():
    lines = ["📋 白名单群列表"]
    for gid in runtime_config.allowed_groups:
        users = [
            str(qq) for qq, routes in runtime_config.per_user_routes.items()
            if gid in routes
        ]
        users_str = f" → 用户: {', '.join(users)}" if users else ""
        lines.append(f"  {gid}{users_str}")
    if not runtime_config.allowed_groups:
        lines.append("  （暂无白名单群）")
    await lazy_cmd.finish("\n".join(lines))


async def _lazy_user_info(target_qq: int):
    user = user_mgr.get_user(target_qq)
    if not user:
        await lazy_cmd.finish(f"用户 {target_qq} 未注册。")
        return

    routes = runtime_config.per_user_routes.get(target_qq, [])
    lines = [
        f"📋 用户 {target_qq} 信息",
        f"  学号: {user.studentid}",
        f"  Token: {'有效' if user.token else '无'}",
        f"  通知群: {routes if routes else '未绑定'}",
    ]
    await lazy_cmd.finish("\n".join(lines))


async def _lazy_status():
    lines = [
        "📋 全局配置概览",
        f"  白名单群数: {len(runtime_config.allowed_groups)}",
        f"  已注册用户: {len(user_mgr.all_users())}",
        f"  带路由用户: {len(runtime_config.per_user_routes)}",
        f"  点名监控: {'开' if config.enable_rollcall else '关'}",
        f"  待办监控: {'开' if config.enable_todo else '关'}",
        f"  轮询间隔: {config.poll_interval}s",
        f"  LAZY SERVER: {config.server_url}",
    ]
    await lazy_cmd.finish("\n".join(lines))
