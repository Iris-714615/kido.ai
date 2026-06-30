from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import decode_access_token
from app.core.settings import get_settings
from app.db.session import get_db
from app.models import ChildProfile, Subscription, SubscriptionPlan, User, UserRole


def get_db_session() -> Session:
    yield from get_db()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
) -> User:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization scheme")
    settings = get_settings()
    try:
        payload = decode_access_token(token, settings.secret_key)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user_id = int(payload["sub"])
    stmt = select(User).where(User.id == user_id)
    user = db.scalar(stmt)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_current_child_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ChildProfile:
    if current_user.role != UserRole.CHILD:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Child account required")
    stmt = (
        select(ChildProfile)
        .where(ChildProfile.user_id == current_user.id)
        .options(selectinload(ChildProfile.user))
    )
    profile = db.scalar(stmt)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Child profile not found")
    return profile


def get_current_parent(current_user: User = Depends(get_current_user)) -> User:
    """校验当前用户为家长角色，返回 User 对象。"""
    if current_user.role != UserRole.PARENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Parent account required")
    return current_user


def get_parent_child_or_404(
    child_id: int,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> ChildProfile:
    """校验 child_id 归属于当前家长，防止越权访问他人儿童数据。"""
    child = db.get(ChildProfile, child_id)
    if child is None or child.parent_user_id != current_parent.id:
        raise HTTPException(status_code=404, detail="Child not found")
    return child


def get_user_subscription(user: User, db: Session) -> tuple[Subscription, SubscriptionPlan]:
    """获取用户当前订阅及套餐信息。如果不存在则自动创建免费版。"""
    from app.core.bootstrap import ensure_free_subscription

    sub = ensure_free_subscription(db, user.id)
    plan = db.get(SubscriptionPlan, sub.plan_id)
    return sub, plan


def get_subscription_features(user: User = Depends(get_current_user), db: Session = Depends(get_db_session)) -> dict:
    """获取当前用户订阅功能权限，返回 features_json 字典。"""
    _, plan = get_user_subscription(user, db)
    return plan.features_json if plan else {}


def check_feature_access(features: dict, feature_name: str) -> None:
    """检查特定功能是否可用，不可用则抛 403。"""
    if not features.get(feature_name, False):
        raise HTTPException(
            status_code=403,
            detail=f"当前套餐不支持此功能，请升级订阅",
        )

