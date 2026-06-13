import stripe
import os
from database import update_user_plan

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PLANES = {
    "pro": {
        "stripe_price_id": "price_PRO_ID_AQUI",
        "valor_mp": 2900,
        "nombre": "BitMind Pro"
    },
    "trader": {
        "stripe_price_id": "price_TRADER_ID_AQUI",
        "valor_mp": 7900,
        "nombre": "BitMind Trader"
    }
}

# ── STRIPE ──────────────────────────────────────────

def crear_sesion_stripe(email: str, plan: str):
    precio = PLANES[plan]["stripe_price_id"]
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        customer_email=email,
        line_items=[{"price": precio, "quantity": 1}],
        success_url="https://bitmind.app.br/sucesso?plan=" + plan,
        cancel_url="https://bitmind.app.br/cancelado",
    )
    return session.url

def webhook_stripe(payload, sig_header):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception:
        return False
    if event["type"] == "checkout.session.completed":
        data = event["data"]["object"]
        email = data.get("customer_email")
        plan = data.get("metadata", {}).get("plan", "pro")
        if email:
            update_user_plan(email, plan)
    return True

# ── MERCADO PAGO ─────────────────────────────────────

def crear_pago_mp(email: str, plan: str):
    import mercadopago
    sdk = mercadopago.SDK(os.getenv("MP_ACCESS_TOKEN"))
    datos = PLANES[plan]
    preference_data = {
        "items": [{
            "title": datos["nombre"],
            "quantity": 1,
            "unit_price": datos["valor_mp"] / 100,
            "currency_id": "BRL"
        }],
        "payer": {"email": email},
        "back_urls": {
            "success": "https://bitmind.app.br/sucesso?plan=" + plan,
            "failure": "https://bitmind.app.br/cancelado"
        },
        "auto_return": "approved"
    }
    result = sdk.preference().create(preference_data)
    return result["response"]["init_point"]
