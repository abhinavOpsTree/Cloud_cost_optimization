from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), default="spendsmart")
    dataset: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="started")
    records: Mapped[int] = mapped_column(Integer, default=0)
    raw_path: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class EC2Instance(Base):
    __tablename__ = "ec2_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[str] = mapped_column(String(120), default="unknown", index=True)
    account_name: Mapped[str | None] = mapped_column(String(255), index=True)
    region: Mapped[str] = mapped_column(String(100), default="unknown", index=True)

    instance_id: Mapped[str] = mapped_column(String(120), index=True)
    instance_name: Mapped[str | None] = mapped_column(String(255))
    instance_type: Mapped[str | None] = mapped_column(String(100), index=True)
    state: Mapped[str | None] = mapped_column(String(50), index=True)

    platform: Mapped[str | None] = mapped_column(String(100))
    availability_zone: Mapped[str | None] = mapped_column(String(100))
    vpc_id: Mapped[str | None] = mapped_column(String(120))
    subnet_id: Mapped[str | None] = mapped_column(String(120))

    cpu_utilization_pct: Mapped[float | None] = mapped_column(Float)
    memory_utilization_pct: Mapped[float | None] = mapped_column(Float)

    monthly_cost: Mapped[float | None] = mapped_column(Float)
    estimated_monthly_savings: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="USD")

    lifecycle: Mapped[str | None] = mapped_column(String(100))
    recommendation: Mapped[str | None] = mapped_column(Text)

    tags: Mapped[dict | None] = mapped_column(JSON)
    source_json: Mapped[dict | None] = mapped_column(JSON)

    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "region",
            "instance_id",
            name="uq_ec2_instance",
        ),
    )


class EC2Lifecycle(Base):
    __tablename__ = "ec2_lifecycle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(120), index=True)
    lifecycle_state: Mapped[str | None] = mapped_column(String(100))
    launch_time: Mapped[str | None] = mapped_column(String(100))
    age_days: Mapped[float | None] = mapped_column(Float)
    source_json: Mapped[dict | None] = mapped_column(JSON)


class AMIInventory(Base):
    __tablename__ = "ami_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ami_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(80))
    creation_date: Mapped[str | None] = mapped_column(String(100))
    age_days: Mapped[float | None] = mapped_column(Float)
    size_gb: Mapped[float | None] = mapped_column(Float)
    source_json: Mapped[dict | None] = mapped_column(JSON)


class OptimizationFinding(Base):
    __tablename__ = "optimization_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(50), default="EC2", index=True)
    resource_id: Mapped[str | None] = mapped_column(String(180), index=True)
    finding_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    estimated_monthly_savings: Mapped[float] = mapped_column(Float, default=0)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(80), default="local")
    status: Mapped[str] = mapped_column(String(30), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AISummary(Base):
    __tablename__ = "ai_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    summary_type: Mapped[str] = mapped_column(String(80), index=True)
    provider: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    context_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
