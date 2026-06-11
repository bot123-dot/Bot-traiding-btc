from fastapi import FastAPI, Query
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

def analisis_ia(precio, tendencia, idioma):
    lang = "español" if idioma == "es" else "português brasileiro"
    mensaje = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        system=f"Eres un analista de criptomonedas. Responde SIEMPRE en exactamente 2 frases cortas en {lang}. NUNCA uses markdown, asteriscos, almohadillas ni títulos. Solo texto plano.",
        messages=[{
            "role": "user",
            "content": f"Bitcoin está en ${precio:,.2f} USD con tendencia {tendencia}."
        }]
    )
    return mensaje.content[0].text

def hora_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")

@app.get("/", response_class=HTMLResponse)
def inicio(lang: str = Query("es")):
    global historial_precios
    precio = obtener_precio()
    hora = hora_brasil()

    historial_precios.append({"hora": hora, "precio": precio})
    if len(historial_precios) > 48:
        historial_precios = historial_precios[-48:]

    if len(historial_precios) > 1:
        diferencia = precio - historial_precios[-2]["precio"]
        subiendo = diferencia > 0
    else:
        subiendo = None

    if lang == "es":
        tendencia_txt = "SUBIENDO ↗" if subiendo else "BAJANDO ↘" if subiendo is not None else "ESTABLE →"
        if precio < 60000:
            decision = "COMPRAR"; color = "#00ff88"
        elif precio > 65000:
            decision = "VENDER"; color = "#ff4444"
        else:
            decision = "ESPERAR"; color = "orange"
        btn_lang = "🇧🇷 Português"
        btn_url = "/?lang=pt"
        label_analisis = "🤖 Análisis IA"
        label_actualizado = "Actualizado"
        label_cada = "Se actualiza cada 30 seg"
        label_precio = "Precio actual"
    else:
        tendencia_txt = "SUBINDO ↗" if subiendo else "CAINDO ↘" if subiendo is not None else "ESTÁVEL →"
        if precio < 60000:
            decision = "COMPRAR"; color = "#00ff88"
        elif precio > 65000:
            decision = "VENDER"; color = "#ff4444"
        else:
            decision = "AGUARDAR"; color = "orange"
        btn_lang = "🇪🇸 Español"
        btn_url = "/?lang=es"
        label_analisis = "🤖 Análise IA"
        label_actualizado = "Atualizado"
        label_cada = "Atualiza a cada 30 seg"
        label_precio = "Preço atual"

    color_tendencia = "#00ff88" if subiendo else "#ff4444" if subiendo is not None else "orange"
    analisis = analisis_ia(precio, tendencia_txt, lang)
    labels = [p["hora"] for p in historial_precios]
    valores = [p["precio"] for p in historial_precios]

    html = f"""
    <html>
    <head>
        <title>CryptoMind</title>
        <meta http-equiv="refresh" content="30;url=/?lang={lang}">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: 'Arial', sans-serif; background: #0d0d1a; color: white; min-height: 100vh; }}
            .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; text-align: center; border-bottom: 2px solid #f0a500; }}
            .logo {{ font-size: 28px; font-weight: bold; color: #f0a500; letter-spacing: 2px; }}
            .logo span {{ color: white; }}
            .tagline {{ font-size: 12px; color: #aaa; margin-top: 4px; }}
            .lang-btn {{ position: absolute; top: 20px; right: 15px; background: #16213e; border: 1px solid #f0a500; color: #f0a500; padding: 6px 12px; border-radius: 20px; text-decoration: none; font-size: 13px; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px 15px; }}
            .precio-card {{ background: #16213e; border-radius: 16px; padding: 25px; text-align: center; margin-bottom: 15px; border: 1px solid #ffffff11; }}
            .label-precio {{ font-size: 12px; color: #aaa; text-transform: uppercase; letter-spacing: 1px; }}
            .precio {{ font-size: 48px; font-weight: bold; margin: 8px 0; }}
            .tendencia {{ font-size: 18px; color: {color_tendencia}; font-weight: bold; }}
            .decision {{ font-size: 32px; font-weight: bold; color: {color}; margin-top: 8px; padding: 8px 20px; border: 2px solid {color}; border-radius: 30px; display: inline-block; }}
            .grafico-card {{ background: #16213e; border-radius: 16px; padding: 20px; margin-bottom: 15px; border: 1px solid #ffffff11; }}
            .analisis-card {{ background: #16213e; border-left: 4px solid #f0a500; border-radius: 0 16px 16px 0; padding: 15px 20px; margin-bottom: 15px; }}
            .analisis-titulo {{ color: #f0a500; font-weight: bold; font-size: 14px; margin-bottom: 8px; }}
            .analisis-texto {{ font-size: 15px; line-height: 1.6; color: #ddd; }}
            .footer {{ text-align: center; color: #555; font-size: 12px; padding: 10px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <a href="{btn_url}" class="lang-btn">{btn_lang}</a>
            <div class="logo">Crypto<span>Mind</span></div>
            <div class="tagline">AI-Powered Bitcoin Trading Signal</div>
        </div>

        <div class="container">
            <div class="precio-card">
                <div class="label-precio">{label_precio}</div>
                <div class="precio">${precio:,.2f}</div>
                <div class="tendencia">{tendencia_txt}</div>
                <div style="margin-top:12px">
                    <span class="decision">{decision}</span>
                </div>
            </div>

            <div class="grafico-card">
                <canvas id="graficoBTC"></canvas>
            </div>

            <div class="analisis-card">
                <div class="analisis-titulo">{label_analisis}:</div>
                <div class="analisis-texto">{analisis}</div>
            </div>

            <div class="footer">
                {label_actualizado}: {hora} | {label_cada}
            </div>
        </div>

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
                        backgroundColor: 'rgba(240,165,0,0.1)',
                        borderWidth: 2,
                        pointRadius: 3,
                        fill: true,
                        tension: 0.4
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ labels: {{ color: 'white', font: {{ size: 12 }} }} }} }},
                    scales: {{
                        x: {{ ticks: {{ color: '#aaa', maxTicksLimit: 5 }} }},
                        y: {{ ticks: {{ color: '#aaa' }} }}
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """
    return html
