"""Token 管理。

TokenManager 为纯工具类，每次使用时独立实例化以避免多会话冲突。
不再保留模块级单例。

认证流程：
1. POST /api/auth/login → 返回 UUID token
2. 404 → 用户未注册，自动调 POST /api/auth/register
3. 401 → 密码错误
"""

import httpx
from nonebot.log import logger


class TokenManager:
    """管理单个用户的 LAZY SERVER token。"""

    def __init__(self, server_url: str, studentid: str, password: str):
        self.server_url = server_url
        self.studentid = studentid
        self.password = password
        self.token: str | None = None

    async def login(self) -> str:
        """登录获取 token，如未注册则自动注册。返回 token 字符串。"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.server_url}/api/auth/login",
                json={"studentid": self.studentid, "password": self.password},
                timeout=10,
            )
            if resp.status_code == 404:
                logger.info("用户未注册，尝试自动注册")
                resp = await client.post(
                    f"{self.server_url}/api/auth/register",
                    json={"studentid": self.studentid, "password": self.password},
                    timeout=10,
                )
            if resp.status_code == 401:
                raise RuntimeError("学号或密码错误")
            if resp.status_code != 200:
                raise RuntimeError(
                    f"认证失败 (HTTP {resp.status_code}): {resp.text}"
                )
            data = resp.json()
            self.token = data["token"]
            return self.token

    async def ensure_token(self) -> str:
        """确保 token 可用，如为 None 则自动登录。"""
        if self.token is None:
            await self.login()
        return self.token

    async def handle_401(self):
        """处理 token 过期：置空后重新登录。"""
        logger.warning("Token 失效，尝试重新登录")
        self.token = None
        try:
            await self.login()
        except Exception as e:
            logger.error(f"重新登录失败: {e}")
            raise
