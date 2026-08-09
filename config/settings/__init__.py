"""根据 DJANGO_ENV 环境变量动态加载对应环境的配置模块。

默认值为 dev（SQLite + 调试模式）；生产环境需设置 DJANGO_ENV=prod。
"""
import os

DJANGO_ENV = os.environ.get('DJANGO_ENV', 'dev')

if DJANGO_ENV == 'prod':
    from .prod import *  # noqa: F403, F401
else:
    from .dev import *  # noqa: F403, F401
