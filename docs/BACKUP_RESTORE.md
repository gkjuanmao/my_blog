# 数据库备份与恢复（OPS-08）

**背景**：生产库是 SQLite 单文件 `db_data/db.sqlite3`（宿主机 bind mount，容器销毁重建不丢），
但它没有冗余 —— 误执行 `scripts/blog.sh down --purge`、误删 `db_data/`、或磁盘损坏都会**整站数据丢失**。
本文给出备份/恢复步骤；备份用脚本一条命令完成。

---

## 一、备份

```bash
scripts/blog.sh backup                 # → ~/my_blog_backups/my_blog_db_<时间戳>.sqlite3（+ .sha256）
scripts/blog.sh backup --out /data/bak.sqlite3
```

脚本行为：

1. 优先宿主 `sqlite3 .backup`（**热备**，有并发写也拿到一致快照）；宿主没有 `sqlite3` 时，
   改借**运行中容器内的 python** `sqlite3.backup()`（同样安全）；两者都没有才退回 `cp`
   （会明确告警"非事务安全"）。
2. `PRAGMA integrity_check` 校验，结果必须为 `ok`，否则视为备份失败并退出。
3. 生成同名 `.sha256`。

> ⚠️ 备份的是**数据库**。`media/`（封面/附件/内联图）是独立的媒体卷，**不在**本备份里。

## 二、恢复

```bash
# 0) 先校验包完整（在备份文件所在目录执行，-c 按当前目录解析文件名）
sha256sum -c my_blog_db_20261006-120000.sqlite3.sha256     # → 成功

# 1) 停容器（SQLite 文件不能在运行中直接替换）
scripts/blog.sh down

# 2) 把备份放回 bind mount 路径（覆盖现有库）
mkdir -p db_data
cp ~/my_blog_backups/my_blog_db_20261006-120000.sqlite3 db_data/db.sqlite3

# 3) 起容器（entrypoint 会跑 migrate；旧库缺的新迁移会自动补上）
scripts/blog.sh up
```

验收：

- `scripts/blog.sh status` → app/nginx/front/redis healthy；
- `http://<IP>:18888/api/v1/articles/` 返回数据，条数与备份时一致；
- 打开一篇文章，封面正常（若 404 见下）。

## 三、注意事项

- **不要**在容器运行时替换 `db_data/db.sqlite3`：SQLite 可能正持有句柄/写事务，替换会导致
  脏页或 `database disk image is malformed`。
- **降级恢复需谨慎**：用**更旧**的库配**更新**的代码时，`migrate` 只做前向迁移；若期间有
  数据删除类迁移，无法自动回滚。恢复后先小范围核对。
- **媒体不在库内**：换机器或清空媒体卷后封面会 404，执行 `scripts/blog.sh seed-media`
  （数据迁移）或从备份的 `media/` 目录回填。
- **SELinux**：`db_data/` 的挂载在 compose 里已带 `:z`，手工 `cp` 进去的文件会在容器重启挂载时
  重新打标，无需额外 `chcon`。
- **建议**：把 `scripts/blog.sh backup` 挂到 `cron`/`systemd timer` 定期执行，并把
  `~/my_blog_backups/` 同步到异机或对象存储（本地备份挡不住整盘损坏）。