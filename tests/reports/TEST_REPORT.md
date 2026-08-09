# API 测试报告

> **测试框架**：pytest + pytest-django  
> **执行时间**：2026-08-09  
> **测试模块**：`tests/`（独立模块）  
> **报告文件**：`tests/reports/junit.xml`、`tests/reports/htmlcov/`

## 一、测试概况

| 指标 | 结果 |
| :--- | :--- |
| 用例总数 | 62 |
| 通过 | 62 ✅ |
| 失败 | 0 |
| 跳过 | 0 |
| 通过率 | 100% |
| 代码覆盖率 | 86% |

## 二、用例执行明细

### 认证模块（users）

| 用例 ID | 接口 | 场景 | 结果 |
| :--- | :--- | :--- | :--- |
| AUTH-001 | POST /api/v1/login/ | 正常登录 | ✅ |
| AUTH-002 | POST /api/v1/login/ | 用户名错误 → 401 | ✅ |
| AUTH-003 | POST /api/v1/login/ | 密码错误 → 401 | ✅ |
| AUTH-004 | POST /api/v1/login/ | 缺少 username → 422 | ✅ |
| AUTH-005 | POST /api/v1/login/ | 缺少 password → 422 | ✅ |
| AUTH-006 | POST /api/v1/login/ | username 为空 → 422 | ✅ |
| AUTH-010 | POST /api/v1/token/refresh/ | 正常刷新 | ✅ |
| AUTH-011 | POST /api/v1/token/refresh/ | token 过期 → 401 | ✅ |
| AUTH-012 | POST /api/v1/token/refresh/ | 无效 token → 401 | ✅ |
| AUTH-013 | POST /api/v1/token/refresh/ | 缺少 refresh → 422 | ✅ |
| AUTH-016 | GET /api/v1/me/ | 正常获取用户信息 | ✅ |
| AUTH-017 | GET /api/v1/me/ | 未携带 Token → 401 | ✅ |
| AUTH-018 | GET /api/v1/me/ | Token 格式错误 → 401 | ✅ |
| AUTH-019 | GET /api/v1/me/ | Token 过期 → 401 | ✅ |

### 文章公开接口（articles）

| 用例 ID | 接口 | 场景 | 结果 |
| :--- | :--- | :--- | :--- |
| CAT-001 | GET /api/v1/categories/ | 正常获取分类列表 | ✅ |
| CAT-002 | GET /api/v1/categories/ | 无分类返回空数组 | ✅ |
| ART-001 | GET /api/v1/articles/ | 默认分页第 1 页 10 条 | ✅ |
| ART-002 | GET /api/v1/articles/?page=2 | 第 2 页 5 条 | ✅ |
| ART-003 | GET /api/v1/articles/?page_size=5 | 自定义每页数量 | ✅ |
| ART-004 | GET /api/v1/articles/?page=0 | 非法 page → 422 | ✅ |
| ART-005 | GET /api/v1/articles/ | 草稿不出现 | ✅ |
| ART-006 | GET /api/v1/articles/?category_slug= | 按分类过滤 | ✅ |
| ART-007 | GET /api/v1/articles/ | 空数据库 | ✅ |
| ART-015 | GET /api/v1/articles/{slug}/ | 正常获取详情 | ✅ |
| ART-016 | GET /api/v1/articles/{slug}/ | 文章不存在 → 404 | ✅ |
| ART-017 | GET /api/v1/articles/{slug}/ | 未发布文章 → 404 | ✅ |
| ART-018 | GET /api/v1/articles/{slug}/ | 阅读量 +1 | ✅ |
| SRC-001 | GET /api/v1/articles/search/ | 正常搜索 | ✅ |
| SRC-002 | GET /api/v1/articles/search/ | 无匹配返回空数组 | ✅ |
| SRC-003 | GET /api/v1/articles/search/ | 缺少 keyword → 422 | ✅ |
| SRC-004 | GET /api/v1/articles/search/ | 大小写不敏感 | ✅ |
| SRC-005 | GET /api/v1/articles/search/ | 草稿不参与搜索 | ✅ |

### 文章管理接口（articles - admin）

| 用例 ID | 接口 | 场景 | 结果 |
| :--- | :--- | :--- | :--- |
| ADM-001 | POST /api/v1/admin/articles/ | 正常创建（201） | ✅ |
| ADM-002 | POST /api/v1/admin/articles/ | 未登录 → 401 | ✅ |
| ADM-003 | POST /api/v1/admin/articles/ | 缺少 title → 422 | ✅ |
| ADM-004 | POST /api/v1/admin/articles/ | 缺少 cover → 422 | ✅ |
| ADM-005 | POST /api/v1/admin/articles/ | slug 重复 → 400 | ✅ |
| ADM-006 | POST /api/v1/admin/articles/ | 封面格式错误 → 400 | ✅ |
| ADM-007 | POST /api/v1/admin/articles/ | 封面超 20MB → 400 | ✅ |
| ADM-008 | POST /api/v1/admin/articles/ | 附件格式错误 → 400 | ✅ |
| ADM-009 | POST /api/v1/admin/articles/ | 中文文件名保留 | ✅ |
| ADM-010 | POST /api/v1/admin/articles/ | category_id/tag_ids 传空串视为未填 | ✅ |
| ADM-011 | POST /api/v1/admin/articles/ | tag_ids 传 JSON 数组字符串 | ✅ |
| ADM-012 | POST /api/v1/admin/articles/ | tag_ids 用重复字段 / category_id 字符串 | ✅ |
| ADM-038 | DELETE /api/v1/admin/articles/{id}/ | 正常删除（200 信封） | ✅ |
| ADM-039 | DELETE /api/v1/admin/articles/{id}/ | 文章不存在 → 404 | ✅ |
| ADM-040 | DELETE /api/v1/admin/articles/{id}/ | 未登录 → 401 | ✅ |
| ADM-041 | GET /api/v1/admin/articles/ | 管理列表含草稿 | ✅ |
| ADM-042 | GET /api/v1/admin/articles/ | 未登录 → 401 | ✅ |
| ADM-043 | GET /api/v1/admin/articles/ | is_published=false 过滤草稿 | ✅ |
| ADM-044 | GET /api/v1/admin/articles/ | 标题关键词搜索 | ✅ |
| ADM-045 | GET /api/v1/admin/articles/ | category_slug 过滤 | ✅ |
| ADM-046 | GET /api/v1/admin/articles/ | 管理列表分页 | ✅ |
| ADM-047 | DELETE /api/v1/admin/articles/slug/{slug}/ | 按 slug 删除草稿 | ✅ |
| ADM-048 | DELETE /api/v1/admin/articles/slug/{slug}/ | slug 不存在 → 404 | ✅ |
| ADM-049 | DELETE /api/v1/admin/articles/slug/{slug}/ | 未登录 → 401 | ✅ |
| ADM-050 | POST /api/v1/admin/articles/ | 英文标题自动生成 slug | ✅ |
| ADM-051 | POST /api/v1/admin/articles/ | 中文标题自动生成拼音 slug | ✅ |
| ADM-052 | POST /api/v1/admin/articles/ | 手动 slug 优先 | ✅ |
| ADM-053 | POST /api/v1/admin/articles/ | 自动生成 slug 冲突加后缀 | ✅ |
| ADM-054 | POST /api/v1/admin/articles/ | 手动 slug 冲突加后缀 | ✅ |
| ADM-055 | PUT /api/v1/admin/articles/{id}/ | 更新 slug 冲突加后缀且排除自身 | ✅ |

## 三、代码覆盖率

| 模块 | 覆盖率 |
| :--- | :--- |
| articles | 97%（models 94%、schemas 95%、api 接近全绿） |
| users | 98%（api 100%） |
| common | 58%（exceptions 70%、responses 80%；pagination 0% —— 当前未被接口使用） |
| **总计** | **86%** |

## 四、测试期间发现并修复的问题

1. **AUTH-006（username 为空应返回 422）**：`LoginIn` 未约束最小长度，空字符串会通过 Pydantic 校验并进入 `authenticate()`，返回 401。已在 `users/schemas.py` 为 `username`/`password` 增加 `Field(..., min_length=1)`，空值现在返回 422。
2. **接口响应信封统一**：为符合 TEST.md 断言与 DESIGN 5.1 的统一响应约定，将公开接口（login/refresh/me/categories/tags/articles 列表与详情/search）从裸 JSON 调整为 `{code, message, data}` 信封；`search` 由分页 dict 改为数组；`articles/` 列表改为手动分页（保留 `items/total/page/page_size`，page=0 返回 422）。
3. **multipart 可选字段空串 / tag_ids 编码兼容（ADM-010~012）**：django-ninja 对 multipart 数组字段用 `getlist` 期望重复字段，且把空字符串当作真实值，导致 Swagger UI 发送的 `category_id=`、`tag_ids=`、`tag_ids=[1]` 均报 422。已在 `articles/schemas.py` 为 `ArticleCreateIn`/`ArticleUpdateIn` 的 `category_id`/`tag_ids` 增加 `mode='before'` 校验器，统一兼容：空串视为未填、JSON 数组字符串、逗号分隔、重复字段四种编码。
4. **新增管理文章列表与按 slug 删除（ADM-041~049）**：此前无管理列表接口，未发布草稿无法通过 API 定位（公开接口仅返回已发布文章）。新增 `GET /api/v1/admin/articles/`（含草稿，支持 `is_published`/`keyword`/`category_slug` 过滤与分页）与 `DELETE /api/v1/admin/articles/slug/{slug}/`，草稿可被枚举并删除。
5. **slug 后端自动生成（ADM-050~055）**：新增 `articles/utils.py`（`generate_slug` 中文转拼音 + `unique_slug` 冲突自动加后缀）；`ArticleCreateIn.slug` 改为可选，创建时为空则由 title 生成（手动传入仍优先）；更新接口 slug 冲突时加后缀且排除自身。同时发现 django-ninja 的 `Schema` 内部 `model_validator(mode='wrap')` 会把输入包装成只读 `DjangoGetter`，导致 `mode='before'` 校验器不可写，故改为在 API 层生成；并记录 Django 6 `Client.put` 需显式 `content_type='application/x-www-form-urlencoded'` + `urlencode` 编码。

## 五、复现命令

```bash
uv run pytest tests/                                        # 全部测试
uv run pytest tests/test_login.py::TestLoginAPI             # 单个测试类
uv run pytest tests/ --junitxml=tests/reports/junit.xml \
  --cov=articles --cov=users --cov=common \
  --cov-report=term --cov-report=html:tests/reports/htmlcov # 覆盖率
```
