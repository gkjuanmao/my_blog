"""正文内联图片：压缩、内容寻址落盘、URL 提取。

设计要点（详见 docs/ARTICLE_MARKDOWN_PLAN.md §4/§7.7）：

- **压缩**：统一转 WebP、剥 EXIF/ICC、最长边 ≤1920；已规范（canonical）的 WebP 原样返回，
  保证「导出 → 导入 → 再导出」收敛，不会每轮重写。
- **内容寻址命名**：``inline/<sha256(落盘字节)[:32]>.webp``。文件名完全由内容决定，
  客户端字符串不参与路径（归档 T9），同图天然去重、重导天然幂等。
- **原子落盘**：同目录临时文件 + ``os.replace``。**绝不调用 ``Storage.save()``** —— 它在
  同名时会追加随机后缀，破坏内容寻址。仅适用本地 ``FileSystemStorage``。
- **URL 提取**：从**消毒后的最终 HTML**解析 ``<img src>``，导出打包 / skip 补齐 / purge
  三处共用同一实现。
"""
import hashlib
import os
import posixpath
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage
from PIL import Image, ImageOps

_EXT_TO_FORMAT = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP'}
_PILLOW_FORMAT_TO_EXT = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}


class InlineImageError(ValueError):
    """内联图片处理失败（调用方转成 400 / 该篇失败）。"""


@dataclass(frozen=True)
class ProcessedImage:
    """压缩结果：可直接落盘的 WebP 字节 + 尺寸 + 告警。"""

    data: bytes
    width: int
    height: int
    warnings: list[str] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        """落盘字节的 SHA-256（幂等与内容寻址的唯一依据）。"""
        return hashlib.sha256(self.data).hexdigest()


def extension_of(filename: str | None) -> str:
    """取小写扩展名（无扩展名返回空串）。"""
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[-1].lower()


def media_prefix() -> str:
    """内联图 URL 前缀（如 ``/media/inline/``），大小写按配置保留。"""
    return f'{settings.MEDIA_URL}{settings.INLINE_IMAGE_DIR}/'


def _storage_path(rel: str) -> str:
    """把相对路径解析成绝对路径（仅支持本地 FileSystemStorage）。"""
    if not isinstance(default_storage, FileSystemStorage):
        raise InlineImageError('内联图片仅支持本地 FileSystemStorage 存储后端')
    return default_storage.path(rel)


def _normalize_mode(image: Image.Image) -> Image.Image:
    """把调色板/灰度等模式归一到 WebP 可编码的模式。"""
    if image.mode in ('RGB', 'RGBA'):
        return image
    if image.mode == 'P':
        has_alpha = 'transparency' in image.info
        return image.convert('RGBA' if has_alpha else 'RGB')
    if image.mode in ('LA', 'L'):
        return image.convert('RGBA' if image.mode == 'LA' else 'RGB')
    return image.convert('RGB')


def _is_webp(data: bytes) -> bool:
    """按魔数判断是否为 WebP（``RIFF....WEBP``）。"""
    return len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP'


def _is_canonical(image: Image.Image) -> bool:
    """canonical 判定：必须是 WebP、尺寸达标、且原始输入不含 EXIF / ICC。

    ⚠️ 必须在任何变换（``exif_transpose`` 会抹掉 EXIF 证据）**之前**调用，否则会把
    带方向信息的旋转原图误判为 canonical，从而原样返回**仍含 EXIF** 的字节。
    """
    if (image.format or '').upper() != 'WEBP':
        return False
    long_edge = settings.INLINE_IMAGE_MAX_LONG_EDGE
    if max(image.size) > long_edge:
        return False
    info = image.info or {}
    return 'exif' not in info and 'icc_profile' not in info


def _encode_webp(image: Image.Image, *, lossless: bool) -> bytes:
    """把图片编码成 WebP（``method=6`` 压缩率最好但更慢，博客量级可接受）。"""
    buffer = BytesIO()
    if lossless:
        image.save(buffer, format='WEBP', lossless=True, quality=100, method=6)
    else:
        image.save(
            buffer, format='WEBP', quality=settings.INLINE_IMAGE_WEBP_QUALITY, method=6
        )
    return buffer.getvalue()


def process_inline_image(data: bytes, ext: str) -> ProcessedImage:
    """校验并压缩内联图片，返回规范 WebP 字节。

    :raises InlineImageError: 扩展名/格式/像素/体积不合法，或压缩后仍超上限。
    """
    ext = ext.lower()
    if ext not in settings.INLINE_IMAGE_EXTENSIONS:
        raise InlineImageError('图片仅支持 JPG/PNG/WebP 格式')
    if len(data) > settings.INLINE_IMAGE_MAX_BYTES:
        raise InlineImageError('图片大小不能超过 10MB')

    try:
        source = Image.open(BytesIO(data))
        width, height = source.size
        # 先按头部读到的尺寸判像素，再 load()：否则压缩炸弹会在解码阶段就吃满内存
        if width * height > settings.INLINE_IMAGE_MAX_PIXELS:
            raise InlineImageError('图片像素数超过上限')
        canonical = _is_canonical(source)
        source.load()
    except InlineImageError:
        raise
    except Image.DecompressionBombError as exc:  # pragma: no cover - 依赖 Pillow 阈值
        raise InlineImageError('图片像素数超过上限') from exc
    except Exception as exc:
        raise InlineImageError('无法解析该图片文件') from exc

    if canonical:
        return ProcessedImage(data=data, width=width, height=height, warnings=[])

    actual_format = (source.format or '').upper()
    if _PILLOW_FORMAT_TO_EXT.get(actual_format) is None:
        raise InlineImageError('图片仅支持 JPG/PNG/WebP 格式')
    if _EXT_TO_FORMAT[ext] != actual_format:
        raise InlineImageError('图片内容与扩展名不一致')

    warnings: list[str] = []
    image: Image.Image = ImageOps.exif_transpose(source) or source
    image = _normalize_mode(image)

    long_edge = settings.INLINE_IMAGE_MAX_LONG_EDGE
    if max(image.size) > long_edge:
        image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)

    # WebP 保存会从 info 带出 EXIF，必须显式删键，否则"剥离 EXIF"失效
    image.info.pop('exif', None)
    image.info.pop('icc_profile', None)

    if (image.format or '').upper() == 'PNG':
        # 截图/文字图用无损更清晰；与有损取小者，避免"体积反增"
        lossless = _encode_webp(image, lossless=True)
        lossy = _encode_webp(image, lossless=False)
        data = lossless if len(lossless) <= len(lossy) else lossy
    else:
        data = _encode_webp(image, lossless=False)

    if len(data) > settings.INLINE_IMAGE_OUTPUT_BYTES:
        raise InlineImageError('图片压缩后仍超过 8MB')

    return ProcessedImage(data=data, width=image.width, height=image.height, warnings=warnings)


def inline_rel_path(data: bytes) -> str:
    """内容寻址的相对路径：``inline/<sha256[:32]>.webp``。"""
    digest = hashlib.sha256(data).hexdigest()[:32]
    return f'{settings.INLINE_IMAGE_DIR}/{digest}.webp'


def store_inline_image(data: bytes) -> str:
    """把（已压缩的）WebP 字节按内容寻址原子落盘，返回相对 ``MEDIA_ROOT`` 的路径。

    - 已存在同内容文件 → 直接复用（**不 touch mtime**）；
    - 不存在 → 同目录临时文件写满后 ``os.replace`` 原子替换（内容寻址 ⇒ 覆盖安全），
      彻底避免 Django ``Storage.save()`` 的随机后缀与"半成品被当已存在"。
    """
    if not _is_webp(data):
        raise InlineImageError('内联图片必须是 WebP 字节')

    rel = inline_rel_path(data)
    if default_storage.exists(rel):
        return rel

    abs_path = _storage_path(rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    tmp_path = f'{abs_path}.{uuid.uuid4().hex}.tmp'
    try:
        with open(tmp_path, 'wb') as handle:
            handle.write(data)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, abs_path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_path)
        raise
    return rel


def inline_url(data: bytes) -> str:
    """给定落盘字节，返回其公开 URL（如 ``/media/inline/<hash>.webp``）。"""
    return f'{settings.MEDIA_URL}{inline_rel_path(data)}'


class _ImgSrcCollector(HTMLParser):
    """收集最终 HTML 中所有 ``<img src>``。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != 'img':
            return
        src = dict(attrs).get('src')
        if src:
            self.srcs.append(src)


def normalize_inline_name(src: str) -> str | None:
    """把 ``src`` 归一化成内联图文件名；非内联图返回 ``None``。

    覆盖：相对路径、无前导斜杠（``media/inline/x.webp``）、绝对 URL、协议相对、
    大小写差异、百分号编码。
    """
    path = urlsplit((src or '').strip()).path
    if not path:
        return None
    path = unquote(path)
    path = posixpath.normpath(path)
    if not path.startswith('/'):
        path = f'/{path}'
    prefix = media_prefix()
    if not path.lower().startswith(prefix.lower()):
        return None
    name = path[len(prefix):].strip('/')
    if not name or '/' in name:
        return None
    return name.lower()


def extract_inline_names(html: str | None) -> set[str]:
    """从**已消毒的最终 HTML**提取内联图文件名集合（导出/skip 补齐/purge 共用）。"""
    if not html:
        return set()
    collector = _ImgSrcCollector()
    collector.feed(html)
    collector.close()
    names = {normalize_inline_name(src) for src in collector.srcs}
    return {name for name in names if name}


def list_inline_files() -> list[str]:
    """列出 ``MEDIA_ROOT/inline/`` 下的文件名（不含子目录）。"""
    directory = os.path.join(str(settings.MEDIA_ROOT), settings.INLINE_IMAGE_DIR)
    if not os.path.isdir(directory):
        return []
    return sorted(
        entry
        for entry in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, entry))
    )
