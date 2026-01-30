import os
import httpx

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

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
        "LOW": "Poza zakresem budżetu (spróbuj upsell / doprecyzowanie)",
        "EVENT_STREAM": "Event / stream (od 1000 zł)",
        "VIDEO": "Film / wideo (od 2000 zł)",
        "RETAINER": "Abonament (od 2500 zł / miesiąc)",
    }.get(segment, "Nieznany segment")

async def generate_email_draft(*, name: str, email: str, company: str | None, budget: int, need: str) -> tuple[str, str]:
    """
    Zwraca: (subject, body)
    """
    if not OPENAI_API_KEY:
        # Fallback bez AI (żeby system działał nawet bez klucza)
        subj = f"Propozycja współpracy – {company or name}"
        body = (
            f"Cześć {name},\n\n"
            f"Dzięki za wiadomość. Wstępnie brzmi to jak: {need}.\n"
            f"Budżet, który podałeś/aś: {budget} zł.\n\n"
            f"Podeślę 2–3 warianty zakresu – czy pasuje rozmowa 10 minut dziś lub jutro?\n\n"
            f"Pozdrawiam\nKrzysztof"
        )
        return subj, body

    system = (
        "Jesteś doświadczonym sprzedawcą usług produkcji wideo i streamingu B2B (premium, ale ludzko). "
        "Piszesz po polsku, konkretnie, bez korpo-tonu. "
        "Tworzysz mail, który brzmi jak od człowieka: krótko, celnie, z jednym pytaniem domykającym. "
        "Nie obiecuj rzeczy bez ustalenia zakresu."
    )

    segment = classify_segment(budget)
    label = offer_label(segment)

    user = f"""
Dane leada:
- Imię: {name}
- Email: {email}
- Firma: {company or "brak"}
- Potrzeba: {need}
- Budżet: {budget} PLN
Segment: {label}

Zadanie:
1) Wygeneruj temat maila (max 60 znaków).
2) Napisz treść maila (120–200 słów), z:
   - 1 zdaniem personalizacji (odnieś się do 'Potrzeba')
   - 2–3 krótkimi wariantami (Basic/Standard/Premium) opisanymi jednym zdaniem każdy (bez cen, tylko zakres)
   - 1 pytaniem domykającym (termin + doprecyzowanie)
3) Zakończ podpisem: "Krzysztof | ElectronicArt".
Zwróć wynik w formacie:
SUBJECT: ...
BODY:
...
"""

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

    # proste parsowanie
    subject = "Propozycja współpracy"
    body = text
    if "SUBJECT:" in text and "BODY:" in text:
        subject = text.split("SUBJECT:", 1)[1].split("BODY:", 1)[0].strip()
        body = text.split("BODY:", 1)[1].strip()
    return subject, body
