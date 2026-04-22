"""Authentication routes: login, refresh, OTP."""

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from executec2.server.auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    client_ip,
    enforce_limit,
    limit_key_user_ip,
    require_roles,
)
from executec2.server.models import OTPType, TokenClaims

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str


class OTPRequest(BaseModel):
    type: str  # "connect" | "tunnel"


class OTPResponse(BaseModel):
    otp: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    rate_limiter = request.app.state.rate_limiter
    ip = client_ip(request)

    if not rate_limiter.is_allowed(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"X-Code": "RATE_LIMITED"},
        )

    jwt_manager = request.app.state.jwt_manager
    operators = request.app.state.operators

    if not jwt_manager.verify_password(body.username, body.password, operators):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"X-Code": "UNAUTHORIZED"},
        )

    roles = list(operators[body.username]["roles"])
    return TokenResponse(
        access_token=jwt_manager.create_access_token(body.username, roles=roles),
        refresh_token=jwt_manager.create_refresh_token(body.username, roles=roles),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = auth_header.removeprefix("Bearer ")
    jwt_manager = request.app.state.jwt_manager

    try:
        claims = jwt_manager.verify_token(token, expected_type="refresh")
    except pyjwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"X-Code": "UNAUTHORIZED"},
        )

    return TokenResponse(
        access_token=jwt_manager.create_access_token(claims.username, roles=claims.roles),
        refresh_token=jwt_manager.create_refresh_token(claims.username, roles=claims.roles),
    )


@router.post("/otp", response_model=OTPResponse)
async def get_otp(
    body: OTPRequest,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    enforce_limit(
        request,
        "otp",
        limit_key_user_ip(request, claims.username),
        detail="Too many OTP requests",
    )
    otp_store = request.app.state.otp_store
    try:
        otp_type = OTPType(body.type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid OTP type")
    otp = otp_store.generate(claims.username, otp_type)
    return OTPResponse(otp=otp)
