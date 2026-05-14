"""轮询引擎 — 多用户差异检测。

Poller 遍历 UserManager 中所有注册用户，每人独立：
1. 确保 Token 有效
2. 拉取点名/待办数据
3. 与 seen_ids 做 diff，发现新项后触发通知
4. 更新 seen_ids

首次启动时所有 seen_ids 为空，自动跳过第一轮通知。
"""

import httpx
from nonebot.log import logger

from .config import config
from .state import user_mgr, UserSession
from .auth import TokenManager
from .notifier import notifier


def _extract_items(data, key: str) -> list[dict]:
    """从 LAZY SERVER 响应中提取数据项列表。

    兼容多种返回格式：list 直接返回，dict 尝试预设 key 列表，
    保证与 LAZY server 侧 _extract_items 逻辑一致。
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in (
            key, "rollcalls", "todos", "items",
            "data", "list", "uploads", "activities",
        ):
            if k in data and isinstance(data[k], list):
                return data[k]
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


class Poller:
    """定时轮询调度器，处理所有注册用户的数据拉取和通知触发。"""

    async def run(self):
        """一次完整的轮询：遍历所有用户。"""
        for user in list(user_mgr.all_users()):
            try:
                await self._poll_user(user)
            except Exception as e:
                logger.error(
                    f"轮询用户 {user.studentid} 时发生未预期错误: {e}"
                )

    async def _poll_user(self, user: UserSession):
        """处理单个用户的轮询（Token 管理 → 数据拉取 → diff 通知）。"""
        tm = TokenManager(user.server_url, user.studentid, user.password)
        tm.token = user.token

        try:
            await tm.ensure_token()
        except Exception as e:
            user.consecutive_failures += 1
            logger.error(
                f"用户 {user.studentid} Token 失败"
                f" ({user.consecutive_failures}/5): {e}"
            )
            if user.consecutive_failures >= 5:
                await notifier.alert_superusers(
                    f"用户 {user.studentid} 连续 5 次轮询失败"
                )
            return

        user.consecutive_failures = 0
        user.token = tm.token

        async with httpx.AsyncClient() as client:
            if config.enable_rollcall:
                await self._poll_rollcall(client, user, tm)
            if config.enable_todo:
                await self._poll_todo(client, user, tm)

    async def _fetch_data(
        self, client: httpx.AsyncClient,
        tm: TokenManager, task_id: str,
    ) -> dict | None:
        """拉取单任务数据，自动处理 401 重新认证。"""
        url = f"{config.server_url}/api/data/{task_id}"
        try:
            resp = await client.get(
                url, params={"token": tm.token}, timeout=10,
            )
            if resp.status_code == 401:
                logger.warning("Token 失效 (401)，尝试重新登录")
                await tm.handle_401()
                resp = await client.get(
                    url, params={"token": tm.token}, timeout=10,
                )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"拉取 {task_id} 数据失败: {e}")
            return None

    async def _poll_rollcall(
        self, client: httpx.AsyncClient,
        user: UserSession, tm: TokenManager,
    ):
        body = await self._fetch_data(client, tm, "rollcall_watch")
        if body is None:
            return
        if body.get("status") != "ok" or body.get("data") is None:
            return

        items = _extract_items(body["data"], "rollcalls")
        if not items:
            return

        has_new = any(
            item.get("rollcall_id") not in user.state.seen_rollcall_ids
            for item in items
        )
        if has_new:
            await notifier.notify_rollcalls(user.qq_id, items)

        user.state.seen_rollcall_ids.update(
            item["rollcall_id"]
            for item in items if "rollcall_id" in item
        )

    async def _poll_todo(
        self, client: httpx.AsyncClient,
        user: UserSession, tm: TokenManager,
    ):
        body = await self._fetch_data(client, tm, "todo_watch")
        if body is None:
            return
        if body.get("status") != "ok" or body.get("data") is None:
            return

        items = _extract_items(body["data"], "todos")
        if not items:
            return

        has_new = any(
            item.get("id") not in user.state.seen_todo_ids
            for item in items
        )
        if has_new:
            await notifier.notify_todos(user.qq_id, items)

        user.state.seen_todo_ids.update(
            item["id"] for item in items if "id" in item
        )
