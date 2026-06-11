from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import requests
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta

app = FastAPI()
client = Anthropic()

historiales = {"BTC": [], "ETH": [], "SOL": [], "BNB": [], "XRP": []}

PARES = {
    "BTC": {"nombre": "Bitcoin", "simbolo": "BTC-USD", "comprar": 60000, "vender": 65000},
    "ETH": {"nombre": "Ethereum", "simbolo": "ETH-USD", "comprar": 2800, "vender": 3500},
    "SOL": {"nombre": "Solana", "simbolo": "SOL-USD", "comprar": 120, "vender": 180},
    "BNB": {"nombre": "BNB", "simbolo": "BNB-USD", "comprar": 500, "vender": 650},
    "XRP": {"nombre": "XRP", "simbolo": "XRP-USD", "comprar": 0.5, "vender": 0.8},
}

def obtener_precio(simbolo):
    url = f"https://api.coinbase.com/v2/prices/{simbolo}/spot"
    respuesta = requests.get(url)
    return float(respuesta.json()["data"]["amount"])

def calcular_rsi(precios, periodo=14):
    if len(precios) < periodo + 1:
        return None
    ganancias, perdidas = [], []
    for i in range(1, periodo + 1):
        diff = precios[-i] - precios[-i-1]
        if diff > 0:
            ganancias.append(diff); perdidas.append(0)
        else:
            ganancias.append(0); perdidas.append(abs(diff))
    avg_g = sum(ganancias) / periodo
    avg_p = sum(perdidas) / periodo
    if avg_p == 0:
        return 100
    return round(100 - (100 / (1 + avg_g/avg_p)), 1)

def calcular_mm(precios, periodo=7):
    if len(precios) < periodo:
        return None
    return round(sum(precios[-periodo:]) / periodo, 2)

def analisis_ia(cripto, precio, tendencia, rsi, idioma):
    lang = "español" if idioma == "es" else "português brasileiro"
    rsi_txt = f"RSI={rsi}" if rsi else "RSI insuficiente"
    mensaje = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=120,
        system=f"Eres un analista de criptomonedas. Responde SIEMPRE en exactamente 2 frases cortas en {lang}. NUNCA uses markdown, asteriscos, almohadillas ni títulos. Solo texto plano.",
        messages=[{
            "role": "user",
            "content": f"{cripto} está en ${precio:,.2f} USD, tendencia {tendencia}, {rsi_txt}."
        }]
    )
    return mensaje.content[0].text

def hora_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")

@app.get("/", response_class=HTMLResponse)
def inicio(lang: str = Query("es"), cripto: str = Query("BTC")):
    if cripto not in PARES:
        cripto = "BTC"

    par = PARES[cripto]
    precio = obtener_precio(par["simbolo"])
    hora = hora_brasil()

    historiales[cripto].append({"hora": hora, "precio": precio})
    if len(historiales[cripto]) > 48:
        historiales[cripto] = historiales[cripto][-48:]

    lista = [p["precio"] for p in historiales[cripto]]
    rsi = calcular_rsi(lista)
    mm7 = calcular_mm(lista)

    if len(historiales[cripto]) > 1:
        diff = precio - historiales[cripto][-2]["precio"]
        subiendo = diff > 0
    else:
        subiendo = None

    if rsi is not None:
        if rsi < 30:
            decision_key = "comprar"; color = "#00ff88"
        elif rsi > 70:
