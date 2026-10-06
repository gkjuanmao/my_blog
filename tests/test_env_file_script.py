"""``scripts/blog.sh`` 的 ``check_env_file`` 行为测试（TEST-10）。

prod 启动路径此前未测：``.env`` 缺失时是否从 ``.env.example`` 自动生成、
``DJANGO_ENV=prod`` 缺 ``DJANGO_SECRET_KEY`` 是否阻断、``env_value`` 的引号/CR 处理。

做法：把 ``blog.sh`` 的顶层副作用（``cd "$ROOT_DIR"``）与末尾 ``main "$@"`` 调用去掉后
``source`` 进来，再在隔离的临时工作目录里直接调用这些函数 —— 不会真的改动仓库里的
``.env``/``db_data``。
"""
import shutil
import subprocess
from pathlib import Path

import pytest

BLOG_SH = Path(__file__).resolve().parent.parent / 'scripts' / 'blog.sh'
# 需要在 source 时去掉的顶层行（否则会切走 cwd / 直接执行入口）
STRIPPED_LINES = {'cd "$ROOT_DIR"', 'main "$@"'}

pytestmark = pytest.mark.skipif(shutil.which('bash') is None, reason='需要 bash')


def _library() -> str:
    """blog.sh 归一化为 LF，并去掉顶层副作用行。"""
    text = BLOG_SH.read_text(encoding='utf-8').replace('\r\n', '\n')
    lines = [line for line in text.split('\n') if line.strip() not in STRIPPED_LINES]
    return '\n'.join(lines)


def _work(tmp_path: Path) -> Path:
    directory = tmp_path / 'work'
    directory.mkdir(exist_ok=True)
    return directory


def _write_env(tmp_path: Path, content: str) -> None:
    (_work(tmp_path) / '.env').write_text(content, encoding='utf-8')


def _run(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """在 tmp_path/work 里 source blog.sh（已去副作用）后执行 body。"""
    work = _work(tmp_path)
    (work / 'blog_lib.sh').write_text(_library(), encoding='utf-8', newline='\n')
    return subprocess.run(
        ['bash', '-c', f'source ./blog_lib.sh\n{body}\n'],
        cwd=str(work),
        capture_output=True,
        text=True,
    )


def _output(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


class TestCheckEnvFile:
    def test_auto_generates_env_from_example(self, tmp_path):
        (_work(tmp_path) / '.env.example').write_text('DJANGO_ENV=dev\n', encoding='utf-8')

        result = _run(tmp_path, 'check_env_file')

        assert result.returncode == 0, _output(result)
        assert (_work(tmp_path) / '.env').read_text(encoding='utf-8') == 'DJANGO_ENV=dev\n'
        assert '自动生成' in _output(result)

    def test_missing_env_and_example_dies(self, tmp_path):
        result = _run(tmp_path, 'check_env_file')

        assert result.returncode != 0
        assert '.env.example' in _output(result)

    def test_prod_without_secret_key_dies(self, tmp_path):
        _write_env(tmp_path, 'DJANGO_ENV=prod\nDJANGO_SECRET_KEY=\n')

        result = _run(tmp_path, 'check_env_file')

        assert result.returncode != 0
        assert 'DJANGO_SECRET_KEY' in _output(result)

    def test_prod_with_secret_key_passes(self, tmp_path):
        _write_env(tmp_path, 'DJANGO_ENV=prod\nDJANGO_SECRET_KEY=abc\n')

        result = _run(tmp_path, 'check_env_file')

        assert result.returncode == 0, _output(result)
        assert (_work(tmp_path) / 'db_data').is_dir()

    def test_dev_without_secret_key_passes(self, tmp_path):
        _write_env(tmp_path, 'DJANGO_ENV=dev\n')

        result = _run(tmp_path, 'check_env_file')

        assert result.returncode == 0, _output(result)

    def test_defaults_to_dev_when_env_unset(self, tmp_path):
        """不写 DJANGO_ENV 时按 dev 处理，不得因缺密钥阻断。"""
        _write_env(tmp_path, '# 空配置\n')

        result = _run(tmp_path, 'check_env_file')

        assert result.returncode == 0, _output(result)


class TestEnvValue:
    def test_strips_quotes_and_carriage_return(self, tmp_path):
        """CRLF 的 .env（Windows 编辑过）也要读到干净值 —— 回归 TEST-10 发现的缺陷。"""
        _work(tmp_path)
        (_work(tmp_path) / '.env').write_bytes(b'DJANGO_ENV="prod"\r\n')

        result = _run(tmp_path, 'env_value DJANGO_ENV')

        assert result.stdout.strip() == 'prod'

    def test_crlf_prod_is_detected_by_check_env_file(self, tmp_path):
        """CRLF 下 DJANGO_ENV=prod 必须仍被识别为 prod（否则 prod 缺密钥会被漏检）。"""
        _work(tmp_path)
        (_work(tmp_path) / '.env').write_bytes(b'DJANGO_ENV=prod\r\nDJANGO_SECRET_KEY=\r\n')

        result = _run(tmp_path, 'check_env_file')

        assert result.returncode != 0
        assert 'DJANGO_SECRET_KEY' in _output(result)

    def test_missing_file_returns_nonzero(self, tmp_path):
        result = _run(tmp_path, 'env_value DJANGO_ENV || echo MISSING')

        assert 'MISSING' in result.stdout
