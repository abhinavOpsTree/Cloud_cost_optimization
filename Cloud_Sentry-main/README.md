# Cloud Sentry AI

> AI-powered AWS EC2 cost optimization engine with 
> 3-tier governance. Prescription-only :- recommends, 
> never executes.

Built by **OpsTree** as part of the SpendSmart FinOps 
platform. Cloud Sentry analyzes your EC2 fleet, 
identifies optimization opportunities, runs every 
recommendation through a deterministic governance 
pipeline, and presents human-readable prescriptions 
for engineers to act on.

---

## What It Does

- Analyzes EC2 instances using real AWS billing data 
  and CloudWatch metrics
- Generates recommendations across 4 tracks: 
  Rightsizing, Spot Conversion, Scheduling, EKS 
  Optimization
- Runs every recommendation through 3 governance tiers 
  before surfacing it
- Explains each recommendation with AI-generated 
  rationale and confidence reasoning
- Exposes a FastAPI backend consumed by the SpendSmart 
  frontend

**What it deliberately does not do:** Cloud Sentry has 
no execution capability in production. Every approved 
recommendation is implemented manually by an engineer. 
This is an architectural decision, not a limitation.

---

## Architecture

### 5 Agents

| Agent | Role |
|---|---|
| `FleetIntelligenceProcessor` | Loads and enriches EC2 fleet data from UnitEconPro + CloudWatch |
| `FinOpsAnalystAgent` | Runs analysis skills across all instances, generates recommendations |
| `GovernanceAgent` | Applies 3-tier governance to every recommendation |
| `FinOpsChatAgent` | Answers natural language questions about the fleet using Gemini |
| `DevOpsRemediationAgent` | Generates Terraform, AWS CLI, and rollback scripts (backend only, not exposed in UI) |

### 3-Tier Governance

```
Tier 1 — Production Shield (deterministic)
  Hard blocks production-tagged instances.
  No AI involved. Cannot be overridden.

Tier 2 — Risk Flagging (deterministic)
  Flags high-network-traffic instances, EKS nodes,
  and instances with utilisation spikes.
  Requires human review before approval.

Tier 3 — AI Reasoning (Gemini)
  Used only when Tiers 1 and 2 run out of signal.
  Ambiguous cases assessed by Gemini.
  Capped at 20 calls per analysis run.
  7-day cache to avoid redundant calls.
```

**AI never overrides Tier 1 or Tier 2 outcomes.**

### Skill System

Each optimization track is a self-contained Python 
class inheriting from `BaseAnalysisSkill`. Adding a 
new skill requires implementing 4 methods:

```python
def can_apply(self, instance: dict) -> bool
def analyse(self, instance: dict) -> dict
def recommend(self, instance, finding) -> dict
def generate_script(self, instance, recommendation) -> dict
```

See `skills/CONTRIBUTING.md` and 
`skills/analysis/template_skill.py` to get started.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API | FastAPI + Uvicorn |
| Database | SQLite (via state_store.py) |
| AI | Google Gemini (gemini-3.6-flash) |
| AWS Data | UnitEconPro API + boto3/CloudWatch |
| Billing | AWS CUR via UnitEconPro |

---

## Project Structure

```
cloud-sentry/
├── agents/               # 5 core agents
├── api/                  # FastAPI routes (main.py)
├── core/                 # Base classes, skill registry,
│                         # instance specs, state store
├── skills/
│   ├── analysis/         # Rightsizing, Spot, Schedule, EKS
│   ├── context/          # Fleet and savings context builders
│   ├── governance/       # Production Shield, Risk Flagging,
│   │                     # Ambiguous Reasoning
│   └── remediation/      # Script generators (Terraform, CLI)
├── reporters/            # Tag Compliance Reporter
├── services/             # Chatbot, Cost Anomaly, Spot Simulator
├── scripts/              # Utility and verification scripts
├── tests/                # Test suite
├── config.yaml           # Configuration
└── requirements.txt      # Python dependencies
```

---

## Running Locally

### Prerequisites
- Python 3.11+
- Access to UnitEconPro API
- Google Gemini API key
- AWS credentials with CloudWatch read access

### Setup

```bash
# Clone the repo
git clone https://github.com/Opstree-Data-and-AI/Cloud_Sentry.git
cd Cloud_Sentry

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Fill in GEMINI_API_KEY, UNITECONPRO_API_URL, 
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

# Run the API
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

API will be available at `http://localhost:8000`

---

## Key API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/analyse` | Trigger full fleet analysis |
| `GET` | `/api/v1/recommendations` | Get all recommendations |
| `PUT` | `/api/v1/recommendations/{id}/approve` | Approve a recommendation |
| `PUT` | `/api/v1/recommendations/{id}/ignore` | Ignore a recommendation |
| `GET` | `/api/v1/instances` | Get full instance list |
| `GET` | `/api/v1/tag-audit` | Get tag coverage report |
| `POST` | `/api/v1/chat` | Chat with FinOps Assistant |
| `GET` | `/api/v1/skills` | Get registered skills |

---

## Contributing a Skill

1. Copy `skills/analysis/template_skill.py`
2. Rename and implement the 4 required methods
3. Set `NAME`, `DISPLAY_NAME`, `DESCRIPTION`, `TRACK`
4. Drop the file into `skills/analysis/`
5. It registers automatically on next startup

Read `skills/CONTRIBUTING.md` for full guidance and 
examples.

---

## Design Principles

- **Prescription-only by design.** No infrastructure 
  changes happen automatically. Engineers approve and 
  implement manually.
- **Deterministic-first.** AI (Gemini) is used only 
  where deterministic rules run out of signal. Tier 1 
  and Tier 2 are pure Python.
- **Transparent reasoning.** Every recommendation 
  includes AI rationale, confidence score with 
  breakdown, and governance tier results.
- **Honest about data gaps.** Instances without 
  CloudWatch metrics are clearly marked. Confidence 
  scores reflect data availability.

---

## License

MIT License — see `LICENSE` for details.

---

*Cloud Sentry AI is developed and maintained by the 
OpsTree Data & AI team.*
