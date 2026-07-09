from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import decode_access_token
from app.core.settings import get_settings
from app.db.session import get_db
from app.models import (
    ChatMessage,
    ChatSession,
    ChildProfile,
    ExploreRecord,
    Subscription,
    SubscriptionPlan,
    User,
    UserRole,
)


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


# ========== 当日配额检查 ==========


class _DailyQuotaChecker:
    """检查当日使用配额的依赖工厂。免费用户超出配额则抛 403。

    配额取自订阅套餐 features_json 中的对应键：
    - explore_daily_limit：每日探索次数上限
    - chat_daily_limit：每日对话次数上限
    其中 -1 表示无限制（付费套餐）。
    """

    def __init__(self, feature_key: str, quota_label: str) -> None:
        self.feature_key = feature_key
        self.quota_label = quota_label

    def __call__(
        self,
        child: ChildProfile = Depends(get_current_child_profile),
        db: Session = Depends(get_db_session),
    ) -> None:
        from app.core.bootstrap import ensure_free_subscription

        # 确定订阅所属用户：优先 parent，回退 child user（demo 账户无 parent）
        subscriber_id = child.parent_user_id if child.parent_user_id is not None else child.user_id
        sub = ensure_free_subscription(db, subscriber_id)
        plan = db.get(SubscriptionPlan, sub.plan_id)

        limit = plan.features_json.get(self.feature_key) if plan else None
        # 未配置限制或 -1 表示无限制（付费套餐），直接放行
        if limit is None or limit == -1:
            return

        today = datetime.now(timezone.utc).date()
        # 统计当日使用量：若有 parent 则统计其名下所有 child，否则仅统计当前 child
        if child.parent_user_id is not None:
            child_ids = select(ChildProfile.id).where(ChildProfile.parent_user_id == child.parent_user_id)
        else:
            child_ids = [child.id]

        if self.feature_key == "explore_daily_limit":
            count = db.scalar(
                select(func.count(ExploreRecord.id)).where(
                    ExploreRecord.child_id.in_(child_ids),
                    func.date(ExploreRecord.created_at) == today,
                )
            ) or 0
        elif self.feature_key == "chat_daily_limit":
            session_ids = select(ChatSession.id).where(ChatSession.child_id.in_(child_ids))
            count = db.scalar(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.session_id.in_(session_ids),
                    ChatMessage.role == "user",
                    func.date(ChatMessage.created_at) == today,
                )
            ) or 0
        else:
            return

        if count >= limit:
            raise HTTPException(
                status_code=403,
                detail=f"今日{self.quota_label}次数已达免费上限（{limit}次/天），请升级订阅",
            )


check_explore_quota = _DailyQuotaChecker("explore_daily_limit", "探索")
check_chat_quota = _DailyQuotaChecker("chat_daily_limit", "对话")

