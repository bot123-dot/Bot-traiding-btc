from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
from datetime import datetime, timezone, timedelta

app = FastAPI()

def obtener_precio():
    url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    respuesta = requests.get(url)
    return float(respuesta.json()["data"]["amount"])

def hora_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")

@app.get("/", response_class=HTMLResponse)
def inicio():
    precio = obtener_precio()
    hora = hora_brasil()
    if precio < 60000:
        decision = "COMPRAR"
        color = "green"
    elif precio > 65000:
        decision = "VENDER"
        color = "red"
    else:
        decision = "ESPERAR"
        color = "orange"
    return f"""
    <html>
    <head><title>Bot BTC</title>
    <style>
    body{{font-family:Arial;background:#1a1a2e;color:white;text-align:center;padding:50px}}
    h1{{color:#f0a500}}
    .precio{{font-size:60px;font-weight:bold}}
    .decision{{font-size:40px;color:{color};font-weight:bold}}
    .hora{{color:#aaa;font-size:20px}}
    </style></head>
    <body>
    <h1>Bot Trading BTC con IA</h1>
    <div class="precio">${precio:,.2f}</div>
    <div class="decision">{decision}</div>
    <div class="hora">Actualizado: {hora}</div>
    </body></html>
    """
