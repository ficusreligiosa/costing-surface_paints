from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)


class RawMaterial(Base):
    __tablename__ = "raw_materials"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    code = Column(String, unique=True, nullable=False)
    unit = Column(String, default="KG")
    rate = Column(Float, default=0)
    supplier = Column(String, default="")
    updated_date = Column(String, default="")
    min_stock = Column(Float, default=0)
    category = Column(String, default="")
    expiry_date = Column(String, default="")

    inventory = relationship("Inventory", back_populates="raw_material", uselist=False)


class Inventory(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True)
    rm_id = Column(Integer, ForeignKey("raw_materials.id"), unique=True, nullable=False)
    quantity = Column(Float, default=0)

    raw_material = relationship("RawMaterial", back_populates="inventory")


class Formulation(Base):
    __tablename__ = "formulations"
    id = Column(Integer, primary_key=True)
    product_name = Column(String, nullable=False)
    product_code = Column(String, default="")
    product_type = Column(String, default="")
    product_finish = Column(String, default="")
    batch_no = Column(String, default="")
    mfg_date = Column(String, default="")
    remarks = Column(Text, default="")
    ref_no = Column(String, default="")
    party_id = Column(String, default="")
    party_name = Column(String, default="")
    lots = Column(Integer, default=1)
    inventory_debited = Column(Boolean, default=False)
    inventory_partial_debit = Column(Boolean, default=False)
    skipped_debit_rm_ids = Column(JSON, default=list)
    debit_lots = Column(Integer, default=0)
    debit_date = Column(String, default="")
    debit_remarks = Column(Text, default="")
    by = Column(String, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default="")
    lab_values = Column(JSON, nullable=True)
    gloss_value = Column(Float, nullable=True)
    gloss_angle = Column(String, default="")
    lab_notes = Column(Text, default="")

    items = relationship("FormulationItem", back_populates="formulation", cascade="all, delete-orphan")


class FormulationItem(Base):
    __tablename__ = "formulation_items"
    id = Column(Integer, primary_key=True)
    formulation_id = Column(Integer, ForeignKey("formulations.id"), nullable=False, index=True)
    rm_id = Column(Integer, ForeignKey("raw_materials.id"), nullable=False, index=True)
    qty = Column(Float, default=0)
    unit = Column(String, default="KG")
    rate = Column(Float, nullable=True)

    formulation = relationship("Formulation", back_populates="items")


class StockTransaction(Base):
    __tablename__ = "stock_transactions"
    id = Column(Integer, primary_key=True)
    rm_id = Column(Integer, ForeignKey("raw_materials.id"), nullable=False, index=True)
    type = Column(String, nullable=False)
    qty = Column(Float, default=0)
    date = Column(String, default="")
    remarks = Column(Text, default="")
    by = Column(String, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    time = Column(String, default="")
    user = Column(String, default="")
    action = Column(String, default="")
    detail = Column(Text, default="")


class FormulationComment(Base):
    __tablename__ = "formulation_comments"
    id = Column(Integer, primary_key=True)
    formulation_id = Column(Integer, ForeignKey("formulations.id"), nullable=False)
    type = Column(String, default="production")
    text = Column(Text, default="")
    by = Column(String, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default="")


class BasePrice(Base):
    __tablename__ = "base_prices"
    id = Column(Integer, primary_key=True)
    formulation_id = Column(Integer, ForeignKey("formulations.id"), nullable=False, index=True)
    rm_id = Column(Integer, ForeignKey("raw_materials.id"), nullable=False, index=True)
    rm_name = Column(String, default="")
    entered_rate = Column(Float, default=0)
    qty = Column(Float, default=0)
    unit = Column(String, default="KG")
    saved_at = Column(String, default="")


class Machine(Base):
    __tablename__ = "machines"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, default="")
    hourly_machine_cost = Column(Float, default=0)
    std_kg_hr = Column(Float, nullable=True)
    active = Column(Boolean, default=True)


class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    start_time = Column(String, default="")
    end_time = Column(String, default="")
    crosses_midnight = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    color = Column(String, default="#2563eb")


class ProductionLog(Base):
    __tablename__ = "production_logs"
    id = Column(Integer, primary_key=True)
    worker_name = Column(String, default="")
    date = Column(String, default="")
    shift_id = Column(Integer, nullable=True)
    shift_name = Column(String, default="")
    product_name = Column(String, default="")
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    rpm = Column(String, default="")
    hour_meter = Column(String, default="")
    start_time = Column(String, default="")
    end_time = Column(String, default="")
    break_mins = Column(Float, default=0)
    rm_input = Column(Float, default=0)
    fg_output = Column(Float, default=0)
    formulation_id = Column(Integer, nullable=True)
    remarks = Column(Text, default="")
    by = Column(String, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default="")


class ForecastInputRow(Base):
    __tablename__ = "forecast_input_rows"
    id = Column(Integer, primary_key=True)
    row_index = Column(Integer, default=0)
    batch_no = Column(String, default="")
    ref_no = Column(String, default="")
    product_name = Column(String, default="")
    order_qty = Column(Float, default=0)
    order_date = Column(String, default="")
    created_at = Column(String, default="")
    by = Column(String, default="")


class PartyLookup(Base):
    __tablename__ = "party_lookup"
    id = Column(Integer, primary_key=True)
    ref_no = Column(String, index=True)
    party_id = Column(String, default="")
    party_name = Column(String, default="")


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, default="")


class Session(Base):
    """
    Issued on login, required on every write action so the backend always
    knows who is calling and what their role is — closes the gap flagged in
    the role-workflow spec: the old system only hid buttons in the UI, it
    never checked permissions server-side.
    """
    __tablename__ = "sessions"
    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, default="")
