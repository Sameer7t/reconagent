"""
Transaction Processing and Reconciliation Route Controller.

Provides:
- POST /transactions/process: Runs deterministic 3-way reconciliation on supplied transaction data.
"""
from fastapi import APIRouter, Depends

from api.dependencies import get_orchestrator
from api.schemas import ReconcileTransactionRequest, CaseDetailResponse
from api.routes.cases import _transaction_result_to_response
from pipeline.orchestrator import MasterOrchestrator

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post("/process", response_model=CaseDetailResponse)
def process_transaction(
    payload: ReconcileTransactionRequest,
    orchestrator: MasterOrchestrator = Depends(get_orchestrator),
):
    """
    Executes 3-way reconciliation on transaction documents.
    Branches to autonomous AI investigation if discrepancies are detected.
    """
    tx_res = orchestrator.process_transaction(
        po_data=payload.po_data,
        invoice_data=payload.invoice_data,
        receipt_data_list=payload.receipt_data_list,
        case_id=payload.case_id,
    )
    return _transaction_result_to_response(tx_res)

