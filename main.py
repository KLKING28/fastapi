from fastapi import FastAPI
from pydantic import BaseModel
import os

app = FastAPI(title="AI Marketing Agent")

# ===== MODELE =====

class Lead(BaseModel):
    name: str
    email: str
    company: str | None = None
    budget: int
    need: str


# ===== LOGIKA AGENTA =====

def classify_offer(budget: int) -> str:
    if budget < 1000:
        return "Poza zakresem – edukacja / upsell"
    elif budget < 2000:
        return "Event / stream (od 1000 zł)"
    elif budget < 2500:
        return "Film / wideo (od 2000 zł)"
    else:
        return "Abonament (od 2500 zł / miesiąc)"


# ===== ENDPOINTY =====

@app.get("/")
def root():
    return {"status": "AI Marketing Agent is running 🚀"}


@app.post("/lead")
def process_lead(lead: Lead):
    offer = classify_offer(lead.budget)

    return {
        "lead": lead.name,
        "email": lead.email,
        "recommended_offer": offer,
        "next_step": "Skontaktuj się z klientem lub wyślij ofertę automatycznie"
    }
