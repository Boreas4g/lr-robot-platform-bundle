from fastapi import Depends, Header, HTTPException, Request, status

from .config import get_settings
from .schemas import User
from .store import store


def synthetic_operator() -> User:
    """Built-in identity used for every request while auth is disabled."""
    return User(username="operator", name="操作员", role="系统管理员")


def get_current_user(authorization: str | None = Header(default=None)) -> User:
    if not get_settings().auth_enabled:
        return synthetic_operator()
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    user = store.user_for_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要登录")
    return user


def require_debug_access(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"系统管理员", "维护人员"}:
        raise HTTPException(status_code=403, detail="当前账号没有调试权限")
    return user


def require_feature_access(request: Request, user: User = Depends(get_current_user)) -> User:
    """Shared robot users can operate the three public modules, never debug APIs."""
    if request.url.path.startswith(("/api/v1/debug/", "/api/v1/chassis-params")):
        return require_debug_access(user)
    return user
