"""管理端权限矩阵：/api/v1/admin/** 一律要求 staff。

本项目无公开注册、账号只能在 admin 创建；管理端点（文章/分类/标签 CRUD、
批量删除、预览、归档、传图、HTML 导入）必须统一要求 staff，避免普通登录用户
越权管理。本文件用参数化矩阵钉住这一口径：匿名 → 401、非 staff → 403、
staff → 不因鉴权被拒（允许 400/404/422 等业务响应）。
"""
import pytest

ADMIN_ENDPOINTS = [
    ('get', '/api/v1/admin/articles/'),
    ('get', '/api/v1/admin/articles/999999/'),
    ('post', '/api/v1/admin/articles/'),
    ('put', '/api/v1/admin/articles/999999/'),
    ('delete', '/api/v1/admin/articles/999999/'),
    ('delete', '/api/v1/admin/articles/slug/not-exist/'),
    ('post', '/api/v1/admin/articles/bulk-delete/'),
    ('post', '/api/v1/admin/articles/preview/'),
    ('get', '/api/v1/admin/articles/export/'),
    ('get', '/api/v1/admin/articles/export/estimate/'),
    ('get', '/api/v1/admin/articles/import/limits/'),
    ('post', '/api/v1/admin/articles/import/stage/'),
    ('post', '/api/v1/admin/articles/import/commit/'),
    ('post', '/api/v1/admin/articles/images/'),
    ('post', '/api/v1/admin/articles/convert-html/'),
    ('post', '/api/v1/admin/categories/'),
    ('get', '/api/v1/admin/categories/999999/'),
    ('put', '/api/v1/admin/categories/999999/'),
    ('delete', '/api/v1/admin/categories/999999/'),
    ('post', '/api/v1/admin/tags/'),
    ('get', '/api/v1/admin/tags/999999/'),
    ('put', '/api/v1/admin/tags/999999/'),
    ('delete', '/api/v1/admin/tags/999999/'),
]

_ENDPOINT_IDS = [f'{method.upper()} {url}' for method, url in ADMIN_ENDPOINTS]


@pytest.mark.django_db
class TestAdminPermissionMatrix:
    @pytest.mark.parametrize(('method', 'url'), ADMIN_ENDPOINTS, ids=_ENDPOINT_IDS)
    def test_anonymous_rejected(self, api_client, method, url):
        """匿名访问管理端点一律 401。"""
        response = getattr(api_client, method)(url)
        assert response.status_code == 401

    @pytest.mark.parametrize(('method', 'url'), ADMIN_ENDPOINTS, ids=_ENDPOINT_IDS)
    def test_non_staff_forbidden(self, api_client, plain_header, method, url):
        """非 staff 的登录用户访问管理端点一律 403。"""
        response = getattr(api_client, method)(url, **plain_header)
        assert response.status_code == 403

    @pytest.mark.parametrize(('method', 'url'), ADMIN_ENDPOINTS, ids=_ENDPOINT_IDS)
    def test_staff_not_blocked_by_auth(self, api_client, staff_header, method, url):
        """staff 通过鉴权（业务上可能是 400/404/422，但不应是 401/403）。"""
        response = getattr(api_client, method)(url, **staff_header)
        assert response.status_code not in (401, 403)
