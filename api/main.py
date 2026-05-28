"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

# 让 news.* / wechat.* 的 logger.info / logger.warning 都能打印到终端，
# 不然 uvicorn 默认只放它自己的 access log，应用层日志被静默吞掉。
# force=True 是关键：覆盖 uvicorn 启动时设置的 root handlers。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)

log = logging.getLogger(__name__)

app = FastAPI(title="AI News Analyzer", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


REFRESH_INTERVAL_SECONDS = 3600  # 每小时自动刷新一次


@app.on_event("startup")
async def _startup():
    """启动时立即建缓存，然后每小时自动刷新。可选地启动微信守护进程。"""
    asyncio.create_task(_auto_refresh_loop())

    # 微信守护进程（opt-in）：.env 中设 WECHAT_ENABLED=true 后才启动
    try:
        from wechat import start_daemon_async
        # 略晚一拍再启微信，让 FastAPI 路由先就绪（dispatcher 要回调 /api/*）
        async def _delayed_wechat():
            await asyncio.sleep(2)
            start_daemon_async()
        asyncio.create_task(_delayed_wechat())
    except Exception as exc:  # noqa: BLE001
        print(f"[wechat] startup failed: {exc}")


async def _auto_refresh_loop():
    from news.article_cache import cache_status, fetch_and_cache
    from news.config import load_config

    loop = asyncio.get_running_loop()

    while True:
        status = cache_status()
        age = status.get("age_minutes", 9999)

        # 若缓存不足 55 分钟则跳过（避免刚启动就双重刷新）
        if status["has_today"] and age < 55:
            wait = (55 - age) * 60
            print(f"[cache] 缓存 {age:.0f} 分钟前刷新过，{wait/60:.0f} 分钟后再刷新")
            await asyncio.sleep(wait)
            continue

        print("[cache] 开始自动刷新 RSS 数据...")
        try:
            cfg = await loop.run_in_executor(None, load_config)
            articles = await loop.run_in_executor(None, lambda: fetch_and_cache(cfg))
            print(f"[cache] 自动刷新完成：{len(articles)} 篇文章")
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] 自动刷新失败：{exc}")

        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
