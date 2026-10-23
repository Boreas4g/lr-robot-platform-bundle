from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..config import get_settings
from ..dependencies import get_current_user, synthetic_operator
from ..schemas import AuthResponse, CurrentUserResponse, LoginRequest, RegisterRequest, User
from ..store import store

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest) -> AuthResponse:
    result = store.authenticate(request.username, request.password)
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token, user = result
    return AuthResponse(token=token, user=user)


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, user: User = Depends(get_current_user)) -> User:
    if not get_settings().auth_enabled:
        return synthetic_operator()
    if user.role != "系统管理员":
        raise HTTPException(status_code=403, detail="账号由管理员创建，不开放自行注册")
    try:
        return store.register(request.username, request.password, request.name)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/me", response_model=CurrentUserResponse)
def me(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(user=user)


@router.post("/logout", status_code=204)
def logout(authorization: str | None = Header(default=None)) -> None:
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    store.revoke_token(token)


@router.get("/bookarm-access")
def bookarm_access(path: str, method: str, user: User = Depends(get_current_user)) -> dict:
    """Authorise the public proxy before it attaches the private device token."""
    if user.role in {"系统管理员", "维护人员"}:
        return {"allowed": True}
    # Book registration and the overview hardware indicator are public features.
    # Every camera, joint, tuning, and direct workflow endpoint stays private.
    import re

    allowed = (
        (path == "/v1/studio/library" and method in {"GET", "POST"})
        or (path == "/v1/studio/library/verify-all" and method == "POST")
        or (bool(re.fullmatch(r"/v1/studio/library/[^/]+/image", path)) and method == "GET")
        or (path == "/v1/studio/hardware/status" and method == "GET")
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="当前账号没有调试权限")
    return {"allowed": True}
