"""压缩包与条目校验：安全闸门 + 字段校验 + 媒体读取。

安全要点（详见 docs/ARTICLE_IMPORT_EXPORT.md §5）：
- 不使用 ``extractall``；先归一化条目名再逐条判定，拒绝绝对路径/``..``/盘符/软链。
- 条目名按 NFC + 大小写折叠去重，任何重复 → 整包 400。
- 读取一律 ``zf.open()`` + 分块，统计**真实**字节数，不信任 ``ZipInfo.file_size``。
"""
import io
import json
import re
import stat
import unicodedata
import warnings as warnings_module
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from django.conf import settings
from django.core.validators import validate_slug
from django.utils import timezone
from PIL import Image, ImageOps

from .errors import ItemError, LimitExceeded, PackageError
from .format import (
    ARTICLE_JSON_NAME,
    SCHEMA_ARTICLE,
    extension_of,
    sha256_bytes,
)
from .limits import Limits, limits

JUNK_DIR_PARTS = {'__macosx'}
JUNK_FILES = {'.ds_store', 'thumbs.db'}
VALID_IMPORT_ACTIONS = {'auto', 'skip', 'update', 'create_new'}
# Pillow 的 format 名 → 允许的扩展名
FORMAT_EXTENSIONS = {'jpeg': {'jpg', 'jpeg'}, 'png': {'png'}, 'webp': {'webp'}}
SAVE_FORMATS = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP'}


def _nfc(text: str) -> str:
    return unicodedata.normalize('NFC', text)


def normalize_entry_name(name: str) -> str:
    """把 zip 条目名归一化为 POSIX 风格（``\\`` → ``/``）。"""
    return name.replace('\\', '/')


def _depth_of(name: str) -> int:
    return len(PurePosixPath(name).parts)


def _is_junk(name: str) -> bool:
    parts = [part.lower() for part in PurePosixPath(name).parts]
    if any(part in JUNK_DIR_PARTS for part in parts[:-1]):
        return True
    return parts[-1] in JUNK_FILES if parts else False


@dataclass
class Budget:
    """整包读取预算：统计真实解压字节数。"""

    total: int = 0

    def charge(self, size: int, lim: Limits) -> None:
        self.total += size
        if self.total > lim.max_total_uncompressed:
            raise LimitExceeded(
                f'解压总量超过上限 {lim.max_total_uncompressed} 字节'
            )


@dataclass
class MediaRef:
    """包内一个媒体文件的引用。"""

    entry_name: str
    original_name: str
    data: bytes
    declared_sha256: str | None
    declared_size: int | None
    warnings: list[str] = field(default_factory=list)
    # **将被写入存储的字节**：封面已是规范格式就原样存，否则重编码后存。
    # 幂等比较与 `*_sha256` 列都基于它（见方案 D24）。
    stored_bytes: bytes = b''

    @property
    def extension(self) -> str:
        return extension_of(self.entry_name)


@dataclass
class ParsedArticle:
    """文章元数据（``present`` 用于区分"键缺失"与"显式空值"）。"""

    title: str
    slug: str
    publish_time: datetime
    present: frozenset[str]
    summary: str
    location: str
    is_published: bool | None
    category: dict | None
    tags: list[dict] | None
    author_username: str | None
    import_action: str
    schema_warning: bool = False


@dataclass
class ArticleEntry:
    """包内的一篇文章条目。"""

    dir_path: str
    json_entry: str
    raw: dict
    parsed: ParsedArticle | None = None
    cover: MediaRef | None = None
    attachment: MediaRef | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.parsed.slug if self.parsed else ''

    @property
    def title(self) -> str:
        return self.parsed.title if self.parsed else ''

    def all_warnings(self) -> list[str]:
        """条目级 + 媒体级（哈希不一致、遗留 HTML 等）告警，供报告使用。"""
        out = list(self.warnings)
        for media in (self.cover, self.attachment):
            if media is not None:
                out.extend(media.warnings)
        return out

    def ok(self) -> bool:
        return not self.errors


@dataclass
class PackageInfo:
    """一次校验的产物。"""

    entries: list[ArticleEntry]
    warnings: list[str]
    entries_count: int
    uncompressed_bytes: int
    sha256: str


# --------------------------------------------------------------------------- 读取


def read_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    lim: Limits,
    budget: Budget,
    *,
    max_bytes: int | None = None,
) -> bytes:
    """分块读取一个条目，严格按**真实**字节数计费。

    不信任 ``info.file_size``：红队实测一个"声明 1 字节"的条目可解出 64MiB。
    """
    cap = min(max_bytes or lim.max_member_bytes, lim.max_member_bytes)
    if info.file_size and info.file_size > cap:
        raise LimitExceeded(f'条目 {info.filename} 声明尺寸超过上限 {cap} 字节')
    declared_ratio = info.file_size / max(info.compress_size, 1)
    if declared_ratio > lim.max_compression_ratio:
        raise LimitExceeded(f'条目 {info.filename} 压缩比异常（{declared_ratio:.0f}:1）')

    chunks: list[bytes] = []
    read = 0
    with zf.open(info) as handle:
        # 单条目也受总量、单成员上限与压缩比三重约束
        while True:
            chunk = handle.read(64 * 1024)
            if not chunk:
                break
            read += len(chunk)
            if read > cap:
                raise LimitExceeded(f'条目 {info.filename} 解压后超过上限 {cap} 字节')
            if read / max(info.compress_size, 1) > lim.max_compression_ratio:
                raise LimitExceeded(f'条目 {info.filename} 实际压缩比异常')
            budget.charge(len(chunk), lim)
            chunks.append(chunk)
    if info.file_size and read != info.file_size:
        raise PackageError(f'条目 {info.filename} 声明的尺寸与实际不一致')
    return b''.join(chunks)


# --------------------------------------------------------------------------- 包级校验


def _check_infos(zf: zipfile.ZipFile, lim: Limits) -> tuple[list[zipfile.ZipInfo], list[str]]:
    """逐条校验条目名与类型，返回（可用的文件条目, 警告）。"""
    files: list[zipfile.ZipInfo] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for info in zf.infolist():
        raw_name = info.filename
        if not raw_name or raw_name.endswith('/'):
            continue  # 目录条目
        name = normalize_entry_name(raw_name)
        if _is_junk(name):
            continue
        if info.flag_bits & 0x1:
            raise PackageError('不支持加密的压缩包')
        if name.startswith('/') or name.startswith('//') or re.match(r'^[A-Za-z]:', name):
            raise PackageError(f'条目名非法（绝对路径）: {raw_name}')
        parts = PurePosixPath(name).parts
        if '..' in parts:
            raise PackageError(f'条目名非法（路径穿越）: {raw_name}')
        if len(name) > lim.max_path_length:
            raise PackageError(f'条目名过长（>{lim.max_path_length}）: {raw_name}')
        if _depth_of(name) > lim.max_depth:
            raise PackageError(f'条目层级过深（>{lim.max_depth}）: {raw_name}')
        mode = info.external_attr >> 16
        # 只拒绝**声明了文件类型**且不是普通文件/目录的条目（软链/设备等）。
        # 注意：Python zipfile 写文件时 external_attr 只带权限位（如 0o600），
        # 此时 S_IFMT(mode) == 0，不能当成"类型非法"。
        file_type = stat.S_IFMT(mode)
        if file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise PackageError(f'条目类型不允许（软链/设备等）: {raw_name}')
        key = _nfc(name).casefold()
        if key in seen:
            raise PackageError(f'压缩包内存在重复条目（含大小写/NFC 变体）: {name}')
        seen.add(key)
        files.append(info)

    if len(files) > lim.max_entries:
        raise LimitExceeded(f'条目数 {len(files)} 超过上限 {lim.max_entries}')
    if not files:
        raise PackageError('压缩包内没有可用文件')
    return files, warnings


def _discover_entries(files: list[zipfile.ZipInfo]) -> list[tuple[str, zipfile.ZipInfo]]:
    """递归发现 ``article.json``，返回 (所在目录, info) 列表。"""
    found: list[tuple[str, zipfile.ZipInfo]] = []
    for info in files:
        name = normalize_entry_name(info.filename)
        if PurePosixPath(name).name.lower() != ARTICLE_JSON_NAME:
            continue
        parent = str(PurePosixPath(name).parent)
        found.append(('' if parent == '.' else parent, info))
    found.sort(key=lambda item: item[1].filename)
    return found


def _check_nesting(dirs: list[str]) -> set[str]:
    """找出嵌套的 article.json 目录（父目录也是文章目录 → 该篇失败）。"""
    ambiguous: set[str] = set()
    for current in dirs:
        for other in dirs:
            if other != current and (other == '' or current.startswith(other + '/')):
                ambiguous.add(current)
                break
    return ambiguous


# --------------------------------------------------------------------------- 条目校验


def parse_article_json(raw: bytes) -> dict:
    """解析 article.json：UTF-8(含 BOM) → GBK 回退 → 友好报错。"""
    text: str | None = None
    for encoding in ('utf-8-sig', 'gbk'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ItemError('article.json 编码无法识别（需 UTF-8 或 GBK）')
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        detail = f'第 {exc.lineno} 行第 {exc.colno} 列'
        raise ItemError(f'article.json 不是合法 JSON（{detail}）') from None
    if not isinstance(data, dict):
        raise ItemError('article.json 顶层必须是对象')
    return data


def _expect_str(data: dict, key: str, *, max_length: int, required: bool) -> str | None:
    if key not in data:
        if required:
            raise ItemError(f'缺少必填字段: {key}')
        return None
    value = data[key]
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ItemError(f'字段 {key} 必须是字符串')
    if len(value) > max_length:
        raise ItemError(f'字段 {key} 超长（>{max_length}）')
    return value


def _parse_publish_time(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ItemError('publish_time 必须是 ISO8601 字符串')
    text = value.strip().replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ItemError('publish_time 不是合法的 ISO8601 时间') from None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed)
    return parsed


def parse_fields(data: dict) -> ParsedArticle:
    """字段级校验：不合法即 ItemError（该篇失败，不影响其它条目）。"""
    title = _expect_str(data, 'title', max_length=200, required=True) or ''
    if not title.strip():
        raise ItemError('title 不能为空')

    slug = _expect_str(data, 'slug', max_length=200, required=True) or ''
    try:
        validate_slug(slug)
    except Exception:
        raise ItemError(f'slug 不合法（仅允许字母/数字/连字符/下划线）: {slug!r}') from None

    publish_time = _parse_publish_time(data.get('publish_time'))

    is_published = data.get('is_published')
    if 'is_published' in data and not isinstance(is_published, bool):
        raise ItemError('is_published 必须是布尔值（true/false）')

    category = data.get('category')
    if category is not None:
        if not isinstance(category, dict):
            raise ItemError('category 必须是对象或 null')
        cat_slug = category.get('slug')
        if not isinstance(cat_slug, str) or not cat_slug.strip():
            raise ItemError('category.slug 不能为空')
        if len(str(category.get('name') or '')) > 100:
            raise ItemError('category.name 超长（>100）')
        if len(str(category.get('description') or '')) > 255:
            raise ItemError('category.description 超长（>255）')

    tags = data['tags'] if 'tags' in data else None
    if tags is not None:
        if not isinstance(tags, list):
            raise ItemError('tags 必须是数组')
        for item in tags:
            if not isinstance(item, dict) or not str(item.get('slug') or '').strip():
                raise ItemError('tags 每项都必须是含 slug 的对象')
            if len(str(item.get('name') or '')) > 100:
                raise ItemError('标签名超长（>100）')

    author = data.get('author')
    author_username = None
    if isinstance(author, dict) and author.get('username'):
        author_username = str(author['username'])

    action = 'auto'
    import_block = data.get('import')
    if isinstance(import_block, dict) and import_block.get('action'):
        candidate = str(import_block['action'])
        if candidate in VALID_IMPORT_ACTIONS:
            action = candidate

    schema = data.get('schema')

    return ParsedArticle(
        title=title,
        slug=slug,
        publish_time=publish_time,
        present=frozenset(data.keys()),
        summary=_expect_str(data, 'summary', max_length=500, required=False) or '',
        location=_expect_str(data, 'location', max_length=255, required=False) or '',
        is_published=is_published,
        category=category,
        tags=tags,
        author_username=author_username,
        import_action=action,
        schema_warning=schema not in (None, SCHEMA_ARTICLE),
    )


def _is_canonical_image(data: bytes, ext: str) -> bool:
    """文件是否已到"规范"结构（尾部无附加数据）。

    只用于决定**是否需要重编码**，不是权威校验：拿不准就返回 False（宁可重编码）。
    若无条件重编码，导出出去的字节就永远不等于记录的源哈希，
    导致「导出 → 导入 → 导出 → 导入」无限重写（实测）。
    """
    if ext in ('jpg', 'jpeg'):
        return data.endswith(b'\xff\xd9')
    if ext == 'png':
        return data.endswith(b'IEND\xaeB`\x82')
    if ext == 'webp':
        if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
            return False
        declared = int.from_bytes(data[4:8], 'little') + 8
        return declared in (len(data), len(data) - 1)  # RIFF 允许 1 字节 padding
    return False


def process_cover(data: bytes, ext: str, lim: Limits) -> tuple[bytes, list[str]]:
    """校验封面，返回**应写入存储的字节**。

    - 已是规范格式且无 EXIF 方向 → **原样存储**（保证导出→导入字节等价、可幂等）；
    - 否则重编码（校正方向 + 剥离 EXIF/尾部附加数据）。
    """
    warnings: list[str] = []
    if ext not in settings.COVER_EXTENSIONS:
        raise ItemError(f'封面扩展名不允许: {ext}')
    if len(data) > settings.COVER_MAX_BYTES:
        raise ItemError('封面大小不能超过 20MB')

    with warnings_module.catch_warnings():
        warnings_module.simplefilter('error', Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
                if width * height > lim.max_image_pixels:
                    raise ItemError(f'封面像素数超限（{width}x{height}）')
                fmt = (img.format or '').lower()
                img.load()
                if ext not in FORMAT_EXTENSIONS.get(fmt, set()):
                    raise ItemError(f'封面实际格式 {fmt or "未知"} 与扩展名 .{ext} 不一致')
                # 告警依据必须是 Orientation 标签值，不能看对象身份：
                # Pillow 12.x 在**没有** Orientation 时也会返回副本（实测）。
                orientation = img.getexif().get(0x0112)
                rotated = orientation not in (None, 1)
                canonical = _is_canonical_image(data, ext)
                if rotated:
                    warnings.append('封面含 EXIF 方向信息，已按方向校正并剥离元数据')
                elif not canonical:
                    warnings.append('封面尾部含附加数据（疑似 polyglot），已重编码清除')

                if rotated or not canonical:
                    buffer = io.BytesIO()
                    target = SAVE_FORMATS.get(ext, 'PNG')
                    oriented = ImageOps.exif_transpose(img)
                    if target == 'JPEG':
                        oriented.convert('RGB').save(
                            buffer, format='JPEG', quality=88, optimize=True
                        )
                    else:
                        oriented.save(buffer, format=target)
                    encoded = buffer.getvalue()
                else:
                    encoded = data
        except ItemError:
            raise
        except Exception as exc:  # 解压炸弹、截断文件、伪造图片
            raise ItemError(f'封面无法解析: {type(exc).__name__}') from None

    if len(encoded) > settings.COVER_MAX_BYTES:
        raise ItemError('封面重编码后仍超过 20MB')
    return encoded, warnings


def _allowed_attachment_extensions(*, allow_legacy: bool) -> set[str]:
    allowed = set(settings.ATTACHMENT_EXTENSIONS)
    if allow_legacy:
        allowed |= set(settings.ATTACHMENT_LEGACY_EXTENSIONS)
    return allowed


def check_attachment(data: bytes, ext: str, *, allow_legacy: bool) -> list[str]:
    """校验附件：白名单 + 体积。返回警告（遗留 html 会告警）。"""
    allowed = _allowed_attachment_extensions(allow_legacy=allow_legacy)
    if ext not in allowed:
        raise ItemError(f'附件扩展名不允许: {ext or "(无)"}')
    if len(data) > settings.ATTACHMENT_MAX_BYTES:
        raise ItemError('附件大小不能超过 50MB')
    if ext in settings.ATTACHMENT_LEGACY_EXTENSIONS:
        return ['附件为历史遗留的 HTML 类型，浏览器将强制下载']
    return []


# --------------------------------------------------------------------------- 主入口


def validate_package(
    path,
    *,
    allow_legacy_html: bool = True,
    limits_override: Limits | None = None,
) -> PackageInfo:
    """校验整个压缩包，返回 PackageInfo（含逐条目的 errors/warnings）。"""
    lim = limits_override or limits()
    from .format import file_sha256

    warnings: list[str] = []
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise PackageError('文件不是合法的 ZIP 压缩包（或已损坏）') from None

    with zf:
        files, entry_warnings = _check_infos(zf, lim)
        warnings.extend(entry_warnings)
        budget = Budget()
        discovered = _discover_entries(files)
        if not discovered:
            raise PackageError('压缩包内没有找到 article.json')

        dirs = [item[0] for item in discovered]
        ambiguous = _check_nesting(dirs)

        entries: list[ArticleEntry] = []
        for dir_path, info in discovered:
            entry = ArticleEntry(
                dir_path=dir_path, json_entry=normalize_entry_name(info.filename), raw={}
            )
            entries.append(entry)
            if dir_path in ambiguous:
                entry.errors.append('该目录下存在嵌套的 article.json，无法判定归属')
                continue
            try:
                raw = read_member(
                    zf, info, lim, budget, max_bytes=lim.max_json_bytes
                )
                entry.raw = parse_article_json(raw)
                entry.parsed = parse_fields(entry.raw)
                if entry.parsed.schema_warning:
                    entry.warnings.append(
                        f'article.json 的 schema 版本未知，已尽力导入: {entry.raw.get("schema")!r}'
                    )
                _resolve_media(zf, entry, files, lim, budget, allow_legacy_html)
            except ItemError as exc:
                entry.errors.append(exc.message)
            except LimitExceeded as exc:
                raise exc
            except PackageError:
                raise
            except Exception as exc:  # 兜底：不让单条目的意外异常整包失败
                entry.errors.append(f'条目解析失败: {type(exc).__name__}')

        # 包内 slug 重复 → 后者失败（不静默"后者覆盖前者"）
        seen_slugs: set[str] = set()
        for entry in entries:
            if not entry.parsed:
                continue
            key = entry.parsed.slug
            if key in seen_slugs:
                entry.errors.append(f'压缩包内 slug 重复: {key}')
            seen_slugs.add(key)

        sha = file_sha256(path)

    return PackageInfo(
        entries=entries,
        warnings=warnings,
        entries_count=len(files),
        uncompressed_bytes=budget.total,
        sha256=sha,
    )


def _resolve_media(
    zf: zipfile.ZipFile,
    entry: ArticleEntry,
    files: list[zipfile.ZipInfo],
    lim: Limits,
    budget: Budget,
    allow_legacy_html: bool,
) -> None:
    """按 article.json 的声明解析封面与附件（含单候选回退）。"""
    base = entry.dir_path
    for role, key in (('cover', 'cover'), ('attachment', 'attachment')):
        declared = entry.raw.get(key)
        names: list[str] = []
        original = ''
        declared_sha = None
        declared_size = None
        if isinstance(declared, dict):
            rel = str(declared.get('file') or '')
            original = str(declared.get('original_name') or '')
            declared_sha = declared.get('sha256') or None
            declared_size = declared.get('size')
            if rel:
                candidate = f'{base}/{rel}' if base else rel
                candidate = normalize_entry_name(candidate)
                if '..' in PurePosixPath(candidate).parts:
                    entry.errors.append(f'{role}.file 不允许包含 ".."')
                    continue
                names.append(candidate)
        else:
            # 键缺失：仅当目录下恰好只有一个同角色候选文件时才回退
            candidates = _role_candidates(files, base, role, allow_legacy_html)
            if len(candidates) == 1:
                names.append(candidates[0])
                entry.warnings.append(
                    f'{role} 未在 article.json 中声明，已按目录内唯一候选文件使用: '
                    f'{PurePosixPath(candidates[0]).name}'
                )
            elif len(candidates) > 1:
                entry.errors.append(
                    f'{role} 未声明，且目录内存在多个同类型候选文件，无法自动选择'
                )
                continue
            else:
                entry.errors.append(f'缺少必填的{role}（封面/附件）')
                continue

        target = names[0]
        info = _find_info(files, target)
        if info is None:
            candidates = _role_candidates(files, base, role, allow_legacy_html)
            if len(candidates) == 1:
                target = candidates[0]
                info = _find_info(files, target)
                entry.warnings.append(
                    f'{role} 声明的 {names[0]} 不存在，已改用目录内唯一候选文件 '
                    f'{PurePosixPath(target).name}'
                )
            elif len(candidates) > 1:
                entry.errors.append(
                    f'{role} 声明的文件不存在，且目录内存在多个候选文件，无法自动选择'
                )
                continue
            else:
                entry.errors.append(f'{role} 声明的文件在压缩包内不存在: {names[0]}')
                continue
        if info is None:  # 理论上不可达，仅为类型收窄
            entry.errors.append(f'{role} 的文件无法定位')
            continue

        data = read_member(
            zf, info, lim, budget, max_bytes=settings.COVER_MAX_BYTES
            if role == 'cover'
            else settings.ATTACHMENT_MAX_BYTES
        )
        ext = extension_of(target)
        media_warnings: list[str] = []
        if declared_sha and declared_sha != sha256_bytes(data):
            media_warnings.append(f'{role}.sha256 与包内文件不一致，已以包内文件为准')
        if isinstance(declared_size, int) and declared_size != len(data):
            media_warnings.append(f'{role}.size 与包内文件不一致，已以包内文件为准')

        if role == 'cover':
            if ext not in settings.COVER_EXTENSIONS:
                entry.errors.append(f'封面扩展名不允许: {ext}')
                continue
            # 在这里一次完成“校验 + 决定存储字节”，避免 planner/importer 重复处理
            try:
                stored, cover_warnings = process_cover(data, ext, lim)
            except ItemError as exc:
                entry.errors.append(exc.message)
                continue
            media_warnings.extend(cover_warnings)
        else:
            try:
                media_warnings.extend(check_attachment(data, ext, allow_legacy=allow_legacy_html))
            except ItemError as exc:
                entry.errors.append(exc.message)
                continue
            stored = data

        media = MediaRef(
            entry_name=target,
            original_name=original or PurePosixPath(target).name,
            data=data,
            declared_sha256=declared_sha,
            declared_size=declared_size,
            warnings=media_warnings,
            stored_bytes=stored,
        )
        if role == 'cover':
            entry.cover = media
        else:
            entry.attachment = media


def _find_info(files: list[zipfile.ZipInfo], target: str) -> zipfile.ZipInfo | None:
    for info in files:
        if normalize_entry_name(info.filename) == target:
            return info
    return None


def _role_candidates(
    files: list[zipfile.ZipInfo], base: str, role: str, allow_legacy_html: bool
) -> list[str]:
    """同一目录下的同角色候选文件（不递归）。"""
    out: list[str] = []
    for info in files:
        name = normalize_entry_name(info.filename)
        parent = str(PurePosixPath(name).parent)
        parent = '' if parent == '.' else parent
        if parent != base:
            continue
        base_name = PurePosixPath(name).name.lower()
        if base_name == ARTICLE_JSON_NAME:
            continue
        ext = extension_of(name)
        if role == 'cover':
            if ext in settings.COVER_EXTENSIONS:
                out.append(name)
        elif ext in _allowed_attachment_extensions(allow_legacy=allow_legacy_html):
            out.append(name)
    return sorted(out)
