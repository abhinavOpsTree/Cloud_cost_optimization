# SpendSmart / UnitEconPro Cost Optimization Platform — EC2 Processing Focus

This version is built from the provided UnitEconPro Swagger PDF.

## Design rule

**Catalog everything from Swagger. Process only EC2.**

The codebase contains:
- the full known UnitEconPro endpoint catalog from the Swagger PDF;
- the full schema-name catalog visible in Swagger;
- generic source access for every cataloged endpoint;
- dedicated EC2 source wrappers;
- EC2-only raw ingestion;
- EC2-only normalzation and persistence;
- EC2-only cost/optimization analysis;
- EC2-only Streamlit UI;
- EC2-only Groq context.

No non-EC2 service is processed into the database yet.

## SpendSmart / UnitEconPro source

Default base URL:

```text
https://uniteconpro-api.opstree.net
```

Swagger / OpenAPI:
- Swagger UI: `/docs`
- OpenAPI document: `/openapi.json`

## EC2 source endpoints used for processing

```text
GET /api/v1/compute/ec2/summary
GET /api/v1/compute/ec2/instances
GET /api/v1/compute/ec2/lifecycle
GET /api/v1/compute/ec2/amis
GET /api/v1/compute/ec2/instances/{instance_id}/metadata
```

Optimization / recommendation endpoints used as additional EC2 evidence:

```text
GET  /api/v1/optimizations/
POST /api/v1/optimizations/sync
GET  /api/v1/optimizations/summary
GET  /api/v1/optimizations/compute/ec2

GET /api/v1/recommendations
GET /api/v1/recommendations/summary

GET   /api/v1/stateful/recommendations
GET   /api/v1/stateful/recommendations/summary
GET   /api/v1/stateful/recommendations/{rec_id}
POST  /api/v1/stateful/recommendations/sync
PATCH /api/v1/stateful/recommendations/{rec_id}/status
DELETE /api/v1/stateful/recommendations/purge
```

## Full source catalog

See:

```text
app/services/spendsmart/endpoint_registry.py
```

That registry includes Dashboard, Analytics, EC2, ECR, EKS, ECS, S3, EBS, RDS, VPC, ELB, Data Transfer, CloudWatch, Budget, Accounts, Account Access, Optimizations, Settings, Permissions, Alerts, Alert Rules, Comparison, Report, Suggestions, Recommendations, and Stateful Recommendations.

## Swagger schema catalog

See:

```text
app/services/spendsmart/schema_registry.py
```

The PDF lists the schema names but does not expose the expanded field definitions. Therefore no field definitions are invented for non-EC2 schemas.

For EC2, normalization is deliberately alias-tolerant until the real `/openapi.json` is available.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Start API:

```bash
uvicorn app.main:app --reload
```

Open local API docs:

```text
http://127.0.0.1:8000/docs
```

Start Streamlit:

```bash
PYTHONPATH=. streamlit run streamlit_app/Home.py
```

## EC2 processing flow

```text
SpendSmart EC2 APIs
        ↓
Raw bundle snapshot
        ↓
EC2 normalizer
        ↓
EC2 tables
        ↓
EC2 analytics
        ↓
SpendSmart optimization/recommendation evidence
        ↓
Local conservative EC2 rules
        ↓
Groq EC2 FinOps assistant
        ↓
FastAPI + Streamlit
```
