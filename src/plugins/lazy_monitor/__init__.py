"""向后兼容 shim。

通过 `load_plugins("src/plugins")` 加载时自动转发到 nonebot_plugin_lazy。
新项目推荐直接使用 `nonebot.load_plugin("nonebot_plugin_lazy")`。
"""

from nonebot_plugin_lazy import *  # noqa: F401,F403
