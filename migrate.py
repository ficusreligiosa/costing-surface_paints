"""
One-time migration: Google Sheets (exported as CSV) -> the new database.

HOW TO USE
----------
1. Export each relevant Sheets tab as CSV (File > Download > CSV, one file
   per tab) into a folder, e.g. ./sheets_export/RawMaterials.csv,
   ./sheets_export/Formulations.csv, etc.

2. Once you have the REAL column headers from each tab, fill in the
   `MAPPING` dict below for that table — this is the ONLY thing you should
   need to edit. Each mapping is:
       "sheet_column_name": "model_field_name"
   Leave a mapping empty ({}) for any table you haven't gotten headers for
   yet — running with an empty mapping just skips that table and prints a
   warning, it won't crash the whole run.

3. Dry run first (default) — prints what WOULD be inserted, touches
   nothing:
       python migrate.py --source ./sheets_export

4. Once the dry run output looks right, actually write to the DB:
       python migrate.py --source ./sheets_export --commit

This script is intentionally separate from app/main.py and app/actions.py
so it doesn't collide with any other work happening on those files — it
only imports app.models and app.database, never edits them.
"""
import argparse
import csv
import sys
from pathlib import Path

# Import the REAL models so migrated rows land in exactly the same shape
# the backend already reads/writes.
from app.database import SessionLocal, engine
from app import models as m


# ── STEP 1: fill these in once you have the real Sheet headers ─────────
# Key = table name (also expected CSV filename without .csv)
# Value = {"sheet_column": "model_field", ...}
#
# TODO: replace every mapping below with the real column names once your
# sir sends the headers. Names here are best-guess placeholders based on
# the existing frontend's field names — do not trust them blindly.

MAPPING = {
    "Users": {
        "model": m.User,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "username": "username",
            "password": "password_hash",
            "name": "name",
            "role": "role",
        },
    },
    "Shifts": {
        "model": m.Shift,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "name": "name",
            "startTime": "start_time",
            "endTime": "end_time",
            "crossesMidnight": "crosses_midnight",
            "color": "color",
            "active": "active",
        },
    },
    "Machines": {
        "model": m.Machine,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "name": "name",
            "type": "type",
            "hourlyMachineCost": "hourly_machine_cost",
            "stdKgHr": "std_kg_hr",
            "active": "active",
        },
    },
    "Settings": {
        "model": m.Setting,
        "natural_key": "key",
        "fields": {
            "key": "key",
            "value": "value",
        },
    },
    "RawMaterials": {
        "model": m.RawMaterial,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "name": "name",
            "code": "code",
            "unit": "unit",
            "rate": "rate",
            "supplier": "supplier",
            "updatedDate": "updated_date",
            "minStock": "min_stock",
            "category": "category",
        },
    },
    "Inventory": {
        "model": m.Inventory,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "rmId": "rm_id",
            "quantity": "quantity",
        },
    },
    "Formulations": {
        "model": m.Formulation,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "productName": "product_name",
            "productCode": "product_code",
            "productType": "product_type",
            "productFinish": "product_finish",
            "batchNo": "batch_no",
            "mfgDate": "mfg_date",
            "remarks": "remarks",
            "refNo": "ref_no",
            "partyId": "party_id",
            "partyName": "party_name",
            "lots": "lots",
            "inventoryDebited": "inventory_debited",
            "by": "by",
            "byName": "by_name",
            "createdAt": "created_at",
            "glossValue": "gloss_value",
            "glossAngle": "gloss_angle",
            "labNotes": "lab_notes",
        },
    },
    "FormulationItems": {
        "model": m.FormulationItem,
        "natural_key": None,
        "fields": {
            "formulationId": "formulation_id",
            "rmId": "rm_id",
            "qty": "qty",
            "unit": "unit",
            "rate": "rate",
        },
    },
    "FormulationComments": {
        "model": m.FormulationComment,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "formulationId": "formulation_id",
            "type": "type",
            "text": "text",
            "by": "by",
            "byName": "by_name",
            "createdAt": "created_at",
        },
    },
    "StockTransactions": {
        "model": m.StockTransaction,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "rmId": "rm_id",
            "type": "type",
            "qty": "qty",
            "date": "date",
            "remarks": "remarks",
            "by": "by",
        },
    },
    "ProductionLogs": {
        "model": m.ProductionLog,
        "natural_key": "id",
        "fields": {},  # Handled dynamically due to column structural shifts
    },
    "AuditLog": {
        "model": m.AuditLog,
        "natural_key": None,
        "fields": {
            "time": "time",
            "user": "user",
            "action": "action",
            "detail": "detail",
        },
    },
    "BasePrices": {
        "model": m.BasePrice,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "formulationId": "formulation_id",
            "rmId": "rm_id",
            "rmName": "rm_name",
            "enteredRate": "entered_rate",
            "qty": "qty",
            "unit": "unit",
            "savedAt": "saved_at",
        },
    },
    "ForecastInput": {
        "model": m.ForecastInputRow,
        "natural_key": None,
        "fields": {
            "rowIndex": "row_index",
            "batchNo": "batch_no",
            "refNo": "ref_no",
            "productName": "product_name",
            "orderQty": "order_qty",
            "orderDate": "order_date",
            "createdAt": "created_at",
            "by": "by",
        },
    },
    "PartyLookup": {
        "model": m.PartyLookup,
        "natural_key": "id",
        "fields": {
            "id": "id",
            "refNo": "ref_no",
            "partyId": "party_id",
            "partyName": "party_name",
        },
    },
    "Sheet2": {
        "model": m.PartyLookup,
        "natural_key": "id",
        "fields": {
            "refNo": "ref_no",
            "partyId": "party_id",
            "partyName": "party_name",
        },
    },
    "live order sheet data": {
        "model": m.PartyLookup,
        "natural_key": "id",
        "fields": {
            "REF NO": "ref_no",
            "refNo": "ref_no",
            "partyId": "party_id",
            "partyName": "party_name",
        },
    },
}

# Ordered list of tables to migrate (dependencies first)
MIGRATION_ORDER = [
    "Users",
    "Shifts",
    "Machines",
    "Settings",
    "PartyLookup",
    "Sheet2",
    "live order sheet data",
    "RawMaterials",
    "Inventory",
    "Formulations",
    "FormulationItems",
    "FormulationComments",
    "StockTransactions",
    "ProductionLogs",
    "AuditLog",
    "BasePrices",
    "ForecastInput",
]


def coerce(value, field_name):
    """Very light type coercion — extend as real data reveals edge cases."""
    if value is None or value == "":
        return None
    numeric_fields = {
        "rate", "quantity", "qty", "min_stock", "lots", "hourly_machine_cost", 
        "std_kg_hr", "rm_id", "id", "formulation_id", "shift_id", "machine_id",
        "break_mins", "rm_input", "fg_output", "order_qty", "row_index", "entered_rate"
    }
    boolean_fields = {"active", "crosses_midnight", "inventory_debited"}
    
    if field_name in numeric_fields:
        try:
            return float(value)
        except ValueError:
            return None
            
    if field_name in boolean_fields:
        if isinstance(value, str):
            return value.strip().upper() == "TRUE"
        return bool(value)
        
    return value.strip() if isinstance(value, str) else value


def read_csv(csv_path: Path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def migrate_table(db, source_dir: Path, table_name: str, commit: bool):
    conf = MAPPING.get(table_name)
    if not conf or (not conf["fields"] and table_name != "ProductionLogs"):
        print(f"[SKIP] {table_name}: no mapping filled in yet")
        return 0, 0

    csv_path = source_dir / f"{table_name}.csv"
    if not csv_path.exists():
        print(f"[SKIP] {table_name}: {csv_path} not found")
        return 0, 0

    model = conf["model"]
    natural_key = conf.get("natural_key")
    inserted, skipped = 0, 0

    # Custom handling for ProductionLogs due to row structure shifts (lengths 17 vs 19)
    if table_name == "ProductionLogs":
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return 0, 0
        data_rows = rows[1:]
        
        for idx, row in enumerate(data_rows):
            # Clean trailing empty strings
            while row and row[-1] == "":
                row.pop()
            l = len(row)
            if l == 17:
                fields = ["id", "worker_name", "date", "product_name", "machine_id", "rpm", "hour_meter", "start_time", "end_time", "break_mins", "rm_input", "fg_output", "formulation_id", "remarks", "by", "by_name", "created_at"]
            elif l == 19 or l == 20:
                row = row[:19]
                fields = ["id", "worker_name", "date", "shift_id", "shift_name", "product_name", "machine_id", "rpm", "hour_meter", "start_time", "end_time", "break_mins", "rm_input", "fg_output", "formulation_id", "remarks", "by", "by_name", "created_at"]
            else:
                print(f"  [WARN] {table_name} row {idx+2} skipped — unexpected column count: {l}")
                skipped += 1
                continue
                
            kwargs = {fields[i]: coerce(row[i], fields[i]) for i in range(len(fields))}
            
            if natural_key and kwargs.get(natural_key) is not None:
                existing = db.query(model).filter_by(**{natural_key: kwargs[natural_key]}).first()
                if existing:
                    skipped += 1
                    continue
                    
            obj = model(**kwargs)
            print(f"  {'[INSERT]' if commit else '[DRY-RUN would insert]'} {table_name}: {kwargs}")
            if commit:
                db.add(obj)
            inserted += 1
            
    else:
        # Standard table migration using DictReader mapping
        rows = read_csv(csv_path)
        for row in rows:
            kwargs = {}
            missing_cols = []
            for sheet_col, field in conf["fields"].items():
                if sheet_col not in row:
                    missing_cols.append(sheet_col)
                    continue
                val = coerce(row[sheet_col], field)
                # If we are migrating the Users table, encrypt plaintext passwords
                if table_name == "Users" and field == "password_hash" and val:
                    from app.security import hash_password
                    if not (str(val).startswith("$2") and len(str(val)) == 60):
                        val = hash_password(str(val))
                kwargs[field] = val

            if missing_cols:
                print(f"  [WARN] {table_name} row skipped — missing columns: {missing_cols}")
                skipped += 1
                continue

            if natural_key and kwargs.get(natural_key) is not None:
                existing = db.query(model).filter_by(**{natural_key: kwargs[natural_key]}).first()
                if existing:
                    skipped += 1
                    continue

            obj = model(**kwargs)
            print(f"  {'[INSERT]' if commit else '[DRY-RUN would insert]'} {table_name}: {kwargs}")
            if commit:
                db.add(obj)
            inserted += 1

    if commit:
        db.commit()

    return inserted, skipped


def main():
    parser = argparse.ArgumentParser(description="Migrate Sheets CSV exports into the new DB")
    parser.add_argument("--source", required=True, help="Folder containing per-tab CSV exports")
    parser.add_argument("--commit", action="store_true", help="Actually write to the DB (default: dry run)")
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        print(f"Source folder not found: {source_dir}")
        sys.exit(1)

    m.Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    mode = "COMMIT (writing to DB)" if args.commit else "DRY RUN (no changes will be made)"
    print(f"=== Migration — {mode} ===\n")

    totals = {"inserted": 0, "skipped": 0}
    try:
        for table_name in MIGRATION_ORDER:
            print(f"--- {table_name} ---")
            ins, skip = migrate_table(db, source_dir, table_name, args.commit)
            totals["inserted"] += ins
            totals["skipped"] += skip
            print()
    finally:
        db.close()

    print(f"=== Done — {totals['inserted']} rows {'inserted' if args.commit else 'would be inserted'}, "
          f"{totals['skipped']} skipped ===")
    if not args.commit:
        print("\nThis was a dry run. Re-run with --commit once the output above looks correct.")


if __name__ == "__main__":
    main()
