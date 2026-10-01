"""归档格式：schema 常量、JSON 序列化与包内命名规则。"""
import hashlib
import re
from datetime import datetime

from django.utils.text import slugify

from articles.models import Article

SCHEMA_ARTICLE = 'myblog.article/v1'
SCHEMA_ARCHIVE = 'myblog.archive/v1'

ARTICLE_JSON_NAME = 'article.json'
MANIFEST_NAME = 'manifest.json'
README_NAME = 'README.md'
ARTICLES_DIR = 'articles'

# 包内媒体文件采用**约定名 + 实际扩展名**（而非 UUID），便于人工替换
COVER_BASENAME = 'cover'
ATTACHMENT_BASENAME = 'attachment'

# 幂等键前缀（源字节哈希）
SOURCE_SHA_FIELD = 'cover_image_sha256'


def sha256_bytes(data: bytes) -> str:
    """计算字节串的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(data).hexdigest()


def file_sha256(path) -> str:
    """流式计算磁盘文件的 SHA-256。"""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def extension_of(name: str | None) -> str:
    """取小写扩展名（None 或无扩展名返回空串）。"""
    if not name or '.' not in name:
        return ''
    return name.rsplit('.', 1)[-1].lower()


def safe_path_slug(raw: str) -> str:
    """把 slug 变成可安全用于包内目录名的 ASCII 片段。

    绝不直接把 article.json 里的 slug 拼进路径：手改包可能含 ``/``、``..``、CRLF
    （否则会产出"连本系统导入器都拒绝"的包）。
    """
    cleaned = slugify(raw or '')
    cleaned = re.sub(r'^[-.]+|[-.]+$', '', cleaned)
    cleaned = cleaned[:80]
    return cleaned or 'article'


def article_dir_name(index: int, slug: str) -> str:
    """包内文章目录名：NNN-<slug>（序号仅用于排序与识别）。"""
    return f'{index:03d}-{safe_path_slug(slug)}'


def cover_entry_name(ext: str) -> str:
    """包内封面文件名。"""
    return f'{COVER_BASENAME}.{ext}' if ext else COVER_BASENAME


def attachment_entry_name(ext: str) -> str:
    """包内附件文件名。"""
    return f'{ATTACHMENT_BASENAME}.{ext}' if ext else ATTACHMENT_BASENAME


def build_article_json(
    article: Article,
    *,
    cover: dict | None,
    attachment: dict | None,
    exported_at: datetime,
    app_version: str,
    import_action: str = 'auto',
) -> dict:
    """把 Article 序列化成 article.json 的内容。"""
    category = article.category
    return {
        'schema': SCHEMA_ARTICLE,
        'source': {
            'id': article.id,
            'exported_at': exported_at.isoformat(),
            'app_version': app_version,
        },
        'title': article.title,
        'slug': article.slug,
        'summary': article.summary,
        'publish_time': article.publish_time.isoformat(),
        'location': article.location,
        'is_published': article.is_published,
        # 导出但导入时忽略（D3）；在 manifest.ignored_on_import 里显式声明
        'views': article.views,
        'created_at': article.created_at.isoformat(),
        'updated_at': article.updated_at.isoformat(),
        'author': {'username': article.author.username},
        'category': (
            {
                'slug': category.slug,
                'name': category.name,
                'description': category.description,
            }
            if category is not None
            else None
        ),
        'tags': [{'slug': tag.slug, 'name': tag.name} for tag in article.tags.all()],
        'cover': cover,
        'attachment': attachment,
        'import': {'action': import_action},
    }


def build_manifest(
    *,
    exported_at: datetime,
    app_version: str,
    django_version: str,
    filters: dict,
    articles: list[dict],
    warnings: list[str],
    limits_snapshot: dict,
) -> dict:
    """构建 manifest.json（advisory：仅供参考，导入不依赖它）。"""
    return {
        'schema': SCHEMA_ARCHIVE,
        'generator': {
            'app': 'my_blog',
            'version': app_version,
            'django': django_version,
        },
        'exported_at': exported_at.isoformat(),
        'filters': filters,
        'ignored_on_import': ['views', 'created_at', 'updated_at'],
        'limits': limits_snapshot,
        'warnings': warnings,
        'articles': articles,
    }


README_TEMPLATE = """# 文章归档包说明

本压缩包由「my_blog」后台导出，可**直接再次导入**，也可以**手工编辑后再导入**。

## 目录结构

```
manifest.json                     包级索引（仅供参考，导入时不依赖它）
README.md                         本文件
articles/
  001-<slug>/                     NNN 序号仅用于排序与识别，可随意改名
    article.json                  该文章的**全部元数据**（唯一真相源，直接改这个）
    cover.<ext>                   封面图片（jpg/jpeg/png/webp）
    attachment.<ext>              附件（pdf/doc/docx）
```

## 怎么改

| 想做的事 | 怎么做 |
| --- | --- |
| 改标题 / 摘要 / 发布时间 / 地点 / 是否发布 | 编辑 `article.json` 对应字段 |
| 改分类 / 标签 | 编辑 `category.slug` / `tags[].slug`；不存在时会被自动创建 |
| 换封面 / 换附件 | 用**同名**新文件覆盖；`sha256` 不一致只会告警，不影响导入 |
| 只改文件名、忘了改 JSON | 若该目录下**只有一个**同类型候选文件，会自动使用（并在报告中告警） |
| 删除某篇文章 | 删掉整个目录即可，`manifest.json` 不必同步 |
| 新增一篇文章 | 复制一个目录，改 `article.json`（**slug 必须改且必须唯一**） |
| 让某篇强制覆盖/跳过 | 写 `"import": {"action": "update"}` |

## 注意事项

1. `article.json` 必须保存为 **UTF-8**（带 BOM 也可以），**不要写注释和尾逗号**。
2. `slug` 只能包含字母、数字、连字符、下划线，且必须唯一；否则该篇会被跳过。
3. `publish_time` 建议带时区偏移量，如 `2026-08-18T00:00:00+08:00`。
4. 重新打包时多套一层目录没关系（导入会递归查找 `article.json`）。
5. 以下字段**导出但导入时会被忽略**：`views`、`created_at`、`updated_at`。
   （因此本包不是「灾难恢复备份」，只是内容迁移/交换格式。）
6. 附件仅接受 `pdf` / `doc` / `docx`（历史遗留的 `html` 仍可导入，但浏览器会强制下载）。
"""
