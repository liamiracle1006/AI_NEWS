# encoding:utf-8
"""Channel 抽象基类（P12.6）。

dispatcher 通过这个接口操作渠道，不应该再 import 任何 IlinkXxx 类。
未来加 Telegram / Discord 一个新文件实现这个接口即可。

设计原则：
- 不强制实现 send_image / send_file（不是所有渠道都支持）；调用方应该 try
- known_users 必须实现（scheduler 主动推送依赖它）
- start / stop 是生命周期，daemon 调
- set_dispatcher 是回调注入，必须实现
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..types import IncomingMessage


class Channel(ABC):
    """所有消息渠道的统一接口。"""

    # ── 必须实现 ───────────────────────────────────────────────────────

    @abstractmethod
    def set_dispatcher(self, fn: "Callable[[IncomingMessage, Channel], None]") -> None:
        """注册收到消息时的回调。dispatcher 在初始化时调一次。"""
        raise NotImplementedError

    @abstractmethod
    def start(self) -> bool:
        """启动渠道（QR 登录 / WebSocket 连接 / 长轮询线程等）。
        返回 True = 启动成功；False = 启动失败（daemon 会 log + 不继续）。
        阻塞直到初始登录完成（可能要扫码），随后内部起后台轮询线程。
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """停止渠道，清理资源。daemon 关闭时调。"""
        raise NotImplementedError

    @abstractmethod
    def send_text(self, to_user_id: str, text: str) -> bool:
        """发文本消息。返回是否成功。"""
        raise NotImplementedError

    @abstractmethod
    def known_users(self) -> list[str]:
        """有过会话的 user_id 列表（scheduler 主动推送时挑 fallback 用）。"""
        raise NotImplementedError

    # ── 可选实现（默认返回 False / 不支持）────────────────────────────

    def send_image(self, to_user_id: str, image_data) -> bool:
        """发图。image_data: bytes / BytesIO / file path。不支持就返回 False。"""
        return False

    def send_file(self, to_user_id: str, file_path: str) -> bool:
        """发文件（绝对路径）。不支持就返回 False。"""
        return False
