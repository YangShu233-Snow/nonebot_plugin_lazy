# nonebot_plugin_lazy

Nonebot2 插件，作为 LAZY SERVER 的 HTTP 消费者，定时轮询学在浙大的点名和待办数据，发现新项目后通过 QQ 群和私聊通知用户。

## 功能特性

- **点名监控** — 定时拉取进行中的点名，新点名出现时即时通知
- **待办监控** — 定时拉取待办任务，新待办出现时即时通知
- **私聊注册** — 用户在私聊中通过 `/register` 命令绑定学号密码，安全声明确认后自动验证
- **多用户支持** — 支持 .env 静态配置 + 多人私聊注册，每人独立 Token 和通知
- **任务管理** — 通过 `/task` 命令查看和修改监控任务的启用状态与轮询间隔
- **@用户通知** — 群通知 @ 具体用户（数据触发者），而非 @全体成员
- **自动重连** — Token 过期自动重新登录，服务器不可达告警

## 安装

### 方式一：nb plugin install（推荐）

通过 Nonebot2 CLI 安装，自动处理依赖：

```bash
nb plugin install nonebot-plugin-lazy
```

### 方式二：pip install

直接通过 pip 安装：

```bash
pip install nonebot-plugin-lazy
```

开发模式下使用可编辑安装：

```bash
git clone https://github.com/yangshu233/nonebot_plugin_lazy.git
cd nonebot_plugin_lazy
pip install -e .
```

### 方式三：本地插件（开发/测试）

克隆仓库后，在 `bot.py` 中加载：

```python
nonebot.load_plugins("src/plugins")
```

`src/plugins/lazy_monitor/` 保留了一个向后兼容的 shim，会自动转发到 `nonebot_plugin_lazy`。

## 配置

在 `.env`（或 `.env.prod`）中添加以下配置：

```dotenv
# LAZY 服务器地址（必填）
LAZY_MONITOR__SERVER_URL=http://127.0.0.1:8765

# 可选：静态配置学号密码（不配置则等待私聊注册）
LAZY_MONITOR__STUDENTID=3240100106
LAZY_MONITOR__PASSWORD=your_password
LAZY_MONITOR__OWNER_QQ=123456789

# 轮询间隔（秒，默认30）
LAZY_MONITOR__POLL_INTERVAL=30

# 通知目标
LAZY_MONITOR__NOTIFY_GROUPS=[123456789]
LAZY_MONITOR__NOTIFY_USERS=[987654321]

# 功能开关
LAZY_MONITOR__ENABLE_ROLLCALL=true
LAZY_MONITOR__ENABLE_TODO=true

# 重试策略
LAZY_MONITOR__MAX_RETRIES=3
LAZY_MONITOR__RETRY_DELAY=5
```

> 注意：`list[int]` 类型的字段（NOTIFY_GROUPS 等）使用 JSON 数组格式 `[123, 456]`。

## 使用

### 注册

| 场景 | 命令 | 行为 |
|------|------|------|
| 私聊 | `/register` | 四步骤对话：安全提示→确认→学号→密码→验证→绑定 |
| 群聊 | `/register` | @用户并引导到私聊 |

### 任务管理

所有命令均需使用私聊或在群聊中 @Bot 触发。

| 命令 | 说明 |
|------|------|
| `/task list` | 列出所有监控任务及当前状态 |
| `/task enable <task_id>` | 启用指定任务 |
| `/task disable <task_id>` | 停用指定任务 |
| `/task interval <task_id> <秒>` | 修改指定任务的轮询间隔 |
| `/task reset <task_id>` | 恢复指定任务为系统默认配置 |

示例：
```
/task list
/task enable rollcall_watch
/task interval todo_watch 120
/task disable todo_watch
```

### 通知格式

点名通知：
```
🔔 新点名通知
————————
课程：新中国史
发起人：陈荣
类型：雷达点名
```

待办通知：
```
📋 新待办通知
————————
标题：微积分第四章作业
课程：微积分（上）
截止时间：2026-05-20 23:59
```

## 项目结构

```
nonebot_plugin_lazy/
├── nonebot_plugin_lazy/   ← pip/nb install 的标准包
│   ├── __init__.py        # 插件入口：启动时注册 .env 账号 + 启动定时任务
│   ├── config.py          # Pydantic 配置模型，绑定 .env 环境变量
│   ├── state.py           # 多用户会话管理（UserManager + UserSession + MonitorState）
│   ├── auth.py            # Token 管理（登录/自动注册/401 重认证）
│   ├── monitor.py         # 轮询引擎：多用户独立拉取数据 + 差异检测
│   ├── notifier.py        # 通知格式化 + OneBot 消息发送（@用户）
│   └── handler.py         # 命令处理器（/register 注册 /task 任务管理）
│
├── src/plugins/
│   └── lazy_monitor/
│       └── __init__.py    # 向后兼容 shim（转发到 nonebot_plugin_lazy）
│
├── pyproject.toml         # 构建配置 + nb plugin install 元数据
├── .env.example           # 配置模板
└── README.md              # 本文件
```

## 架构

```
用户 ── QQ 消息 ──→ go-cqhttp ── OneBot WS ──→ Nonebot2 Bot
                                                    │
                                            nonebot_plugin_lazy
                                                    │
                                           HTTP 轮询 (30s)
                                                    │
                                                    ▼
                                              LAZY SERVER
                                                    │
                                           HTTP 请求 学在浙大 API
```

## 依赖

- nonebot2 >= 2.4.0
- nonebot-adapter-onebot >= 2.4.0
- nonebot-plugin-apscheduler
- httpx >= 0.28.0
- Python >= 3.12

## 许可证

AGPL-3.0-only
