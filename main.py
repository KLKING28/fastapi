from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from datetime import datetime
import os

from db import ENGINE, SessionLocal
from models import Lead, Base
from ai_writer import classify_segment, offer_label, generate_email_draft
from mailer import send_email

app = FastAPI(title="AI Marketing Agent")

# Tworzymy tabele przy starcie (MVP). Docelowo damy migracje.
Base.metadata.create_all(bind=ENGINE)

APPROVAL_TOKEN = os.getenv("APPROVAL_TOKEN", "")

class LeadIn(BaseModel):
    name: str
    email: str
    company: str | None = None
    budget: int
    need: str

@app.get("/")
def root():
    return {"status": "AI Marketing Agent is running 🚀"}

@app.post("/lead")
async def create_lead(lead: LeadIn):
    segment = classify_segment(lead.budget)
    label = offer_label(segment)

  try:
    subject, body = await generate_email_draft(lead)
except Exception as e:
    subject = "Nowe zapytanie"
    body = f"Lead zapisany, AI chwilowo niedostępne.\n\n{str(e)}"

await send_email(
    name=lead.name,
    email=lead.email,
    company=lead.company,
    budget=lead.budget,
    need=lead.need,
    subject=subject,
    body=body,
)

    db = SessionLocal()
    try:
        row = Lead(
            name=lead.name,
            email=lead.email,
            company=lead.company,
            budget=lead.budget,
            need=lead.need,
            segment=segment,
            status="DRAFT_READY",
            draft_subject=subject,
            draft_body=body,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {
            "lead_id": row.id,
            "recommended_offer": label,
            "status": row.status,
            "draft_subject": subject,
            "draft_body": body,
            "next_step": "Zatwierdź wysyłkę: POST /lead/{lead_id}/approve",
        }
    finally:
        db.close()

@app.get("/lead/{lead_id}")
def get_lead(lead_id: int):
    db = SessionLocal()
    try:
        row = db.get(Lead, lead_id)
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {
            "lead_id": row.id,
            "name": row.name,
            "email": row.email,
            "company": row.company,
            "budget": row.budget,
            "need": row.need,
            "segment": row.segment,
            "status": row.status,
            "draft_subject": row.draft_subject,
            "draft_body": row.draft_body,
            "sent_at": row.sent_at,
            "created_at": row.created_at,
        }
    finally:
        db.close()

@app.get("/leads")
def list_leads(limit: int = 50):
    db = SessionLocal()
    try:
        rows = db.query(Lead).order_by(Lead.id.desc()).limit(limit).all()
        return [
            {
                "lead_id": r.id,
                "name": r.name,
                "email": r.email,
                "company": r.company,
                "budget": r.budget,
                "segment": r.segment,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    finally:
        db.close()

@app.post("/lead/{lead_id}/approve")
def approve_and_send(lead_id: int, x_approval_token: str | None = Header(default=None)):
    if not APPROVAL_TOKEN:
        raise HTTPException(status_code=500, detail="APPROVAL_TOKEN is not set")
    if x_approval_token != APPROVAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid approval token")

    db = SessionLocal()
    try:
        row = db.get(Lead, lead_id)
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found")
        if row.status == "SENT":
            return {"ok": True, "message": "Already sent", "lead_id": row.id}

        if not row.draft_subject or not row.draft_body:
            raise HTTPException(status_code=400, detail="Draft is missing")

        send_email(to_email=row.email, subject=row.draft_subject, body=row.draft_body)

        row.status = "SENT"
        row.sent_at = datetime.utcnow()
        db.commit()

        return {"ok": True, "lead_id": row.id, "status": row.status}
    finally:
        db.close()
