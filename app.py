"""SentrySAP - Streamlit UI (4 tabs). Run with:  streamlit run app.py

The UI talks directly to the service layer (sentrysap/services.py); the APScheduler watch loop runs
inside this process, started once via st.cache_resource.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from sentrysap.knowledge import KnowledgeBaseError, SUPPORTED_EXTENSIONS
from sentrysap.llm import LLMError
from sentrysap.services import Services, build_services

st.set_page_config(page_title="SentrySAP", page_icon="🛡️", layout="wide")

SEVERITY_BADGE = {"critical": "🟥 CRITICAL", "high": "🟧 HIGH", "medium": "🟨 MEDIUM", "low": "🟩 LOW"}


@st.cache_resource(show_spinner="Starting SentrySAP...")
def get_services() -> Services:
    """Build all services once per server process and start the scheduler."""
    return build_services(start_scheduler=True)


svc = get_services()

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🛡️ SentrySAP")
    st.caption("Knows your custom SAP landscape - and acts before you ask.")
    actor = st.text_input("Your name (recorded in the audit log)", value="demo.user")
    if not svc.settings.llm_ready:
        st.error("LLM_API_KEY is not set. Copy `.env.example` to `.env`, add your free key, restart.")
    st.caption(f"LLM: `{svc.settings.llm_model}` · embeddings: `{svc.settings.embedding_provider}`")
    st.divider()
    st.subheader("⚡ Watch mode")
    st.caption(f"Scheduler: {'running' if svc.watcher.running else 'stopped'} · every "
               f"{svc.settings.watch_interval_seconds}s · next {svc.watcher.next_run}")
    last = svc.watcher.last
    if last.ran_at:
        st.caption(f"Last cycle {last.ran_at}: {last.findings} matches, {len(last.new_alerts)} new alerts")
    if last.error:
        st.warning(last.error)
    if st.button("▶ Run watch cycle now", use_container_width=True):
        with st.spinner("Evaluating rules and building alert cards..."):
            res = svc.watcher.run_cycle()
        st.toast(f"{len(res.new_alerts)} new alert(s)" + (f" - {res.error}" if res.error else ""))
        st.rerun()
    if st.button("🎲 Inject random SAP event", use_container_width=True):
        try:
            ev = svc.sap.inject_random_event()
            st.toast(f"SAP event: {ev['type']} ({ev['entity']} {ev['entity_id']})")
        except RuntimeError as exc:
            st.error(str(exc))
    with st.expander("Simulated SAP event feed"):
        events = svc.sap.recent_events(15)
        if events:
            st.dataframe(pd.DataFrame([{"time": e["ts"][11:19], "type": e["type"], "entity": f"{e['entity']} {e['entity_id']}",
                                        "status": e["status"]} for e in events]), hide_index=True,
                         use_container_width=True)
        else:
            st.caption("No events yet - run `python seed.py`.")

tab_ask, tab_upload, tab_queue, tab_audit = st.tabs(
    ["💬 Ask SentrySAP", "📤 Upload Documents", "🔔 Action Queue", "📋 Audit Log"])

# ----------------------------------------------------------------------------- tab 1: ask
with tab_ask:
    st.subheader("Ask about YOUR SAP landscape")
    st.caption("Answers come only from your uploaded SOPs, ABAP and wiki pages. "
               "Try: *How do I block a vendor?* · *How do I escalate a late PO?* · *Which transaction creates a replenishment PO?*")
    if "messages" not in st.session_state:
        st.session_state.messages = []
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander(f"Sources ({len(msg['sources'])})"):
                    for s in msg["sources"]:
                        st.markdown(f"**{s['source']}** · {s['doc_type']} · match {s['score']:.0%}")
                        st.caption(s["excerpt"])
    if question := st.chat_input("Ask a question, e.g. 'How do I block a vendor?'"):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Searching your documents..."):
                    ans = svc.kb.answer(question)
                text = ans.text if ans.grounded else (
                    ans.text + ("" if "knowledge base is empty" in ans.text else
                                "\n\nTry rephrasing, or upload the relevant SOP/wiki page in **Upload Documents**."))
                sources = [{"source": c.source, "doc_type": c.doc_type, "score": c.score, "excerpt": c.excerpt()}
                           for c in ans.sources]
            except LLMError as exc:
                text, sources = f"⚠️ {exc}", []
            st.markdown(text)
            if sources:
                with st.expander(f"Sources ({len(sources)})"):
                    for s in sources:
                        st.markdown(f"**{s['source']}** · {s['doc_type']} · match {s['score']:.0%}")
                        st.caption(s["excerpt"])
        st.session_state.messages.append({"role": "assistant", "content": text, "sources": sources})

# ----------------------------------------------------------------------------- tab 2: upload
with tab_upload:
    st.subheader("Teach SentrySAP your landscape")
    files = st.file_uploader("PDF, TXT, MD or .abap files", type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
                             accept_multiple_files=True)
    type_choice = st.selectbox("Document type", ["auto-detect", "sop", "abap", "wiki", "other"])
    if st.button("Ingest selected files", type="primary", disabled=not files):
        for f in files or []:
            try:
                with st.spinner(f"Embedding {f.name}..."):
                    res = svc.kb.ingest(f.name, f.getvalue(), None if type_choice == "auto-detect" else type_choice)
                st.success(f"{res.source}: {res.chunks} chunks stored as '{res.doc_type}'.")
            except (KnowledgeBaseError, LLMError) as exc:
                st.error(f"{f.name}: {exc}")
    st.divider()
    st.markdown("#### Ingested documents")
    docs = svc.kb.list_documents()
    if not docs:
        st.info("Nothing ingested yet. Run `python seed.py` or upload files above.")
    for d in docs:
        c1, c2, c3, c4 = st.columns([5, 1.2, 1.2, 1.4])
        c1.write(f"📄 **{d['source']}**")
        c2.write(str(d["doc_type"]))
        c3.write(f"{d['chunks']} chunks")
        if c4.button("🗑 Delete", key=f"del_{d['source']}"):
            svc.kb.delete_document(str(d["source"]))
            st.rerun()

# ----------------------------------------------------------------------------- tab 3: queue
@st.fragment(run_every="10s")
def render_queue() -> None:
    """Pending alerts with playbook + draft + approval buttons (auto-refreshes every 10 s)."""
    if "flash" in st.session_state:
        kind, msg = st.session_state.pop("flash")
        (st.success if kind == "ok" else st.warning)(msg)
    pending = svc.alerts.list_alerts("pending")
    st.subheader(f"Pending actions ({len(pending)})")
    if not pending:
        st.info("No pending alerts. Use **Inject random SAP event** then **Run watch cycle now** in the sidebar.")
    for a in pending:
        with st.container(border=True):
            st.markdown(f"### {SEVERITY_BADGE.get(a['severity'], a['severity'])} · {a['title']}")
            st.caption(f"Alert #{a['id']} · rule `{a['rule_id']}` · {a['created_at']} · written by {a['generator']}")
            st.write(a["summary"])
            left, right = st.columns(2)
            with left:
                st.markdown(f"**Affected PO:** {a['affected_po']}")
                st.markdown("**Suggested action**")
                st.write(a["suggested_action"])
            with right:
                st.markdown("**📘 Your company's playbook**")
                if a["playbook_excerpt"]:
                    st.caption(f"{a['playbook_source']} · match {a['playbook_score']:.0%}")
                    st.info(a["playbook_excerpt"])
                else:
                    st.warning("No documented procedure found for this situation. Consider writing an SOP.")
            st.markdown(f"**✉️ {a['draft_label']}**")
            st.code(a["draft_email"], language=None)
            reason = st.text_input("Rejection reason (optional)", key=f"reason_{a['id']}")
            b1, b2, _ = st.columns([1.3, 1, 4])
            if b1.button("✅ Approve & Execute", key=f"ok_{a['id']}", type="primary"):
                try:
                    result = svc.alerts.approve(a["id"], actor or "unknown")
                    st.session_state["flash"] = ("ok", f"Alert #{a['id']} approved and executed: {result}")
                except Exception as exc:  # noqa: BLE001 - show any failure to the user
                    st.session_state["flash"] = ("warn", f"Alert #{a['id']}: {exc}")
                st.rerun()
            if b2.button("❌ Reject", key=f"no_{a['id']}"):
                try:
                    svc.alerts.reject(a["id"], actor or "unknown", reason)
                    st.session_state["flash"] = ("ok", f"Alert #{a['id']} rejected and logged.")
                except ValueError as exc:
                    st.session_state["flash"] = ("warn", str(exc))
                st.rerun()


with tab_queue:
    render_queue()

# ----------------------------------------------------------------------------- tab 4: audit
with tab_audit:
    st.subheader("Audit log")
    all_alerts = svc.alerts.list_alerts()
    m1, m2, m3 = st.columns(3)
    m1.metric("Pending", sum(a["status"] == "pending" for a in all_alerts))
    m2.metric("Approved", sum(a["status"] == "approved" for a in all_alerts))
    m3.metric("Rejected", sum(a["status"] == "rejected" for a in all_alerts))
    order = st.radio("Order", ["Newest first", "Oldest first"], horizontal=True)
    rows = svc.alerts.audit_rows(newest_first=order == "Newest first")
    if rows:
        df = pd.DataFrame(rows).rename(columns={"ts": "Time (UTC)", "actor": "Who", "action": "What",
                                                "alert_id": "Alert #", "title": "Alert", "severity": "Severity",
                                                "detail": "Detail"}).drop(columns=["id"])
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("Download CSV", df.to_csv(index=False), "sentrysap_audit_log.csv", "text/csv")
    else:
        st.info("The audit log is empty.")
