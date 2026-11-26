from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import (
    Actor,
    ActorRole,
    create_access_token,
    create_refresh_token,
    get_current_actor,
    require_roles,
    verify_refresh_token,
)
from app.core.config import Settings, get_settings
from app.core.passwords import hash_password, verify_password
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenIssueRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: ActorRole = "analyst"
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)


class TokenIssueResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    actor: Actor


class UserRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: ActorRole
    is_active: bool


def _resolve_settings(request: Request) -> Settings:
    app_cfg = getattr(request.app.state, "settings", None)
    if isinstance(app_cfg, Settings):
        return app_cfg
    return get_settings()


@router.get("/me", response_model=Actor)
async def get_me(actor: Actor = Depends(get_current_actor)) -> Actor:
    """Return the resolved actor context for the current request."""
    return actor


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Register a new user account with PBKDF2 password hashing (analyst role by default)."""
    email_norm = payload.email.strip().lower()
    existing = (
        await db.execute(select(User).where(func.lower(User.email) == email_norm))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{email_norm}' is already registered.",
        )

    total_users = int((await db.scalar(select(func.count(User.id)))) or 0)
    assigned_role: ActorRole = "admin" if total_users == 0 else "analyst"

    user = User(
        email=email_norm,
        full_name=payload.full_name.strip(),
        role=assigned_role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await record_audit_event(
        db,
        event_type="auth.user_registered",
        actor=Actor(email=email_norm, role=assigned_role, auth_method="password"),
        entity_type="user",
        entity_id=user.id,
        action="registered",
        details={"role": assigned_role},
    )
    await db.commit()
    await db.refresh(user)
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=cast(ActorRole, user.role),
        is_active=user.is_active,
    )


@router.post("/login", response_model=TokenIssueResponse)
async def login_user(
    payload: UserLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenIssueResponse:
    """Authenticate a persisted user and return access + refresh Bearer tokens."""
    settings = _resolve_settings(request)
    email_norm = payload.email.strip().lower()
    user = (
        await db.execute(select(User).where(func.lower(User.email) == email_norm))
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    role = cast(ActorRole, user.role)
    access = create_access_token(
        email=user.email,
        role=role,
        secret_key=settings.auth_secret_key,
        ttl_seconds=settings.auth_access_token_ttl_seconds,
    )
    refresh = create_refresh_token(
        email=user.email,
        role=role,
        secret_key=settings.auth_secret_key,
        ttl_seconds=settings.auth_refresh_token_ttl_seconds,
    )
    await record_audit_event(
        db,
        event_type="auth.login",
        actor=Actor(email=user.email, role=role, auth_method="password"),
        entity_type="user",
        entity_id=user.id,
        action="login_success",
    )
    await db.commit()
    return TokenIssueResponse(
        access_token=access,
        refresh_token=refresh,
        actor=Actor(email=user.email, role=role, auth_method="bearer_token"),
    )


@router.post("/refresh", response_model=TokenIssueResponse)
async def refresh_session(
    payload: RefreshTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenIssueResponse:
    """Exchange a valid refresh token for a fresh access + refresh token pair."""
    settings = _resolve_settings(request)
    actor = verify_refresh_token(payload.refresh_token, settings.auth_secret_key)
    user = (
        await db.execute(select(User).where(func.lower(User.email) == actor.email.lower()))
    ).scalar_one_or_none()
    if user is not None and not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled.",
        )

    role = cast(ActorRole, user.role) if user is not None else actor.role
    access = create_access_token(
        email=actor.email,
        role=role,
        secret_key=settings.auth_secret_key,
        ttl_seconds=settings.auth_access_token_ttl_seconds,
    )
    refresh = create_refresh_token(
        email=actor.email,
        role=role,
        secret_key=settings.auth_secret_key,
        ttl_seconds=settings.auth_refresh_token_ttl_seconds,
    )
    return TokenIssueResponse(
        access_token=access,
        refresh_token=refresh,
        actor=Actor(email=actor.email, role=role, auth_method="bearer_token"),
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(require_roles("controller", "admin")),
) -> list[UserOut]:
    """List persisted user accounts (controller/admin only)."""
    rows = (await db.execute(select(User).order_by(User.email.asc()))).scalars().all()
    return [
        UserOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=cast(ActorRole, u.role),
            is_active=u.is_active,
        )
        for u in rows
    ]


@router.post("/token", response_model=TokenIssueResponse)
async def issue_dev_token(
    payload: TokenIssueRequest,
    request: Request,
) -> TokenIssueResponse:
    """Issue a signed dev/test HMAC token (disabled in production)."""
    settings = _resolve_settings(request)
    if settings.app_env.strip().lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development token issuance is disabled in production.",
        )

    token = create_access_token(
        email=payload.email.strip(),
        role=payload.role,
        secret_key=settings.auth_secret_key,
        ttl_seconds=payload.ttl_seconds,
    )
    return TokenIssueResponse(
        access_token=token,
        actor=Actor(email=payload.email.strip(), role=payload.role, auth_method="bearer_token"),
    )
