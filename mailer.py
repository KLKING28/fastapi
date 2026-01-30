import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")


def send_email(to_email: str, subject: str, content: str):
    """
    Wysyła mail przez SendGrid
    """
    if not SENDGRID_API_KEY:
        raise ValueError("Brak SENDGRID_API_KEY w zmiennych środowiskowych")

    if not EMAIL_FROM:
        raise ValueError("Brak EMAIL_FROM w zmiennych środowiskowych")

    message = Mail(
        from_email=EMAIL_FROM,
        to_emails=to_email,
        subject=subject,
        html_content=content
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        return {
            "status": "sent",
            "status_code": response.status_code
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def send_offer_email(to_email: str, client_name: str, offer_html: str):
    subject = f"{client_name}, przygotowaliśmy coś specjalnie dla Ciebie"
    return send_email(
        to_email=to_email,
        subject=subject,
        content=offer_html
    )


def send_internal_notification(content: str):
    """
    Mail do Ciebie (np. lead, status, wynik)
    """
    owner_email = EMAIL_FROM
    subject = "🤖 AI Marketing Agent – nowa aktywność"
    return send_email(
        to_email=owner_email,
        subject=subject,
        content=content
    )
