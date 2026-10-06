"""统一异常处理器测试（TEST-06）：HttpError / ValidationError / 500 兜底。

重点覆盖 500 兜底的两条设计意图：① 返回统一信封；② **不把内部细节泄露给调用方**
（``str(exc)`` 可能含绝对路径、约束名等，只写服务端日志）。
"""
import json

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from ninja import NinjaAPI, Router
from ninja.errors import HttpError
from ninja.testing import TestClient

from common.exceptions import (
    handle_exception,
    handle_http_error,
    handle_validation_error,
    register_exception_handlers,
)


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


def _body(response) -> dict:
    return json.loads(response.content)


class TestHttpErrorHandler:
    def test_preserves_status_and_message(self, rf):
        response = handle_http_error(rf.get('/api/v1/x/'), HttpError(404, '文章不存在'))

        assert response.status_code == 404
        assert _body(response) == {'code': 404, 'message': '文章不存在', 'data': None}


class TestValidationErrorHandler:
    def test_always_returns_400_single_line_string(self, rf):
        exc = ValidationError({'title': ['不能为空'], 'slug': ['已存在']})

        response = handle_validation_error(rf.post('/api/v1/x/'), exc)

        assert response.status_code == 400
        message = _body(response)['message']
        assert isinstance(message, str)
        assert 'title: 不能为空' in message
        assert 'slug: 已存在' in message

    def test_non_field_error_has_no_field_prefix(self, rf):
        exc = ValidationError({'__all__': ['正文与附件至少填一项']})

        message = _body(handle_validation_error(rf.post('/x/'), exc))['message']

        assert message == '正文与附件至少填一项'

    def test_plain_messages_are_joined(self, rf):
        exc = ValidationError(['第一条', '第二条'])

        message = _body(handle_validation_error(rf.post('/x/'), exc))['message']

        assert message == '第一条; 第二条'

    def test_never_returns_dict_or_list(self, rf):
        """前端按字符串渲染 message，任何分支都不能返回 dict/list。"""
        for exc in (
            ValidationError({'a': ['x']}),
            ValidationError(['only']),
            ValidationError({'__all__': ['all']}),
        ):
            message = _body(handle_validation_error(rf.post('/x/'), exc))['message']
            assert isinstance(message, str)


class TestServerErrorHandler:
    def test_generic_message_without_leaking_details(self, rf):
        exc = RuntimeError('sqlite3.OperationalError: /srv/my_blog/db_data/db.sqlite3 is locked')

        response = handle_exception(rf.get('/api/v1/articles/'), exc)
        body = _body(response)

        assert response.status_code == 500
        assert body == {'code': 500, 'message': '服务器内部错误', 'data': None}
        assert 'db.sqlite3' not in response.content.decode()
        assert 'OperationalError' not in response.content.decode()


class TestRegisteredHandlersIntegration:
    """用真实 NinjaAPI + TestClient 验证注册后 500 兜底确实生效。"""

    @staticmethod
    def _client() -> TestClient:
        api = NinjaAPI()
        router = Router()

        @router.get('/boom')
        def boom(request):
            raise RuntimeError('internal: /srv/private/db.sqlite3')

        api.add_router('', router)
        register_exception_handlers(api)
        return TestClient(api)

    def test_unhandled_exception_returns_envelope(self):
        response = self._client().get('/boom')

        assert response.status_code == 500
        assert response.json() == {'code': 500, 'message': '服务器内部错误', 'data': None}
        assert 'db.sqlite3' not in response.content.decode()
