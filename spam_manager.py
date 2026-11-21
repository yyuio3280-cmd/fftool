# -*- coding: utf-8 -*-
"""
spam_manager.py — Keep-Alive Spam Manager (متوافق مع البوت)
مبني على المنطق المصحح الذي يعمل، مع واجهة async للبوت.
"""
from __future__ import annotations

import os
import sys
import time
import socket
import hashlib
import logging
import threading
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import urllib3
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# ───────────────── إعدادات ─────────────────
AES_KEY = b"Yg&tc%DEuh6%Zc^8"
AES_IV = b"6oyZDr22E3ychjM%"
RELEASE = "OB55"
CLIENT_VER = "1.120.1"
PARALLEL_ONLINE = 2
PARALLEL_CHAT = 2
PING_INTERVAL = 3.0
RECONNECT_DELAY = 2.0

JWT_API = "https://ff-jwt-gen-api.lovable.app/api/public/token?access_token={token}"
INSPECT_URL = "https://100067.connect.garena.com/oauth/token/inspect?access_token={t}&client_type=2"
LOGIN_URLS = [
    "https://loginbp.ppmainecoonghj.com/MajorLogin",
    "https://loginbp.ggpolarbear.com/MajorLogin",
]
CLIENT_HOST = "clientbp.ppmainecoonghj.com"

UA = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
HEADERS_BASE = {
    "User-Agent": UA,
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Unity-Version": "2018.4.12f1",
    "X-GA-SV": "1789535859",
    "X-GA": "v1 1",
    "ReleaseVersion": RELEASE,
}

# pb2 اختياري
_MajorLoginRes = None
_GetLoginDataRes = None
_MajorLoginReq = None
HAS_PB2 = False

# حالة الجلسات النشطة (متوافق مع البوت)
active_sessions: Dict[str, Dict[str, Any]] = {}


def _log(msg: str):
    logger.info(msg)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_pb2():
    global _MajorLoginRes, _GetLoginDataRes, _MajorLoginReq, HAS_PB2
    try:
        import MajoRLoGinrEq_pb2 as mlr
        _MajorLoginReq = getattr(mlr, "MajorLogin", None) or getattr(mlr, "MajorLoginReq", None)
    except Exception:
        pass
    try:
        import thunderFF_pb2 as th
        _MajorLoginRes = getattr(th, "MajorLoginRes", None)
        _GetLoginDataRes = getattr(th, "GetLoginDataRes", None)
        if _MajorLoginReq is None:
            _MajorLoginReq = getattr(th, "MajorLoginReq", None)
    except Exception:
        pass
    if _MajorLoginRes is None:
        try:
            import MajorLoginRes_pb2 as m
            _MajorLoginRes = getattr(m, "MajorLoginRes", None)
        except Exception:
            pass
    if _GetLoginDataRes is None:
        try:
            import GetLoginDataRes_pb2 as g
            _GetLoginDataRes = getattr(g, "GetLoginDataRes", None) or getattr(g, "GetLoginData", None)
        except Exception:
            pass
    HAS_PB2 = bool(_MajorLoginRes and _GetLoginDataRes)


# تحميل pb2 مرة واحدة عند الاستيراد
try:
    load_pb2()
except Exception:
    pass


def aes_encrypt(data: bytes, key=AES_KEY, iv=AES_IV) -> bytes:
    return AES.new(key, AES.MODE_CBC, iv).encrypt(pad(data, 16))


def inspect_token(token: str) -> dict:
    r = requests.get(
        INSPECT_URL.format(t=token),
        headers={
            "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)",
            "Connection": "close",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "100067.connect.garena.com",
        },
        timeout=12,
        verify=False,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise RuntimeError(f"inspect error: {d.get('error')}")
    return d


def build_major_payload(open_id: str, token: str, platform: int = 4) -> bytes:
    if _MajorLoginReq is not None:
        try:
            p = _MajorLoginReq()
            for name, val in [
                ("event_time", int(time.time() * 1000) & 0xFFFFFFFF),
                ("game_id", 1),
                ("platform_id", int(platform) if platform else 4),
                ("client_version", CLIENT_VER),
                ("system_software", "Android OS 13 / API-33"),
                ("system_hardware", "Handheld"),
                ("telecom_operator", "Android"),
                ("network", "wifi"),
                ("screen_width", 1080),
                ("screen_height", 2400),
                ("dpi", "480"),
                ("cpu_hardware", "arm64-v8a"),
                ("memory", 8),
                ("gl_render", "Adreno"),
                ("gl_version", "OpenGL ES 3.2"),
                ("device_id", hashlib.md5(open_id.encode()).hexdigest()[:16]),
                ("client_ip", "0.0.0.0"),
                ("language", "en"),
                ("open_id", open_id),
                ("open_id_type", str(platform or 4)),
                ("device_type", "Handheld"),
                ("device_model", "SM-G998B"),
                ("login_token", token),
                ("access_token", token),
                ("token", token),
                ("platform_type", int(platform) if platform else 4),
                ("platform", int(platform) if platform else 4),
                ("release_channel", "and_usa"),
                ("extra_info", "empty"),
            ]:
                try:
                    if hasattr(p, name):
                        setattr(p, name, val)
                except Exception:
                    pass
            raw = p.SerializeToString()
            return aes_encrypt(raw)
        except Exception as e:
            _log(f"build protobuf payload fail: {e}")

    def _str(fn, s):
        b = s.encode("utf-8")
        return bytes([(fn << 3) | 2, len(b)]) + b

    def _varint(fn, n):
        n = int(n) & 0xFFFFFFFFFFFFFFFF
        out = bytes([(fn << 3) | 0])
        while n > 0x7F:
            out += bytes([(n & 0x7F) | 0x80])
            n >>= 7
        out += bytes([n & 0x7F])
        return out

    body = b""
    body += _varint(1, int(time.time()))
    body += _str(3, open_id)
    body += _str(4, token)
    body += _varint(5, int(platform) if platform else 4)
    body += _str(6, CLIENT_VER)
    body += _str(7, "Android OS 13")
    body += _str(8, RELEASE)
    return aes_encrypt(body)


def parse_major_response(content: bytes):
    if not content or len(content) < 20:
        return None
    blobs = [content[64:] if len(content) > 64 else content, content]
    for raw in list(blobs):
        for off in (0, 32, 64):
            chunk = raw[off:]
            aligned = chunk[: len(chunk) - (len(chunk) % 16)] if len(chunk) >= 16 else b""
            if not aligned:
                continue
            try:
                pt = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).decrypt(aligned)
                padn = pt[-1]
                if 1 <= padn <= 16:
                    pt = pt[:-padn]
                blobs.append(pt)
            except Exception:
                pass

    if _MajorLoginRes is not None:
        for blob in blobs:
            for off in range(0, min(160, max(1, len(blob)))):
                try:
                    m = _MajorLoginRes()
                    m.ParseFromString(blob[off:])
                    tok = getattr(m, "token", None)
                    reg = getattr(m, "region", None)
                    if tok and reg:
                        return {
                            "token": tok,
                            "account_id": int(getattr(m, "account_id", 0) or 0),
                            "server_time": int(getattr(m, "server_time", 0) or time.time()),
                            "aes_ak": bytes(getattr(m, "aes_ak", b"") or b""),
                            "iv_i": bytes(getattr(m, "iv_i", b"") or b""),
                            "region": str(reg),
                            "url": str(getattr(m, "url", "") or f"https://{CLIENT_HOST}"),
                        }
                except Exception:
                    continue

    try:
        import blackboxprotobuf

        def walk(o, found=None):
            if found is None:
                found = {}
            if isinstance(o, dict):
                for v in o.values():
                    walk(v, found)
            elif isinstance(o, (list, tuple)):
                for v in o:
                    walk(v, found)
            elif isinstance(o, (bytes, bytearray)):
                try:
                    s = o.decode("utf-8", "ignore")
                except Exception:
                    s = ""
                if s.startswith("eyJ") and len(s) > 40:
                    found.setdefault("token", s)
            elif isinstance(o, str):
                if o.startswith("eyJ") and len(o) > 40:
                    found.setdefault("token", o)
                if o in ("BD", "IND", "ME", "SG", "TH", "BR"):
                    found.setdefault("region", o)
                if o.startswith("http"):
                    found.setdefault("url", o)
            elif isinstance(o, int) and o > 100000:
                found.setdefault("account_id", o)
            return found

        for blob in blobs:
            for off in (0, 8, 16, 32, 64):
                if off >= len(blob):
                    continue
                try:
                    msg, _ = blackboxprotobuf.decode_message(blob[off:])
                    f = walk(msg)
                    if f.get("token"):
                        return {
                            "token": f["token"],
                            "account_id": int(f.get("account_id") or 0),
                            "server_time": int(time.time()),
                            "aes_ak": AES_KEY,
                            "iv_i": AES_IV,
                            "region": f.get("region") or "ME",
                            "url": f.get("url") or f"https://{CLIENT_HOST}",
                        }
                except Exception:
                    continue
    except Exception as e:
        _log(f"blackbox: {e}")
    return None


def major_login(token: str, open_id: str, platform: int) -> dict:
    payload = build_major_payload(open_id, token, platform)
    last_err = None
    for url in LOGIN_URLS:
        try:
            h = dict(HEADERS_BASE)
            r = requests.post(url, headers=h, data=payload, timeout=15, verify=False)
            _log(f"MajorLogin {url} → {r.status_code} len={len(r.content)}")
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                continue
            parsed = parse_major_response(r.content)
            if parsed and parsed.get("token"):
                return parsed
            last_err = "parse fail"
        except Exception as e:
            last_err = str(e)
            _log(f"MajorLogin err: {e}")
    raise RuntimeError(f"MajorLogin failed: {last_err}")


def jwt_api_fallback(token: str) -> dict:
    url = JWT_API.format(token=token)
    r = requests.get(url, timeout=15, verify=False)
    r.raise_for_status()
    d = r.json()
    jwt = d.get("token")
    if not jwt or not str(jwt).startswith("ey"):
        raise RuntimeError("JWT API no token")
    region = d.get("region") or "ME"
    try:
        region = (d.get("jwt_decoded") or {}).get("payload", {}).get("lock_region") or region
    except Exception:
        pass
    return {
        "token": jwt,
        "account_id": int(d.get("account_uid") or d.get("Uid") or 0),
        "server_time": int(time.time()),
        "aes_ak": AES_KEY,
        "iv_i": AES_IV,
        "region": str(region),
        "url": d.get("url") or f"https://{CLIENT_HOST}",
        "online": None,
        "chat": None,
        "name": "",
    }


def get_login_data(payload: bytes, jwt: str, base_url: str) -> dict:
    gurl = str(base_url).rstrip("/") + "/GetLoginData"
    h = dict(HEADERS_BASE)
    h["Authorization"] = f"Bearer {jwt}"
    h["Host"] = CLIENT_HOST
    r = requests.post(gurl, headers=h, data=payload, timeout=15, verify=False)
    _log(f"GetLoginData → {r.status_code} len={len(r.content)}")
    if r.status_code != 200:
        raise RuntimeError(f"GetLoginData {r.status_code}")
    content = r.content
    if _GetLoginDataRes is not None:
        for off in range(0, min(128, max(1, len(content)))):
            try:
                res = _GetLoginDataRes()
                res.ParseFromString(content[off:])
                online = getattr(res, "functional_addrs", None) or getattr(res, "Online_IP_Port", None)
                chat = getattr(res, "informational_addrs", None) or getattr(res, "AccountIP_Port", None) or online
                name = getattr(res, "nickname", None) or getattr(res, "AccountName", None) or ""
                if online and ":" in str(online):
                    return {
                        "online": str(online).strip(),
                        "chat": str(chat or online).strip(),
                        "name": str(name or ""),
                    }
            except Exception:
                continue
    try:
        import blackboxprotobuf
        import re as _re
        msg, _ = blackboxprotobuf.decode_message(content)
        found = []

        def walk(o):
            if isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, (list, tuple)):
                for v in o:
                    walk(v)
            elif isinstance(o, (bytes, bytearray, str)):
                s = o.decode("utf-8", "ignore") if isinstance(o, (bytes, bytearray)) else o
                if _re.match(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}$", s):
                    found.append(s)

        walk(msg)
        if found:
            return {"online": found[0], "chat": found[1] if len(found) > 1 else found[0], "name": ""}
    except Exception as e:
        _log(f"GetLoginData blackbox: {e}")
    raise RuntimeError("GetLoginData parse fail")


def region_prefix(region: str, typ: str) -> str:
    reg = (region or "ME").upper()
    if typ == "OnLine":
        return "7219" if reg == "BD" else ("7214" if reg == "IND" else "7215")
    return "8119" if reg == "BD" else ("8114" if reg == "IND" else "8115")


def ka_bytes(region: str) -> bytes:
    reg = (region or "ME").upper()
    hx = "0219" if reg == "BD" else ("0214" if reg == "IND" else "0215")
    return bytes.fromhex(hx)


def build_tcp_auth(account_id, jwt, server_time, key, iv, region, typ) -> bytes:
    uid_hex = f"{int(account_id):016x}"
    ts_hex = f"{int(server_time):08x}"
    enc = aes_encrypt(jwt.encode("utf-8"), key, iv).hex()
    length = f"{len(enc)//2:08x}"
    prefix = region_prefix(region, typ)
    return bytes.fromhex(f"{prefix}{uid_hex}{ts_hex}00000000{length}{enc}")


def split_host_port(addr: str):
    host, _, port = str(addr).partition(":")
    return host.strip(), int(port)


class SpamWorker(threading.Thread):
    def __init__(self, name, host, port, auth_pkt, ka_pkt, stop_evt):
        super().__init__(daemon=True, name=name)
        self.host = host
        self.port = port
        self.auth_pkt = auth_pkt
        self.ka_pkt = ka_pkt
        self.stop_evt = stop_evt
        self.ok = False

    def run(self):
        while not self.stop_evt.is_set():
            sock = None
            try:
                sock = socket.create_connection((self.host, self.port), timeout=10)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(20)
                sock.sendall(self.auth_pkt)
                self.ok = True
                _log(f"{self.name} connected {self.host}:{self.port}")
                while not self.stop_evt.is_set():
                    time.sleep(PING_INTERVAL)
                    try:
                        sock.sendall(self.ka_pkt)
                    except Exception:
                        break
                    try:
                        sock.settimeout(0.3)
                        sock.recv(4096)
                    except Exception:
                        pass
                    sock.settimeout(20)
            except Exception as e:
                _log(f"{self.name} err: {e}")
            finally:
                try:
                    if sock:
                        sock.close()
                except Exception:
                    pass
            if not self.stop_evt.is_set():
                time.sleep(RECONNECT_DELAY)


def _authenticate_sync(token: str) -> dict:
    """مصادقة متزامنة (تعمل في thread منفصل)."""
    _log("Inspect token...")
    info = inspect_token(token)
    open_id = info.get("open_id")
    platform = int(info.get("platform") or 4)
    _log(f"open_id={open_id} platform={platform}")
    if not open_id:
        raise RuntimeError("no open_id")

    major = None
    try:
        major = major_login(token, open_id, platform)
        _log(f"MajorLogin OK region={major.get('region')} uid={major.get('account_id')}")
    except Exception as e:
        _log(f"MajorLogin fail → JWT API: {e}")
        major = jwt_api_fallback(token)
        _log(f"JWT API OK region={major.get('region')} uid={major.get('account_id')}")

    ak = major.get("aes_ak") or AES_KEY
    aiv = major.get("iv_i") or AES_IV
    if isinstance(ak, str):
        ak = ak.encode("latin1")
    if isinstance(aiv, str):
        aiv = aiv.encode("latin1")
    ak, aiv = bytes(ak), bytes(aiv)
    if len(ak) != 16 or len(aiv) != 16:
        ak, aiv = AES_KEY, AES_IV

    payload = build_major_payload(open_id, token, platform)
    online = major.get("online")
    chat = major.get("chat")
    name = major.get("name") or ""
    if not online:
        try:
            g = get_login_data(payload, major["token"], major.get("url") or f"https://{CLIENT_HOST}")
            online, chat, name = g["online"], g["chat"], g.get("name") or ""
        except Exception as e:
            _log(f"GetLoginData fail: {e}")
            raise

    return {
        "jwt": major["token"],
        "account_id": int(major.get("account_id") or 0),
        "server_time": int(major.get("server_time") or time.time()),
        "ak": ak,
        "aiv": aiv,
        "region": str(major.get("region") or "ME").upper(),
        "online": online,
        "chat": chat or online,
        "name": name,
        "open_id": open_id,
        "platform": platform,
        "pname": {4: "Guest", 8: "Google", 3: "Facebook", 5: "VK", 6: "Huawei", 11: "X", 13: "Apple"}.get(platform, str(platform)),
    }


# ============================================================
# 🎛️ BOT-COMPATIBLE INTERFACE
# ============================================================
def is_session_active(account_id: str) -> bool:
    """هل الجلسة نشطة لهذا الحساب؟"""
    return str(account_id) in active_sessions


async def start_login_session(access_token: str, account_id: str = "", user_id: str = ""):
    """
    يُستدعى من bot.py:
        success, result = await spam_manager.start_login_session(access_token, account_id=aid)
    """
    global active_sessions
    aid = str(account_id)

    if aid and aid in active_sessions:
        return False, "⚠️ جلسة تسجيل دخول نشطة بالفعل لهذا الحساب!"

    loop = asyncio.get_event_loop()

    try:
        auth = await loop.run_in_executor(None, _authenticate_sync, access_token)
    except Exception as e:
        return False, f"❌ فشل المصادقة: {e}"

    if not auth or not auth.get("online"):
        return False, "❌ فشل تسجيل الدخول على جميع المنصات!"

    region = auth["region"] if auth["region"] in ("ME", "BD", "IND") else "ME"
    oh, op = split_host_port(auth["online"])
    ch, cp = split_host_port(auth["chat"])

    auth_on = build_tcp_auth(
        auth["account_id"], auth["jwt"], auth["server_time"],
        auth["ak"], auth["aiv"], region, "OnLine"
    )
    auth_ch = build_tcp_auth(
        auth["account_id"], auth["jwt"], auth["server_time"],
        auth["ak"], auth["aiv"], region, "ChaT"
    )
    ka = ka_bytes(region)

    stop_evt = threading.Event()
    workers = []

    for i in range(PARALLEL_ONLINE):
        w = SpamWorker(f"ON-{i+1}-{aid}", oh, op, auth_on, ka, stop_evt)
        w.start()
        workers.append(w)

    for i in range(PARALLEL_CHAT):
        w = SpamWorker(f"CH-{i+1}-{aid}", ch, cp, auth_ch, ka, stop_evt)
        w.start()
        workers.append(w)

    if not aid:
        aid = str(auth["account_id"])

    active_sessions[aid] = {
        "stop_event": stop_evt,
        "workers": workers,
        "name": auth.get("name") or "Unknown",
        "uid": str(auth["account_id"]),
        "platform": auth.get("pname") or str(auth.get("platform")),
        "region": region,
        "user_id": str(user_id),
        "data": auth,
    }

    _log(f"✅ Spam started for {auth.get('name')} UID={auth['account_id']} region={region}")

    # نرجع dict متوافق مع ما يتوقعه البوت
    result = {
        "name": auth.get("name") or "Unknown",
        "uid": auth["account_id"],
        "region": region,
        "platform": auth.get("pname") or str(auth.get("platform")),
        "sessions": PARALLEL_ONLINE + PARALLEL_CHAT,
        "ping": PING_INTERVAL,
    }
    return True, result


async def stop_login_session(account_id: str):
    """
    يُستدعى من bot.py:
        success, msg = await spam_manager.stop_login_session(aid)
    """
    global active_sessions
    aid = str(account_id)

    if aid not in active_sessions:
        return False, "⚠️ لا توجد جلسة نشطة لهذا الحساب لإيقافها!"

    sess = active_sessions[aid]
    stop_evt = sess.get("stop_event")
    workers = sess.get("workers") or []

    if stop_evt:
        stop_evt.set()

    for w in workers:
        try:
            w.join(timeout=3)
        except Exception:
            pass

    del active_sessions[aid]
    _log(f"🛑 Spam stopped for account {aid}")
    return True, "✅ **تم إيقاف جلسة تسجيل الدخول بنجاح!**"


def get_login_status() -> str:
    """يُستدعى من bot.py لعرض حالة الجلسات."""
    if not active_sessions:
        return "🔴 **لا توجد جلسات نشطة حالياً**"

    lines = []
    for aid, s in active_sessions.items():
        alive = any(w.is_alive() for w in (s.get("workers") or []))
        status = "🟢" if alive else "🔴"
        lines.append(
            f"{status} <b>{s['name']}</b> (UID: {s['uid']}) [{s.get('platform', '?')}]"
        )
    return "\n".join(lines)
