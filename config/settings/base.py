"""Django 基础配置：所有环境共享的通用配置。"""
from datetime import timedelta
from pathlib import Path

# 项目根目录（config/settings 的上级的上级）
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 应用注册
INSTALLED_APPS = [
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 第三方应用
    'corsheaders',
    'ninja',
    # 自定义应用
    'articles.apps.ArticlesConfig',
    'users.apps.UsersConfig',
    'common',
]

MIDDLEWARE = [
    # CORS 中间件需放在最前，否则跨域请求头不生效
    'corsheaders.middleware.CorsMiddleware',
    # 修复 PUT/PATCH 等非 POST 请求的 multipart 文件解析
    'ninja.compatibility.files.fix_request_files_middleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# 跨域配置：允许前端开发服务器访问（Vite 默认端口）
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# 默认使用 SQLite，生产环境在 prod.py 中切换为 PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 自定义用户模型（users app）
AUTH_USER_MODEL = 'users.User'

# JWT Token 配置（django-ninja-jwt 兼容读取 SIMPLE_JWT）
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_TZ = True

STATIC_URL = 'static/'

# 全局静态文件目录（按需创建）
STATICFILES_DIRS = [BASE_DIR / 'static']

# 生产环境 collectstatic 的输出目录
STATIC_ROOT = BASE_DIR / 'staticfiles'

# 媒体文件（用户上传）配置
MEDIA_URL = '/media/'

MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
