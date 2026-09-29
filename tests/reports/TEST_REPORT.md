# API 测试报告

> **测试框架**：pytest + pytest-django
> **执行时间**：2026-09-30
> **测试模块**：`tests/`（独立模块，`testpaths = ["tests"]`）
> **测试配置**：`DJANGO_SETTINGS_MODULE = config.settings.dev`
> **报告文件**：`tests/reports/junit.xml`、`tests/reports/htmlcov/`（htmlcov 已 gitignore）

## 一、测试概况

| 指标 | 结果 |
| :--- | :--- |
| 用例总数 | 141 |
| 通过 | 141 ✅ |
| 失败 | 0 |
| 跳过 | 0 |
| 通过率 | 100% |
| 代码覆盖率 | 88% |

### 按测试文件分布

| 测试文件 | 用例数 | 覆盖接口/主题 |
| :--- | :--- | :--- |
| tests/test_login.py | 8 | `POST /login/`（含失败限流） |
| tests/test_token_refresh.py | 5 | `POST /token/refresh/`（含轮换黑名单） |
| tests/test_me.py | 4 | `GET /me/` |
| tests/test_categories.py | 2 | `GET /categories/` |
| tests/test_tags.py | 2 | `GET /tags/` |
| tests/test_article_list.py | 10 | `GET /articles/`（分页/过滤） |
| tests/test_article_detail.py | 4 | `GET /articles/{slug}/`（views+1） |
| tests/test_article_search.py | 7 | `GET /articles/search/`（分页信封） |
| tests/test_create_article.py | 20 | `POST /admin/articles/` |
| tests/test_update_article.py | 14 | `PUT /admin/articles/{id}/` |
| tests/test_delete_article.py | 6 | 删除（含磁盘文件清理） |
| tests/test_admin_articles.py | 13 | `GET /admin/articles/`（过滤/分页/排序）、按 slug 删除 |
| tests/test_admin_article_detail.py | 4 | `GET /admin/articles/{id}/` |
| tests/test_admin_categories.py | 15 | 分类 CRUD |
| tests/test_admin_tags.py | 14 | 标签 CRUD |
| tests/test_slug_generation.py | 6 | slug 自动生成/唯一化 |
| tests/test_media_url_relative.py | 3 | 媒体 URL 相对路径 |
| tests/test_user_avatar.py | 4 | 头像路径与校验 |

## 二、本轮迭代新增/变更的用例

| 用例 ID | 内容 | 结果 |
| :--- | :--- | :--- |
| AUTH-007 | 登录连续失败达上限 → 429（正确密码同样被拦截） | ✅ |
| AUTH-008 | 登录成功清除失败计数 | ✅ |
| AUTH-010 | 刷新返回轮换后的 refresh（与旧值不同） | ✅ |
| AUTH-014 | 轮换后旧 refresh 重放 → 401（黑名单）；新 refresh 可用 | ✅ |
| ADM-041 | 按 id 删除文章同步清理封面/附件文件 | ✅ |
| ADM-042 | 按 slug 删除同步清理文件 | ✅ |
| ADM-043 | `QuerySet.delete()`（admin 批量删除路径）触发清理 | ✅ |
| SRC-001~005 | 搜索返回值改为分页信封 `{items,total,page,page_size}` | ✅ |
| SRC-006 | 搜索分页：total=3、page_size=2 时第 1 页 2 条、第 2 页 1 条 | ✅ |
| SRC-007 | 搜索 `page_size=101` → 422 | ✅ |
| TAG-001/002 | 公开标签列表正常/空数据 | ✅ |
| AVT-001~004 | 头像路径 `avatars/YYYY/MM/<uuid>.jpg`；JPG 通过、GIF/超 2MB 拒绝 | ✅ |
| ADM-056/057 | 管理列表 `ordering=publish_time` / `-publish_time` 升/降序 | ✅ |
| ADM-058 | `ordering=password` → 400「不支持的排序字段」（白名单） | ✅ |
| ADM-059 | 状态过滤与排序组合 | ✅ |

## 三、代码覆盖率

| 模块 | 覆盖率 | 备注 |
| :--- | :--- | :--- |
| articles/models.py | 94% | |
| articles/api.py | 92% | |
| articles/schemas.py | 84% | multipart 归一化分支 |
| articles/utils.py | 95% | |
| articles/signals.py | 100% | 删除清理 |
| articles/apps.py | 67% | `ready()` 中的进程判断分支 |
| articles/defaults.py | 100% | |
| users/api.py | 96% | 登录/刷新/me |
| users/models.py | 96% | 头像 |
| users/schemas.py | 100% | |
| users/authentication.py | 88% | |
| common/exceptions.py | 70% | 兜底 500 分支 |
| common/responses.py | 80% | |
| common/pagination.py | 0% | 当前未被任何接口引用（列表接口为手动分页） |
| **总计** | **88%** | |

## 四、已知的历史问题（已修复，保留记录）

1. **AUTH-006（username 为空应返回 422）**：`LoginIn` 增加 `Field(..., min_length=1)`。
2. **响应信封统一**：公开接口统一为 `{code, message, data}`。
3. **multipart 可选字段空串 / tag_ids 编码兼容（ADM-010~012）**：`schemas.py` 的 `mode='before'` 校验器统一处理空串、JSON 数组字符串、逗号分隔、重复字段。
4. **管理文章列表与按 slug 删除（ADM-041~049）**。
5. **slug 后端自动生成（ADM-050~055）**：中文转拼音 + 冲突加后缀；并记录 django-ninja `Schema` 内部 `model_validator(mode='wrap')` 会使 `mode='before'` 失效、以及 Django 6 `Client.put` 需显式 `content_type` + `urlencode` 的坑。

## 五、复现命令

```bash
uv run pytest                                                # 全部测试
uv run pytest tests/test_login.py::TestLoginAPI              # 单个测试类
uv run ruff check .                                          # lint
uv run mypy config articles common users                     # 类型检查
uv run pytest --junitxml=tests/reports/junit.xml \
  --cov=articles --cov=users --cov=common \
  --cov-report=term --cov-report=html:tests/reports/htmlcov  # 覆盖率
```
