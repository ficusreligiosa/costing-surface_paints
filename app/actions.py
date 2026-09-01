"""
Each function here mirrors one `action` from the old Google Apps Script
backend (gasCall). Keeping the same action names + payload/response shapes
means the existing frontend only needs its GAS_URL swapped — no rewrite.
"""
from datetime import datetime
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from . import models as m
from .security import hash_password, verify_password, new_token


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Serializers: ORM row -> the exact JSON shape the frontend expects ──

def ser_user(u: m.User, include_password=False):
    d = {"id": u.id, "username": u.username, "name": u.name, "role": u.role}
    if include_password:
        d["password"] = u.password_hash
    return d


def ser_rm(r: m.RawMaterial):
    return {
        "id": r.id, "name": r.name, "code": r.code, "unit": r.unit,
        "rate": r.rate, "supplier": r.supplier, "updatedDate": r.updated_date,
        "minStock": r.min_stock, "category": r.category, "expiryDate": r.expiry_date,
    }


def ser_inventory(i: m.Inventory):
    return {"id": i.id, "rmId": i.rm_id, "quantity": i.quantity}


def ser_formulation(f: m.Formulation):
    return {
        "id": f.id, "productName": f.product_name, "productCode": f.product_code,
        "productType": f.product_type, "productFinish": f.product_finish,
        "batchNo": f.batch_no, "mfgDate": f.mfg_date, "remarks": f.remarks,
        "refNo": f.ref_no, "partyId": f.party_id, "partyName": f.party_name,
        "lots": f.lots, "inventoryDebited": f.inventory_debited,
        "inventoryPartialDebit": f.inventory_partial_debit,
        "skippedDebitRmIds": f.skipped_debit_rm_ids or [],
        "debitLots": f.debit_lots, "debitDate": f.debit_date,
        "debitRemarks": f.debit_remarks, "by": f.by, "byName": f.by_name,
        "createdAt": f.created_at, "labValues": f.lab_values,
        "glossValue": f.gloss_value, "glossAngle": f.gloss_angle,
        "labNotes": f.lab_notes,
        "items": [
            {"rmId": it.rm_id, "qty": it.qty, "unit": it.unit, "rate": it.rate}
            for it in f.items
        ],
    }


def ser_txn(t: m.StockTransaction):
    return {"id": t.id, "rmId": t.rm_id, "type": t.type, "qty": t.qty,
            "date": t.date, "remarks": t.remarks, "by": t.by}


def ser_audit(a: m.AuditLog):
    return {"time": a.time, "user": a.user, "action": a.action, "detail": a.detail}


def ser_comment(c: m.FormulationComment):
    return {"id": c.id, "formulationId": c.formulation_id, "type": c.type,
            "text": c.text, "by": c.by, "byName": c.by_name, "createdAt": c.created_at}


def ser_baseprice(b: m.BasePrice):
    return {"id": b.id, "formulationId": b.formulation_id, "rmId": b.rm_id,
            "rmName": b.rm_name, "enteredRate": b.entered_rate, "qty": b.qty,
            "unit": b.unit, "savedAt": b.saved_at}


def ser_machine(mc: m.Machine):
    return {"id": mc.id, "name": mc.name, "type": mc.type,
            "hourlyMachineCost": mc.hourly_machine_cost, "stdKgHr": mc.std_kg_hr,
            "active": mc.active}


def ser_shift(s: m.Shift):
    return {"id": s.id, "name": s.name, "startTime": s.start_time,
            "endTime": s.end_time, "crossesMidnight": s.crosses_midnight,
            "active": s.active, "color": s.color}


def ser_prodlog(p: m.ProductionLog):
    return {"id": p.id, "workerName": p.worker_name, "date": p.date,
            "shiftId": p.shift_id, "shiftName": p.shift_name,
            "productName": p.product_name, "machineId": p.machine_id,
            "rpm": p.rpm, "hourMeter": p.hour_meter, "startTime": p.start_time,
            "endTime": p.end_time, "breakMins": p.break_mins,
            "rmInput": p.rm_input, "fgOutput": p.fg_output,
            "formulationId": p.formulation_id, "remarks": p.remarks,
            "by": p.by, "byName": p.by_name, "createdAt": p.created_at}


def ser_forecast_row(r: m.ForecastInputRow):
    return {"rowIndex": r.row_index, "batchNo": r.batch_no, "refNo": r.ref_no,
            "productName": r.product_name, "orderQty": r.order_qty,
            "orderDate": r.order_date, "createdAt": r.created_at, "by": r.by}


def ser_party(p: m.PartyLookup):
    return {"refNo": p.ref_no, "partyId": p.party_id, "partyName": p.party_name}


# ── Actions ──────────────────────────────────────────────────────────

def action_login(db: Session, payload: dict, current_user=None):
    username = payload.get("username", "")
    password = payload.get("password", "")
    user = db.scalar(select(m.User).where(m.User.username == username))
    if not user or not verify_password(password, user.password_hash):
        return {"success": False, "error": "Invalid credentials"}
    token = new_token()
    db.add(m.Session(token=token, user_id=user.id, created_at=now_str()))
    db.commit()
    return {"success": True, "user": ser_user(user), "token": token}


def get_current_user(db: Session, token: str):
    """Resolves a session token to the User who owns it, or None."""
    if not token:
        return None
    sess = db.get(m.Session, token)
    if not sess:
        return None

    # Enforce session expiry (e.g. 24 hours)
    from datetime import timedelta
    try:
        created_time = datetime.strptime(sess.created_at, "%Y-%m-%d %H:%M:%S")
        if datetime.now() - created_time > timedelta(hours=24):
            db.delete(sess)
            db.commit()
            return None
    except Exception:
        # If parsing or db delete fails, treat as invalid
        return None

    return db.get(m.User, sess.user_id)


# Roles allowed to see raw material rates / batch costing figures.
# Per the role-workflow spec: "Admin is the only role (along with
# formulation, in some views) that can see raw material rates, batch
# costs, and per-unit costing."
COST_VISIBLE_ROLES = {"admin", "formulation"}


def strip_cost_fields(data: dict, role: str):
    if role in COST_VISIBLE_ROLES:
        return data
    for rm in data["rawMaterials"]:
        rm["rate"] = None
    for f in data["formulations"]:
        for it in f["items"]:
            it["rate"] = None
    return data


def action_load_all(db: Session, payload: dict, current_user=None):
    data = {
        "users": [ser_user(u) for u in db.scalars(select(m.User))],
        "rawMaterials": [ser_rm(r) for r in db.scalars(select(m.RawMaterial))],
        "inventory": [ser_inventory(i) for i in db.scalars(select(m.Inventory))],
        "formulations": [
            ser_formulation(f) for f in db.scalars(
                select(m.Formulation).options(selectinload(m.Formulation.items))
            )
        ],
        "stockTransactions": [ser_txn(t) for t in db.scalars(select(m.StockTransaction))],
        "auditLog": [ser_audit(a) for a in db.scalars(
            select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(200))],
        "formulationComments": [ser_comment(c) for c in db.scalars(select(m.FormulationComment))],
        "basePrices": [ser_baseprice(b) for b in db.scalars(select(m.BasePrice))],
        "machines": [ser_machine(mc) for mc in db.scalars(select(m.Machine))],
        "shifts": [ser_shift(s) for s in db.scalars(select(m.Shift))],
        "productionLogs": [ser_prodlog(p) for p in db.scalars(select(m.ProductionLog))],
        "forecastInputRows": [ser_forecast_row(r) for r in db.scalars(select(m.ForecastInputRow))],
        "partyLookup": [ser_party(p) for p in db.scalars(select(m.PartyLookup))],
    }
    settings = {s.key: s.value for s in db.scalars(select(m.Setting))}
    data["packagingCost"] = float(settings.get("packagingCost", 26))
    data["debitInventoryOnSave"] = settings.get("debitInventoryOnSave", "true") == "true"
    data["labourRate"] = float(settings.get("labourRate", 60))
    role = current_user.role if current_user else "view"
    data = strip_cost_fields(data, role)
    return {"success": True, "data": data}


def action_save_formulation(db: Session, payload: dict, current_user=None):
    """
    Creates or edits a formulation's recipe (header fields + ingredient
    list) ONLY. It deliberately cannot touch inventory or the
    inventoryDebited flag — per the role-workflow spec, "formulation
    saved" and "inventory debited" are two separate, deliberately
    decoupled states. Debiting only happens through action_debit_inventory,
    which enforces the one-time/irreversible rule server-side.
    """
    fdata = payload.get("formulation", {})
    items = payload.get("items", [])
    fid = fdata.get("id") or 0

    if fid:
        f = db.get(m.Formulation, fid)
        if not f:
            return {"success": False, "error": "Formulation not found"}
    else:
        f = m.Formulation()
        db.add(f)

    f.product_name = fdata.get("productName", "")
    f.product_code = fdata.get("productCode", "")
    f.product_type = fdata.get("productType", "")
    f.product_finish = fdata.get("productFinish", "")
    f.batch_no = fdata.get("batchNo", "")
    f.mfg_date = fdata.get("mfgDate", "")
    f.remarks = fdata.get("remarks", "")
    f.ref_no = fdata.get("refNo", "")
    f.party_id = fdata.get("partyId", "")
    f.party_name = fdata.get("partyName", "")
    f.lots = fdata.get("lots", 1)
    f.by = fdata.get("by", "")
    f.by_name = fdata.get("byName", "")
    f.created_at = fdata.get("createdAt", now_str())
    # Note: inventoryDebited / debitLots / debitDate / debitRemarks /
    # skippedDebitRmIds are intentionally NOT settable here — see
    # action_debit_inventory. This closes the old loophole where any
    # edit call could silently flip a formulation to "debited".

    db.flush()  # assign f.id if new

    # Replace items wholesale (matches frontend's "send full items array" pattern)
    for old_item in list(f.items):
        db.delete(old_item)
    db.flush()
    for it in items:
        db.add(m.FormulationItem(
            formulation_id=f.id, rm_id=it["rmId"], qty=it["qty"],
            unit=it.get("unit", "KG"), rate=it.get("rate"),
        ))
    db.flush()

    is_new = not fid or fid == 0
    settings = {s.key: s.value for s in db.scalars(select(m.Setting))}
    debit_on_save = settings.get("debitInventoryOnSave", "true") == "true"
    is_formulation_user = current_user and current_user.role == "formulation"

    if debit_on_save and is_formulation_user and is_new and not f.inventory_debited:
        db.refresh(f)
        debit_payload = {
            "formulationId": f.id,
            "lots": f.lots or 1,
            "remark": "Auto-debit on formulation save"
        }
        action_debit_inventory(db, debit_payload, current_user)
    else:
        db.commit()

    return {"success": True, "newId": f.id}


def action_debit_inventory(db: Session, payload: dict, current_user=None):
    """
    The one-time, irreversible stock deduction described in the role-workflow
    spec (Section 3.3). Enforced here, not just hidden in the UI:
      - rejects if this formulation has already been debited
      - converts G/ML ingredient units to KG before comparing to stock
      - skips (and records) any ingredient with insufficient stock rather
        than failing the whole debit
      - everything happens in one transaction — a failure partway through
        rolls back cleanly rather than leaving inventory half-debited
    """
    fid = payload.get("formulationId")
    lots = payload.get("lots")
    remark = (payload.get("remark") or "").strip()

    f = db.get(m.Formulation, fid)
    if not f:
        return {"success": False, "error": "Formulation not found"}
    db.refresh(f)
    if f.inventory_debited:
        return {"success": False, "error": "This formulation has already been debited — it cannot be debited again."}
    if not lots or lots < 1:
        return {"success": False, "error": "Enter a valid number of lots"}

    base_lots = f.lots or 1
    debit_time = now_str()
    skipped_ids, skipped_names = [], []

    for item in f.items:
        rm = db.get(m.RawMaterial, item.rm_id)
        if not rm:
            continue
        unit = (item.unit or rm.unit or "KG").upper()
        qty_kg = item.qty / 1000 if unit in ("G", "ML") else item.qty
        qty_per_lot = qty_kg / base_lots
        total_needed = qty_per_lot * lots

        inv = db.scalar(select(m.Inventory).where(m.Inventory.rm_id == item.rm_id))
        available = inv.quantity if inv else 0
        if available < total_needed:
            skipped_ids.append(item.rm_id)
            skipped_names.append(rm.name)
            continue

        inv.quantity = available - total_needed
        db.add(m.StockTransaction(
            rm_id=item.rm_id, type="consumption", qty=-total_needed,
            date=debit_time[:10],
            remarks=f"Inventory Debit — {f.batch_no or f.product_name} ({lots} lots)",
            by=current_user.username if current_user else "",
        ))

    f.inventory_debited = True
    f.inventory_partial_debit = len(skipped_names) > 0
    f.skipped_debit_rm_ids = skipped_ids
    f.debit_lots = lots
    f.debit_date = debit_time[:10]
    auto_remark = remark
    if skipped_names:
        note = f"Not debited (zero/insufficient stock): {', '.join(skipped_names)}."
        auto_remark = f"{auto_remark}. {note}" if auto_remark else note
    f.debit_remarks = auto_remark or "Inventory debited successfully."

    detail = f"{f.product_name} — {lots} lot{'s' if lots != 1 else ''} — Batch: {f.batch_no or '—'}"
    if skipped_names:
        detail += f" | Skipped (zero stock): {', '.join(skipped_names)}"
    db.add(m.AuditLog(
        time=debit_time, user=current_user.name if current_user else "",
        action="Inventory debited", detail=detail,
    ))

    db.commit()
    return {"success": True, "partial": bool(skipped_names), "skipped": skipped_names}


def action_update_batch_number(db: Session, payload: dict, current_user=None):
    """
    Amar's single-purpose action: change ONLY the batch number (and, if the
    caller is admin/formulation, the product code) on an existing
    formulation. Nothing about the recipe, items, or cost is touched here —
    matching the role-workflow spec's description of his restricted account.
    """
    fid = payload.get("formulationId")
    new_batch = (payload.get("batchNo") or "").strip()
    f = db.get(m.Formulation, fid)
    if not f:
        return {"success": False, "error": "Formulation not found"}

    old_batch = f.batch_no
    f.batch_no = new_batch

    # Product Code is hidden from Amar's role in the UI — only let
    # admin/formulation change it even if it's present in the payload.
    if current_user and current_user.role in ("admin", "formulation") and "productCode" in payload:
        f.product_code = payload["productCode"]

    db.add(m.AuditLog(
        time=now_str(), user=current_user.name if current_user else "",
        action="Updated batch code",
        detail=f"{f.product_code} — Batch {new_batch} (was {old_batch}) by {current_user.name if current_user else ''}",
    ))
    db.commit()
    return {"success": True}


def action_save_raw_material(db: Session, payload: dict, current_user=None):
    rdata = payload.get("rm", {})
    is_new = payload.get("isNew", False)
    if is_new or not rdata.get("id"):
        r = m.RawMaterial(code=rdata.get("code", ""))
        db.add(r)
    else:
        r = db.get(m.RawMaterial, rdata["id"])
        if not r:
            return {"success": False, "error": "Raw material not found"}

    r.name = rdata.get("name", "")
    r.code = rdata.get("code", r.code)
    r.unit = rdata.get("unit", "KG")
    r.rate = rdata.get("rate", 0)
    r.supplier = rdata.get("supplier", "")
    r.updated_date = rdata.get("updatedDate", "")
    r.min_stock = rdata.get("minStock", 0)
    r.category = rdata.get("category", "")
    r.expiry_date = rdata.get("expiryDate", "")
    db.flush()

    if is_new:
        inv = db.scalar(select(m.Inventory).where(m.Inventory.rm_id == r.id))
        if not inv:
            db.add(m.Inventory(rm_id=r.id, quantity=0))

    db.commit()
    return {"success": True, "newId": r.id}


def action_delete_raw_material(db: Session, payload: dict, current_user=None):
    rm_id = payload.get("rmId")
    r = db.get(m.RawMaterial, rm_id)
    if r:
        inv = db.scalar(select(m.Inventory).where(m.Inventory.rm_id == rm_id))
        if inv:
            db.delete(inv)
        db.delete(r)
        db.commit()
    return {"success": True}


def action_update_inventory(db: Session, payload: dict, current_user=None):
    rm_id = payload.get("rmId")
    new_qty = payload.get("newQuantity")
    inv = db.scalar(select(m.Inventory).where(m.Inventory.rm_id == rm_id))
    if inv:
        inv.quantity = new_qty
        db.commit()
        return {"success": True}
    return {"success": False, "error": "Inventory row not found"}


def action_add_transaction(db: Session, payload: dict, current_user=None):
    t = payload.get("transaction", {})
    txn = m.StockTransaction(
        rm_id=t["rmId"], type=t["type"], qty=t["qty"],
        date=t.get("date", ""), remarks=t.get("remarks", ""), by=t.get("by", ""),
    )
    db.add(txn)
    db.commit()
    return {"success": True, "newId": txn.id}


def action_adjust_stock(db: Session, payload: dict, current_user=None):
    tx_data = payload.get("transaction", {})
    rm_id = int(tx_data.get("rmId"))
    qty = float(tx_data.get("qty", 0))
    tx_type = tx_data.get("type", "adjustment")
    remarks = tx_data.get("remarks") or ""
    date = tx_data.get("date") or ""

    # 1. Update Inventory
    inv = db.scalar(select(m.Inventory).where(m.Inventory.rm_id == rm_id))
    if not inv:
        return {"success": False, "error": "Inventory record not found"}
    inv.quantity += qty
    if inv.quantity < 0:
        inv.quantity = 0

    # 2. Update Raw Material updated_date if date is provided
    rm = db.get(m.RawMaterial, rm_id)
    if rm and date:
        rm.updated_date = date

    # 3. Add Stock Transaction
    txn = m.StockTransaction(
        rm_id=rm_id, type=tx_type, qty=qty,
        date=date, remarks=remarks, by=current_user.username if current_user else ""
    )
    db.add(txn)

    # 4. Add Audit Log
    rm_name = rm.name if rm else "Unknown"
    detail = f"{rm_name} {'+' if qty > 0 else ''}{qty} ({tx_type})"
    audit = m.AuditLog(
        time=now_str(), user=current_user.name if current_user else "",
        action=f"Stock {tx_type}", detail=detail
    )
    db.add(audit)

    db.commit()
    return {"success": True, "newQuantity": inv.quantity}


def action_add_audit(db: Session, payload: dict, current_user=None):
    e = payload.get("entry", {})
    db.add(m.AuditLog(
        time=e.get("time", now_str()), user=e.get("user", ""),
        action=e.get("action", ""), detail=e.get("detail", ""),
    ))
    db.commit()
    return {"success": True}


def action_save_setting(db: Session, payload: dict, current_user=None):
    key = payload.get("key")
    value = payload.get("value")

    # Non-admins are only allowed to update the 'nextId' setting
    if current_user and current_user.role != "admin" and key != "nextId":
        return {
            "success": False,
            "error": "Only admins are permitted to change this setting.",
        }

    s = db.get(m.Setting, key)
    if not s:
        s = m.Setting(key=key)
        db.add(s)
    s.value = str(value)
    db.commit()
    return {"success": True}


def action_save_user(db: Session, payload: dict, current_user=None):
    udata = payload.get("user", {})
    is_new = payload.get("isNew", False)
    if is_new:
        u = m.User(username=udata["username"])
        db.add(u)
    else:
        u = db.get(m.User, udata["id"])
        if not u:
            return {"success": False, "error": "User not found"}
        u.username = udata.get("username", u.username)

    u.name = udata.get("name", "")
    u.role = udata.get("role", "")
    if udata.get("password"):
        u.password_hash = hash_password(udata["password"])
    db.commit()
    return {"success": True, "newId": u.id}


def action_delete_user(db: Session, payload: dict, current_user=None):
    user_id = payload.get("userId")
    requested_by = payload.get("requestedBy")
    if user_id == requested_by:
        return {"success": False, "error": "Cannot delete yourself"}
    u = db.get(m.User, user_id)
    if u:
        db.delete(u)
        db.commit()
    return {"success": True}


def action_save_production_log(db: Session, payload: dict, current_user=None):
    ldata = payload.get("log", {})
    lid = ldata.get("id")
    log = db.get(m.ProductionLog, lid) if lid else None
    if not log:
        log = m.ProductionLog()
        db.add(log)
    log.worker_name = ldata.get("workerName", "")
    log.date = ldata.get("date", "")
    log.shift_id = ldata.get("shiftId")
    log.shift_name = ldata.get("shiftName", "")
    log.product_name = ldata.get("productName", "")
    log.machine_id = ldata.get("machineId")
    log.rpm = ldata.get("rpm", "")
    log.hour_meter = ldata.get("hourMeter", "")
    log.start_time = ldata.get("startTime", "")
    log.end_time = ldata.get("endTime", "")
    log.break_mins = ldata.get("breakMins", 0)
    log.rm_input = ldata.get("rmInput", 0)
    log.fg_output = ldata.get("fgOutput", 0)
    log.formulation_id = ldata.get("formulationId")
    log.remarks = ldata.get("remarks", "")
    log.by = ldata.get("by", "")
    log.by_name = ldata.get("byName", "")
    log.created_at = ldata.get("createdAt", now_str())
    db.commit()
    return {"success": True, "newId": log.id}


def action_delete_production_log(db: Session, payload: dict, current_user=None):
    log = db.get(m.ProductionLog, payload.get("logId"))
    if log:
        db.delete(log)
        db.commit()
    return {"success": True}


def action_save_lab_gloss(db: Session, payload: dict, current_user=None):
    fdata = payload.get("formulation", {})
    f = db.get(m.Formulation, fdata.get("id"))
    if not f:
        return {"success": False, "error": "Formulation not found"}
    if "labValues" in fdata:
        f.lab_values = fdata["labValues"]
    if "glossValue" in fdata:
        f.gloss_value = fdata["glossValue"]
    f.gloss_angle = fdata.get("glossAngle", f.gloss_angle)
    f.lab_notes = fdata.get("labNotes", f.lab_notes)
    db.commit()
    return {"success": True}


def action_save_comment(db: Session, payload: dict, current_user=None):
    c = payload.get("comment", {})
    comment = m.FormulationComment(
        formulation_id=c["formulationId"], type=c.get("type", "production"),
        text=c.get("text", ""), by=c.get("by", ""), by_name=c.get("byName", ""),
        created_at=c.get("createdAt", now_str()),
    )
    db.add(comment)
    db.commit()
    return {"success": True, "newId": comment.id}


def action_patch_formulation_parties(db: Session, payload: dict, current_user=None):
    for p in payload.get("patches", []):
        f = db.get(m.Formulation, p.get("id"))
        if f:
            f.party_id = p.get("partyId", f.party_id)
            f.party_name = p.get("partyName", f.party_name)
    db.commit()
    return {"success": True}


def action_save_machine(db: Session, payload: dict, current_user=None):
    mdata = payload.get("machine", {})
    mid = mdata.get("id")
    machine = db.get(m.Machine, mid) if mid else None
    if not machine:
        machine = m.Machine()
        db.add(machine)
    machine.name = mdata.get("name", "")
    machine.type = mdata.get("type", "")
    machine.hourly_machine_cost = mdata.get("hourlyMachineCost", 0)
    machine.std_kg_hr = mdata.get("stdKgHr")
    machine.active = mdata.get("active", True)
    db.commit()
    return {"success": True, "newId": machine.id}


def action_save_shift(db: Session, payload: dict, current_user=None):
    sdata = payload.get("shift", {})
    sid = sdata.get("id")
    shift = db.get(m.Shift, sid) if sid else None
    if not shift:
        shift = m.Shift()
        db.add(shift)
    shift.name = sdata.get("name", "")
    shift.start_time = sdata.get("startTime", "")
    shift.end_time = sdata.get("endTime", "")
    shift.crosses_midnight = sdata.get("crossesMidnight", False)
    shift.active = sdata.get("active", True)
    shift.color = sdata.get("color", "#2563eb")
    db.commit()
    return {"success": True, "newId": shift.id}


def action_delete_shift(db: Session, payload: dict, current_user=None):
    shift = db.get(m.Shift, payload.get("shiftId"))
    if shift:
        db.delete(shift)
        db.commit()
    return {"success": True}


def action_delete_machine(db: Session, payload: dict, current_user=None):
    machine = db.get(m.Machine, payload.get("machineId"))
    if machine:
        db.query(m.ProductionLog).filter(m.ProductionLog.machine_id == machine.id).update({m.ProductionLog.machine_id: None})
        db.delete(machine)
        db.commit()
    return {"success": True}


def action_import_formulations(db: Session, payload: dict, current_user=None):
    import json
    formulations = payload.get("formulations", [])
    items = payload.get("formulationItems", [])
    raw_materials_data = payload.get("rawMaterials", [])
    
    def safe_float(val):
        if val is None or str(val).strip() == "" or str(val).lower() == "none":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def safe_bool(val):
        if val is None:
            return False
        if isinstance(val, str):
            return val.strip().upper() in ("TRUE", "1", "YES", "Y")
        return bool(val)
        
    imported_f = 0
    updated_f = 0
    imported_items = 0
    
    # Process optional RawMaterials sheet data if provided
    if raw_materials_data:
        for rm in raw_materials_data:
            rm_id_val = rm.get("id") or rm.get("ID")
            if rm_id_val is None:
                continue
            try:
                rm_id = int(float(rm_id_val))
            except (ValueError, TypeError):
                continue
            name = str(rm.get("name") or rm.get("Name") or "").strip()
            code = str(rm.get("code") or rm.get("Code") or f"RM{rm_id:03d}").strip()
            if not name:
                continue
            unit_val = str(rm.get("unit") or rm.get("Unit") or "KG")
            rate_val = float(safe_float(rm.get("rate") or rm.get("Rate")) or 0)
            supplier_val = str(rm.get("supplier") or rm.get("Supplier") or "")
            cat_val = str(rm.get("category") or rm.get("Category") or "")
            min_stock_val = float(safe_float(rm.get("minStock") or rm.get("min_stock")) or 0)

            existing = db.get(m.RawMaterial, rm_id)
            if existing:
                existing.name = name
                existing.code = code
                existing.unit = unit_val
                existing.rate = rate_val
                existing.supplier = supplier_val
                existing.category = cat_val
                existing.min_stock = min_stock_val
            else:
                existing_code = db.scalar(select(m.RawMaterial).where(m.RawMaterial.code == code))
                if existing_code:
                    code = f"{code}_{rm_id}"
                db.add(m.RawMaterial(
                    id=rm_id,
                    name=name,
                    code=code,
                    unit=unit_val,
                    rate=rate_val,
                    supplier=supplier_val,
                    category=cat_val,
                    min_stock=min_stock_val
                ))
        db.flush()
        
    max_f_id = 0
    incoming_fids = []
    
    for f_data in formulations:
        fid_val = f_data.get("id") or f_data.get("ID")
        if fid_val is None:
            continue
        try:
            fid = int(float(fid_val))
        except (ValueError, TypeError):
            continue
        incoming_fids.append(fid)
        if fid > max_f_id:
            max_f_id = fid
            
        existing = db.get(m.Formulation, fid)
        if existing:
            f = existing
            updated_f += 1
        else:
            f = m.Formulation(id=fid)
            db.add(f)
            imported_f += 1
            
        # Clean Excel formula strings
        def clean_formula(val):
            if isinstance(val, str) and val.strip().startswith("="):
                return ""
            return val

        f.product_name = clean_formula(str(f_data.get("productName") or f_data.get("product_name") or ""))
        f.product_code = clean_formula(str(f_data.get("productCode") or f_data.get("product_code") or ""))
        f.product_type = clean_formula(str(f_data.get("productType") or f_data.get("product_type") or ""))
        f.product_finish = clean_formula(str(f_data.get("productFinish") or f_data.get("product_finish") or ""))
        f.batch_no = clean_formula(str(f_data.get("batchNo") or f_data.get("batch_no") or ""))
        f.mfg_date = clean_formula(str(f_data.get("mfgDate") or f_data.get("mfg_date") or ""))
        f.remarks = clean_formula(str(f_data.get("remarks") or f_data.get("remarks") or ""))
        f.ref_no = clean_formula(str(f_data.get("refNo") or f_data.get("ref_no") or ""))
        
        party_id = clean_formula(str(f_data.get("partyId") or f_data.get("party_id") or ""))
        party_name = clean_formula(str(f_data.get("partyName") or f_data.get("party_name") or ""))
        
        # If party id/name are empty but ref_no is present, lookup from PartyLookup
        if f.ref_no and not party_id and not party_name:
            lookup = db.get(m.PartyLookup, f.ref_no)
            if lookup:
                party_id = lookup.party_id
                party_name = lookup.party_name
                
        f.party_id = party_id
        f.party_name = party_name
        f.lots = int(safe_float(f_data.get("lots")) or 1)
        
        # Coerce inventory_debited boolean
        f.inventory_debited = safe_bool(f_data.get("inventoryDebited") or f_data.get("inventory_debited"))
        f.inventory_partial_debit = safe_bool(f_data.get("inventoryPartialDebit") or f_data.get("inventory_partial_debit"))
            
        skipped_ids = f_data.get("skippedDebitRmIds") or f_data.get("skipped_debit_rm_ids") or []
        if isinstance(skipped_ids, str):
            try:
                f.skipped_debit_rm_ids = json.loads(skipped_ids)
            except Exception:
                f.skipped_debit_rm_ids = []
        else:
            f.skipped_debit_rm_ids = skipped_ids
            
        f.debit_lots = int(safe_float(f_data.get("debitLots") or f_data.get("debit_lots")) or 0)
        f.debit_date = str(f_data.get("debitDate") or f_data.get("debit_date") or "")
        f.debit_remarks = str(f_data.get("debitRemarks") or f_data.get("debit_remarks") or "")
        f.by = str(f_data.get("by") or "")
        f.by_name = str(f_data.get("byName") or f_data.get("by_name") or "")
        f.created_at = str(f_data.get("createdAt") or f_data.get("created_at") or now_str())
        
        lab_vals = f_data.get("labValues") or f_data.get("lab_values")
        if isinstance(lab_vals, str) and lab_vals:
            try:
                f.lab_values = json.loads(lab_vals)
            except Exception:
                f.lab_values = None
        else:
            f.lab_values = lab_vals

        # Support individual lab columns if labValues is missing
        if f.lab_values is None:
            lab_l = f_data.get("labL") or f_data.get("lab_l")
            lab_a = f_data.get("labA") or f_data.get("lab_a")
            lab_b = f_data.get("labB") or f_data.get("lab_b")
            lab_recorded_at = f_data.get("labRecordedAt") or f_data.get("lab_recorded_at")
            lab_recorded_by = f_data.get("labRecordedBy") or f_data.get("lab_recorded_by")
            if lab_l is not None or lab_a is not None or lab_b is not None:
                f.lab_values = {
                    "L": safe_float(lab_l),
                    "A": safe_float(lab_a),
                    "B": safe_float(lab_b),
                    "recordedAt": str(lab_recorded_at or ""),
                    "recordedBy": str(lab_recorded_by or "")
                }
            
        f.gloss_value = safe_float(f_data.get("glossValue") or f_data.get("gloss_value"))
        f.gloss_angle = str(f_data.get("glossAngle") or f_data.get("gloss_angle") or "")
        f.lab_notes = str(f_data.get("labNotes") or f_data.get("lab_notes") or "")

    # CRITICAL FIX: Flush pending Formulation inserts to DB so foreign keys in formulation_items are satisfied!
    db.flush()

    # Delete old formulation items for incoming formulations in bulk
    if incoming_fids:
        db.query(m.FormulationItem).filter(m.FormulationItem.formulation_id.in_(incoming_fids)).delete(synchronize_session=False)

    valid_fids = set(db.scalars(select(m.Formulation.id)).all())
    valid_rmids = set(db.scalars(select(m.RawMaterial.id)).all())

    # Map formulation items by formulationId
    items_by_fid = {}
    missing_rms_to_add = {}
    for it in items:
        fid_val = it.get("formulationId") or it.get("formulation_id")
        if fid_val is None:
            continue
        try:
            fid = int(float(fid_val))
        except (ValueError, TypeError):
            continue
        if fid not in items_by_fid:
            items_by_fid[fid] = []
        items_by_fid[fid].append(it)

        # Collect missing raw materials referenced in items
        rm_id_val = it.get("rmId") or it.get("rm_id")
        if rm_id_val is not None:
            try:
                rm_id = int(float(rm_id_val))
                if rm_id not in valid_rmids and rm_id not in missing_rms_to_add:
                    missing_rms_to_add[rm_id] = m.RawMaterial(
                        id=rm_id,
                        name=f"RM-{rm_id}",
                        code=f"RM{rm_id:03d}",
                        unit=str(it.get("unit") or "KG"),
                        rate=float(safe_float(it.get("rate")) or 0.0),
                        supplier="",
                        category="",
                        min_stock=0.0
                    )
            except (ValueError, TypeError):
                pass

    # Auto-provision any missing raw material IDs so no recipe items get dropped
    if missing_rms_to_add:
        for rm_obj in missing_rms_to_add.values():
            db.add(rm_obj)
        db.flush()
        valid_rmids = set(db.scalars(select(m.RawMaterial.id)).all())

    # Bulk insert all valid new formulation items
    new_items_mappings = []
    for fid, it_list in items_by_fid.items():
        if fid not in incoming_fids or fid not in valid_fids:
            # Skip items for formulations we didn't process or that don't exist in DB
            continue
        for it in it_list:
            rm_id_val = it.get("rmId") or it.get("rm_id")
            if rm_id_val is None:
                continue
            try:
                rm_id = int(float(rm_id_val))
            except (ValueError, TypeError):
                continue
            if rm_id not in valid_rmids:
                # Skip items referencing non-existent raw materials to prevent FK constraint violation
                continue
            qty_val = it.get("qty") or it.get("qty")
            new_items_mappings.append({
                "formulation_id": fid,
                "rm_id": rm_id,
                "qty": float(safe_float(qty_val) or 0),
                "unit": str(it.get("unit") or "KG"),
                "rate": safe_float(it.get("rate"))
            })
            imported_items += 1

    if new_items_mappings:
        db.bulk_insert_mappings(m.FormulationItem, new_items_mappings)

    # Update nextId setting in database if max_f_id is higher
    if max_f_id > 0:
        setting = db.get(m.Setting, "nextId")
        if setting:
            try:
                val = json.loads(setting.value)
                if val.get("formulation", 0) <= max_f_id:
                    val["formulation"] = max_f_id + 1
                    setting.value = json.dumps(val)
            except Exception:
                pass
                
    db.commit()
    return {
        "success": True, 
        "importedFormulations": imported_f, 
        "updatedFormulations": updated_f, 
        "importedItems": imported_items
    }



def action_delete_formulation(db: Session, payload: dict, current_user=None):
    fid_val = payload.get("id") or payload.get("formulationId")
    if fid_val is None:
        return {"success": False, "error": "Formulation ID missing"}
    try:
        fid = int(float(fid_val))
    except (ValueError, TypeError):
        return {"success": False, "error": "Invalid Formulation ID"}

    f = db.get(m.Formulation, fid)
    if not f:
        return {"success": False, "error": f"Formulation ID {fid} not found"}

    db.query(m.FormulationItem).filter(m.FormulationItem.formulation_id == fid).delete(synchronize_session=False)
    db.query(m.FormulationComment).filter(m.FormulationComment.formulation_id == fid).delete(synchronize_session=False)
    db.query(m.BasePrice).filter(m.BasePrice.formulation_id == fid).delete(synchronize_session=False)
    db.delete(f)
    db.commit()
    return {"success": True}


ACTIONS = {
    "login": action_login,
    "loadAll": action_load_all,
    "saveFormulation": action_save_formulation,
    "deleteFormulation": action_delete_formulation,
    "debitInventory": action_debit_inventory,
    "updateBatchNumber": action_update_batch_number,
    "saveRawMaterial": action_save_raw_material,
    "deleteRawMaterial": action_delete_raw_material,
    "updateInventory": action_update_inventory,
    "addTransaction": action_add_transaction,
    "addAudit": action_add_audit,
    "saveSetting": action_save_setting,
    "saveUser": action_save_user,
    "deleteUser": action_delete_user,
    "saveProductionLog": action_save_production_log,
    "deleteProductionLog": action_delete_production_log,
    "saveLabGloss": action_save_lab_gloss,
    "saveComment": action_save_comment,
    "patchFormulationParties": action_patch_formulation_parties,
    "saveMachine": action_save_machine,
    "deleteMachine": action_delete_machine,
    "saveShift": action_save_shift,
    "deleteShift": action_delete_shift,
    "importFormulations": action_import_formulations,
    "adjustStock": action_adjust_stock,
}


# ── Server-side permission map ──────────────────────────────────────
# This is the piece the role-workflow spec calls out as missing from the
# old system: "permissions only hide buttons rather than blocking actions
# server-side." Every write action is checked against this table before
# its handler ever runs — a labentry or batchedit account calling
# debitInventory directly (bypassing the UI) is rejected here, not just
# hidden from view.
#
# "*" means every logged-in role may call it (loadAll — visibility of
# specific fields within it, like cost, is handled separately by
# strip_cost_fields).
#
ACTION_PERMISSIONS = {
    "loadAll": "*",
    "saveFormulation": {"admin", "formulation"},
    "deleteFormulation": {"admin", "formulation"},
    "debitInventory": {"admin", "formulation"},
    "updateBatchNumber": {"admin", "formulation", "batchedit"},
    "saveLabGloss": {"admin", "formulation", "labentry"},
    "saveComment": {"admin", "formulation"},
    "patchFormulationParties": {"admin", "formulation"},
    "saveRawMaterial": {"admin", "inventory"},
    "deleteRawMaterial": {"admin"},
    "updateInventory": {"admin", "inventory"},
    "addTransaction": {"admin", "inventory"},
    "addAudit": "*",
    "saveSetting": {"admin", "formulation"},
    "saveUser": {"admin"},
    "deleteUser": {"admin"},
    "saveProductionLog": {"admin", "production"},
    "deleteProductionLog": {"admin", "production"},
    "saveMachine": {"admin"},
    "deleteMachine": {"admin"},
    "saveShift": {"admin", "production"},
    "deleteShift": {"admin"},
    "importFormulations": {"admin", "formulation"},
    "adjustStock": {"admin", "inventory"},
}


def check_permission(action: str, role: str) -> bool:
    allowed = ACTION_PERMISSIONS.get(action)
    if allowed is None:
        # Fail closed: an action with no explicit rule is denied rather
        # than silently allowed.
        return False
    if allowed == "*":
        return True
    return role in allowed
