"""
FastAPI Dependency Injection Providers for ReconAgent.
"""
from pathlib import Path
from typing import Optional
from agent.db import InvestigationDatabase, DEFAULT_DB_PATH
from agent.user_db import UserDatabase
from agent.review_queue import ReviewQueueManager, get_review_queue
from pipeline.orchestrator import MasterOrchestrator


_orchestrator_instance: Optional[MasterOrchestrator] = None
_db_instance: Optional[InvestigationDatabase] = None
_user_db_instance: Optional[UserDatabase] = None

def get_db() -> InvestigationDatabase:
    """Provides singleton SQLite database repository."""
    global _db_instance
    if _db_instance is None:
        _db_instance = InvestigationDatabase(DEFAULT_DB_PATH)
    return _db_instance

def get_user_db() -> UserDatabase:
    """Provides singleton PostgreSQL user database repository."""
    global _user_db_instance
    if _user_db_instance is None:
        _user_db_instance = UserDatabase()
    return _user_db_instance


def get_review_queue_dep() -> ReviewQueueManager:
    """Provides ReviewQueueManager synchronized with database."""
    db = get_db()
    return get_review_queue(db=db)


def get_orchestrator() -> MasterOrchestrator:
    """Provides MasterOrchestrator wired with DB and review queue."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        db = get_db()
        rq = get_review_queue_dep()
        _orchestrator_instance = MasterOrchestrator(
            db_path=db.db_path,
            review_queue=rq,
        )
    return _orchestrator_instance

