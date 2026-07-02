from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.core.settings import get_settings
from app.dependencies import get_current_user, get_db_session
from app.models import ChildProfile, User, UserRole
from app.schemas import AuthResponse, ChildProfilePublic, DemoResponse, LoginRequest, RegisterRequest, UserPublic
from app.services.otp import verify_otp
from app.services.notification import send_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _serialize_child_profile(profile: ChildProfile | None) -> ChildProfilePublic | None:
    return ChildProfilePublic.model_validate(profile) if profile is not None else None


@router.get("/demo", response_model=DemoResponse)
def demo_login(db: Session = Depends(get_db_session)) -> DemoResponse:
    settings = get_settings()
    user = db.scalar(select(User).where(User.username == settings.demo_username))
    if user is None:
        raise HTTPException(status_code=500, detail="Demo account not seeded")
    profile = db.scalar(select(ChildProfile).where(ChildProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(status_code=500, detail="Demo profile not seeded")
    token = create_access_token(user.id, user.role.value, settings.secret_key, settings.access_token_ttl_minutes)
    return DemoResponse(
        access_token=token,
        user=UserPublic.model_validate(user),
        child_profile=_serialize_child_profile(profile),
        demo_username=settings.demo_username,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db_session)) -> AuthResponse:
    settings = get_settings()
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    # 注册手机验证码校验：如果是家长注册，要求用户名字段为手机号（或单独入参，此处兼容 username 作为手机号格式）
    # 在生产环境下，可在 Payload 中扩展手机号和验证码字段，以下为非阻塞式集成示范
    # if payload.role == "PARENT":
    #     if not verify_otp(payload.username, "用户输入的验证码"):
    #         raise HTTPException(status_code=400, detail="手机验证码验证失败")

    role = UserRole(payload.role)
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password, settings.secret_key),
        role=role,
        email=payload.email,
    )
    db.add(user)
    db.flush()

    child_profile: ChildProfile | None = None
    if role == UserRole.CHILD:
        child_profile = ChildProfile(
            user_id=user.id,
            parent_user_id=None,
            nickname=payload.nickname or payload.username,
            age=payload.age or settings.demo_age,
            current_level=1,
            token_balance=1000,
        )
        if payload.parent_username:
            parent = db.scalar(select(User).where(User.username == payload.parent_username))
            if parent is not None and parent.role == UserRole.PARENT:
                child_profile.parent_user_id = parent.id
        db.add(child_profile)

    db.commit()

    if payload.email:
        send_email(
            to_email=payload.email,
            subject="欢迎加入 KidoAI 家长端",
            html_content=f"<h3>欢迎加入 KidoAI！</h3><p>您已成功注册账号，用户名：{payload.username}</p><p>开始陪伴孩子探索世界吧！</p>",
            user_id=user.id,
        )

    token = create_access_token(user.id, user.role.value, settings.secret_key, settings.access_token_ttl_minutes)
    return AuthResponse(
        access_token=token,
        user=UserPublic.model_validate(user),
        child_profile=_serialize_child_profile(child_profile),
    )


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db_session)) -> AuthResponse:
    settings = get_settings()
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash, settings.secret_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    child_profile = db.scalar(select(ChildProfile).where(ChildProfile.user_id == user.id))
    token = create_access_token(user.id, user.role.value, settings.secret_key, settings.access_token_ttl_minutes)
    return AuthResponse(
        access_token=token,
        user=UserPublic.model_validate(user),
        child_profile=_serialize_child_profile(child_profile),
    )


@router.get("/me", response_model=AuthResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)) -> AuthResponse:
    child_profile = db.scalar(select(ChildProfile).where(ChildProfile.user_id == current_user.id))
    return AuthResponse(
        access_token="",
        user=UserPublic.model_validate(current_user),
        child_profile=_serialize_child_profile(child_profile),
    )
