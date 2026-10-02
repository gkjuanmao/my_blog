"""封面图片处理：统一压缩为 WebP、限制最长边、剥 EXIF/ICC。

与内联图（``articles/images.py``）同思路但**独立成模块**：两者的目标形态不同
（封面 ``COVER_MAX_LONG_EDGE`` / 内联图 ``INLINE_IMAGE_MAX_LONG_EDGE``），且封面的
幂等约束更严 —— 归档包必须能「导出 → 导入 → 再导出」字节收敛，否则每轮都会重写
并损失画质（实测教训）。

两条硬规则：

1. **已达标就原样返回**（``_is_normalized``）。判定必须在任何变换之前做：
   ``exif_transpose`` 会把 EXIF 抹掉，之后再看 ``info['exif']`` 永远是没有。
2. **凡是重新编码，输出一定是 WebP**。因此落盘扩展名恒为 ``.webp``，由
   :class:`ProcessedCover` 的 ``ext`` 字段给出（调用方据此拼存储路径）。
"""
import hashlib
from dataclasses import dataclass, field
from io import BytesIO

from django.conf import settings
from PIL import Image, ImageOps

# Pillow 的 format 名 → 允许的扩展名（与 COVER_EXTENSIONS 对齐）。
# MPO 必须映射到 jpg/jpeg：手机（尤其 iPhone）拍的人像/连拍照片存成 MPO，
# 它本质是"JPEG + 附加帧"，Pillow 报的 format 是 MPO 而不是 JPEG ——
# 漏掉它会直接把手机原图的封面上传打成 400（实测踩到）。
_FORMAT_TO_EXT: dict[str, set[str]] = {
    'JPEG': {'jpg', 'jpeg'},
    'MPO': {'jpg', 'jpeg'},
    'PNG': {'png'},
    'WEBP': {'webp'},
}


class CoverError(ValueError):
    """封面处理失败（上传端点转成 400，归档校验转成该篇失败）。"""


@dataclass(frozen=True)
class ProcessedCover:
    """压缩结果：可直接落盘的字节 + 落盘扩展名 + 尺寸 + 告警。

    ``ext`` 恒为 ``webp``（见模块文档第 2 条）。
    """

    data: bytes
    ext: str
    width: int
    height: int
    warnings: list[str] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        """落盘字节的 SHA-256（``cover_image_sha256`` 的唯一依据）。"""
        return hashlib.sha256(self.data).hexdigest()


def _is_webp(data: bytes) -> bool:
    """按魔数判断是否为 WebP（``RIFF....WEBP``）。"""
    return len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP'


def _normalize_mode(image: Image.Image) -> Image.Image:
    """把调色板/灰度等模式归一到 WebP 可编码的模式（保留透明通道）。"""
    if image.mode in ('RGB', 'RGBA'):
        return image
    if image.mode == 'P':
        return image.convert('RGBA' if 'transparency' in image.info else 'RGB')
    if image.mode in ('LA', 'L'):
        return image.convert('RGBA' if image.mode == 'LA' else 'RGB')
    return image.convert('RGB')


def _structure_ok(ext: str, data: bytes) -> bool:
    """文件尾部结构是否干净（无附加数据）。

    只用于决定**是否要重编码**与给出 polyglot 告警，不是权威校验：
    拿不准就返回 False（宁可重编码）。
    """
    if ext in ('jpg', 'jpeg'):
        return data.endswith(b'\xff\xd9')
    if ext == 'png':
        return data.endswith(b'IEND\xaeB`\x82')
    if ext == 'webp':
        if not _is_webp(data):
            return False
        declared = int.from_bytes(data[4:8], 'little') + 8
        return declared in (len(data), len(data) - 1)  # RIFF 允许 1 字节 padding
    return False


def _is_normalized(image: Image.Image, data: bytes) -> bool:
    """是否已是目标形态：WebP、最长边达标、无 EXIF/ICC、尾部结构干净。

    ⚠️ 必须在任何变换（``exif_transpose``）**之前**调用，否则会把带方向信息的
    旋转原图误判为已达标，从而原样返回仍含 EXIF 的字节。
    """
    if (image.format or '').upper() != 'WEBP' or not _is_webp(data):
        return False
    if max(image.size) > settings.COVER_MAX_LONG_EDGE:
        return False
    if not _structure_ok('webp', data):
        return False
    info = image.info or {}
    return 'exif' not in info and 'icc_profile' not in info


def _encode_webp(image: Image.Image, *, lossless: bool) -> bytes:
    """把图片编码成 WebP（``method=6`` 压缩率最好；封面数量少，可接受）。"""
    buffer = BytesIO()
    if lossless:
        image.save(buffer, format='WEBP', lossless=True, quality=100, method=6)
    else:
        image.save(
            buffer, format='WEBP', quality=settings.COVER_WEBP_QUALITY, method=6
        )
    return buffer.getvalue()


def process_cover(data: bytes, ext: str, *, max_pixels: int) -> ProcessedCover:
    """校验封面并返回**应写入存储的字节**。

    - 已达标（WebP、最长边合格、无元数据、结构干净）→ 原样返回，保证幂等；
    - 否则重编码：校正方向 → 剥 EXIF/ICC → 缩放最长边 → 编码 WebP。

    :raises CoverError: 扩展名/格式/像素/体积不合法，或压缩后仍超上限。
    """
    ext = ext.lower()
    if ext not in settings.COVER_EXTENSIONS:
        raise CoverError('封面仅支持 JPG/PNG/WebP 格式')
    if len(data) > settings.COVER_MAX_BYTES:
        raise CoverError(f'封面大小不能超过 {settings.COVER_MAX_BYTES // 1024**2}MB')

    warnings: list[str] = []
    try:
        source = Image.open(BytesIO(data))
        width, height = source.size
        # 先按头部尺寸判像素再 load()：否则压缩炸弹会在解码阶段就吃满内存
        if width * height > max_pixels:
            raise CoverError(f'封面像素数超限（{width}x{height}）')
        normalized = _is_normalized(source, data)
        # 告警依据必须是 Orientation 标签值，不能看对象身份：
        # Pillow 12.x 在**没有** Orientation 时也会返回副本（实测）。
        rotated = source.getexif().get(0x0112) not in (None, 1)
        source.load()
    except CoverError:
        raise
    except Image.DecompressionBombError as exc:  # pragma: no cover - 依赖 Pillow 阈值
        raise CoverError('封面像素数超限') from exc
    except Exception as exc:
        raise CoverError('封面无法解析') from exc

    actual = (source.format or '').upper()
    if ext not in _FORMAT_TO_EXT.get(actual, set()):
        raise CoverError(f'封面实际格式 {actual or "未知"} 与扩展名 .{ext} 不一致')

    if normalized and not rotated:
        return ProcessedCover(
            data=data, ext='webp', width=width, height=height, warnings=[]
        )

    if rotated:
        warnings.append('封面含 EXIF 方向信息，已按方向校正并剥离元数据')
    elif not _structure_ok(ext, data):
        warnings.append('封面尾部含附加数据（疑似 polyglot），已重编码清除')

    image: Image.Image = ImageOps.exif_transpose(source) or source
    image = _normalize_mode(image)

    long_edge = settings.COVER_MAX_LONG_EDGE
    if max(image.size) > long_edge:
        image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)

    # WebP 保存会从 info 带出 EXIF/ICC，必须显式删键，否则"剥离元数据"失效
    image.info.pop('exif', None)
    image.info.pop('icc_profile', None)

    if actual == 'PNG':
        # 截图/图形类封面用无损更清晰；与有损取小者，避免"体积反增"
        lossless = _encode_webp(image, lossless=True)
        lossy = _encode_webp(image, lossless=False)
        encoded = lossless if len(lossless) <= len(lossy) else lossy
    else:
        encoded = _encode_webp(image, lossless=False)

    if len(encoded) > settings.COVER_OUTPUT_BYTES:
        raise CoverError(
            f'封面压缩后仍超过 {settings.COVER_OUTPUT_BYTES // 1024**2}MB'
        )

    return ProcessedCover(
        data=encoded,
        ext='webp',
        width=image.width,
        height=image.height,
        warnings=warnings,
    )
