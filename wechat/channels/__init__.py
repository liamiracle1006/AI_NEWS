# encoding:utf-8
"""Channel 抽象层（P12.6）。

为未来加 Telegram / Discord / 钉钉 等渠道留口。当前只有 IlinkChannel 实现。

Channel 基类定义统一接口：send_text / send_image / send_file / known_users / start /
stop / set_dispatcher。dispatcher 通过这个抽象操作，不直接耦合 iLink 协议细节。
"""
from .base import Channel

__all__ = ["Channel"]
