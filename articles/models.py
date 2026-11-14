"""博客文章数据模型：文章、分类、标签。"""
import uuid

from django.conf import settings
from django.db import models


def _dynamic_upload_path(prefix: str, filename: str) -> str:
    """按当前年月与 UUID 生成文件存储路径，保留原始扩展名。"""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    name = f'{uuid.uuid4().hex}.{ext}' if ext else uuid.uuid4().hex
    return f'{prefix}/{name}'


def cover_upload_path(instance, filename: str) -> str:
    """封面图片动态路径：covers/UUID.ext。"""
    return _dynamic_upload_path('covers', filename)


def file_upload_path(instance, filename: str) -> str:
    """附件动态路径：files/UUID.ext。"""
    return _dynamic_upload_path('files', filename)


class Category(models.Model):
    """文章分类。"""

    name = models.CharField(max_length=100, verbose_name='分类名称')
    slug = models.SlugField(max_length=100, unique=True, verbose_name='URL 别名')
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='分类描述',
    )

    class Meta:
        verbose_name = '分类'
        verbose_name_plural = '分类'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    """文章标签。"""

    name = models.CharField(max_length=100, verbose_name='标签名称')
    slug = models.SlugField(max_length=100, unique=True, verbose_name='URL 别名')

    class Meta:
        verbose_name = '标签'
        verbose_name_plural = '标签'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class Article(models.Model):
    """博客文章，含封面图与附件文件。"""

    title = models.CharField(max_length=200, db_index=True, verbose_name='标题')
    slug = models.SlugField(max_length=200, unique=True, db_index=True, verbose_name='URL 别名')
    summary = models.CharField(max_length=500, blank=True, verbose_name='摘要')
    content = models.TextField(blank=True, default='', verbose_name='Markdown 正文')
    publish_time = models.DateTimeField(db_index=True, verbose_name='发布时间')
    location = models.CharField(max_length=255, blank=True, verbose_name='地点')
    cover_image = models.ImageField(
        upload_to=cover_upload_path,
        verbose_name='封面图片',
    )
    cover_image_name = models.CharField(max_length=255, verbose_name='封面原始文件名')
    cover_image_sha256 = models.CharField(
        max_length=64, blank=True, verbose_name='封面落盘文件 SHA-256（当前文件字节哈希，非源文件）'
    )
    file = models.FileField(
        upload_to=file_upload_path, blank=True, default='', verbose_name='附件文件'
    )
    file_name = models.CharField(
        max_length=255, blank=True, default='', verbose_name='附件原始文件名'
    )
    file_sha256 = models.CharField(
        max_length=64, blank=True, verbose_name='附件落盘文件 SHA-256（当前文件字节哈希，非源文件）'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='作者',
    )
    # 归属变更审计：谁在什么时候把这篇划给了别人（只有超管能改，见 articles/api.py）
    author_changed_at = models.DateTimeField(null=True, blank=True, verbose_name='归属变更时间')
    author_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='归属变更人',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='所属分类',
    )
    tags = models.ManyToManyField(Tag, blank=True, verbose_name='标签')
    is_published = models.BooleanField(default=False, verbose_name='是否发布')
    views = models.PositiveIntegerField(default=0, verbose_name='阅读量')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '文章'
        verbose_name_plural = '文章'
        ordering = ['-publish_time']

    def __str__(self) -> str:
        return self.title


class ArchiveTicket(models.Model):
    """一次性下载票据（导出包 / 回滚包）。

    id 即 URL 中的 ticket（能力 URL，不绑定 owner，见方案 P1-A）：TTL + 单次使用 +
    nginx 侧 access_log off 构成缓解手段。
    """

    class Kind(models.TextChoices):
        EXPORT = 'export', '导出包'
        ROLLBACK = 'rollback', '回滚包'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='archive_tickets',
        verbose_name='创建者',
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, verbose_name='类型')
    path = models.CharField(max_length=255, verbose_name='相对 ARCHIVE_ROOT 的路径')
    filename = models.CharField(max_length=255, verbose_name='下载文件名')
    bytes = models.BigIntegerField(default=0, verbose_name='体积')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    expires_at = models.DateTimeField(verbose_name='过期时间')
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='使用时间')

    class Meta:
        verbose_name = '归档下载票据'
        verbose_name_plural = '归档下载票据'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['expires_at'])]

    def __str__(self) -> str:
        return f'{self.kind}:{self.id}'


class ArchiveStaging(models.Model):
    """导入暂存包（两阶段流程的中间态）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='archive_stagings',
        verbose_name='上传者',
    )
    dir = models.CharField(max_length=255, verbose_name='相对 ARCHIVE_ROOT 的目录')
    sha256 = models.CharField(max_length=64, verbose_name='包 SHA-256')
    bytes = models.BigIntegerField(default=0, verbose_name='包体积')
    entries = models.IntegerField(default=0, verbose_name='条目数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    expires_at = models.DateTimeField(verbose_name='过期时间')
    consumed_at = models.DateTimeField(
        null=True, blank=True, verbose_name='已执行时间'
    )
    lease_until = models.DateTimeField(
        null=True, blank=True, verbose_name='使用中租约到期'
    )

    class Meta:
        verbose_name = '归档导入暂存'
        verbose_name_plural = '归档导入暂存'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['expires_at'])]

    def __str__(self) -> str:
        return f'staging:{self.id}'


class ArticleImportTask(models.Model):
    """归档导入任务（异步执行，由独立的 import_worker 进程消费）。

    为什么要有这张表：导入是分钟级的长任务，同步跑会占着 HTTP 连接，
    前端 15s 超时先于服务端完成，用户看到「网络错误」但文章其实写进去了。
    改成「入队 → worker 执行 → 前端轮询」后，HTTP 只负责表达意图。

    设计铁律：**计划（plan）绝不在入队时冻结**。``build_plan`` 是对数据库的
    实时快照，排队任务的前置任务会改变快照结果；冻结它等于给队列埋一个
    必然过期的结论。因此这里只存「意图」（staging + strategy + 三个开关），
    计划在 worker 里执行前现算。
    """

    class Status(models.TextChoices):
        QUEUED = 'queued', '排队中'
        RUNNING = 'running', '执行中'
        SUCCEEDED = 'succeeded', '已完成'
        FAILED = 'failed', '失败'
        CANCELED = 'canceled', '已取消'

    class Phase(models.TextChoices):
        WAITING = 'waiting', '排队中'
        VALIDATING = 'validating', '校验压缩包'
        SNAPSHOTTING = 'snapshotting', '生成回滚包'
        WRITING = 'writing', '写入文章'
        DONE = 'done', '结束'

    #: 终态集合：轮询据此停止，列表据此判断「进行中」
    TERMINAL_STATUSES = frozenset({Status.SUCCEEDED, Status.FAILED, Status.CANCELED})
    ACTIVE_STATUSES = frozenset({Status.QUEUED, Status.RUNNING})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='import_tasks',
        verbose_name='提交者',
    )
    # 暂存包被 purge 掉后任务仍要可查（历史记录比暂存行活得久）
    staging = models.ForeignKey(
        ArchiveStaging,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks',
        verbose_name='暂存包',
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, verbose_name='状态'
    )
    phase = models.CharField(
        max_length=16, choices=Phase.choices, default=Phase.WAITING, verbose_name='阶段'
    )
    # 给人看的一句话进度（"写入文章 42/180"），前端不必自己拼文案
    phase_label = models.CharField(max_length=64, blank=True, default='', verbose_name='阶段文案')

    # 入队时快照，执行期不可变（避免前端中途改参数导致计划与意图不符）
    strategy = models.CharField(max_length=16, default='skip', verbose_name='导入策略')
    auto_create_taxonomy = models.BooleanField(default=True, verbose_name='自动创建分类与标签')
    as_draft = models.BooleanField(default=False, verbose_name='全部导入为草稿')

    #: {sha256, entries, bytes_uncompressed}：用于「同一个包导过两次」的防呆提示
    package = models.JSONField(default=dict, verbose_name='包信息')
    #: 入队时预检的 totals（create/update/skip/failed），与执行结果不一致时记 plan_drift
    preview_totals = models.JSONField(default=dict, verbose_name='预检快照')

    total = models.IntegerField(default=0, verbose_name='总条目')
    processed = models.IntegerField(default=0, verbose_name='已处理')
    created = models.IntegerField(default=0, verbose_name='新建')
    updated = models.IntegerField(default=0, verbose_name='覆盖')
    skipped = models.IntegerField(default=0, verbose_name='跳过')
    failed = models.IntegerField(default=0, verbose_name='失败')

    #: 终态报告，结构与同步版 commit 的响应一致（含 items / plan_drift）
    report = models.JSONField(default=dict, verbose_name='执行报告')
    error_code = models.CharField(max_length=32, blank=True, default='', verbose_name='错误码')
    error_message = models.CharField(
        max_length=255, blank=True, default='', verbose_name='错误信息'
    )
    error_hint = models.CharField(max_length=255, blank=True, default='', verbose_name='处理指引')
    rollback_ticket = models.ForeignKey(
        ArchiveTicket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='import_tasks',
        verbose_name='回滚包票据',
    )

    worker_id = models.CharField(max_length=64, blank=True, default='', verbose_name='执行进程')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    # 心跳用于判定「进程被杀掉后遗留的 running」：见 tasks.sweep_stale
    heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name='心跳')
    # 已领取次数（每次 claim +1）。锁被别的执行者占用时靠它做重试上限，
    # 避免误起第二个 worker 就把任务判死（见 tasks._requeue_after_lock_conflict）
    attempts = models.IntegerField(default=0, verbose_name='执行尝试次数')
    # 下次可被领取的时间：锁冲突后延迟重排，避免两个 worker 每 2s 互相空转抢锁
    next_attempt_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name='下次可执行时间'
    )

    class Meta:
        verbose_name = '归档导入任务'
        verbose_name_plural = '归档导入任务'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['finished_at']),
        ]

    def __str__(self) -> str:
        return f'task:{self.id}:{self.status}'

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    def progress(self) -> dict:
        total = self.total or 0
        if total:
            percent = min(100, round(self.processed * 100 / total))
        else:
            percent = 100 if self.is_terminal else 0
        return {
            'total': total,
            'processed': self.processed,
            'create': self.created,
            'update': self.updated,
            'skip': self.skipped,
            'failed': self.failed,
            'percent': percent,
        }
