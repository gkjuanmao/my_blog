"""prod 配置单测（TEST-04）：TLS / ALLOWED_HOSTS / 缓存 / 密钥等环境变量分支。

pytest 恒以 ``config.settings.dev`` 运行（见 pyproject.toml），这里用 ``importlib.reload``
在受控环境变量下**单独重载** ``config.settings.prod``，不会污染 ``django.conf.settings``
（后者在 pytest-django 启动时已按 dev 固定）。
"""
import importlib
from types import ModuleType

import pytest


def _load_prod(monkeypatch: pytest.MonkeyPatch, **env: str | None) -> ModuleType:
    """在给定环境变量下重载 ``config.settings.prod`` 并返回模块。

    默认注入占位的 ``DJANGO_SECRET_KEY`` 与 ``REDIS_URL``（避免每次都触发缓存回落告警）；
    传入 ``KEY=None`` 可显式删除该变量。
    """
    monkeypatch.setenv('DJANGO_SECRET_KEY', 'unit-test-secret')
    monkeypatch.setenv('REDIS_URL', 'redis://unit-test/0')
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return importlib.reload(importlib.import_module('config.settings.prod'))


class TestSecretKey:
    def test_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(RuntimeError, match='DJANGO_SECRET_KEY'):
            _load_prod(monkeypatch, DJANGO_SECRET_KEY=None)

    def test_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prod = _load_prod(monkeypatch)
        assert prod.SECRET_KEY == 'unit-test-secret'


class TestAllowedHosts:
    def test_falls_back_to_localhost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prod = _load_prod(monkeypatch, DJANGO_ALLOWED_HOSTS='')
        assert prod.ALLOWED_HOSTS == ['localhost', '127.0.0.1']

    def test_parses_and_trims_comma_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prod = _load_prod(monkeypatch, DJANGO_ALLOWED_HOSTS=' blog.example.com , 1.2.3.4 ')
        assert prod.ALLOWED_HOSTS == ['blog.example.com', '1.2.3.4']


class TestTls:
    def test_off_by_default_and_hsts_gated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 即使显式给了 HSTS 秒数，TLS 关闭时也必须归零（HTTP 下 HSTS 无意义）
        prod = _load_prod(
            monkeypatch, DJANGO_USE_TLS=None, DJANGO_SECURE_HSTS_SECONDS='31536000'
        )
        assert prod.SECURE_SSL_REDIRECT is False
        assert prod.SESSION_COOKIE_SECURE is False
        assert prod.CSRF_COOKIE_SECURE is False
        assert prod.SECURE_PROXY_SSL_HEADER is None
        assert prod.SECURE_HSTS_SECONDS == 0
        assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is False
        assert prod.SECURE_HSTS_PRELOAD is False

    def test_on_enables_redirect_secure_cookie_hsts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prod = _load_prod(
            monkeypatch,
            DJANGO_USE_TLS='true',
            DJANGO_SECURE_HSTS_SECONDS='31536000',
            DJANGO_CSRF_TRUSTED_ORIGINS='https://blog.example.com',
        )
        assert prod.SECURE_SSL_REDIRECT is True
        assert prod.SESSION_COOKIE_SECURE is True
        assert prod.CSRF_COOKIE_SECURE is True
        assert prod.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https')
        assert prod.SECURE_HSTS_SECONDS == 31536000
        assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
        assert prod.SECURE_HSTS_PRELOAD is True
        assert prod.CSRF_TRUSTED_ORIGINS == ['https://blog.example.com']


class TestCache:
    def test_redis_when_url_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prod = _load_prod(monkeypatch, REDIS_URL='redis://redis:6379/0')
        default = prod.CACHES['default']
        assert default['BACKEND'].endswith('RedisCache')
        assert default['LOCATION'] == 'redis://redis:6379/0'

    def test_locmem_fallback_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.warns(RuntimeWarning, match='REDIS_URL'):
            prod = _load_prod(monkeypatch, REDIS_URL='')
        assert prod.CACHES['default']['BACKEND'].endswith('LocMemCache')


class TestMisc:
    def test_debug_off_and_docs_default_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prod = _load_prod(monkeypatch)
        assert prod.DEBUG is False
        assert prod.ENABLE_API_DOCS is False

    def test_docs_can_be_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prod = _load_prod(monkeypatch, ENABLE_API_DOCS='true')
        assert prod.ENABLE_API_DOCS is True


def test_wsgi_and_asgi_importable() -> None:
    import config.asgi
    import config.wsgi

    assert callable(config.wsgi.application)
    assert callable(config.asgi.application)
