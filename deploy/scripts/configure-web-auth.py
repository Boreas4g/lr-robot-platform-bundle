#!/usr/bin/env python3
"""Provision public credentials without loading or rewriting robot business data.

Run with the control-api Python environment after stopping lr-control-api.
The API loads these user records on its next startup.
"""
from pathlib import Path
import os
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / 'LR-Web/apps/control-api'
sys.path.insert(0, str(API))
os.chdir(API)
from app.config import Settings
from app.db import Database, UserModel
from app.store import _hash_password, _verify_password

credentials = ROOT / '.local-deploy/hotspot-access.txt'
credentials.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
settings = Settings()
if not settings.use_postgres:
    raise SystemExit('Persistent PostgreSQL storage is required for deployed accounts')
if not credentials.exists():
    password = 'Library-' + secrets.token_hex(5)
    admin_password = 'Admin-' + secrets.token_urlsafe(15)
    database = Database(settings)
    with database.session() as session:
        if session.get(UserModel, 'operator') is not None:
            raise SystemExit('operator already exists; use the existing account or reset it explicitly')
        session.add(UserModel(username='operator', name='图书馆操作员', role='图书馆操作员', password_hash=_hash_password(password)))
        admin = session.get(UserModel, 'admin')
        rotated = admin is not None and _verify_password('123456', admin.password_hash)
        if rotated:
            admin.password_hash = _hash_password(admin_password)
        fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write('热点名称：图书馆机器人\n热点密码：12345678\n访问地址：http://192.168.4.1:8000\n')
            output.write(f'网站账号：operator\n网站密码：{password}\n网站角色：图书馆操作员\n')
            if rotated:
                output.write(f'维护账号：admin\n维护密码：{admin_password}\n')
            output.write('网站会话有效期：24 小时；控制 API 重启后需重新登录。\n')
    database.engine.dispose()
else:
    credentials.chmod(0o600)

# Keep private database, MQTT and device settings verbatim.
environment = API / '.env'
content = environment.read_text()
for key, value in [('LR_AUTH_ENABLED', 'true'), ('LR_SINGLE_OPERATOR', 'false')]:
    pattern = rf'(?m)^{key}=.*$'
    content = re.sub(pattern, f'{key}={value}', content) if re.search(pattern, content) else content.rstrip() + f'\n{key}={value}\n'
fd = os.open(environment, os.O_WRONLY | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write(content)
print(f'Authentication configured. Private credentials: {credentials}')
