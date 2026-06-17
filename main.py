from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import requests
from anthropic import Anthropic
import os
from datetime import datetime, timezone, timedelta

app = FastAPI()
client = Anthropic()

historiales = {"BTC": [], "ETH": [], "SOL": [], "BNB": [], "XRP": []}
visitas = {"total": 0, "BTC": 0, "ETH": 0, "SOL": 0, "BNB": 0, "XRP": 0, "resumen": 0, "about": 0}

PARES = {
    "BTC": {"nombre": "Bitcoin", "simbolo": "BTC-USD", "simbolo_cb": "BTC-USD"},
    "ETH": {"nombre": "Ethereum", "simbolo": "ETH-USD", "simbolo_cb": "ETH-USD"},
    "SOL": {"nombre": "Solana", "simbolo": "SOL-USD", "simbolo_cb": "SOL-USD"},
    "BNB": {"nombre": "BNB", "simbolo": "BNB-USD", "simbolo_cb": "BNB-USD"},
    "XRP": {"nombre": "XRP", "simbolo": "XRP-USD", "simbolo_cb": "XRP-USD"},
}

def obtener_precio(simbolo):
    url = f"https://api.coinbase.com/v2/prices/{simbolo}/spot"
    respuesta = requests.get(url)
    return float(respuesta.json()["data"]["amount"])

def obtener_velas_4h(simbolo):
    try:
        url = f"https://api.exchange.coinbase.com/products/{simbolo}/candles?granularity=21600&limit=50"
        respuesta = requests.get(url)
        velas = respuesta.json()
        # Formato: [time, low, high, open, close, volume]
        cierres = [v[4] for v in reversed(velas)]
        highs = [v[2] for v in reversed(velas)]
        lows = [v[1] for v in reversed(velas)]
        return cierres, highs, lows
    except:
        return [], [], []

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

def calcular_mm(precios, periodo=20):
    if len(precios) < periodo:
        return None
    return round(sum(precios[-periodo:]) / periodo, 2)

def detectar_bos(highs, lows):
    if len(highs) < 5:
        return "Indeterminado"
    ultimo_max = max(highs[-5:-1])
    ultimo_min = min(lows[-5:-1])
    precio_actual = highs[-1]
    if precio_actual > ultimo_max:
        return "Alcista (BOS ↗)"
    elif precio_actual < ultimo_min:
        return "Bajista (BOS ↘)"
    return "Lateral"

def detectar_order_block(cierres, highs, lows):
    if len(cierres) < 10:
        return None, None
    for i in range(len(cierres)-2, max(len(cierres)-10, 0), -1):
        if cierres[i] < cierres[i-1] and cierres[i+1] > cierres[i]:
            ob_high = highs[i]
            ob_low = lows[i]
            return round(ob_low, 2), round(ob_high, 2)
    return None, None

def calcular_confluencias(precio, cierres, highs, lows):
    confluencias = 0
    detalles = []

    rsi_4h = calcular_rsi(cierres)
    mm20 = calcular_mm(cierres, 20)
    mm50 = calcular_mm(cierres, 50)
    estructura = detectar_bos(highs, lows)
    ob_low, ob_high = detectar_order_block(cierres, highs, lows)

    # Confluencia 1: RSI
    if rsi_4h and rsi_4h < 35:
        confluencias += 1
        detalles.append(f"RSI sobrevendido ({rsi_4h})")
    elif rsi_4h and rsi_4h > 65:
        confluencias += 1
        detalles.append(f"RSI sobrecomprado ({rsi_4h})")

    # Confluencia 2: Estructura
    if "Alcista" in estructura:
        confluencias += 1
        detalles.append("BOS alcista confirmado")
    elif "Bajista" in estructura:
        confluencias += 1
        detalles.append("BOS bajista confirmado")

    # Confluencia 3: Media Móvil
    if mm20 and mm50:
        if mm20 > mm50 and precio > mm20:
            confluencias += 1
            detalles.append("Precio sobre MM20 y MM50")
        elif mm20 < mm50 and precio < mm20:
            confluencias += 1
            detalles.append("Precio bajo MM20 y MM50")

    # Confluencia 4: Order Block
    if ob_low and ob_high:
        if ob_low <= precio <= ob_high:
            confluencias += 1
            detalles.append(f"Precio en OB ${ob_low}-${ob_high}")

    return confluencias, detalles, rsi_4h, mm20, mm50, estructura, ob_low, ob_high

def determinar_senal(precio, confluencias, detalles, estructura):
    if confluencias >= 3:
        if "Alcista" in estructura or any("sobrevendido" in d for d in detalles):
            return "comprar", "#00ff88", "🟢 ALTA CONFLUENCIA"
        elif "Bajista" in estructura or any("sobrecomprado" in d for d in detalles):
            return "vender", "#ff4444", "🔴 ALTA CONFLUENCIA"
    elif confluencias == 2:
        return "esperar", "orange", "🟡 CONFLUENCIA MEDIA"
    return "esperar", "orange", "⚪ BAJA CONFLUENCIA"

def analisis_ia(cripto, precio, estructura, confluencias, detalles, rsi, idioma):
    lang = "español latinoamericano" if idioma == "es" else "português brasileiro"
    detalles_txt = ", ".join(detalles) if detalles else "sin confluencias claras"
    mensaje = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        system=f"Eres un trader profesional especialista en Smart Money Concepts (SMC). Responde en {lang}. NUNCA uses markdown, asteriscos, almohadillas ni títulos. Solo texto plano y directo.",
        messages=[{
            "role": "user",
            "content": f"{cripto} está en ${precio:,.2f} USD. Estructura: {estructura}. Confluencias SMC detectadas ({confluencias}): {detalles_txt}. RSI 4H: {rsi}. Dame un análisis SMC en 3 frases máximo."
        }]
    )
    return mensaje.content[0].text

def hora_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")

def calcular_mm_simple(precios, periodo=7):
    if len(precios) < periodo:
        return None
    return round(sum(precios[-periodo:]) / periodo, 2)

@app.get("/", response_class=HTMLResponse)
def inicio(lang: str = Query("es"), cripto: str = Query("BTC")):
    global visitas
    if cripto not in PARES:
        cripto = "BTC"

    visitas["total"] += 1
    visitas[cripto] += 1

    par = PARES[cripto]
    precio = obtener_precio(par["simbolo"])
    hora = hora_brasil()

    historiales[cripto].append({"hora": hora, "precio": precio})
    if len(historiales[cripto]) > 48:
        historiales[cripto] = historiales[cripto][-48:]

    lista = [p["precio"] for p in historiales[cripto]]
    mm7 = calcular_mm_simple(lista)

    if len(historiales[cripto]) > 1:
        diff = precio - historiales[cripto][-2]["precio"]
        subiendo = diff > 0
    else:
        subiendo = None

    # Obtener datos 4H y calcular confluencias SMC
    cierres, highs, lows = obtener_velas_4h(par["simbolo_cb"])

    if len(cierres) > 15:
        confluencias, detalles, rsi_4h, mm20, mm50, estructura, ob_low, ob_high = calcular_confluencias(precio, cierres, highs, lows)
        decision_key, color, nivel_confluencia = determinar_senal(precio, confluencias, detalles, estructura)
    else:
        confluencias, detalles, rsi_4h, mm20, mm50 = 0, [], None, None, None
        estructura = "Indeterminado"
        ob_low, ob_high = None, None
        decision_key = "esperar"; color = "orange"
        nivel_confluencia = "⚪ Sin datos"

    if lang == "es":
        tendencia_txt = "SUBIENDO ↗" if subiendo else "BAJANDO ↘" if subiendo is not None else "ESTABLE →"
        decisiones = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "ESPERAR"}
        btn_lang = "🇧🇷 Português"; btn_url = f"/?lang=pt&cripto={cripto}"
        label_analisis = "🤖 Análisis SMC con IA"
        label_actualizado = "Actualizado"
        label_cada = "Se actualiza cada 30 seg"
        label_precio = "Precio actual"
        label_indicadores = "Indicadores SMC 4H"
        label_confluencias = "Confluencias"
        label_estructura = "Estructura"
        label_ob = "Order Block"
        label_mm20 = "MM20"
        label_mm50 = "MM50"
    else:
        tendencia_txt = "SUBINDO ↗" if subiendo else "CAINDO ↘" if subiendo is not None else "ESTÁVEL →"
        decisiones = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "AGUARDAR"}
        btn_lang = "🇪🇸 Español"; btn_url = f"/?lang=es&cripto={cripto}"
        label_analisis = "🤖 Análise SMC com IA"
        label_actualizado = "Atualizado"
        label_cada = "Atualiza a cada 30 seg"
        label_precio = "Preço atual"
        label_indicadores = "Indicadores SMC 4H"
        label_confluencias = "Confluências"
        label_estructura = "Estrutura"
        label_ob = "Order Block"
        label_mm20 = "MM20"
        label_mm50 = "MM50"

    decision = decisiones[decision_key]
    color_tendencia = "#00ff88" if subiendo else "#ff4444" if subiendo is not None else "orange"
    analisis = analisis_ia(par["nombre"], precio, estructura, confluencias, detalles, rsi_4h, lang)

    labels = [p["hora"] for p in historiales[cripto]]
    valores = lista
    rsi_display = str(rsi_4h) if rsi_4h else "..."
    mm20_display = f"${mm20:,.2f}" if mm20 else "..."
    mm50_display = f"${mm50:,.2f}" if mm50 else "..."
    mm7_display = f"${mm7:,.2f}" if mm7 else "..."
    ob_display = f"${ob_low:,.2f} - ${ob_high:,.2f}" if ob_low and ob_high else "..."
    confluencias_color = "#00ff88" if confluencias >= 3 else "orange" if confluencias == 2 else "#aaa"

    html = f"""
    <html>
    <head>
        <title>BitMind</title>
        <meta http-equiv="refresh" content="30;url=/?lang={lang}&cripto={cripto}">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: Arial, sans-serif; background: #0d0d1a; color: white; min-height: 100vh; }}
            .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; text-align: center; border-bottom: 2px solid #f0a500; position: relative; }}
            .logo {{ font-size: 28px; font-weight: bold; color: #f0a500; letter-spacing: 2px; }}
            .logo span {{ color: white; }}
            .tagline {{ font-size: 12px; color: #aaa; margin-top: 4px; }}
            .lang-btn {{ position: absolute; top: 20px; right: 15px; background: #16213e; border: 1px solid #f0a500; color: #f0a500; padding: 6px 12px; border-radius: 20px; text-decoration: none; font-size: 13px; }}
            .tabs {{ display: flex; justify-content: center; gap: 8px; padding: 15px; flex-wrap: wrap; background: #0d0d1a; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px 15px; }}
            .precio-card {{ background: #16213e; border-radius: 16px; padding: 25px; text-align: center; margin-bottom: 15px; border: 1px solid #ffffff11; }}
            .label-precio {{ font-size: 12px; color: #aaa; text-transform: uppercase; letter-spacing: 1px; }}
            .precio {{ font-size: 48px; font-weight: bold; margin: 8px 0; }}
            .tendencia {{ font-size: 18px; color: {color_tendencia}; font-weight: bold; }}
            .decision {{ font-size: 32px; font-weight: bold; color: {color}; margin-top: 8px; padding: 8px 20px; border: 2px solid {color}; border-radius: 30px; display: inline-block; }}
            .nivel {{ font-size: 13px; color: {confluencias_color}; margin-top: 8px; font-weight: bold; }}
            .smc-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; }}
            .smc-card {{ background: #16213e; border-radius: 12px; padding: 12px; text-align: center; border: 1px solid #ffffff11; }}
            .smc-titulo {{ font-size: 10px; color: #aaa; text-transform: uppercase; margin-bottom: 5px; }}
            .smc-valor {{ font-size: 15px; font-weight: bold; color: #f0a500; }}
            .confluencias-card {{ background: #16213e; border-radius: 12px; padding: 15px; margin-bottom: 15px; border: 2px solid {confluencias_color}; }}
            .conf-titulo {{ font-size: 12px; color: #aaa; text-transform: uppercase; margin-bottom: 8px; }}
            .conf-num {{ font-size: 36px; font-weight: bold; color: {confluencias_color}; display: inline-block; margin-right: 10px; }}
            .conf-detalle {{ font-size: 13px; color: #ddd; margin-top: 5px; }}
            .grafico-card {{ background: #16213e; border-radius: 16px; padding: 20px; margin-bottom: 15px; border: 1px solid #ffffff11; }}
            .analisis-card {{ background: #16213e; border-left: 4px solid #f0a500; border-radius: 0 16px 16px 0; padding: 15px 20px; margin-bottom: 15px; }}
            .analisis-titulo {{ color: #f0a500; font-weight: bold; font-size: 14px; margin-bottom: 8px; }}
            .analisis-texto {{ font-size: 15px; line-height: 1.6; color: #ddd; }}
            .footer {{ text-align: center; color: #555; font-size: 12px; padding: 10px; }}
            .tab-btn {{ padding: 8px 16px; border-radius: 20px; text-decoration: none; font-weight: bold; font-size: 14px; border: 1px solid #f0a500; }}
            .tab-active {{ background: #f0a500; color: #0d0d1a; }}
            .tab-inactive {{ background: #16213e; color: #f0a500; }}
            .ind-label {{ font-size: 11px; color: #aaa; text-transform: uppercase; margin-bottom: 8px; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="header">
            <a href="{btn_url}" class="lang-btn">{btn_lang}</a>
            <div class="logo">Bit<span>Mind</span></div>
            <div class="tagline">AI-Powered SMC Crypto Trading Signal</div>
        </div>

        <div class="tabs">
            <a href="/?lang={lang}&cripto=BTC" class="tab-btn {'tab-active' if cripto=='BTC' else 'tab-inactive'}">BTC</a>
            <a href="/?lang={lang}&cripto=ETH" class="tab-btn {'tab-active' if cripto=='ETH' else 'tab-inactive'}">ETH</a>
            <a href="/?lang={lang}&cripto=SOL" class="tab-btn {'tab-active' if cripto=='SOL' else 'tab-inactive'}">SOL</a>
            <a href="/?lang={lang}&cripto=BNB" class="tab-btn {'tab-active' if cripto=='BNB' else 'tab-inactive'}">BNB</a>
            <a href="/?lang={lang}&cripto=XRP" class="tab-btn {'tab-active' if cripto=='XRP' else 'tab-inactive'}">XRP</a>
            <a href="/resumen?lang={lang}" class="tab-btn tab-inactive">📊</a>
            <a href="/about?lang={lang}" class="tab-btn tab-inactive">ℹ️</a>
        </div>

        <div class="container">
            <div class="precio-card">
                <div class="label-precio">{label_precio} — {par["nombre"]}</div>
                <div class="precio">${precio:,.2f}</div>
                <div class="tendencia">{tendencia_txt}</div>
                <div style="margin-top:12px">
                    <span class="decision">{decision}</span>
                </div>
                <div class="nivel">{nivel_confluencia}</div>
            </div>

            <div class="ind-label">{label_indicadores}</div>

            <div class="confluencias-card">
                <div class="conf-titulo">{label_confluencias} SMC</div>
                <span class="conf-num">{confluencias}/4</span>
                <span style="font-size:13px;color:#aaa;">{estructura}</span>
                {''.join([f'<div class="conf-detalle">✅ {d}</div>' for d in detalles]) if detalles else '<div class="conf-detalle" style="color:#555;">Sin confluencias detectadas aún</div>'}
            </div>

            <div class="smc-grid">
                <div class="smc-card">
                    <div class="smc-titulo">RSI 4H</div>
                    <div class="smc-valor">{rsi_display}</div>
                </div>
                <div class="smc-card">
                    <div class="smc-titulo">{label_ob}</div>
                    <div class="smc-valor" style="font-size:12px">{ob_display}</div>
                </div>
                <div class="smc-card">
                    <div class="smc-titulo">{label_mm20}</div>
                    <div class="smc-valor" style="font-size:13px">{mm20_display}</div>
                </div>
                <div class="smc-card">
                    <div class="smc-titulo">{label_mm50}</div>
                    <div class="smc-valor" style="font-size:13px">{mm50_display}</div>
                </div>
            </div>

            <div class="grafico-card">
                <canvas id="graficoCripto"></canvas>
            </div>

            <div class="analisis-card">
                <div class="analisis-titulo">{label_analisis}:</div>
                <div class="analisis-texto">{analisis}</div>
            </div>

            <div style="text-align:center; margin-bottom:15px;">
                <a href="https://wa.me/?text=🤖 BitMind SMC - Crypto Trading con IA%0A💰 {par['nombre']}: ${precio:,.2f}%0A📊 Señal: {decision} ({confluencias}/4 confluencias)%0A👉 https://bitmind.app.br"
                   target="_blank"
                   style="background:#25D366;color:white;padding:12px 25px;border-radius:30px;text-decoration:none;font-size:16px;font-weight:bold;">
                    📲 Compartir en WhatsApp
                </a>
            </div>

            <div class="footer">
                {label_actualizado}: {hora} | {label_cada}
            </div>
        </div>

        <script>
            const ctx = document.getElementById('graficoCripto').getContext('2d');
            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {labels},
                    datasets: [{{
                        label: '{cripto}/USD',
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


@app.get("/resumen", response_class=HTMLResponse)
def resumen(lang: str = Query("es")):
    global visitas
    visitas["total"] += 1
    visitas["resumen"] += 1

    datos = []
    for cripto, par in PARES.items():
        try:
            precio = obtener_precio(par["simbolo"])
            hist = historiales[cripto]
            if len(hist) > 1:
                diff = precio - hist[-1]["precio"]
                subiendo = diff > 0
            else:
                subiendo = None

            cierres, highs, lows = obtener_velas_4h(par["simbolo_cb"])
            if len(cierres) > 15:
                confluencias, detalles, rsi_4h, mm20, mm50, estructura, ob_low, ob_high = calcular_confluencias(precio, cierres, highs, lows)
                decision_key, color, nivel = determinar_senal(precio, confluencias, detalles, estructura)
            else:
                confluencias = 0; color = "orange"
                decision_key = "esperar"

            decisiones_es = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "ESPERAR"}
            decisiones_pt = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "AGUARDAR"}
            decision = decisiones_pt[decision_key] if lang == "pt" else decisiones_es[decision_key]

            tend = "↗" if subiendo else "↘" if subiendo is not None else "→"
            tend_color = "#00ff88" if subiendo else "#ff4444" if subiendo is not None else "orange"
            datos.append({"cripto": cripto, "nombre": par["nombre"], "precio": precio, "tend": tend, "tend_color": tend_color, "decision": decision, "color": color, "confluencias": confluencias})
        except:
            pass

    filas = ""
    
