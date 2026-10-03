"""Optional FastAPI backend exposing the same services over HTTP.  Run:  uvicorn api:app --reload

The Streamlit app does NOT need this (it imports the service layer directly, so the required
`streamlit run app.py` flow works with one process). Use the API to integrate other frontends.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from sentrysap.knowledge import KnowledgeBaseError
from sentrysap.llm import LLMError
from sentrysap.services import Services, build_services

_svc: Optional[Services] = None


def svc() -> Services:
    """Return the initialised services (set up in the lifespan hook)."""
    if _svc is None:
        raise HTTPException(503, "Service not ready")
    return _svc


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start services + the APScheduler watch loop on startup; stop them on shutdown."""
    global _svc
    _svc = build_services(start_scheduler=True)
    yield
    _svc.watcher.shutdown()


app = FastAPI(title="SentrySAP API", version="1.0.0", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str


class DecisionRequest(BaseModel):
    actor: str = "api.user"
    reason: str = ""


def _wrap(exc: Exception) -> HTTPException:
    """Map domain errors to HTTP status codes."""
    if isinstance(exc, LLMError):
        return HTTPException(503, str(exc))
    if isinstance(exc, (KnowledgeBaseError, ValueError)):
        return HTTPException(400, str(exc))
    return HTTPException(500, str(exc))


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness + scheduler status."""
    return {"ok": True, "scheduler": svc().watcher.running, "chunks": svc().kb.count()}


@app.get("/documents")
def documents() -> list[dict[str, object]]:
    """List ingested documents."""
    return svc().kb.list_documents()


@app.post("/documents")
async def upload(file: UploadFile = File(...), doc_type: Optional[str] = None) -> dict[str, Any]:
    """Ingest an uploaded PDF/TXT/MD/ABAP file."""
    try:
        res = svc().kb.ingest(file.filename or "upload.txt", await file.read(), doc_type)
    except (KnowledgeBaseError, LLMError) as exc:
        raise _wrap(exc) from exc
    return {"source": res.source, "doc_type": res.doc_type, "chunks": res.chunks}


@app.delete("/documents/{source}")
def delete_document(source: str) -> dict[str, int]:
    """Delete one document."""
    return {"deleted_chunks": svc().kb.delete_document(source)}


@app.post("/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    """Ask mode (RAG)."""
    try:
        ans = svc().kb.answer(req.question)
    except LLMError as exc:
        raise _wrap(exc) from exc
    return {"answer": ans.text, "grounded": ans.grounded,
            "sources": [{"source": c.source, "doc_type": c.doc_type, "score": round(c.score, 3),
                         "excerpt": c.excerpt()} for c in ans.sources]}


@app.get("/alerts")
def alerts(status: Optional[str] = None) -> list[dict[str, Any]]:
    """List alerts, optionally filtered by status (pending|approved|rejected)."""
    return svc().alerts.list_alerts(status)


@app.post("/alerts/{alert_id}/approve")
def approve(alert_id: int, req: DecisionRequest) -> dict[str, str]:
    """Approve & execute an alert's action."""
    try:
        return {"result": svc().alerts.approve(alert_id, req.actor)}
    except Exception as exc:  # noqa: BLE001
        raise _wrap(exc) from exc


@app.post("/alerts/{alert_id}/reject")
def reject(alert_id: int, req: DecisionRequest) -> dict[str, str]:
    """Reject an alert."""
    try:
        svc().alerts.reject(alert_id, req.actor, req.reason)
    except ValueError as exc:
        raise _wrap(exc) from exc
    return {"result": "rejected"}


@app.post("/watch/run")
def run_watch() -> dict[str, Any]:
    """Run one watch cycle immediately."""
    r = svc().watcher.run_cycle()
    return {"findings": r.findings, "new_alerts": r.new_alerts, "error": r.error}


@app.post("/events/inject")
def inject() -> dict[str, Any]:
    """Inject a random simulated SAP event."""
    try:
        return svc().sap.inject_random_event()
    except RuntimeError as exc:
        raise _wrap(exc) from exc


@app.get("/audit")
def audit(newest_first: bool = True) -> list[dict[str, Any]]:
    """Audit log rows."""
    return svc().alerts.audit_rows(newest_first)
