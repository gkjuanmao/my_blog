"""用户头像测试：upload_to 路径规则与格式/大小校验（对齐 DESIGN 4.1 / 7.2）。"""
import io
import re

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from users.models import validate_avatar


def _jpeg(name: str = 'avatar.jpg') -> SimpleUploadedFile:
    """生成一张最小 JPEG 上传文件。"""
    img = Image.new('RGB', (10, 10), color='blue')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type='image/jpeg')


@pytest.mark.django_db
class TestUserAvatar:
    def test_avatar_path_uses_uuid(self, user):
        """头像落盘路径为 avatars/%Y/%m/<32位uuid>.ext。"""
        user.avatar.save('我的头像.jpg', _jpeg('我的头像.jpg'))
        user.refresh_from_db()

        assert re.fullmatch(r'avatars/\d{4}/\d{2}/[0-9a-f]{32}\.jpg', user.avatar.name)

    def test_validate_avatar_accepts_jpg(self):
        """校验函数接受 JPG。"""
        validate_avatar(_jpeg())

    def test_validate_avatar_rejects_gif(self):
        """校验函数拒绝 GIF。"""
        gif = SimpleUploadedFile('a.gif', b'GIF89a', content_type='image/gif')

        with pytest.raises(ValidationError):
            validate_avatar(gif)

    def test_validate_avatar_rejects_oversize(self):
        """校验函数拒绝超过 2MB 的文件。"""
        oversize = SimpleUploadedFile(
            'big.jpg', b'x' * (2 * 1024 * 1024 + 1), content_type='image/jpeg'
        )

        with pytest.raises(ValidationError):
            validate_avatar(oversize)
