# nonebot_plugin_lazy — 技术设计

## 项目概述

`nonebot_plugin_lazy` 是基于 Nonebot2 框架的 QQ 机器人插件，作为 LAZY SERVER 的 HTTP 消费者，定时轮询点名/todo 数据，发现新项目后通过 QQ 群/私聊通知用户。

**作为插件安装到已有 Nonebot2 Bot 中，不包含 bot.py。**

```
┌──────────────┐  HTTP (poll)  ┌──────────┐  httpx   ┌────────────┐
│ lazy_monitor  │ ──────────→ │ LAZY SERVER │ ─────→ │ 学在浙大 API │
│ (Nonebot 插件) │              │ (FastAPI)   │         │             │
└──────┬───────┘              └──────────┘         └────────────┘
       │
       │ OneBot V11 (反向 WS)
       ▼
┌──────────┐
│ go-cqhttp │
└──────────┘
       │ QQ 协议
       ▼
   QQ 群 / 私聊
```

零代码依赖 LAZY 仓库，仅通过 REST API 通信。

## 仓库结构

```
nonebot_plugin_lazy/
├── nonebot_plugin_lazy/     ← pip/nb install 的标准包
│   ├── __init__.py          # 插件入口 + 定时任务注册 + UserManager 初始化
│   ├── config.py            # Pydantic 配置模型
│   ├── state.py             # UserSession + UserManager + MonitorState
│   ├── auth.py              # Token 管理（登录/刷新）
│   ├── monitor.py           # 轮询 + 差异检测（多用户）
│   ├── notifier.py          # 通知格式化 + 发送（@用户，非@all）
│   └── handler.py           # 消息处理器（注册 + 任务管理）
│
├── src/plugins/
│   └── lazy_monitor/
│       └── __init__.py      # 向后兼容 shim（转发到 nonebot_plugin_lazy）
│
├── pyproject.toml           # 构建配置 + nb plugin install 元数据
├── .env.example             # 配置模板（仅插件相关）
├── README.md
├── LICENSE                  # AGPL-3.0
├── PLAN.md                  # 本文件
└── .gitignore
```

## 技术选型

| 组件 | 选型 | 说明 |
|------|------|------|
| Bot 框架 | Nonebot2 ≥2.4.0 | 异步 Python QQ 机器人框架 |
| 适配器 | nonebot-adapter-onebot ≥2.4.0 | OneBot V11 协议，反向 WebSocket |
| 定时任务 | nonebot-plugin-apscheduler | interval 触发器 |
| HTTP 客户端 | httpx ≥0.28.0 | 与 LAZY 技术栈一致 |
| 配置管理 | Nonebot 原生 get_plugin_config() | 类型安全，.env 自动绑定 |
| 多步骤对话 | Nonebot2 Matcher.got() | 内建多步骤收集用户输入 |
| Python | ≥3.12 | 与 LAZY SERVER 一致 |
| QQ 协议端 | go-cqhttp / Lagrange | OneBot V11 实现端 |

## LAZY SERVER API 接口

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/login` | 登录，返回 UUID token (32位 hex) |
| `POST` | `/api/auth/register` | 首次注册（login 返回 404 时调用） |

### 数据（核心轮询端点）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/data/rollcall_watch?token=` | 点名数据，响应 `{data: {rollcalls: [...]}}` |
| `GET` | `/api/data/todo_watch?token=` | 待办数据，响应 `{data: {todos: [...]}}` |

### 任务管理（用户可操作）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/tasks?token=` | 列出用户所有监控任务及状态 |
| `PUT` | `/api/tasks/{task_id}?token=` | 覆写任务 interval / enabled |
| `DELETE` | `/api/tasks/{task_id}?token=` | 重置任务为系统默认 |

`PUT` 请求体：

```json
{
    "interval": 120,
    "enabled": true
}
```

两个字段均可选，传 null 表示不修改。

响应格式：

```json
// rollcall_watch
{
    "status": "ok",
    "task_id": "rollcall_watch",
    "data": {
        "rollcalls": [
            {
                "rollcall_id": 123456,
                "course_title": "新中国史",
                "created_by_name": "陈荣",
                "is_radar": true,
                "start_time": "2026-05-13T08:00:00Z",
                "end_time": "2026-05-13T08:30:00Z"
            }
        ]
    }
}

// todo_watch
{
    "status": "ok",
    "task_id": "todo_watch",
    "data": {
        "todos": [
            {
                "id": 456789,
                "title": "微积分第四章作业",
                "course_name": "微积分（上）",
                "end_time": "2026-05-20T23:59:00Z"
            }
        ]
    }
}
```

### 状态码

| 状态 | 含义 | 处理 |
|------|------|------|
| `status: "ok"` | 数据可用 | 正常处理 |
| `status: "pending"` | 服务器尚未拉取数据 | 跳过本轮 |
| `data: null` | 暂无数据 | 跳过本轮 |
| 401 | Token 无效 | 自动 re-login，重试一次 |
| 404 | 用户未注册 | 自动调用 register |

## 插件配置模型

```python
# config.py
class LazyMonitorConfig(BaseModel):
    server_url: str = "http://127.0.0.1:8765"
    studentid: str = ""                     # 学号（可选，空=等待 DM 注册）
    password: str = ""                      # 密码（可选）
    owner_qq: int = 0                       # .env 账号对应的 QQ 号（0=未设置）
    poll_interval: int = 30                 # 轮询间隔（秒）

    notify_groups: list[int] = []           # 群通知目标群号
    notify_users: list[int] = []            # 私聊通知目标 QQ 号（额外广播）

    enable_rollcall: bool = True            # 启用点名监控
    enable_todo: bool = True                # 启用待办监控

    max_retries: int = 3                    # 请求最大重试
    retry_delay: int = 5                    # 重试间隔（秒）

class Config(BaseModel):
    lazy_monitor: LazyMonitorConfig

config = get_plugin_config(Config).lazy_monitor
```

### .env 配置模板

```dotenv
LAZY_MONITOR__SERVER_URL=http://127.0.0.1:8765
LAZY_MONITOR__STUDENTID=3240100106
LAZY_MONITOR__PASSWORD=***
LAZY_MONITOR__OWNER_QQ=123456789
LAZY_MONITOR__POLL_INTERVAL=30
LAZY_MONITOR__NOTIFY_GROUPS=[123456789]
LAZY_MONITOR__NOTIFY_USERS=[987654321]
LAZY_MONITOR__ENABLE_ROLLCALL=true
LAZY_MONITOR__ENABLE_TODO=true
LAZY_MONITOR__MAX_RETRIES=3
LAZY_MONITOR__RETRY_DELAY=5
```

## 核心模块

### state.py — 多用户会话管理

```python
@dataclass
class MonitorState:
    seen_rollcall_ids: set[int] = field(default_factory=set)
    seen_todo_ids: set[int] = field(default_factory=set)

@dataclass
class UserSession:
    qq_id: int                    # QQ 号（-1 = .env 账号）
    studentid: str                # 学号
    token: str                    # LAZY SERVER token
    server_url: str               # 服务器地址
    state: MonitorState = field(default_factory=MonitorState)
    consecutive_failures: int = 0

class UserManager:
    users: dict[int, UserSession]         # qq_id → session
    registration_states: dict[int, str]   # 注册中用户的步骤
    temp_data: dict[int, dict]            # 注册过程中的临时数据

    def add_user(qq_id, studentid, token, server_url) -> UserSession
    def remove_user(qq_id)
    def get_user(qq_id) -> UserSession | None
    def all_users() -> list[UserSession]
```

- 首次轮询 `seen_*_ids` 为空 set，自然过滤所有项（不触发通知）
- `registration_states` 跟踪注册进度：`"confirm"` → `"studentid"` → `"password"`

### auth.py — Token 管理

- `TokenManager` 纯工具类（无模块级单例）
- `login()`: POST `/api/auth/login` → 获取 UUID token；404 → POST `/api/auth/register`
- `ensure_token()`: 每次 API 调用前检查，token 为 None 则自动 login
- `handle_401()`: 收到 401 后重新 login，最多重试 2 次
- 每次使用独立实例化

### monitor.py — 多用户轮询 + 差异检测

```
scheduled_job (interval=30s):
  遍历 user_mgr.all_users() → 对每个用户:
    1. 实例化 TokenManager，重复使用用户已有 token
    2. token_mgr.ensure_token()
    3. if enable_todo: GET /api/data/todo_watch
    4. if enable_rollcall: GET /api/data/rollcall_watch
    5. 对每个响应：
       - status==pending 或 data==null → 跳过
       - 提取 items: data["rollcalls"] / data["todos"]
       - diff: new_ids = items where id not in user.state.seen_*_ids
       - 有新增 → notifier.notify_rollcalls/todos(items, user.qq_id)
       - 更新 user.state.seen_*_ids
    6. 异常处理 → user.consecutive_failures++
    7. 成功 → user.consecutive_failures 清零
```

差异检测：

```python
def _extract_items(data, key: str) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in (key, "rollcalls", "todos", "items", "data", "list", "uploads", "activities"):
            if k in data and isinstance(data[k], list):
                return data[k]
        for v in data.values():
            if isinstance(v, list):
                return v
    return []
```

与 LAZY server monitor.py 中 `_extract_items` 逻辑完全一致，兼容多种返回格式。

### notifier.py — 通知发送（@用户）

- 群通知：`bot.send_group_msg(group_id=group, message=msg)` 含 `MessageSegment.at(qq_id)`
- 私聊通知：`bot.send_private_msg(user_id=qq_id, message=msg)` 发送给数据触发者
- `notify_users` 列表额外广播（可选，接收所有通知）
- 消息发送逐条 try/except，不阻塞后续通知
- 消息格式：

```
点名通知:
🔔 新点名通知
————————
课程：新中国史
发起人：陈荣
类型：雷达点名

待办通知:
📋 新待办通知
————————
标题：微积分第四章作业
课程：微积分（上）
截止时间：2026-05-20 23:59
```

### handler.py — 消息处理器（新建）

#### 注册命令：`/register`

**私聊场景（四步骤）：**

| 步骤 | 触发 | Bot 回复 |
|------|------|----------|
| 1 | 用户发送 `/register` | ⚠️ 安全提示：学号和密码将存储在服务器上，Bot管理员可查看。是否继续？（回复 是/否） |
| 2 | 用户回复 `是` | 请输入学号： |
| 3 | 用户输入学号 | 请输入密码： |
| 4 | 用户输入密码 | 验证中... → ✅ 学号 XXX 已绑定 / ❌ 验证失败 |

**步骤 4 验证逻辑：**
1. 调用 LAZY SERVER `POST /api/auth/login`
2. 404 → 调用 `POST /api/auth/register`
3. 成功 → `UserManager.add_user(qq_id, studentid, token, server_url)`
4. 失败 → `matcher.reject("学号或密码错误，请重新输入")`，返回步骤 3

**群聊场景：**

```
用户: /register
Bot:  @用户 "请在私聊中使用 /register 进行注册"
```

#### 任务管理命令：`/task`

从 `UserManager` 获取当前发送者的 token，调用 LAZY SERVER 任务管理 API。

| 命令 | 实现 |
|------|------|
| `/task` 或 `/task list` | `GET /api/tasks?token=` → 格式化输出所有任务及状态 |
| `/task enable <task_id>` | `PUT /api/tasks/{task_id}?token=` `{"enabled": true}` |
| `/task disable <task_id>` | `PUT /api/tasks/{task_id}?token=` `{"enabled": false}` |
| `/task interval <task_id> <秒>` | `PUT /api/tasks/{task_id}?token=` `{"interval": <秒>}` |
| `/task reset <task_id>` | `DELETE /api/tasks/{task_id}?token=` |

SUPERUSERS 可以使用 `/task --user <qq_id> enable <task_id>` 管理任意用户的配置。

### __init__.py — 插件入口

```python
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler
from nonebot import get_driver

from .config import config
from .state import UserManager
from .auth import TokenManager
from .monitor import Poller

driver = get_driver()

user_mgr = UserManager()
poller = Poller(user_mgr)

@driver.on_startup
async def startup():
    # 1. 如果 .env 配置了凭据，自动注册
    if config.studentid and config.password:
        tm = TokenManager(config.server_url, config.studentid, config.password)
        token = await tm.login()
        user_mgr.add_user(
            qq_id=config.owner_qq if config.owner_qq > 0 else -1,
            studentid=config.studentid,
            token=token,
            server_url=config.server_url,
        )
    # 2. 启动定时轮询
    scheduler.add_job(
        poller.run,
        "interval",
        seconds=config.poll_interval,
        id="lazy_poll",
    )
```

## 注册流程时序

```
  User                  Bot                    LAZY SERVER
   │                     │                         │
   │  /register ────────►│                         │
   │                     │                         │
   │  ⚠️ 安全提示 + 确认◄─│                         │
   │                     │                         │
   │  是 ───────────────►│                         │
   │                     │                         │
   │  请输入学号 ◄───────│                         │
   │                     │                         │
   │  3240100106 ───────►│                         │
   │                     │                         │
   │  请输入密码 ◄───────│                         │
   │                     │                         │
   │  ******* ──────────►│                         │
   │                     │  POST /api/auth/login ─►│
   │                     │◄── {token: "abc123"} ──│
   │                     │                         │
   │  ✅ 注册成功 ◄─────│                         │
   │                     │                         │
   ▼                     ▼                         ▼
```

## 启动流程

```
bot 启动 → 加载 lazy_monitor 插件
  → driver.on_startup:
      → 若 .env 有凭据：登录 LAZY SERVER，注册为 qq_id=-1 的用户
      → scheduler 开始定时轮询(poll_interval=30s)
  → 用户发送 /register：
      → 群聊：被拒绝并指引到私聊
      → 私聊：四步骤注册流程 → 验证 → 绑定
  → 每 30s:
      → 遍历所有注册用户
      → 每人独立 GET /api/data/rollcall_watch + /api/data/todo_watch
      → diff 检测 → 通知（群@该用户 + 私聊）
```

## 错误处理

| 场景 | 处理 |
|------|------|
| Server 不可达 | 记录日志，跳过本轮，`consecutive_failures++`。连续 5 次失败给 SUPERUSERS 发告警 |
| Token 过期 (401) | `handle_401()` 自动重登录，最多 2 次尝试 |
| API 数据异常 | `_extract_items` 返回空列表，静默跳过 |
| data.status == "pending" | 服务器尚未拉取数据，跳过本轮 |
| data == null | 暂无数据，跳过本轮 |
| QQ 消息发送失败 | 逐条 try/except，不阻塞后续通知 |
| 首次启动 | `seen_*_ids` 为空 set，自然过滤所有项，不触发通知 |
| 注册验证失败 | `matcher.reject()` 提示重新输入 |
| .env 凭据无效 | 日志告警，等待 DM 注册补充 |

## 部署架构

```
生产服务器:
  ├── LAZY SERVER (FastAPI)         :8765
  │     └── ~/.lazy_server/         (凭据持久化)
   ├── Nonebot2 Bot                  :8080
   │     ├── bot.py                  (用户已有)
   │     ├── nonebot_plugin_lazy/    (pip/nb install 安装)
   │     └── src/plugins/
   │         └── lazy_monitor/       (或本地插件形式)
  └── go-cqhttp / Lagrange          :5700
        └── ws → localhost:8080/onebot/v11/ws/e
```
