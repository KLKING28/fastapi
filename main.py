import os
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


# =========================
# CONFIG / ENV
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # ustaw w Railway
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
APPROVAL_TOKEN = os.getenv("APPROVAL_TOKEN", "")

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


def normalize_database_url(url: str) -> str:
    # Railway czasem daje postgres://, SQLAlchemy lubi postgresql+psycopg2://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


ENGINE = create_engine(normalize_database_url(DATABASE_URL), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)


# =========================
# DB MODELS
# =========================

class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(300))
    company: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    budget: Mapped[int] = mapped_column(Integer)
    need: Mapped[str] = mapped_column(Text)

    segment: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT_READY")  # DRAFT_READY, SENT

    draft_subject: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    draft_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=ENGINE)


# =========================
# FASTAPI
# =========================

app = FastAPI(title="AI Marketing Agent")

# ✅ CORS – konieczne, żeby panel (localhost:5173) mógł wołać API
# MVP: zostawiamy localhosty. Po deployu panelu na Railway dopiszemy jego domenę.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # jeśli chcesz, możesz chwilowo odblokować wszystko:
        # "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LeadIn(BaseModel):
    name: str
    email: EmailStr
    company: Optional[str] = None
    budget: int
    need: str


def classify_segment(budget: int) -> str:
    if budget < 1000:
        return "LOW"
    if budget < 2000:
        return "EVENT_STREAM"
    if budget < 2500:
        return "VIDEO"
    return "RETAINER"


def offer_label(segment: str) -> str:
    return {
        "LOW": "Poza zakresem budżetu (spróbuj doprecyzować / upsell)",
        "EVENT_STREAM": "Event / stream (od 1000 zł)",
        "VIDEO": "Film / wideo (od 2000 zł)",
        "RETAINER": "Abonament (od 2500 zł / miesiąc)",
    }.get(segment, "Nieznany segment")


async def generate_email_draft(
    name: str,
    email: str,
    company: Optional[str],
    budget: int,
    need: str
) -> tuple[str, str]:
    """
    Zwraca (subject, body). Jeśli OpenAI nie działa → fallback bez wywalania API.
    """
    # Fallback jeśli nie ma klucza:
    if not OPENAI_API_KEY:
        subject = "Nowe zapytanie – szybkie doprecyzowanie"
        body = (
            f"Cześć {name},\n\n"
            f"Dzięki za wiadomość. Wstępnie rozumiem, że chodzi o: {need}.\n"
            "Podeślę konkretną propozycję – czy możesz doprecyzować termin i miejsce?\n\n"
            "Pozdrawiam\nKrzysztof | ElectronicArt"
        )
        return subject, body

    segment = classify_segment(budget)
    label = offer_label(segment)

    system = (
        "Jesteś doświadczonym sprzedawcą usług streamingu i produkcji wideo B2B. "
        "Piszesz po polsku, naturalnie i konkretnie, bez korpo. "
        "Mail ma brzmieć jak od człowieka. Jedno pytanie domykające. "
        "Nie obiecuj rzeczy bez ustalenia zakresu."
    )

    user = f"""
Dane:
- Imię: {name}
- Firma: {company or "brak"}
- Potrzeba: {need}
- Budżet: {budget} PLN
Rekomendacja: {label}

Wygeneruj:
1) SUBJECT: (max 60 znaków)
2) BODY: 120–200 słów, w tym:
   - 1 zdanie personalizacji (odnieś się do potrzeby)
   - 2–3 warianty (Basic/Standard/Premium) – 1 zdanie każdy (bez cen)
   - 1 pytanie domykające (termin + doprecyzowanie)
Podpis: "Krzysztof | ElectronicArt"
Zwróć w formacie:
SUBJECT: ...
BODY:
...
"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.8,
                },
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]

        subject = "Propozycja współpracy"
        body = text

        if "SUBJECT:" in text and "BODY:" in text:
            subject = text.split("SUBJECT:", 1)[1].split("BODY:", 1)[0].strip()
            body = text.split("BODY:", 1)[1].strip()

        return subject, body

    except Exception as e:
        # Fallback przy 429 / błędach:
        subject = "Nowe zapytanie – doprecyzujmy szczegóły"
        body = (
            f"Cześć {name},\n\n"
            f"Dzięki za wiadomość. Wstępnie brzmi to jak: {need}.\n"
            "Podeślę konkretną propozycję – czy możesz doprecyzować termin i format (stream/aftermovie)?\n\n"
            "Pozdrawiam\nKrzysztof | ElectronicArt\n\n"
            f"(INFO TECH: {str(e)})"
        )
        return subject, body


def send_via_sendgrid(to_email: str, subject: str, body_text: str) -> dict:
    if not SENDGRID_API_KEY:
        raise HTTPException(status_code=500, detail="SENDGRID_API_KEY is not set")
    if not EMAIL_FROM:
        raise HTTPException(status_code=500, detail="EMAIL_FROM is not set")

    message = Mail(
        from_email=EMAIL_FROM,
        to_emails=to_email,
        subject=subject,
        plain_text_content=body_text,
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        resp = sg.send(message)
        return {"ok": True, "sendgrid_status": resp.status_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SendGrid error: {str(e)}")


@app.get("/")
def root():
    return {"status": "AI Marketing Agent is running 🚀"}


@app.post("/lead")
async def create_lead(lead: LeadIn):
    segment = classify_segment(lead.budget)
    label = offer_label(segment)

    subject, body = await generate_email_draft(
        name=lead.name,
        email=str(lead.email),
        company=lead.company,
        budget=lead.budget,
        need=lead.need,
    )

    db = SessionLocal()
    try:
        row = Lead(
            name=lead.name,
            email=str(lead.email),
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
            "draft_subject": row.draft_subject,
            "draft_body": row.draft_body,
            "next_step": "Zatwierdź wysyłkę: POST /lead/{lead_id}/approve (header: x-approval-token)",
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
        rows = db.query(Lead).order_by(Lead.created_at.desc()).limit(limit).all()
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
def approve_and_send(lead_id: int, x_approval_token: Optional[str] = Header(default=None)):
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

        send_result = send_via_sendgrid(row.email, row.draft_subject, row.draft_body)

        row.status = "SENT"
        row.sent_at = datetime.utcnow()
        db.commit()

        return {"ok": True, "lead_id": row.id, "status": row.status, **send_result}
    finally:
        db.close()


@app.post("/sendgrid-test")
def sendgrid_test(to_email: EmailStr):
    return send_via_sendgrid(
        str(to_email),
        "SendGrid test from AI Agent ✅",
        "Jeśli to czytasz, wysyłka działa."
    )
