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
    ('post', '/api/v1/admin/articles/import/tasks/'),
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

#: 已对「任意登录用户」开放的归档导入端点（每个作者导自己的包）。
#: 它们仍要求登录（匿名 401），但写域由 planner 的 author 作用域 + 非编辑强制草稿保证，
#: 所以非 staff 不再 403。
OPEN_TO_AUTHENTICATED = {
    'GET /api/v1/admin/articles/import/limits/',
    'POST /api/v1/admin/articles/import/stage/',
    'POST /api/v1/admin/articles/import/tasks/',
    # 文章读写对「作者本人」开放：staff 管全站，其他人只管自己的（越权一律 404）。
    # 分类/标签/导出/传图/HTML 导入仍是编辑专属。
    'GET /api/v1/admin/articles/',
    'GET /api/v1/admin/articles/999999/',
    'POST /api/v1/admin/articles/',
    'PUT /api/v1/admin/articles/999999/',
    'DELETE /api/v1/admin/articles/999999/',
    'DELETE /api/v1/admin/articles/slug/not-exist/',
    'POST /api/v1/admin/articles/bulk-delete/',
}


@pytest.mark.django_db
class TestAdminPermissionMatrix:
    @pytest.mark.parametrize(('method', 'url'), ADMIN_ENDPOINTS, ids=_ENDPOINT_IDS)
    def test_anonymous_rejected(self, api_client, method, url):
        """匿名访问管理端点一律 401。"""
        response = getattr(api_client, method)(url)
        assert response.status_code == 401

    @pytest.mark.parametrize(('method', 'url'), ADMIN_ENDPOINTS, ids=_ENDPOINT_IDS)
    def test_non_staff_forbidden(self, api_client, plain_header, method, url):
        """非 staff 的登录用户访问**编辑类**管理端点一律 403。

        归档导入是例外（见 OPEN_TO_AUTHENTICATED）：它按作者划分写域，
        不靠「只给 staff」把关。
        """
        response = getattr(api_client, method)(url, **plain_header)
        if f'{method.upper()} {url}' in OPEN_TO_AUTHENTICATED:
            assert response.status_code not in (401, 403)
            return
        assert response.status_code == 403

    @pytest.mark.parametrize(('method', 'url'), ADMIN_ENDPOINTS, ids=_ENDPOINT_IDS)
    def test_staff_not_blocked_by_auth(self, api_client, staff_header, method, url):
        """staff 通过鉴权（业务上可能是 400/404/422，但不应是 401/403）。"""
        response = getattr(api_client, method)(url, **staff_header)
        assert response.status_code not in (401, 403)
