from app.db.session import Base, SessionLocal, engine
from app.models import EC2Instance


Base.metadata.create_all(bind=engine)

db = SessionLocal()

db.add(
    EC2Instance(
        account_id="demo",
        account_name="demo-prod",
        region="ap-south-1",
        instance_id="i-demo-001",
        instance_name="payments-api",
        instance_type="m5.2xlarge",
        state="running",
        cpu_utilization_pct=6.5,
        monthly_cost=300,
        estimated_monthly_savings=80,
        source_json={"source": "demo"},
    )
)

db.commit()
db.close()

print("Demo EC2 row inserted")
