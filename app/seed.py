"""
Run once after the database is created:
    python -m app.seed

Creates the same demo users the old system shipped with, so login keeps
working immediately after migration. Change these passwords in the Users
page as soon as you're logged in.
"""
from .database import SessionLocal, engine
from . import models as m
from .security import hash_password

DEMO_USERS = [
    ("admin", "admin123", "Administrator", "admin"),
    ("sudhir", "sudhir123", "Sudhir Ji", "formulation"),
    ("viewer", "view123", "View User", "view"),
    ("reporter", "report123", "Report User", "report"),
    ("invuser", "inv123", "Inventory User", "inventory"),
    ("prodop", "prod123", "Production Operator", "production"),
    ("vivek", "vivek123", "Vivek Goswami", "labentry"),
    ("amar", "amar123", "Amar Goswami", "batchedit"),
]

DEMO_SHIFTS = [
    ("Day Shift", "08:30", "17:00", False, "#2563eb"),
    ("Night Shift", "17:00", "02:00", True, "#7c3aed"),
]


DEMO_RMS = [
    (1, "LDPE Granules", "RM001", "KG", 95.0, "Reliance Polymers", "2025-01-15", 50.0, "Binder"),
    (2, "HDPE Powder", "RM002", "KG", 88.0, "Indian Petrochemicals", "2025-01-20", 100.0, ""),
    (3, "Titanium Dioxide", "RM003", "KG", 320.0, "Lomon Billions", "2025-01-18", 20.0, ""),
    (4, "Carbon Black", "RM004", "KG", 75.0, "Cabot India", "2025-01-12", 30.0, ""),
    (5, "Lubricant (Wax)", "RM005", "KG", 55.0, "Mold Release Pvt", "2025-01-10", 15.0, ""),
    (6, "Calcium Carbonate", "RM006", "KG", 18.0, "Omya India", "2025-01-22", 200.0, ""),
    (7, "Stabilizer (Tin)", "RM007", "KG", 450.0, "Galata Chemicals", "2025-01-08", 10.0, ""),
    (8, "Processing Oil", "RM008", "LTR", 72.0, "Shell India", "2025-01-25", 50.0, ""),
]

DEMO_INV = [
    (1, 320.0),
    (2, 180.0),
    (3, 45.0),
    (4, 60.0),
    (5, 28.0),
    (6, 580.0),
    (7, 8.0),
    (8, 90.0),
]


def seed():
    m.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for username, password, name, role in DEMO_USERS:
            existing = db.query(m.User).filter_by(username=username).first()
            if existing:
                continue
            db.add(m.User(
                username=username,
                password_hash=hash_password(password),
                name=name,
                role=role,
            ))

        for name, start, end, crosses, color in DEMO_SHIFTS:
            existing = db.query(m.Shift).filter_by(name=name).first()
            if existing:
                continue
            db.add(m.Shift(
                name=name, start_time=start, end_time=end,
                crosses_midnight=crosses, active=True, color=color,
            ))

        defaults = {"packagingCost": "26", "debitInventoryOnSave": "true", "labourRate": "60"}
        for key, value in defaults.items():
            if not db.get(m.Setting, key):
                db.add(m.Setting(key=key, value=value))
        db.commit()

        for id, name, code, unit, rate, supplier, updatedDate, minStock, category in DEMO_RMS:
            existing = db.get(m.RawMaterial, id)
            if not existing:
                db.add(m.RawMaterial(
                    id=id, name=name, code=code, unit=unit, rate=rate,
                    supplier=supplier, updated_date=updatedDate, min_stock=minStock,
                    category=category
                ))
        db.commit()

        for rm_id, qty in DEMO_INV:
            existing = db.query(m.Inventory).filter_by(rm_id=rm_id).first()
            if not existing:
                db.add(m.Inventory(rm_id=rm_id, quantity=qty))
        db.commit()

        print("Seed complete — demo users, shifts, raw materials, inventory, and default settings created.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
