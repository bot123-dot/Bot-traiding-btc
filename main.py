from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta

app = FastAPI()
client = Anthropic()

historial_precios = []

def obtener_precio():
    url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    respuesta = requests.get(url)
    return float(respuesta.json()["data"]["amount"])

def analisis_ia(precio, tendencia):
    mensaje = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=150,
        messages=[{
    "role": "user",
    "content": f"El precio del Bitcoin es ${precio:,.2f} USD con tendencia {tendencia}. Dame exactamente 2 frases de análisis en español. Sin títulos, sin markdown, sin asteriscos. Solo texto limpio."
}]
    )
    return mensaje.content[0].text

def hora_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")

@app.get("/", response_class=HTMLResponse)
def inicio():
    global historial_precios
    precio = obtener_precio()
    hora = hora_brasil()

    historial_precios.append({"hora": hora, "precio": precio})
    if len(historial_precios) > 48:
        historial_precios = historial_precios[-48:]

    if len(historial_precios) > 1:
        diferencia = precio - historial_precios[-2]["precio"]
        tendencia = "SUBIENDO ↗" if diferencia > 0 else "BAJANDO ↘"
        color_tendencia = "#00ff88" if diferencia > 0 else "#ff4444"
    else:
        tendencia = "ESTABLE →"
        color_tendencia = "orange"

    if precio < 60000:
        decision = "COMPRAR"
        color = "#00ff88"
    elif precio > 65000:
        decision = "VENDER"
        color = "#ff4444"
    else:
        decision = "ESPERAR"
        color = "orange"

    analisis = analisis_ia(precio, tendencia)

    labels = [p["hora"] for p in historial_precios]
    valores = [p["precio"] for p in historial_precios]

    html = f"""
    <html>
    <head>
        <title>Bot BTC</title>
        <meta http-equiv="refresh" content="30">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {{ font-family: Arial; background: #1a1a2e; color: white; text-align: center; padding: 30px; }}
            h1 {{ color: #f0a500; font-size: 24px; }}
            .precio {{ font-size: 50px; font-weight: bold; margin: 10px; }}
            .decision {{ font-size: 36px; color: {color}; font-weight: bold; }}
            .tendencia {{ font-size: 20px; color: {color_tendencia}; margin: 5px; }}
            .analisis {{ background: #16213e; border-left: 4px solid #f0a500; margin: 20px auto; max-width: 600px; padding: 15px; border-radius: 8px; font-size: 16px; line-height: 1.6; text-align: left; }}
            .analisis-titulo {{ color: #f0a500; font-weight: bold; margin-bottom: 8px; }}
            .grafico {{ max-width: 700px; margin: 20px auto; background: #16213e; padding: 20px; border-radius: 12px; }}
            .hora {{ color: #aaa; font-size: 16px; margin-top: 15px; }}
        </style>
    </head>
    <body>
        <h1>🤖 Bot Trading BTC con IA</h1>
        <div class="precio">${precio:,.2f}</div>
        <div class="tendencia">{tendencia}</div>
        <div class="decision">{decision}</div>

        <div class="grafico">
            <canvas id="graficoBTC"></canvas>
        </div>

        <div class="analisis">
            <div class="analisis-titulo">🤖 Análisis IA:</div>
            {analisis}
        </div>
        <div class="hora">Actualizado: {hora} | Se actualiza cada 30 seg</div>

        <script>
            const ctx = document.getElementById('graficoBTC').getContext('2d');
            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {labels},
                    datasets: [{{
                        label: 'BTC/USD',
                        data: {valores},
                        borderColor: '#f0a500',
                        backgroundColor: 'rgba(240, 165, 0, 0.1)',
                        borderWidth: 2,
                        pointRadius: 3,
                        fill: true,
                        tension: 0.4
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{
                        legend: {{ labels: {{ color: 'white' }} }}
                    }},
                    scales: {{
                        x: {{ ticks: {{ color: '#aaa', maxTicksLimit: 6 }} }},
                        y: {{ ticks: {{ color: '#aaa' }} }}
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """
    return html
