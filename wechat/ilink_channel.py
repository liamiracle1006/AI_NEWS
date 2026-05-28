# encoding:utf-8
"""iLink 通道 — 精简版长轮询 + 发送。

从 CoW 的 weixin_channel.py 提炼出 AI_NEWS 真正需要的部分：
    - 二维码登录（首次启动）
    - 凭证持久化（token + 每用户 context_token）
    - 长轮询 getUpdates
    - 文本/图片/文件发送

剥离的部分：
    - 插件/事件系统（用 set_dispatcher(fn) 替代）
    - 群聊（iLink 只支持单聊）
    - 语音消息（用不到）
    - ChatChannel 基类的 produce/consume/handler 链路
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from .ilink_api import (
    CDN_BASE_URL,
    DEFAULT_BASE_URL,
    WeixinApi,
    upload_media_to_cdn,
)
from .types import IncomingMessage, OutgoingReply, ReplyType

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY = 30
RETRY_DELAY = 2
SESSION_EXPIRED_ERRCODE = -14
TEXT_CHUNK_LIMIT = 4000
QR_LOGIN_TIMEOUT_S = 480
QR_MAX_REFRESHES = 10


def _load_credentials(cred_path: str) -> dict:
    try:
        if os.path.exists(cred_path):
            with open(cred_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[iLink] failed to load credentials: {e}")
    return {}


def _save_credentials(cred_path: str, data: dict):
    os.makedirs(os.path.dirname(cred_path) or ".", exist_ok=True)
    tmp_path = f"{cred_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(tmp_path, 0o600)
    except Exception:
        pass
    os.replace(tmp_path, cred_path)


def _print_qr(qrcode_url: str):
    print("\n" + "=" * 60)
    print("  请使用微信扫描二维码登录 (约 2 分钟过期)")
    print("=" * 60)
    try:
        import qrcode as qr_lib
        qr = qr_lib.QRCode(
            error_correction=qr_lib.constants.ERROR_CORRECT_L,
            box_size=1, border=1,
        )
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        try:
            print(buf.getvalue())
        except UnicodeEncodeError:
            print(f"\n  (终端不支持 Unicode 块字符，请扫链接)")
            print(f"  {qrcode_url}\n")
    except ImportError:
        print(f"\n  {qrcode_url}\n  (pip install qrcode 可在终端显示二维码)\n")


class IlinkChannel:
    """微信 iLink 通道的最小自包含实现。"""

    def __init__(self, credentials_path: str,
                 base_url: str = "",
                 cdn_base_url: str = "",
                 token: str = ""):
        self._credentials_path = os.path.expanduser(credentials_path)
        self._base_url = base_url or DEFAULT_BASE_URL
        self._cdn_base_url = cdn_base_url or CDN_BASE_URL
        self._token = token

        self.api: Optional[WeixinApi] = None
        self._stop_event = threading.Event()
        self._get_updates_buf = ""

        # 每用户最后一次会话 token（发消息时必须 echo）
        self._context_tokens: dict[str, str] = {}
        self._context_tokens_lock = threading.Lock()
        self._received_msg_ids: set[str] = set()  # 去重，CoW 用 ExpiredDict

        # 消息分发回调：fn(msg: IncomingMessage, channel: IlinkChannel) -> None
        self._dispatcher: Optional[Callable[[IncomingMessage, "IlinkChannel"], None]] = None

    # ── 接口 ───────────────────────────────────────────────────────────────

    def set_dispatcher(self, fn: Callable[[IncomingMessage, "IlinkChannel"], None]):
        self._dispatcher = fn

    def start(self) -> bool:
        """登录 + 启动轮询线程。阻塞直到登录成功（或扫码超时）。"""
        creds = _load_credentials(self._credentials_path)
        token = self._token or creds.get("token", "")
        base_url = creds.get("base_url") or self._base_url

        # 恢复 context_tokens（重启后能立即推送）
        for uid, tok in (creds.get("context_tokens") or {}).items():
            if isinstance(uid, str) and isinstance(tok, str) and tok:
                self._context_tokens[uid] = tok
        if self._context_tokens:
            logger.info(f"[iLink] restored {len(self._context_tokens)} context_tokens")

        if not token:
            logger.info("[iLink] no token, starting QR login...")
            login = self._qr_login(base_url)
            if not login:
                logger.error("[iLink] QR login failed")
                return False
            token = login["token"]
            base_url = login.get("base_url", base_url)
            _save_credentials(self._credentials_path, {
                "token": token,
                "base_url": base_url,
                "context_tokens": self._context_tokens,
            })

        self.api = WeixinApi(base_url=base_url, token=token, cdn_base_url=self._cdn_base_url)
        logger.info(f"[iLink] logged in; credentials at {self._credentials_path}")

        threading.Thread(target=self._poll_loop, daemon=True, name="iLink-poll").start()
        return True

    def stop(self):
        self._stop_event.set()

    # ── QR 登录 ─────────────────────────────────────────────────────────────

    def _qr_login(self, base_url: str) -> dict:
        """iLink 二维码登录。状态机来自 CoW 实测：
            wait → scaned（已扫码、待手机确认）→ confirmed（成功）
            或 wait → expired（过期，自动刷新最多 QR_MAX_REFRESHES 次）
        Token 字段是 bot_token，base_url 在响应里叫 baseurl。
        """
        api = WeixinApi(base_url=base_url)
        try:
            qr_resp = api.fetch_qr_code()
        except Exception as e:
            logger.error(f"[iLink] fetch QR failed: {e}")
            return {}
        qrcode = qr_resp.get("qrcode", "")
        qrcode_url = qr_resp.get("qrcode_img_content", "")
        if not qrcode:
            logger.error("[iLink] empty qrcode")
            return {}

        _print_qr(qrcode_url)
        print("  等待扫码...\n")

        scanned_printed = False
        refresh_count = 0
        deadline = time.time() + QR_LOGIN_TIMEOUT_S

        while not self._stop_event.is_set():
            if time.time() >= deadline:
                logger.warning(f"[iLink] QR login timed out after {QR_LOGIN_TIMEOUT_S}s")
                return {}

            try:
                status_resp = api.poll_qr_status(qrcode)
            except Exception as e:
                logger.warning(f"[iLink] QR poll error: {e}")
                time.sleep(2)
                continue

            status = status_resp.get("status", "wait")

            if status == "wait":
                pass
            elif status == "scaned":  # 原版 iLink 拼写就是这样（少一个 n）
                if not scanned_printed:
                    print("  已扫码，请在手机上确认...")
                    scanned_printed = True
            elif status == "expired":
                refresh_count += 1
                if refresh_count >= QR_MAX_REFRESHES:
                    logger.warning(f"[iLink] QR refreshed {QR_MAX_REFRESHES}x, giving up")
                    return {}
                print(f"  二维码已过期，正在刷新（{refresh_count}/{QR_MAX_REFRESHES}）...")
                try:
                    qr_resp = api.fetch_qr_code()
                    qrcode = qr_resp.get("qrcode", "")
                    qrcode_url = qr_resp.get("qrcode_img_content", "")
                    scanned_printed = False
                    _print_qr(qrcode_url)
                except Exception as e:
                    logger.error(f"[iLink] QR refresh failed: {e}")
                    return {}
            elif status == "confirmed":
                bot_token = status_resp.get("bot_token", "")
                bot_id = status_resp.get("ilink_bot_id", "")
                result_base_url = status_resp.get("baseurl", base_url)
                if not bot_token or not bot_id:
                    logger.error("[iLink] confirmed but missing token/bot_id")
                    return {}
                print(f"\n  ✅ 微信登录成功！bot_id={bot_id}")
                logger.info(f"[iLink] login confirmed: bot_id={bot_id}")
                return {"token": bot_token, "base_url": result_base_url}

            self._stop_event.wait(1)

        return {}

    # ── 长轮询 ─────────────────────────────────────────────────────────────

    def _poll_loop(self):
        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                resp = self.api.get_updates(get_updates_buf=self._get_updates_buf)
                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                logger.warning(f"[iLink] getUpdates failed ({consecutive_failures}): {e}")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error(f"[iLink] too many failures, backing off {BACKOFF_DELAY}s")
                    time.sleep(BACKOFF_DELAY)
                    consecutive_failures = 0
                else:
                    time.sleep(RETRY_DELAY)
                continue

            self._get_updates_buf = resp.get("get_updates_buf", self._get_updates_buf)
            msgs = resp.get("msgs", []) or []
            for raw in msgs:
                try:
                    self._handle_incoming(raw)
                except Exception as e:
                    logger.exception(f"[iLink] handle msg failed: {e}")

    def _handle_incoming(self, raw_msg: dict):
        # 拆出文本消息（其他类型暂忽略）
        msg_id = str(raw_msg.get("message_id") or raw_msg.get("seq") or uuid.uuid4().hex[:8])
        if msg_id in self._received_msg_ids:
            return
        self._received_msg_ids.add(msg_id)
        if len(self._received_msg_ids) > 5000:
            # 简易 LRU 清理
            self._received_msg_ids = set(list(self._received_msg_ids)[-2000:])

        from_user_id = raw_msg.get("from_user_id", "")
        context_token = raw_msg.get("context_token", "")
        item_list = raw_msg.get("item_list", []) or []

        text_body = ""
        for item in item_list:
            if item.get("type") == 1:  # ITEM_TEXT
                text_body = item.get("text_item", {}).get("text", "")
                break

        if not text_body or not from_user_id:
            return

        # 更新 context_token
        self._update_context_token(from_user_id, context_token)

        msg = IncomingMessage(
            msg_id=msg_id,
            text=text_body,
            from_user_id=from_user_id,
            context_token=context_token,
            create_time=raw_msg.get("create_time_ms", 0),
        )

        if self._dispatcher:
            try:
                self._dispatcher(msg, self)
            except Exception as e:
                logger.exception(f"[iLink] dispatcher failed: {e}")

    # ── context_token 管理 ─────────────────────────────────────────────────

    def _update_context_token(self, user_id: str, token: str):
        if not user_id or not token:
            return
        with self._context_tokens_lock:
            if self._context_tokens.get(user_id) == token:
                return
            self._context_tokens[user_id] = token
            self._persist_locked()

    def _invalidate_context_token(self, user_id: str):
        with self._context_tokens_lock:
            if user_id in self._context_tokens:
                del self._context_tokens[user_id]
                self._persist_locked()
                logger.info(f"[iLink] invalidated context_token for {user_id}")

    def _persist_locked(self):
        try:
            creds = _load_credentials(self._credentials_path) or {}
            creds["context_tokens"] = dict(self._context_tokens)
            _save_credentials(self._credentials_path, creds)
        except Exception as e:
            logger.warning(f"[iLink] failed to persist context_tokens: {e}")

    def _check_response(self, resp: dict, receiver: str):
        if not isinstance(resp, dict):
            return
        ret = resp.get("ret")
        errcode = resp.get("errcode")
        if ret == SESSION_EXPIRED_ERRCODE or errcode == SESSION_EXPIRED_ERRCODE:
            self._invalidate_context_token(receiver)

    # ── 发送 ───────────────────────────────────────────────────────────────

    def known_users(self) -> list[str]:
        """所有有过会话的 user_id 列表（供 dispatcher fallback）。"""
        with self._context_tokens_lock:
            return list(self._context_tokens.keys())

    def send_text(self, to_user_id: str, text: str) -> bool:
        token = self._context_tokens.get(to_user_id, "")
        if not token:
            logger.warning(f"[iLink] no context_token for {to_user_id}, drop")
            return False
        # 微信文本上限 ~ 5000 字，分块发送
        for chunk in self._chunk_text(text, TEXT_CHUNK_LIMIT):
            try:
                resp = self.api.send_text(to_user_id, chunk, token)
                self._check_response(resp, to_user_id)
            except Exception as e:
                logger.exception(f"[iLink] send_text failed for {to_user_id}: {e}")
                return False
        return True

    def send_image(self, to_user_id: str, image_data) -> bool:
        """image_data: bytes / BytesIO / 文件路径。会自动写临时文件并上传。"""
        token = self._context_tokens.get(to_user_id, "")
        if not token:
            logger.warning(f"[iLink] no context_token for {to_user_id}, drop image")
            return False
        tmp_path = self._materialize_image(image_data)
        try:
            from .ilink_api import upload_media_to_cdn
            meta = upload_media_to_cdn(self.api, tmp_path, to_user_id, media_type=1)
            resp = self.api.send_image_item(
                to=to_user_id,
                context_token=token,
                encrypt_query_param=meta["encrypt_query_param"],
                aes_key_b64=meta["aes_key_b64"],
                ciphertext_size=meta["ciphertext_size"],
            )
            self._check_response(resp, to_user_id)
            return True
        except Exception as e:
            logger.exception(f"[iLink] send_image failed: {e}")
            return False
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def send_file(self, to_user_id: str, file_path: str) -> bool:
        token = self._context_tokens.get(to_user_id, "")
        if not token:
            logger.warning(f"[iLink] no context_token for {to_user_id}, drop file")
            return False
        try:
            meta = upload_media_to_cdn(self.api, file_path, to_user_id, media_type=3)
            resp = self.api.send_file_item(
                to=to_user_id,
                context_token=token,
                encrypt_query_param=meta["encrypt_query_param"],
                aes_key_b64=meta["aes_key_b64"],
                file_name=os.path.basename(file_path),
                file_size=meta["raw_size"],
            )
            self._check_response(resp, to_user_id)
            return True
        except Exception as e:
            logger.exception(f"[iLink] send_file failed: {e}")
            return False

    def send(self, to_user_id: str, reply: OutgoingReply) -> bool:
        if reply.type == ReplyType.TEXT:
            return self.send_text(to_user_id, str(reply.content))
        if reply.type == ReplyType.IMAGE:
            return self.send_image(to_user_id, reply.content)
        if reply.type == ReplyType.FILE:
            return self.send_file(to_user_id, str(reply.content))
        logger.warning(f"[iLink] unsupported reply type: {reply.type}")
        return False

    @staticmethod
    def _chunk_text(text: str, limit: int) -> list[str]:
        if len(text) <= limit:
            return [text]
        chunks = []
        for i in range(0, len(text), limit):
            chunks.append(text[i:i + limit])
        return chunks

    @staticmethod
    def _materialize_image(data) -> str:
        """把 bytes / BytesIO / path 统一落地为一个临时 png 路径。"""
        import tempfile
        if isinstance(data, str) and os.path.exists(data):
            return data
        fd, path = tempfile.mkstemp(prefix="ilink_img_", suffix=".png")
        os.close(fd)
        if isinstance(data, io.BytesIO):
            data.seek(0)
            Path(path).write_bytes(data.read())
        elif isinstance(data, (bytes, bytearray)):
            Path(path).write_bytes(bytes(data))
        else:
            raise ValueError(f"unsupported image data type: {type(data)}")
        return path
