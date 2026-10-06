"""生成演示用游记归档包（供 `scripts/blog.sh seed-demo` 导入）。

自包含：只依赖运行期已有的 Pillow / pypinyin / Django，可**直接在 app 容器内执行**：

    podman exec my_blog_app_1 python /app/scripts/seed_demo.py --out /tmp/seed30.zip --count 30

产物是标准归档包（与系统导出的格式一致，schema 为 v2）：
    manifest.json + README.md
      + articles/NNN-<slug>/article.json   （含 content 结构化 Markdown 正文）
      + articles/NNN-<slug>/cover.jpg
      + articles/NNN-<slug>/attachment.pdf
      + articles/NNN-<slug>/images/<内容寻址名>.webp   （正文插图）

因此导入走的是真实链路（校验 → 预检 → 入库），不是直接写库。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import sys
import unicodedata
import zipfile
from datetime import timedelta

# 允许以 `python scripts/seed_demo.py` 直接在容器内运行
sys.path.insert(0, os.getcwd())

import django  # noqa: E402

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from pypinyin import Style, lazy_pinyin  # noqa: E402

from articles.archive.format import (  # noqa: E402
    ARTICLE_JSON_NAME,
    MANIFEST_NAME,
    README_NAME,
    README_TEMPLATE,
    SCHEMA_ARCHIVE,
    SCHEMA_ARTICLE,
    article_dir_name,
    attachment_entry_name,
    cover_entry_name,
    images_entry_name,
    sha256_bytes,
)
from articles.images import (  # noqa: E402
    inline_rel_path,
    inline_url,
    process_inline_image,
)
from articles.utils import generate_slug  # noqa: E402

# --------------------------------------------------------------------------- 数据

CATEGORIES: list[tuple[str, str]] = [
    ('国内游', '国内长线目的地的行程与攻略'),
    ('境外游', '出境自由行的见闻与准备'),
    ('自然风光', '山川湖海与荒野风光'),
    ('城市漫步', '在城市里慢慢走的日常'),
    ('海岛度假', '海岛、沙滩与潜水'),
]

TAGS = ['徒步', '美食', '摄影', '自驾', '古城', '海岛', '雪山', '露营', '博物馆', '骑行']

# (标题, 地点, 分类, 标签, 摘要)
ENTRIES: list[tuple[str, str, str, list[str], str]] = [
    ('云南丽江古城慢行', '云南·丽江', '城市漫步', ['古城', '摄影'],
     '清晨的石板路还没被游客填满，我在四方街听了一整条巷子的流水声。'),
    ('西藏林芝的春天', '西藏·林芝', '自然风光', ['雪山', '摄影'],
     '桃花开在雪山脚下，318 沿线的每一个弯道都值得停车。'),
    ('四川稻城亚丁徒步记', '四川·稻城', '自然风光', ['徒步', '雪山'],
     '牛奶海的颜色会随光线变三次，走完这一段终于明白什么叫身体在地狱。'),
    ('新疆喀纳斯之秋', '新疆·阿勒泰', '自然风光', ['摄影', '露营'],
     '白桦林在九月末集体变黄，清晨的雾气从湖面一直漫到观鱼台。'),
    ('内蒙古呼伦贝尔草原', '内蒙古·呼伦贝尔', '自然风光', ['自驾', '露营'],
     '公路笔直得像用尺子画出来，两天里遇到的羊比车多。'),
    ('青海湖环湖骑行', '青海·海南州', '自然风光', ['骑行', '摄影'],
     '三百六十公里，逆风的段落最难，但油菜花开的七月值得。'),
    ('甘肃敦煌莫高窟', '甘肃·敦煌', '国内游', ['古城', '博物馆'],
     '在洞窟里待了三个小时，出来时眼睛还停在那些褪色的青绿上。'),
    ('广西阳朔漓江竹筏', '广西·桂林', '自然风光', ['骑行', '摄影'],
     '兴坪的老渔翁还在点灯，江面倒影比山本身更像水墨。'),
    ('贵州黔东南苗寨', '贵州·黔东南', '国内游', ['古城', '美食'],
     '长桌宴从寨头摆到寨尾，酸汤鱼的味道记了很久。'),
    ('福建厦门鼓浪屿', '福建·厦门', '海岛度假', ['海岛', '美食'],
     '岛上没有车，只有琴声、猫和绕不完的小路。'),
    ('浙江杭州西湖四季', '浙江·杭州', '城市漫步', ['骑行', '摄影'],
     '从苏堤骑到杨公堤，春天看柳，秋天看桂，冬天等一场雪。'),
    ('安徽黄山看云海', '安徽·黄山', '自然风光', ['徒步', '雪山'],
     '凌晨四点摸黑上光明顶，日出那一刻所有人都安静了。'),
    ('湖南张家界天门山', '湖南·张家界', '自然风光', ['徒步', '摄影'],
     '玻璃栈道比想象中稳，反倒是山间的雾让人不敢眨眼。'),
    ('江西婺源油菜花', '江西·婺源', '国内游', ['摄影', '美食'],
     '篁岭的晒秋和江岭的花海，是两个季节的两副样子。'),
    ('海南三亚亚龙湾', '海南·三亚', '海岛度假', ['海岛', '美食'],
     '白天浮潜看珊瑚，晚上在沙滩上吃第一市场的和乐蟹。'),
    ('北京中轴线漫步', '北京·东城', '城市漫步', ['博物馆', '骑行'],
     '从永定门一路走到钟鼓楼，七点八公里装下了六百年。'),
    ('上海外滩的夜', '上海·黄浦', '城市漫步', ['摄影', '美食'],
     '江对岸的灯亮起来时，江这边的人都在举着手机。'),
    ('重庆洪崖洞夜游', '重庆·渝中', '城市漫步', ['美食', '摄影'],
     '导航在这里失效，但随便拐进一条巷子都能吃到好东西。'),
    ('陕西西安城墙骑行', '陕西·西安', '国内游', ['古城', '美食'],
     '十三公里城墙上骑一圈，下来直奔回民街。'),
    ('山西平遥古城', '山西·晋中', '国内游', ['古城', '摄影'],
     '票号、镖局和县衙都还在原处，日落后游客一散就安静了。'),
    ('日本京都岚山', '日本·京都', '境外游', ['古城', '摄影'],
     '竹林小径人很多，但往嵯峨野深处走十分钟就只剩风声。'),
    ('泰国清迈慢生活', '泰国·清迈', '境外游', ['美食', '摄影'],
     '在古城里租了辆小摩托，一周只做三件事：吃、逛、发呆。'),
    ('冰岛环岛自驾', '冰岛·雷克雅未克', '境外游', ['自驾', '摄影'],
     '一天里过了四季，瀑布、黑沙滩和极光都赶上了。'),
    ('瑞士因特拉肯', '瑞士·因特拉肯', '境外游', ['雪山', '徒步'],
     '少女峰下的草坡绿得不真实，缆车上去后气温掉到零度。'),
    ('新西兰皇后镇', '新西兰·皇后镇', '境外游', ['徒步', '摄影'],
     '瓦卡蒂普湖的蓝一天里变好几种，傍晚在山顶等灯光亮起。'),
    ('挪威特罗姆瑟追极光', '挪威·特罗姆瑟', '境外游', ['摄影', '露营'],
     '连着三个晚上云层太厚，第四晚绿色的光从山脊后面浮出来。'),
    ('意大利五渔村', '意大利·拉斯佩齐亚', '境外游', ['海岛', '美食'],
     '五个村子靠一条海边小火车连起来，最爱的还是傍晚的韦尔纳扎。'),
    ('摩洛哥马拉喀什', '摩洛哥·马拉喀什', '境外游', ['古城', '美食'],
     '麦地那像迷宫，傍晚的广场上鼓声和炊烟一起升起来。'),
    ('秘鲁马丘比丘', '秘鲁·库斯科', '境外游', ['徒步', '博物馆'],
     '凌晨排队进山，云雾散开的那十秒钟值回全部高原反应。'),
    ('土耳其卡帕多奇亚', '土耳其·格雷梅', '境外游', ['摄影', '露营'],
     '热气球在日出前升空，从空中看这片地貌像另一个星球。'),
]

# --------------------------------------------------------------------------- 封面图


def _vgrad(width: int, height: int, top: tuple, bottom: tuple) -> Image.Image:
    """竖直渐变。"""
    strip = Image.new('RGB', (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        strip.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return strip.resize((width, height))


def _scene_mountain(w, h, rnd):
    img = _vgrad(w, h, (135, 190, 235), (250, 225, 200))
    d = ImageDraw.Draw(img, 'RGBA')
    d.ellipse([w * 0.72, h * 0.10, w * 0.88, h * 0.30], fill=(255, 240, 190, 235))
    for base, color in [(0.55, (92, 112, 130)), (0.68, (68, 88, 108)), (0.80, (44, 60, 78))]:
        pts = [(0, h)]
        x = -w * 0.1
        while x < w * 1.1:
            pts.append((x + w * 0.12, h * base - h * rnd.uniform(0.05, 0.22)))
            x += w * 0.24
            pts.append((x, h * base + h * rnd.uniform(0.0, 0.05)))
            x += w * 0.12
        pts += [(w, h * base + h * 0.2), (w, h)]
        d.polygon(pts, fill=color)
    return img


def _scene_sea(w, h, rnd):
    img = _vgrad(w, h, (255, 190, 130), (170, 215, 235))
    d = ImageDraw.Draw(img, 'RGBA')
    d.ellipse([w * 0.40, h * 0.26, w * 0.60, h * 0.52], fill=(255, 245, 205, 245))
    sea = _vgrad(w, int(h * 0.45), (36, 92, 140), (120, 190, 210))
    img.paste(sea, (0, int(h * 0.55)))
    d = ImageDraw.Draw(img, 'RGBA')
    for i in range(14):
        y = h * 0.58 + i * h * 0.028
        x = rnd.uniform(-w * 0.1, w * 0.8)
        d.line([(x, y), (x + rnd.uniform(w * 0.12, w * 0.34), y)],
               fill=(255, 255, 255, 90), width=2)
    return img


def _scene_desert(w, h, rnd):
    img = _vgrad(w, h, (250, 205, 130), (238, 150, 90))
    d = ImageDraw.Draw(img, 'RGBA')
    d.ellipse([w * 0.60, h * 0.14, w * 0.76, h * 0.32], fill=(255, 235, 180, 230))
    for i, tone in enumerate([(214, 150, 92), (196, 128, 78), (168, 104, 64)]):
        base = h * (0.62 + i * 0.12)
        d.ellipse([-w * 0.25, base, w * 1.25, base + h * 0.55], fill=tone)
    return img


def _scene_city(w, h, rnd):
    img = _vgrad(w, h, (30, 34, 72), (128, 84, 132))
    d = ImageDraw.Draw(img, 'RGBA')
    d.ellipse([w * 0.12, h * 0.10, w * 0.20, h * 0.22], fill=(255, 250, 225, 240))
    x = 0
    while x < w:
        bw = rnd.uniform(w * 0.05, w * 0.10)
        bh = rnd.uniform(h * 0.22, h * 0.52)
        top = h - bh
        d.rectangle([x, top, x + bw, h], fill=(22, 24, 44, 255))
        for wy in range(int(top) + 10, h - 8, 18):
            for wx in range(int(x) + 6, int(x + bw) - 6, 14):
                if rnd.random() < 0.42:
                    d.rectangle([wx, wy, wx + 5, wy + 8], fill=(255, 214, 130, 220))
        x += bw + rnd.uniform(2, 10)
    return img


def _scene_forest(w, h, rnd):
    img = _vgrad(w, h, (226, 236, 220), (86, 132, 96))
    d = ImageDraw.Draw(img, 'RGBA')
    for i, tone in enumerate([(96, 140, 108), (70, 112, 88), (48, 86, 70)]):
        base = h * (0.55 + i * 0.13)
        x = -w * 0.05
        while x < w * 1.05:
            th = h * rnd.uniform(0.16, 0.30)
            d.polygon([(x, base), (x + w * 0.045, base - th), (x + w * 0.09, base)], fill=tone)
            x += w * 0.055
    for i in range(3):
        y = h * (0.35 + i * 0.09)
        d.rectangle([0, y, w, y + h * 0.035], fill=(255, 255, 255, 70))
    return img


def _scene_snow(w, h, rnd):
    img = _vgrad(w, h, (206, 226, 244), (255, 255, 255))
    d = ImageDraw.Draw(img, 'RGBA')
    for i, tone in enumerate([(176, 198, 220), (150, 176, 202), (120, 148, 178)]):
        base = h * (0.58 + i * 0.13)
        pts = [(0, h)]
        x = -w * 0.1
        while x < w * 1.1:
            pts.append((x + w * 0.1, base - h * rnd.uniform(0.08, 0.24)))
            x += w * 0.2
            pts.append((x, base + h * rnd.uniform(0, 0.03)))
            x += w * 0.1
        pts.append((w, h))
        d.polygon(pts, fill=tone)
    for _ in range(320):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h * 0.75)
        r = rnd.uniform(1, 3)
        d.ellipse([x, y, x + r, y + r], fill=(255, 255, 255, 220))
    return img


SCENES = [_scene_mountain, _scene_sea, _scene_desert, _scene_city, _scene_forest, _scene_snow]


def make_cover(index: int) -> bytes:
    """生成一张 1200x675 的 JPEG 封面。"""
    w, h = 1200, 675
    rnd = random.Random(1000 + index)
    img = SCENES[index % len(SCENES)](w, h, rnd).filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=88, optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- 正文（Markdown）

SEASONS = ['四月', '五月', '六月', '九月', '十月', '十一月']
TRANSPORTS = ['高铁 + 自驾', '飞机 + 包车', '长途汽车', '自驾', '火车 + 骑行']
COMPANIONS = ['一个人', '两个人', '和朋友', '带着家人']


def build_content(
    *,
    title: str,
    location: str,
    category: str,
    tags: list[str],
    summary: str,
    index: int,
    image_url: str,
) -> str:
    """生成结构化 Markdown 正文（标题/表格/有序与无序列表/引用/插图/链接都用上）。"""
    rnd = random.Random(3000 + index)
    season = SEASONS[index % len(SEASONS)]
    transport = TRANSPORTS[index % len(TRANSPORTS)]
    companion = COMPANIONS[index % len(COMPANIONS)]
    days = rnd.randint(3, 6)
    budget = rnd.randrange(1800, 9000, 100)
    cat_slug = generate_slug(category)
    tag_text = '、'.join(f'`{tag}`' for tag in tags)

    return f"""{season}的{location}，是{companion}走的一趟。{summary}

## 行程速览

| 项目 | 信息 |
| :--- | :--- |
| 目的地 | {location} |
| 建议天数 | {days} 天 |
| 最佳季节 | {season} |
| 人均预算 | 约 {budget} 元 |
| 交通方式 | {transport} |

## 路上的几天

![{title}]({image_url})

1. **第一天**：抵达 {location}，先在住处附近走一圈，把路上的疲惫走散，顺手把第二天的路线确认一遍。
2. **第二天**：按{transport}的方式往外走，路上留够停车的余地——值得看的地方往往不在计划里。
3. **第三天**：放慢一点，只安排一个重点，其余时间交给街巷、市场或者一段没有目的的步行。
4. **返程**：留半天机动，把没来得及去的地方补上，也为下一次留个理由。

## 几个提醒

- 出发前查一下当季天气，{season}的温差比想象中大，外套别省。
- 门票与住宿尽量提前订，尤其是周末和节假日。
- 现金少带一点备用即可，但小摊与乡镇不一定支持扫码。
- 拍照别只盯着地标，清晨和傍晚的光线最值得多等半小时。

> 行程写得再满，也总会留下遗憾；而遗憾恰好是下次再来的理由。

## 参考信息

- 地点：{location}
- 分类：[{category}](/category/{cat_slug})
- 标签：{tag_text}
"""


def make_inline_image(index: int) -> bytes:
    """生成一张正文插图，并走与上传端点**相同**的管线压成规范 WebP。"""
    w, h = 1200, 800
    rnd = random.Random(4000 + index)
    img = SCENES[(index + 3) % len(SCENES)](w, h, rnd).filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=90, optimize=True)
    return process_inline_image(buf.getvalue(), 'jpg').data


# --------------------------------------------------------------------------- PDF

_ASCII_FILLER = (
    'The road curved along the ridge for another hour before the valley opened. '
    'We stopped where a small stone marker pointed to a spring, filled the bottles, '
    'and watched clouds slide across the far peaks. Nobody spoke for a while; '
    'the wind did the talking. Later the light turned amber and we walked back down '
    'past terraced fields, greeting farmers who were still working. Dinner was simple '
    'and hot, and by nine the whole village had gone quiet.'
).split()


def _ascii(text: str) -> str:
    """中文转拼音后的 ASCII（PDF 内置字体不含 CJK）。"""
    pinyin = ' '.join(lazy_pinyin(text, style=Style.NORMAL))
    norm = unicodedata.normalize('NFKD', pinyin).encode('ascii', 'ignore').decode()
    return ' '.join(norm.split())


def _esc(text: str) -> str:
    return text.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')


def make_pdf(title: str, location: str, index: int) -> bytes:
    """手写一个合法的多页 PDF（Helvetica，ASCII 文本）。"""
    rnd = random.Random(2000 + index)
    title_a = _ascii(title) or f'Travel Notes {index + 1}'
    loc_a = _ascii(location) or 'Unknown'
    pages = rnd.randint(3, 5)

    words: list[str] = []
    while len(words) < pages * 30 * 9:
        words.extend(_ASCII_FILLER)

    objects: dict[int, bytes] = {}
    kids = []
    for p in range(pages):
        page_num, content_num = 4 + 2 * p, 5 + 2 * p
        kids.append(f'{page_num} 0 R')
        body = [' '.join(words[:9])]
        words = words[9:]
        for _ in range(29):
            body.append(' '.join(words[:9]))
            words = words[9:]

        ops = []
        if p == 0:
            ops.append(f'BT /F1 19 Tf 56 782 Td ({_esc(title_a)}) Tj ET')
            loc_line = _esc(f'Location: {loc_a}')
            ops.append(f'BT /F1 11 Tf 56 760 Td ({loc_line}) Tj ET')
            top_y = 726
        else:
            head = _esc(f'{title_a}  -  page {p + 1}')
            ops.append(f'BT /F1 10 Tf 56 800 Td ({head}) Tj ET')
            top_y = 770
        ops.append(f'BT /F1 11 Tf 56 {top_y} Td 17 TL')
        for i, line in enumerate(body):
            text = f'({_esc(line)}) Tj'
            ops.append(text if i == 0 else f'T* {text}')
        ops.append('ET')
        page_label = _esc(f'page {p + 1} / {pages}')
        ops.append(f'BT /F1 9 Tf 56 40 Td ({page_label}) Tj ET')
        stream = '\n'.join(ops).encode('latin-1')
        objects[content_num] = (
            b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream'
        )
        objects[page_num] = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
            f'/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>'
        ).encode()

    objects[1] = b'<< /Type /Catalog /Pages 2 0 R >>'
    kids_ref = ' '.join(kids)
    objects[2] = f'<< /Type /Pages /Kids [{kids_ref}] /Count {pages} >>'.encode()
    objects[3] = (
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica '
        b'/Encoding /WinAnsiEncoding >>'
    )

    buf = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(buf)
        buf.extend(b'%d 0 obj\n' % num)
        buf.extend(objects[num])
        buf.extend(b'\nendobj\n')

    xref_off = len(buf)
    count = max(objects) + 1
    buf.extend(b'xref\n0 %d\n' % count)
    buf.extend(b'0000000000 65535 f \n')
    for num in range(1, count):
        buf.extend(b'%010d 00000 n \n' % offsets[num])
    buf.extend(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (count, xref_off))
    return bytes(buf)


# --------------------------------------------------------------------------- 打包


def build_package(out_path: str, *, count: int, author: str) -> tuple[int, int]:
    """生成归档包，返回 (篇数, 字节数)。"""
    now = timezone.localtime()
    base_time = now - timedelta(days=800)
    exported_at = now.isoformat()
    entries = ENTRIES[:count]

    manifest_articles = []
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for index, (title, location, cat_name, tag_names, summary) in enumerate(entries, start=1):
            slug = generate_slug(title)
            publish_time = base_time + timedelta(days=(index - 1) * 26 + ((index - 1) % 5))
            cover = make_cover(index - 1)
            attachment = make_pdf(title, location, index - 1)
            dir_name = f'articles/{article_dir_name(index, slug)}'
            cover_name = cover_entry_name('jpg')
            attachment_name = attachment_entry_name('pdf')

            # 正文插图：内容寻址名（sha256[:32].webp），正文 URL 与包内文件名天然一致，
            # 导入时不需要改写正文（与上传端点同一条压缩管线）
            image_bytes = make_inline_image(index - 1)
            image_name = os.path.basename(inline_rel_path(image_bytes))
            image_entry = images_entry_name(image_name)
            content = build_content(
                title=title,
                location=location,
                category=cat_name,
                tags=tag_names,
                summary=summary,
                index=index,
                image_url=inline_url(image_bytes),
            )

            payload = {
                'schema': SCHEMA_ARTICLE,
                'source': {'id': None, 'exported_at': exported_at, 'app_version': 'seed-demo'},
                'title': title,
                'slug': slug,
                'summary': summary,
                'content': content,
                'images': [
                    {
                        'file': image_entry,
                        'sha256': sha256_bytes(image_bytes),
                        'size': len(image_bytes),
                    }
                ],
                'publish_time': publish_time.isoformat(),
                'location': location,
                'is_published': True,
                # 以下三项导出但导入时按 D3 忽略
                'views': 0,
                'created_at': publish_time.isoformat(),
                'updated_at': publish_time.isoformat(),
                'author': {'username': author},
                'category': {
                    'slug': generate_slug(cat_name),
                    'name': cat_name,
                    'description': dict(CATEGORIES)[cat_name],
                },
                'tags': [{'slug': generate_slug(n), 'name': n} for n in tag_names],
                'cover': {
                    'file': cover_name,
                    'original_name': f'{title}-封面.jpg',
                    'sha256': sha256_bytes(cover),
                    'size': len(cover),
                },
                'attachment': {
                    'file': attachment_name,
                    'original_name': f'{title}.pdf',
                    'sha256': sha256_bytes(attachment),
                    'size': len(attachment),
                },
                'import': {'action': 'auto'},
            }
            zf.writestr(f'{dir_name}/{cover_name}', cover)
            zf.writestr(f'{dir_name}/{attachment_name}', attachment)
            zf.writestr(f'{dir_name}/{image_entry}', image_bytes)
            zf.writestr(
                f'{dir_name}/{ARTICLE_JSON_NAME}',
                json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
            )
            manifest_articles.append({
                'index': index,
                'path': dir_name,
                'slug': slug,
                'title': title,
                'is_published': True,
                'updated_at': publish_time.isoformat(),
            })

        manifest = {
            'schema': SCHEMA_ARCHIVE,
            'generator': {'app': 'my_blog', 'version': 'seed-demo', 'django': django.get_version()},
            'exported_at': exported_at,
            'filters': {'source': 'seed-demo', 'count': len(manifest_articles)},
            'ignored_on_import': ['views', 'created_at', 'updated_at'],
            'limits': {},
            'warnings': [],
            'articles': manifest_articles,
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        zf.writestr(README_NAME, README_TEMPLATE)

    return len(entries), os.path.getsize(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description='生成演示游记归档包')
    parser.add_argument('--out', default='/tmp/seed_demo.zip', help='输出 zip 路径')
    parser.add_argument('--count', type=int, default=len(ENTRIES), help='篇数（默认全部）')
    parser.add_argument('--author', default='admin', help='包内作者用户名')
    args = parser.parse_args()

    count, size = build_package(args.out, count=args.count, author=args.author)
    digest = hashlib.sha256(open(args.out, 'rb').read()).hexdigest()
    print(f'已生成 {args.out}')
    print(f'  篇数: {count}  体积: {size} 字节  sha256: {digest[:16]}…')


if __name__ == '__main__':
    main()
