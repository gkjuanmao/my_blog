# 个人博客后端 - API 测试用例文档

> **用途**：本文档供 AI 编程工具（OpenCode）读取，自动生成 pytest 测试用例  
> **测试框架**：pytest + pytest-django  
> **最后更新**：2026-08-09

---

## 一、测试基础设施

### 1.1 依赖安装

```bash
uv add --dev pytest pytest-django pytest-cov
```

### 1.2 pytest 配置 (pyproject.toml)

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.dev"
python_files = ["tests.py", "test_*.py", "*_tests.py"]
addopts = "-v --tb=short"
```

### 1.3 全局 Fixture (conftest.py)

在项目根目录创建 `conftest.py`，定义以下 Fixture：

```python
import pytest
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
import io
from users.models import User
from rest_framework_simplejwt.tokens import RefreshToken

@pytest.fixture
def api_client():
    """Django 测试客户端"""
    return Client()

@pytest.fixture
def user(db):
    """创建测试用户"""
    return User.objects.create_user(
        username='testuser',
        password='testpass123',
        email='test@example.com'
    )

@pytest.fixture
def auth_header(user):
    """JWT 认证请求头"""
    refresh = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {str(refresh.access_token)}'}

@pytest.fixture
def test_image():
    """生成 100x100 红色 JPEG 图片"""
    img = Image.new('RGB', (100, 100), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    buffer.seek(0)
    return SimpleUploadedFile('test.jpg', buffer.read(), content_type='image/jpeg')

@pytest.fixture
def test_pdf():
    """生成 100KB PDF 文件"""
    content = b'%PDF-1.4\n' + b'x' * 102400
    return SimpleUploadedFile('test.pdf', content, content_type='application/pdf')
```

---

## 二、认证模块测试 (users)

### 2.1 POST `/api/v1/login/` - 用户登录

#### 测试用例

| 用例ID | 场景 | 输入 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|
| AUTH-001 | 正常登录 | `username="testuser", password="testpass123"` | 200 | `data.access` 和 `data.refresh` 存在 |
| AUTH-002 | 用户名错误 | `username="wrong", password="testpass123"` | 401 | `message` 包含 "用户名或密码错误" |
| AUTH-003 | 密码错误 | `username="testuser", password="wrong"` | 401 | `message` 包含 "用户名或密码错误" |
| AUTH-004 | 缺少 username | `password="testpass123"` | 422 | 参数校验失败 |
| AUTH-005 | 缺少 password | `username="testuser"` | 422 | 参数校验失败 |
| AUTH-006 | username 为空 | `username="", password="testpass123"` | 422 | 参数校验失败 |

#### pytest 代码模板

```python
# users/tests/test_login.py
import pytest

@pytest.mark.django_db
class TestLoginAPI:
    
    def test_auth_001_normal_login(self, api_client, user):
        """正常登录"""
        response = api_client.post('/api/v1/login/', {
            'username': 'testuser',
            'password': 'testpass123'
        }, content_type='application/json')
        
        assert response.status_code == 200
        data = response.json()
        assert data['code'] == 200
        assert 'access' in data['data']
        assert 'refresh' in data['data']
    
    def test_auth_002_wrong_username(self, api_client, user):
        """用户名错误"""
        response = api_client.post('/api/v1/login/', {
            'username': 'wrong',
            'password': 'testpass123'
        }, content_type='application/json')
        
        assert response.status_code == 401
        assert '用户名或密码错误' in response.json()['message']
    
    def test_auth_003_wrong_password(self, api_client, user):
        """密码错误"""
        response = api_client.post('/api/v1/login/', {
            'username': 'testuser',
            'password': 'wrong'
        }, content_type='application/json')
        
        assert response.status_code == 401
    
    def test_auth_004_missing_username(self, api_client):
        """缺少 username"""
        response = api_client.post('/api/v1/login/', {
            'password': 'testpass123'
        }, content_type='application/json')
        
        assert response.status_code == 422
    
    def test_auth_005_missing_password(self, api_client):
        """缺少 password"""
        response = api_client.post('/api/v1/login/', {
            'username': 'testuser'
        }, content_type='application/json')
        
        assert response.status_code == 422
```

### 2.2 POST `/api/v1/token/refresh/` - 刷新 Token

#### 测试用例

| 用例ID | 场景 | 输入 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|
| AUTH-010 | 正常刷新 | 有效的 refresh token | 200 | `data.access` 存在 |
| AUTH-011 | token 过期 | 过期的 refresh token | 401 | `message` 包含 "过期" |
| AUTH-012 | token 无效 | 伪造的 token 字符串 | 401 | `message` 包含 "无效" |
| AUTH-013 | 缺少 refresh | `{}` | 422 | 参数校验失败 |

#### pytest 代码模板

```python
# users/tests/test_token_refresh.py
import pytest
from rest_framework_simplejwt.tokens import RefreshToken
from datetime import timedelta
from django.utils import timezone

@pytest.mark.django_db
class TestTokenRefreshAPI:
    
    def test_auth_010_normal_refresh(self, api_client, user):
        """正常刷新"""
        refresh = RefreshToken.for_user(user)
        response = api_client.post('/api/v1/token/refresh/', {
            'refresh': str(refresh)
        }, content_type='application/json')
        
        assert response.status_code == 200
        assert 'access' in response.json()['data']
    
    def test_auth_012_invalid_token(self, api_client):
        """无效 token"""
        response = api_client.post('/api/v1/token/refresh/', {
            'refresh': 'invalid_token_string'
        }, content_type='application/json')
        
        assert response.status_code == 401
    
    def test_auth_013_missing_refresh(self, api_client):
        """缺少 refresh 字段"""
        response = api_client.post('/api/v1/token/refresh/', {}, 
                                   content_type='application/json')
        
        assert response.status_code == 422
```

### 2.3 GET `/api/v1/me/` - 获取当前用户信息

#### 测试用例

| 用例ID | 场景 | 请求头 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|
| AUTH-016 | 正常获取 | `Authorization: Bearer <valid>` | 200 | 返回用户信息，不含 password |
| AUTH-017 | 未携带 Token | 无 Authorization | 401 | `message` 包含 "未提供认证" |
| AUTH-018 | Token 格式错误 | `Authorization: Bearer xxx` | 401 | `message` 包含 "无效" |
| AUTH-019 | Token 过期 | 过期的 access token | 401 | `message` 包含 "过期" |

#### pytest 代码模板

```python
# users/tests/test_me.py
import pytest

@pytest.mark.django_db
class TestMeAPI:
    
    def test_auth_016_get_user_info(self, api_client, auth_header, user):
        """正常获取用户信息"""
        response = api_client.get('/api/v1/me/', **auth_header)
        
        assert response.status_code == 200
        data = response.json()['data']
        assert data['username'] == 'testuser'
        assert data['email'] == 'test@example.com'
        assert 'password' not in data
    
    def test_auth_017_no_token(self, api_client):
        """未携带 Token"""
        response = api_client.get('/api/v1/me/')
        
        assert response.status_code == 401
    
    def test_auth_018_invalid_token(self, api_client):
        """Token 格式错误"""
        response = api_client.get('/api/v1/me/', 
                                  HTTP_AUTHORIZATION='Bearer invalid_token')
        
        assert response.status_code == 401
```

---

## 三、文章公开接口测试 (articles)

### 3.1 GET `/api/v1/categories/` - 获取分类列表

#### 测试用例

| 用例ID | 场景 | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|
| CAT-001 | 正常获取 | 存在 3 个分类 | 200 | 返回 3 个分类对象 |
| CAT-002 | 无数据 | 数据库为空 | 200 | 返回空数组 `[]` |

#### pytest 代码模板

```python
# articles/tests/test_categories.py
import pytest
from articles.models import Category

@pytest.mark.django_db
class TestCategoriesAPI:
    
    def test_cat_001_get_categories(self, api_client):
        """正常获取分类列表"""
        Category.objects.create(name='技术', slug='tech')
        Category.objects.create(name='生活', slug='life')
        
        response = api_client.get('/api/v1/categories/')
        
        assert response.status_code == 200
        data = response.json()['data']
        assert len(data) == 2
    
    def test_cat_002_empty_categories(self, api_client):
        """无分类数据"""
        response = api_client.get('/api/v1/categories/')
        
        assert response.status_code == 200
        assert response.json()['data'] == []
```

### 3.2 GET `/api/v1/articles/` - 文章列表（分页）

#### 测试用例

| 用例ID | 场景 | 请求参数 | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|:---|
| ART-001 | 正常获取 | 默认 | 15 篇已发布文章 | 200 | 返回第 1 页 10 条 |
| ART-002 | 分页 page=2 | `?page=2` | 15 篇文章 | 200 | 返回第 2 页 5 条 |
| ART-003 | 自定义 page_size | `?page_size=5` | - | 200 | 每页 5 条 |
| ART-004 | 非法 page=0 | `?page=0` | - | 422 | 参数校验失败 |
| ART-005 | 仅返回已发布 | 默认 | 存在草稿 | 200 | 草稿不出现 |
| ART-006 | 按分类过滤 | `?category_slug=tech` | 存在分类 | 200 | 仅返回该分类 |
| ART-007 | 空数据库 | 默认 | 无文章 | 200 | `items=[]`, `total=0` |

#### pytest 代码模板

```python
# articles/tests/test_article_list.py
import pytest
from articles.models import Article, Category
from django.utils import timezone

@pytest.mark.django_db
class TestArticleListAPI:
    
    @pytest.fixture
    def setup_articles(self, user):
        """创建测试文章"""
        category = Category.objects.create(name='技术', slug='tech')
        for i in range(15):
            Article.objects.create(
                title=f'文章{i}',
                slug=f'article-{i}',
                content='内容',
                publish_time=timezone.now(),
                author=user,
                category=category,
                is_published=True
            )
        # 创建一篇草稿
        Article.objects.create(
            title='草稿',
            slug='draft',
            content='草稿内容',
            publish_time=timezone.now(),
            author=user,
            is_published=False
        )
    
    def test_art_001_default_pagination(self, api_client, setup_articles):
        """默认分页"""
        response = api_client.get('/api/v1/articles/')
        
        assert response.status_code == 200
        data = response.json()['data']
        assert len(data['items']) == 10
        assert data['total'] == 15
        assert data['page'] == 1
    
    def test_art_002_page_2(self, api_client, setup_articles):
        """第 2 页"""
        response = api_client.get('/api/v1/articles/?page=2')
        
        assert response.status_code == 200
        data = response.json()['data']
        assert len(data['items']) == 5
    
    def test_art_003_custom_page_size(self, api_client, setup_articles):
        """自定义 page_size"""
        response = api_client.get('/api/v1/articles/?page_size=5')
        
        assert response.status_code == 200
        assert len(response.json()['data']['items']) == 5
    
    def test_art_004_invalid_page(self, api_client):
        """非法 page=0"""
        response = api_client.get('/api/v1/articles/?page=0')
        
        assert response.status_code == 422
    
    def test_art_005_only_published(self, api_client, setup_articles):
        """仅返回已发布文章"""
        response = api_client.get('/api/v1/articles/')
        
        data = response.json()['data']
        slugs = [item['slug'] for item in data['items']]
        assert 'draft' not in slugs
    
    def test_art_006_filter_by_category(self, api_client, setup_articles):
        """按分类过滤"""
        response = api_client.get('/api/v1/articles/?category_slug=tech')
        
        assert response.status_code == 200
        assert response.json()['data']['total'] == 15
    
    def test_art_007_empty_database(self, api_client):
        """空数据库"""
        response = api_client.get('/api/v1/articles/')
        
        assert response.status_code == 200
        data = response.json()['data']
        assert data['items'] == []
        assert data['total'] == 0
```

### 3.3 GET `/api/v1/articles/{slug}/` - 文章详情

#### 测试用例

| 用例ID | 场景 | slug | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|:---|
| ART-015 | 正常获取 | `my-post` | 文章存在 | 200 | 返回完整文章 |
| ART-016 | 文章不存在 | `not-exist` | - | 404 | `message` 包含 "不存在" |
| ART-017 | 未发布文章 | `draft` | `is_published=False` | 404 | 对外不可见 |
| ART-018 | 阅读量 +1 | `my-post` | `views=10` | 200 | 访问后 `views=11` |

#### pytest 代码模板

```python
# articles/tests/test_article_detail.py
import pytest
from articles.models import Article
from django.utils import timezone

@pytest.mark.django_db
class TestArticleDetailAPI:
    
    @pytest.fixture
    def article(self, user):
        return Article.objects.create(
            title='测试文章',
            slug='my-post',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
            views=10
        )
    
    def test_art_015_get_detail(self, api_client, article):
        """正常获取详情"""
        response = api_client.get('/api/v1/articles/my-post/')
        
        assert response.status_code == 200
        data = response.json()['data']
        assert data['title'] == '测试文章'
        assert data['slug'] == 'my-post'
    
    def test_art_016_not_found(self, api_client):
        """文章不存在"""
        response = api_client.get('/api/v1/articles/not-exist/')
        
        assert response.status_code == 404
    
    def test_art_017_unpublished(self, api_client, user):
        """未发布文章"""
        Article.objects.create(
            title='草稿',
            slug='draft',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=False
        )
        
        response = api_client.get('/api/v1/articles/draft/')
        
        assert response.status_code == 404
    
    def test_art_018_views_increment(self, api_client, article):
        """阅读量 +1"""
        response = api_client.get('/api/v1/articles/my-post/')
        
        assert response.status_code == 200
        article.refresh_from_db()
        assert article.views == 11
```

### 3.4 GET `/api/v1/articles/search/?keyword=xxx` - 文章搜索

#### 测试用例

| 用例ID | 场景 | keyword | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|:---|
| SRC-001 | 正常搜索 | `博客` | 标题含"博客" | 200 | 返回匹配文章 |
| SRC-002 | 无匹配 | `不存在` | - | 200 | 返回空数组 |
| SRC-003 | 缺少 keyword | 无参数 | - | 422 | 参数必填 |
| SRC-004 | 大小写不敏感 | `python` | 标题 "Python" | 200 | 能匹配 |
| SRC-005 | 仅搜索已发布 | `草稿` | 草稿含关键词 | 200 | 草稿不出现 |

#### pytest 代码模板

```python
# articles/tests/test_article_search.py
import pytest
from articles.models import Article
from django.utils import timezone

@pytest.mark.django_db
class TestArticleSearchAPI:
    
    @pytest.fixture
    def setup_articles(self, user):
        Article.objects.create(
            title='我的第一篇博客',
            slug='blog-1',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=True
        )
        Article.objects.create(
            title='Python 教程',
            slug='python',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=True
        )
        Article.objects.create(
            title='草稿博客',
            slug='draft-blog',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=False
        )
    
    def test_src_001_normal_search(self, api_client, setup_articles):
        """正常搜索"""
        response = api_client.get('/api/v1/articles/search/?keyword=博客')
        
        assert response.status_code == 200
        data = response.json()['data']
        assert len(data) == 1
        assert data[0]['title'] == '我的第一篇博客'
    
    def test_src_002_no_match(self, api_client, setup_articles):
        """无匹配结果"""
        response = api_client.get('/api/v1/articles/search/?keyword=不存在')
        
        assert response.status_code == 200
        assert response.json()['data'] == []
    
    def test_src_003_missing_keyword(self, api_client):
        """缺少 keyword 参数"""
        response = api_client.get('/api/v1/articles/search/')
        
        assert response.status_code == 422
    
    def test_src_004_case_insensitive(self, api_client, setup_articles):
        """大小写不敏感"""
        response = api_client.get('/api/v1/articles/search/?keyword=python')
        
        assert response.status_code == 200
        assert len(response.json()['data']) == 1
    
    def test_src_005_only_published(self, api_client, setup_articles):
        """仅搜索已发布文章"""
        response = api_client.get('/api/v1/articles/search/?keyword=草稿')
        
        assert response.status_code == 200
        assert response.json()['data'] == []
```

---

## 四、文章管理接口测试 (articles - admin)

### 4.1 POST `/api/v1/admin/articles/` - 创建文章

#### 测试用例

| 用例ID | 场景 | 输入 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|
| ADM-001 | 正常创建 | 完整表单 + 2 个文件 | 201 | 文章创建成功 |
| ADM-002 | 未登录 | 无 Token | 401 | 未认证 |
| ADM-003 | 缺少 title | 无 title 字段 | 422 | 参数校验失败 |
| ADM-004 | 缺少 cover | 无封面文件 | 422 | 文件必填 |
| ADM-005 | slug 重复 | 已存在相同 slug | 201 | slug 自动加后缀 (如 `test-2`) |
| ADM-006 | 封面格式错误 | cover=exe 文件 | 400 | "不支持的文件类型" |
| ADM-007 | 封面超大 | cover=6MB | 400 | "封面不能超过 5MB" |
| ADM-008 | 附件格式错误 | attachment=exe | 400 | "不支持的文件类型" |
| ADM-009 | 文件重命名 | cover="测试.jpg" | 201 | 物理文件 UUID，`cover_image_name="测试.jpg"` |
| ADM-050 | 英文标题自动生成 slug | title="Hello World" | 201 | slug=`hello-world` |
| ADM-051 | 中文标题自动生成 slug | title="第一篇测试文章" | 201 | slug=`di-yi-pian-ce-shi-wen-zhang` |
| ADM-052 | 手动 slug 优先 | slug="my-custom" | 201 | 采用手动 slug |
| ADM-053 | 自动生成冲突加后缀 | title 生成 slug 与已有冲突 | 201 | slug=`hello-world-2` |
| ADM-054 | 手动 slug 冲突加后缀 | slug 与已有冲突 | 201 | slug=`my-custom-2` |

#### pytest 代码模板

```python
# articles/tests/test_create_article.py
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from articles.models import Article, Category, Tag

@pytest.mark.django_db
class TestCreateArticleAPI:
    
    @pytest.fixture
    def setup_data(self, user):
        category = Category.objects.create(name='技术', slug='tech')
        tag = Tag.objects.create(name='Python', slug='python')
        return category, tag
    
    def test_adm_001_normal_create(self, api_client, auth_header, test_image, test_pdf, setup_data):
        """正常创建文章"""
        category, tag = setup_data
        
        response = api_client.post('/api/v1/admin/articles/', {
            'title': '测试文章',
            'slug': 'test-article',
            'content': '# 内容',
            'publish_time': '2026-08-09T14:00:00Z',
            'category_id': category.id,
            'tag_ids': [tag.id],
            'is_published': True,
            'cover': test_image,
            'attachment': test_pdf,
        }, **auth_header)
        
        assert response.status_code == 201
        data = response.json()['data']
        assert data['title'] == '测试文章'
        assert data['cover_image_name'] == 'test.jpg'
        assert data['file_name'] == 'test.pdf'
        
        # 验证数据库
        article = Article.objects.get(slug='test-article')
        assert article.cover_image_name == 'test.jpg'
    
    def test_adm_002_unauthorized(self, api_client, test_image, test_pdf):
        """未登录创建"""
        response = api_client.post('/api/v1/admin/articles/', {
            'title': '测试',
            'slug': 'test',
            'content': '内容',
            'publish_time': '2026-08-09T14:00:00Z',
            'cover': test_image,
            'attachment': test_pdf,
        })
        
        assert response.status_code == 401
    
    def test_adm_003_missing_title(self, api_client, auth_header, test_image, test_pdf):
        """缺少 title"""
        response = api_client.post('/api/v1/admin/articles/', {
            'slug': 'test',
            'content': '内容',
            'publish_time': '2026-08-09T14:00:00Z',
            'cover': test_image,
            'attachment': test_pdf,
        }, **auth_header)
        
        assert response.status_code == 422
    
    def test_adm_005_duplicate_slug(self, api_client, auth_header, user, test_image, test_pdf):
        """slug 重复"""
        Article.objects.create(
            title='已存在',
            slug='test',
            content='内容',
            publish_time='2026-08-09T14:00:00Z',
            author=user
        )
        
        response = api_client.post('/api/v1/admin/articles/', {
            'title': '新文章',
            'slug': 'test',
            'content': '内容',
            'publish_time': '2026-08-09T14:00:00Z',
            'cover': test_image,
            'attachment': test_pdf,
        }, **auth_header)
        
        assert response.status_code == 400
    
    def test_adm_006_invalid_cover_type(self, api_client, auth_header, test_pdf):
        """封面格式错误"""
        bad_file = SimpleUploadedFile('bad.exe', b'MZ' + b'x'*100, 
                                      content_type='application/octet-stream')
        
        response = api_client.post('/api/v1/admin/articles/', {
            'title': '测试',
            'slug': 'test',
            'content': '内容',
            'publish_time': '2026-08-09T14:00:00Z',
            'cover': bad_file,
            'attachment': test_pdf,
        }, **auth_header)
        
        assert response.status_code == 400
```

### 4.2 DELETE `/api/v1/admin/articles/{id}/` - 删除文章

#### 测试用例

| 用例ID | 场景 | id | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|:---|
| ADM-038 | 正常删除 | 存在的 id | 文章存在 | 204 | 文章被删除 |
| ADM-039 | 文章不存在 | 9999 | - | 404 | 不存在 |
| ADM-040 | 未登录 | 1 | 无 Token | 401 | 未认证 |

#### pytest 代码模板

```python
# articles/tests/test_delete_article.py
import pytest
from articles.models import Article
from django.utils import timezone

@pytest.mark.django_db
class TestDeleteArticleAPI:
    
    @pytest.fixture
    def article(self, user):
        return Article.objects.create(
            title='测试文章',
            slug='test',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=True
        )
    
    def test_adm_038_normal_delete(self, api_client, auth_header, article):
        """正常删除"""
        response = api_client.delete(f'/api/v1/admin/articles/{article.id}/', 
                                     **auth_header)
        
        assert response.status_code == 204
        assert not Article.objects.filter(id=article.id).exists()
    
    def test_adm_039_not_found(self, api_client, auth_header):
        """文章不存在"""
        response = api_client.delete('/api/v1/admin/articles/9999/', 
                                     **auth_header)
        
        assert response.status_code == 404
    
    def test_adm_040_unauthorized(self, api_client, article):
        """未登录删除"""
        response = api_client.delete(f'/api/v1/admin/articles/{article.id}/')
        
        assert response.status_code == 401
```

### 4.3 GET `/api/v1/admin/articles/` - 管理文章列表

> 返回**全部文章（含未发布草稿）**，用于后台定位与管理；公开接口 `/articles/` 仅返回已发布文章。

#### 测试用例

| 用例ID | 场景 | 请求参数 | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|:---|
| ADM-041 | 列表含草稿 | 默认 | 1 已发布 + 1 草稿 | 200 | `total=2`，含 `draft-post` |
| ADM-042 | 未登录 | - | - | 401 | 未认证 |
| ADM-043 | 过滤草稿 | `?is_published=false` | 1 草稿 | 200 | `total=1`，仅草稿 |
| ADM-044 | 标题搜索 | `?keyword=草稿` | - | 200 | `total=1` |
| ADM-045 | 分类过滤 | `?category_slug=tech` | - | 200 | `total=2` |
| ADM-046 | 分页 | `?page_size=1` | - | 200 | `items=1`, `total=2` |

### 4.4 DELETE `/api/v1/admin/articles/slug/{slug}/` - 按 slug 删除文章

> 用于删除公开接口不可见的**未发布草稿**；按 id 删除见 4.2。

#### 测试用例

| 用例ID | 场景 | slug | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|:---|
| ADM-047 | 删除草稿 | `draft-post` | 草稿存在 | 200 | 文章被删除 |
| ADM-048 | slug 不存在 | `not-exist` | - | 404 | `message` 包含 "不存在" |
| ADM-049 | 未登录 | `draft-post` | - | 401 | 未认证 |

#### pytest 代码模板

```python
# tests/test_admin_articles.py
import pytest
from django.utils import timezone
from articles.models import Article, Category

@pytest.mark.django_db
class TestAdminArticleListAPI:

    @pytest.fixture
    def setup_articles(self, user):
        category = Category.objects.create(name='技术', slug='tech')
        Article.objects.create(
            title='已发布文章', slug='published', content='内容',
            publish_time=timezone.now(), author=user, category=category, is_published=True,
        )
        Article.objects.create(
            title='草稿文章', slug='draft-post', content='草稿',
            publish_time=timezone.now(), author=user, category=category, is_published=False,
        )

    def test_adm_041_list_all_including_draft(self, api_client, auth_header, setup_articles):
        """列表含草稿"""
        response = api_client.get('/api/v1/admin/articles/', **auth_header)
        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 2
        slugs = [item['slug'] for item in data['items']]
        assert 'draft-post' in slugs

    def test_adm_042_unauthorized(self, api_client):
        """未登录"""
        response = api_client.get('/api/v1/admin/articles/')
        assert response.status_code == 401

    def test_adm_043_filter_unpublished(self, api_client, auth_header, setup_articles):
        """过滤草稿"""
        response = api_client.get('/api/v1/admin/articles/?is_published=false', **auth_header)
        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 1
        assert data['items'][0]['slug'] == 'draft-post'

@pytest.mark.django_db
class TestAdminDeleteBySlugAPI:

    @pytest.fixture
    def draft(self, user):
        return Article.objects.create(
            title='草稿文章', slug='draft-post', content='草稿',
            publish_time=timezone.now(), author=user, is_published=False,
        )

    def test_adm_047_delete_draft_by_slug(self, api_client, auth_header, draft):
        """删除草稿"""
        response = api_client.delete('/api/v1/admin/articles/slug/draft-post/', **auth_header)
        assert response.status_code == 200
        assert not Article.objects.filter(slug='draft-post').exists()

    def test_adm_048_slug_not_found(self, api_client, auth_header):
        """slug 不存在"""
        response = api_client.delete('/api/v1/admin/articles/slug/not-exist/', **auth_header)
        assert response.status_code == 404
        assert '不存在' in response.json()['message']

    def test_adm_049_unauthorized(self, api_client, draft):
        """未登录"""
        response = api_client.delete('/api/v1/admin/articles/slug/draft-post/')
        assert response.status_code == 401
```

### 4.5 PUT `/api/v1/admin/articles/{id}/` - 更新文章（slug 唯一化）

#### 测试用例

| 用例ID | 场景 | 输入 | 前置条件 | 预期状态码 | 预期响应 |
|:---|:---|:---|:---|:---|:---|
| ADM-055 | 更新 slug 冲突 | `slug=b` | 已存在 slug=`b` 的文章 | 200 | 目标文章 slug 变为 `b-2`（排除自身，自身 slug 不误判） |

#### pytest 代码模板

```python
# tests/test_slug_generation.py
import pytest
from django.utils import timezone
from django.utils.http import urlencode
from articles.models import Article

@pytest.mark.django_db
class TestUpdateSlugUniquenessAPI:
    def test_adm_055_update_slug_conflict(self, api_client, auth_header, user):
        """更新 slug 冲突时加后缀，且排除自身"""
        a1 = Article.objects.create(title='A', slug='a', content='x', publish_time=timezone.now(), author=user)
        Article.objects.create(title='B', slug='b', content='x', publish_time=timezone.now(), author=user)

        response = api_client.put(
            f'/api/v1/admin/articles/{a1.id}/', urlencode({'slug': 'b'}),
            content_type='application/x-www-form-urlencoded', **auth_header,
        )
        assert response.status_code == 200
        a1.refresh_from_db()
        assert a1.slug == 'b-2'

        # 更新为自身当前 slug，不应误判冲突
        response = api_client.put(
            f'/api/v1/admin/articles/{a1.id}/', urlencode({'slug': 'b-2'}),
            content_type='application/x-www-form-urlencoded', **auth_header,
        )
        assert response.status_code == 200
        a1.refresh_from_db()
        assert a1.slug == 'b-2'
```

> 注意：Django 6 的 `Client.put` 默认以 `application/octet-stream` 发送并会把 dict `str()` 化，PUT 测试须显式传 `content_type='application/x-www-form-urlencoded'` + `urlencode` 编码的数据。

---

## 五、AI 执行指引

### 5.1 生成测试代码的步骤

1. **读取本文档**：理解每个接口的测试用例
2. **创建测试文件**：按照 `app/tests/test_xxx.py` 的结构创建文件
3. **复制模板代码**：将 pytest 代码模板复制到对应文件
4. **补全断言**：根据"预期响应"列，补充完整的 `assert` 语句
5. **运行测试**：执行 `uv run pytest` 验证

### 5.2 测试文件命名规范

```
users/tests/
├── test_login.py
├── test_token_refresh.py
└── test_me.py

articles/tests/
├── test_categories.py
├── test_article_list.py
├── test_article_detail.py
├── test_article_search.py
├── test_create_article.py
├── test_delete_article.py
└── test_admin_articles.py   # 管理列表 + 按 slug 删除
└── test_slug_generation.py  # slug 自动生成 + 冲突唯一化
```

### 5.3 运行测试命令

```bash
# 运行所有测试
uv run pytest

# 运行特定 app 的测试
uv run pytest users/tests/

# 运行特定测试类
uv run pytest users/tests/test_login.py::TestLoginAPI

# 生成覆盖率报告
uv run pytest --cov=. --cov-report=html
```

### 5.4 测试通过标准

- 所有用例状态码断言通过
- 所有响应数据断言通过
- 数据库状态验证通过
- 无异常抛出（除非预期异常）

---

> **文档结束**  
> AI 工具应根据本文档自动生成完整的 pytest 测试代码，并确保所有测试用例通过。
