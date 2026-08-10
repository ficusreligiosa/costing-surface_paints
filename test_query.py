from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app import models as m

DATABASE_URL = "sqlite:///surface_paints.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

print("--- FORMULATIONS ---")
for f in db.scalars(select(m.Formulation).order_by(m.Formulation.id.desc()).limit(5)):
    print(f"ID: {f.id}, Name: {f.product_name}, Debited: {f.inventory_debited}, Partial: {f.inventory_partial_debit}, Lots: {f.lots}, DebitLots: {f.debit_lots}, Remarks: {f.debit_remarks}, Skipped IDs: {f.skipped_debit_rm_ids}")
    print("Items:")
    for item in f.items:
        print(f"  RM ID: {item.rm_id}, Qty: {item.qty}, Unit: {item.unit}, Rate: {item.rate}")

print("\n--- INVENTORY ---")
for inv in db.scalars(select(m.Inventory)):
    rm = db.get(m.RawMaterial, inv.rm_id)
    print(f"RM ID: {inv.rm_id}, Name: {rm.name if rm else 'Unknown'}, Qty: {inv.quantity}")

db.close()
