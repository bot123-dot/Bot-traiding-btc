from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
import os
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta

app = FastAPI()
client = Anthropic()

def obtener_precio():
    url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    respuesta = requests.get(url)
    return float(respuesta.json()["data"]["amount"])

def analisis_ia(precio):
    if precio < 60000:
        zona = "zona de COMPRA (precio bajo)"
    elif precio > 65000:
        zona = "zona de VENTA (precio alto)"
    else:
        zona = "zona neutral (esperar)"
    
    mensaje = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": f"El precio del Bitcoin es ${precio:,.2f} USD y está en {zona}. Dame un análisis de mercado muy breve en 2 frases máximo, en español."
        }]
    )
    return mensaje.content[0].text

def hora_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")

@app.get("/", response_class=HTMLResponse)
def inicio():
    precio = obtener_precio()
    hora = hora_brasil()
    analisis = analisis_ia(precio)

    if precio < 60000:
        decision = "COMPRAR"
        color = "green"
    elif precio > 65000:
        decision = "VENDER"
        color = "red"
    else:
        decision = "ESPERAR"
        color = "orange"

    html = f"""
    <html>
    <head>
        <title>Bot BTC</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{ font-family: Arial; background: #1a1a2e; color: white; text-align: center; padding: 50px; }}
            h1 {{ color: #f0a500; }}
            .precio {{ font-size: 60px; font-weight: bold; margin: 20px; }}
            .decision {{ font-size: 40px; color: {color}; font-weight: bold; }}
            .hora {{ color: #aaa; font-size: 18px; margin-top: 10px; }}
            .analisis {{ background: #16213e; border-left: 4px solid #f0a500; margin: 30px auto; max-width: 600px; padding: 20px; border-radius: 8px; font-size: 18px; line-height: 1.6; text-align: left; }}
            .analisis-titulo {{ color: #f0a500; font-weight: bold; margin-bottom: 10px; }}
        </style>
    </head>
    <body>
        <h1>Bot Trading BTC con IA</h1>
        <div class="precio">${precio:,.2f}</div>
        <div class="decision">{decision}</div>
        <div class="analisis">
            <div class="analisis-titulo">🤖 Análisis IA:</div>
            {analisis}
        </div>
        <div class="hora">Actualizado: {hora} | Se actualiza cada 30 seg</div>
    </body>
    </html>
    """
    return html
