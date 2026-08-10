import json
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import os

from sqlalchemy import text
from .database import SessionLocal, engine
from . import models
from .actions import ACTIONS, ACTION_PERMISSIONS, check_permission, get_current_user

models.Base.metadata.create_all(bind=engine)

with engine.begin() as conn:
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_formulation_items_formulation_id ON formulation_items(formulation_id);"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_formulation_items_rm_id ON formulation_items(rm_id);"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stock_transactions_rm_id ON stock_transactions(rm_id);"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_base_prices_formulation_id ON base_prices(formulation_id);"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_base_prices_rm_id ON base_prices(rm_id);"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_production_logs_machine_id ON production_logs(machine_id);"))

app = FastAPI(title="Surface Paints Backend")

# Tighten this to your real frontend origin(s) before going to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def dispatch(action: str, payload: dict):
    db: Session = SessionLocal()
    try:
        handler = ACTIONS.get(action)
        if not handler:
            return {"success": False, "error": f"Unknown action: {action}"}

        # login is the only action that runs without an existing session.
        if action == "login":
            return handler(db, payload)

        current_user = get_current_user(db, payload.get("token", ""))
        if not current_user:
            return {"success": False, "error": "Not authenticated — please log in again."}

        if not check_permission(action, current_user.role):
            return {
                "success": False,
                "error": f"Your account ({current_user.role}) is not permitted to perform this action.",
            }

        return handler(db, payload, current_user)
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@app.get("/api")
async def api_get(data: str):
    """
    Mirrors gasCall's GET path, used only for the read-only 'loadAll' action:
        GET /api?data={"action":"loadAll","token":"..."}
    """
    body = json.loads(data)
    action = body.get("action")
    result = dispatch(action, body)
    return JSONResponse(result)


@app.post("/api")
async def api_post(request: Request):
    """
    Mirrors gasCall's POST path, used for every write action. The frontend
    sends Content-Type: text/plain, so we read the raw body and parse it
    ourselves rather than relying on FastAPI's JSON body parsing.
    """
    raw = await request.body()
    body = json.loads(raw.decode("utf-8"))
    action = body.get("action")
    result = dispatch(action, body)
    return JSONResponse(result)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "surface-paints-backend"}


_admin_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin")
if os.path.isdir(_admin_dir):
    app.mount("/admin", StaticFiles(directory=_admin_dir, html=True), name="admin")

_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
