# 部署与资源参数

三平台共用 `cloud-functions/backend.py` 与 `runtime.py`，旧 API 路径/key 保留。
JM 已移除全局图片捕获、downloader 修改和自代理；图片在同请求还原后只编码一次。
账号配置为环境变量，用户 Cookie 覆盖服务账号；客户端逐请求创建，库重试为 0。

VPS：创建 Python 3.14 venv，`pip install -r requirements.txt`，从 `.env.example`
配置 `.env`，`set -a; . ./.env; set +a`，`gunicorn -c gunicorn.conf.py index:app`。
Vercel：导入完整仓库，Flask 入口 `index.py`，Python 3.12。
EdgeOne Makers：Python 云函数，根/catch-all 薄入口使用平台识别标记，核心在产物目录内。
Serverless 清空 `CACHE_DB`；VPS 必须设置各 worker 共用的持久路径。

缓存：每 worker 64MiB、磁盘内容 512MiB；SQLite 原子事务及所有者/90秒租约跨进程
合并相同请求，全局冷图片 2、单 worker 1。RedisURL 可选，短超时，协调失败 503，
热缓存可用；Redis 使用 noeviction，以免协调键被淘汰。SQLite 实际磁盘还含 WAL/空闲页。

width/w 1–2047、quality/q 1–100，LVGL > PNG > JPEG；透明白底、长图完整等比缩小。
默认下载 20MiB、解码 3200万像素、响应 4MiB，HTTP 返回完整二进制和长度。
Cookie/Authorization 响应 private,no-store；错误 no-store；公共图缓存24小时。
诊断 `/health/runtime`、X-Cache、原始/实际尺寸。参数见 `.env.example`。

Nginx 将 `/` 转发 `http://127.0.0.1:3002`，传 Host、X-Forwarded-Host、X-Forwarded-Proto，
读超时25秒；PUBLIC_URL 可含被代理剥离的前缀。CDN 保留图片参数，鉴权跳过读写。
真实平台、Linux原生依赖、Vela/AstroBox 和 VPS P95/RSS 需上线验收。
