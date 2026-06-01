"""Infrastructure UI routes."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from executec2.server.auth import (
    ROLE_ADMIN,
    clear_ui_auth_cookies,
    require_user,
    set_ui_auth_cookies,
    verify_csrf,
)
from executec2.server.models import (
    DeployTarget,
    InfraStage,
    InfrastructureAssetData,
    InfrastructureAssetType,
)

router = APIRouter(tags=["ui"])
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


async def _parse_form_body(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _redirect_login() -> RedirectResponse:
    return RedirectResponse("/ui/login", status_code=303)


def _require_ui_admin(request: Request):
    try:
        claims = require_user(request)
        if ROLE_ADMIN not in claims.roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return claims
    except HTTPException:
        return None


@router.get("/ui/login", response_class=HTMLResponse)
async def ui_login_page(request: Request):
    return _TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {
            "claims": None,
            "error": "",
        },
    )


@router.post("/ui/login")
async def ui_login_submit(request: Request):
    form = await _parse_form_body(request)
    username = form.get("username", "")
    password = form.get("password", "")
    jwt_manager = request.app.state.jwt_manager
    operators = request.app.state.operators
    if not jwt_manager.verify_password(username, password, operators):
        return _TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {
                "claims": None,
                "error": "Invalid credentials",
            },
        )
    csrf_token = secrets.token_urlsafe(24)
    roles = list(operators[username]["roles"])
    access_token = jwt_manager.create_access_token(username, roles)
    response = RedirectResponse("/ui/infrastructure", status_code=303)
    set_ui_auth_cookies(response, access_token, csrf_token)
    return response


@router.post("/ui/logout")
async def ui_logout(request: Request):
    response = RedirectResponse("/ui/login", status_code=303)
    clear_ui_auth_cookies(response)
    return response


@router.get("/ui/infrastructure", response_class=HTMLResponse)
async def ui_infrastructure_index(request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    stages = [
        await request.app.state.infrastructure.build_stage_view(stage)
        for stage in InfraStage
    ]
    runs = await request.app.state.db.deployment_run_list()
    return _TEMPLATES.TemplateResponse(
        request,
        "infrastructure/index.html",
        {
            "claims": claims,
            "stages": stages,
            "runs": [run.model_dump(mode="json") for run in runs[-5:]],
        },
    )


@router.get("/ui/infrastructure/stages/{stage}", response_class=HTMLResponse)
async def ui_stage_view(stage: int, request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    view = await request.app.state.infrastructure.build_stage_view(InfraStage(stage))
    csrf_token = request.cookies.get("ec2_csrf_token", "")
    return _TEMPLATES.TemplateResponse(
        request,
        "infrastructure/stage.html",
        {"claims": claims, "view": view, "csrf_token": csrf_token},
    )


@router.get("/ui/infrastructure/assets/{asset_id}", response_class=HTMLResponse)
async def ui_asset_detail(asset_id: str, request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    asset = await request.app.state.db.infrastructure_asset_get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Infrastructure asset not found")
    chain = await request.app.state.infrastructure.build_ingress_chain_view(asset_id)
    runs = await request.app.state.db.deployment_run_list(asset_id=asset_id)
    csrf_token = request.cookies.get("ec2_csrf_token", "")
    return _TEMPLATES.TemplateResponse(
        request,
        "infrastructure/asset_detail.html",
        {
            "claims": claims,
            "asset": asset.model_dump(mode="json"),
            "chain": chain["chain"],
            "runs": [run.model_dump(mode="json") for run in runs],
            "csrf_token": csrf_token,
            "deploy_targets": [target.value for target in DeployTarget],
        },
    )


@router.get("/ui/infrastructure/runs", response_class=HTMLResponse)
async def ui_runs(request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    runs = await request.app.state.db.deployment_run_list()
    return _TEMPLATES.TemplateResponse(
        request,
        "infrastructure/run_list.html",
        {"claims": claims, "runs": [run.model_dump(mode="json") for run in runs]},
    )


@router.get("/ui/infrastructure/runs/{run_id}", response_class=HTMLResponse)
async def ui_run_detail(run_id: str, request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    run = await request.app.state.db.deployment_run_get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Deployment run not found")
    csrf_token = request.cookies.get("ec2_csrf_token", "")
    return _TEMPLATES.TemplateResponse(
        request,
        "infrastructure/run_detail.html",
        {
            "claims": claims,
            "run": run.model_dump(mode="json"),
            "csrf_token": csrf_token,
        },
    )


@router.get("/ui/infrastructure/drift", response_class=HTMLResponse)
async def ui_drift_summary(request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    summary = await request.app.state.infrastructure.build_drift_health_summary()
    return _TEMPLATES.TemplateResponse(
        request,
        "infrastructure/drift.html",
        {"claims": claims, "summary": summary},
    )


@router.post("/ui/infrastructure/assets")
async def ui_create_asset(request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    form = await _parse_form_body(request)
    verify_csrf(request, form.get("csrf_token", ""))
    stage = int(form.get("stage", "1"))
    asset = InfrastructureAssetData(
        asset_id=secrets.token_hex(8),
        name=form["name"],
        asset_type=InfrastructureAssetType(form["asset_type"]),
        stage=InfraStage(stage),
        provider=form.get("provider", ""),
        config={"hostname": form.get("hostname", form["name"])},
    )
    await request.app.state.db.infrastructure_asset_insert(asset)
    return RedirectResponse(f"/ui/infrastructure/stages/{stage}", status_code=303)


@router.post("/ui/infrastructure/runs")
async def ui_create_run(request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    form = await _parse_form_body(request)
    verify_csrf(request, form.get("csrf_token", ""))
    asset_id = form.get("asset_id", "")
    operation = form.get("operation", "")
    target = form.get("target", "")
    if not asset_id or not operation or not target:
        raise HTTPException(status_code=400, detail="Missing run fields")
    run = await request.app.state.infrastructure.create_plan(
        asset_id=asset_id,
        operation=operation,
        target=DeployTarget(target),
        created_by=claims.username,
    )
    return RedirectResponse(f"/ui/infrastructure/runs/{run.run_id}", status_code=303)


@router.post("/ui/infrastructure/runs/{run_id}/apply")
async def ui_apply_run(run_id: str, request: Request):
    claims = _require_ui_admin(request)
    if claims is None:
        return _redirect_login()
    form = await _parse_form_body(request)
    verify_csrf(request, form.get("csrf_token", ""))
    await request.app.state.infrastructure.apply_run(run_id)
    return RedirectResponse(f"/ui/infrastructure/runs/{run_id}", status_code=303)
