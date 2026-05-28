# encoding:utf-8
"""定时任务：每日推送 + 突发热点告警。

依赖：CoW 已隐式引入 APScheduler-like 调度需求？没有的话用 threading + sleep 自己实现。
为了不增加额外依赖，这里用 threading 写一个最简调度器。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable

import logging
logger = logging.getLogger(__name__)


def _schedule_daily(plugin, hour: int, minute: int, fn: Callable):
    """每日 hh:mm 触发 fn。"""
    def loop():
        while True:
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            sleep_s = (target - now).total_seconds()
            logger.info(f"[AINews] daily push scheduled in {sleep_s/60:.1f} minutes")
            time.sleep(sleep_s)
            try:
                fn()
            except Exception as e:
                logger.exception(f"[AINews] daily push failed: {e}")
            time.sleep(60)  # avoid rerun on same minute

    t = threading.Thread(target=loop, daemon=True, name="AINews-daily")
    t.start()


def _schedule_interval(plugin, minutes: int, fn: Callable):
    """每 N 分钟触发 fn。"""
    def loop():
        # 启动后等 5 分钟再首次跑（避开启动期）
        time.sleep(300)
        while True:
            try:
                fn()
            except Exception as e:
                logger.exception(f"[AINews] interval task failed: {e}")
            time.sleep(minutes * 60)

    t = threading.Thread(target=loop, daemon=True, name="AINews-interval")
    t.start()


def start_scheduler(plugin):
    """启动所有定时任务。plugin 提供 config + 主动发送接口。"""
    cfg = plugin.config

    # 推送 target 留空时，send_to_user 会 fallback 到唯一缓存用户（自用最常见情况）
    if cfg.get("daily_push_enabled", False):
        _schedule_daily(
            plugin,
            hour=int(cfg.get("daily_push_cron_hour", 8)),
            minute=int(cfg.get("daily_push_cron_minute", 0)),
            fn=lambda: _do_daily_push(plugin),
        )
        logger.info("[AINews] daily push enabled at %02d:%02d",
                    cfg.get("daily_push_cron_hour", 8),
                    cfg.get("daily_push_cron_minute", 0))

    if cfg.get("hot_alert_enabled", False):
        _schedule_interval(
            plugin,
            minutes=int(cfg.get("hot_alert_interval_minutes", 60)),
            fn=lambda: _do_hot_alert(plugin),
        )
        logger.info("[AINews] hot alert enabled, interval=%dm",
                    cfg.get("hot_alert_interval_minutes", 60))


def _do_daily_push(plugin):
    """拉热度榜 → 取 top N → 对每个跑一次分析 → 拼摘要 → 发送。"""
    from . import formatter
    from .intent_parser import COUNTRY_ZH, COUNTRY_ALIASES

    # 留空时让 send_to_user 自动 fallback 到唯一缓存用户（方便手动测试）
    target = plugin.config.get("daily_push_target", "")
    top_n = int(plugin.config.get("daily_push_top_n", 3))

    heat = plugin.api_get("/map/heat") or {}
    if not heat:
        plugin.send_to_user(target, "📡 今日暂无新闻热度数据，跳过推送。")
        return

    sorted_pairs = sorted(heat.items(), key=lambda x: x[1], reverse=True)[:top_n]

    # 标题先发
    intro = f"☀️ 早安！今日全球新闻热度 Top {top_n}\n\n"
    for i, (en_name, count) in enumerate(sorted_pairs, 1):
        zh = COUNTRY_ZH.get(en_name, en_name)
        intro += f"{i}. {zh}（{count} 篇）\n"
    intro += "\n稍候发送各国深度分析..."
    plugin.send_to_user(target, intro)

    for en_name, _ in sorted_pairs:
        zh = COUNTRY_ZH.get(en_name, en_name)
        keyword = COUNTRY_ALIASES.get(zh, en_name)
        try:
            result, _job_id = plugin.run_analyze_blocking(keyword)
            brief_id = result.get("_brief_id")  # set by backend after saving
            text = formatter.format_analysis(result, zh, brief_id)
            plugin.send_to_user(target, text)
        except Exception as e:
            plugin.send_to_user(target, f"❌ {zh} 分析失败：{e}")


def _do_hot_alert(plugin, verbose: bool = False):
    """对比今天 vs 昨天热度，发现突增就告警。

    verbose=True 时即便没有告警也回复一条"当前无异常"，方便手动测试看反馈；
    scheduler 自动调用时 verbose=False，保持静默不打扰。
    """
    from .intent_parser import COUNTRY_ZH

    target = plugin.config.get("hot_alert_target", "")
    min_count = int(plugin.config.get("hot_alert_min_count", 5))
    jump = float(plugin.config.get("hot_alert_jump_ratio", 3.0))

    today = plugin.api_get("/map/heat") or {}
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday = plugin.api_get(f"/map/heat?date={yesterday_str}") or {}

    alerts = []
    for country, count in today.items():
        prev = yesterday.get(country, 0)
        if count >= min_count and count >= max(prev, 1) * jump:
            zh = COUNTRY_ZH.get(country, country)
            alerts.append((zh, prev, count))

    if not alerts:
        if verbose:
            plugin.send_to_user(
                target,
                f"🟢 热点告警检查完成 · 当前无异常\n\n"
                f"今日 vs 昨日热度对比：\n"
                f"• 今日 {len(today)} 个国家有报道\n"
                f"• 昨日 {len(yesterday)} 个国家有报道\n"
                f"• 触发阈值：≥{min_count} 篇 且 ×{jump} 增幅\n"
                f"• 无国家达到突增标准"
            )
        return

    lines = ["⚠️ 热度突增告警", ""]
    for zh, prev, count in alerts[:5]:
        lines.append(f"• {zh}：{prev} → {count} 篇（×{count/max(prev,1):.1f}）")
    lines.append("")
    lines.append("💬 回复 '分析 <国家>' 查看为何突增")
    plugin.send_to_user(target, "\n".join(lines))
