"""Local administrator credentials and revocable browser sessions."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

SESSION_SECONDS = 7 * 86400
COOKIE_NAME = "qqbot_admin"


class AdminAuth:
    def __init__(self, directory: Path):
        self.path = directory / "webui-auth.json"
        self.login_file = directory / "webui-login.txt"
        self.lock = threading.Lock()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            os.chmod(self.path, 0o600)
        else:
            password = secrets.token_urlsafe(24)
            salt = secrets.token_hex(16)
            self.data = {
                "username": "admin",
                "salt": salt,
                "password": self.digest(password, salt),
                "initial": True,
                "sessions": {},
            }
            # Never log the bootstrap password or place it in argv/environment.
            fd = os.open(self.login_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as file:
                file.write(
                    "QQ Bridge 管理台初始登录信息\n\n用户名：admin（输入 admin）\n密码："
                    + password
                    + "\n\n登录后可在「设置」修改账号密码；改密后本文件会删除。\n"
                )
            self.save()

    @staticmethod
    def digest(password: str, salt: str) -> str:
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(self.data, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.path)

    def check(self, username: str, password: str) -> bool:
        with self.lock:
            salt, expected, account = (
                self.data["salt"],
                self.data["password"],
                self.data["username"],
            )
        matched = hmac.compare_digest(self.digest(password, salt), expected)
        with self.lock:
            return (
                matched
                and expected == self.data["password"]
                and hmac.compare_digest(username.encode(), account.encode())
            )

    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            self.data["sessions"] = {
                key: expires for key, expires in self.data["sessions"].items() if expires > now
            }
            while len(self.data["sessions"]) >= 50:
                del self.data["sessions"][next(iter(self.data["sessions"]))]
            self.data["sessions"][self.key(token)] = now + SESSION_SECONDS
            self.save()
        return token

    @staticmethod
    def key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def valid(self, token: str) -> bool:
        return bool(token) and self.data["sessions"].get(self.key(token), 0) > time.time()

    @staticmethod
    def csrf(token: str) -> str:
        return hmac.new(token.encode(), b"qqbot-webui-csrf", hashlib.sha256).hexdigest()

    def revoke(self, token: str):
        with self.lock:
            self.data["sessions"].pop(self.key(token), None)
            self.save()

    def change(self, username: str, password: str, current: str) -> bool:
        with self.lock:
            expected, old_salt = self.data["password"], self.data["salt"]
        if not hmac.compare_digest(self.digest(current, old_salt), expected):
            return False
        salt = secrets.token_hex(16)
        digest = self.digest(password, salt)
        with self.lock:
            if expected != self.data["password"]:
                return False
            self.data.update(
                username=username,
                salt=salt,
                password=digest,
                initial=False,
                sessions={},
            )
            self.save()
            self.login_file.unlink(missing_ok=True)
            return True

    def record(self, action, target):
        with self.lock:
            self.data.setdefault("audit", []).append(
                {
                    "action": action,
                    "target": target,
                    "created": time.time(),
                    "username": self.data["username"],
                }
            )
            self.data["audit"] = self.data["audit"][-100:]
            self.save()

    def remember_sessions(self, conversation, session_ids):
        with self.lock:
            history = self.data.setdefault("session_history", [])
            for session_id in session_ids - {None}:
                record = {"id": session_id, "conversation": conversation}
                if record not in history:
                    history.append(record)
            self.save()
