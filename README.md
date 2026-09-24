# ReconAgent: AI-Powered Invoice Reconciliation & Investigation System

An enterprise-grade, multi-stage invoice reconciliation and autonomous forensic investigation platform. ReconAgent enforces strict mathematical integrity validation across source documents (Purchase Orders, Invoices, Delivery Receipts), performs deterministic 3-way matching, autonomously investigates discrepancies using LangGraph agent state machines, and presents plain-English audit reasoning to non-technical business reviewers.

---

## 🌟 Key Features

1. **Pre-Reconciliation Arithmetic Integrity Verification**:
   - Every uploaded document (PO, Invoice, Receipt) is mathematically audited *before* cross-document matching.
   - Computes line-item math (`qty * unit_price - discount + tax == total`), subtotal accuracy, and grand total equations.
   - If internal document arithmetic fails, automated queries are halted immediately to protect against hallucination and wasted compute. The system generates a plain-English rejection report.

2. **Deterministic 3-Way Reconciliation Engine**:
   - Cross-matches Purchase Orders, Invoices, and Goods Delivery Receipts.
   - Compares line items, quantities, and pricing against policy tolerances (0.01 threshold).
   - Classifies price mismatches, quantity shortages, unauthorized surcharges, and missing documentation.

3. **Autonomous Forensic Investigation Agent (LangGraph)**:
   - Dynamic LangGraph state machine with dual-tier LLM routing (Gemini 2.5 Flash / Flash Lite).
   - Leverages a secure tool registry (`get_purchase_order`, `get_invoice`, `get_receipt`, `check_authorization`, `get_vendor_history`).
   - Gathers immutable evidence citations with strict grounding checks.

4. **Short-Form Plain-English Reasoning for Business Users**:
   - Replaces technical error codes and raw Python dictionaries with concise 1–2 sentence explanations.
   - Tailored specifically for Accounts Payable specialists, audit reviewers, and finance controllers.

5. **Human-in-the-Loop Governance & Audit Trail**:
   - Review queue gate (Section 7.4 compliance protocol) for manual specialist sign-off (`APPROVE`, `REJECT`, `ESCALATE`).
   - Interactive React dashboard with document viewer, 3-way match cards, and provenance ribbons.

---

## 🏗️ Architecture

```
   ┌─────────────────────────────────────────────────────────────┐
   │                     1. Document Ingestion                   │
   │           Classification & Multi-Modal Extraction           │
   └──────────────────────────────┬──────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │            2. Pre-Reconciliation Document Validation         │
   │           Deterministic Line Math & Grand Total Audit       │
   └───────────────┬─────────────────────────────┬───────────────┘
           [Math Failed]                 [Math Valid]
                   ▼                             ▼
   ┌─────────────────────────────┐ ┌─────────────────────────────┐
   │  Immediate Invoice Reject   │ │ 3. Deterministic 3-Way Match│
   │  Plain-English Vendor Alert │ │   PO vs Invoice vs Receipt  │
   └─────────────────────────────┘ └──────────────┬──────────────┘
                                                  ▼
                                   ┌─────────────────────────────┐
                                   │ 4. Autonomous Agent Loop    │
                                   │    Evidence & Root Cause    │
                                   └──────────────┬──────────────┘
                                                  ▼
                                   ┌─────────────────────────────┐
                                   │ 5. AP Dashboard & Review    │
                                   │    Plain-English Governance │
                                   └─────────────────────────────┘
```

---

## 🚀 Quickstart

### 1. Backend Setup

```bash
# Clone the repository
git clone https://github.com/<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
cd <YOUR_REPO_NAME>

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Set your GEMINI_API_KEY in .env

# Run FastAPI backend server
uvicorn src.api.main:app --port 8000 --reload
```

API documentation will be available at `http://localhost:8000/docs`.

### 2. Frontend Dashboard Setup

```bash
cd frontend

# Install node dependencies
npm install

# Start Vite development server
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## 🧪 Testing

Run the test suite across pre-validation, deterministic reconciliation, orchestrator, and REST API:

```bash
# Run all core tests
pytest tests/test_pre_reconciliation_document_validation.py tests/test_reconciliation_pipeline.py tests/test_pipeline_orchestrator.py tests/test_api.py -v

# Frontend build verification
cd frontend
npm run build
```

---

## 🔄 CI/CD Automation

This repository includes a continuous integration workflow powered by **GitHub Actions** (`.github/workflows/ci.yml`).
On every push and pull request to `main`:
- **Backend Job**: Automatically sets up Python 3.12, installs dependencies, and runs the full test suite.
- **Frontend Job**: Automatically sets up Node.js 20, validates TypeScript types, and compiles the production Vite bundle.
