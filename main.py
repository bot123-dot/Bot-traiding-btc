from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import requests
import os
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta

app = FastAPI()
client = Anthropic()

historiales = {"BTC": [], "ETH": [], "SOL": [], "BNB": [], "XRP": []}
visitas = {"total": 0, "BTC": 0, "ETH": 0, "SOL": 0, "BNB": 0, "XRP": 0, "resumen": 0, "about": 0}
ultima_senal_enviada = {"cripto": "", "decision": ""}

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

def obtener_velas_6h(simbolo):
    try:
        url = f"https://api.exchange.coinbase.com/products/{simbolo}/candles?granularity=21600&limit=50"
        respuesta = requests.get(url)
        velas = respuesta.json()
        if isinstance(velas, list) and len(velas) > 0:
            cierres = [v[4] for v in reversed(velas)]
            highs = [v[2] for v in reversed(velas)]
            lows = [v[1] for v in reversed(velas)]
            return cierres, highs, lows
        return [], [], []
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
            return round(lows[i], 2), round(highs[i], 2)
    return None, None

def calcular_confluencias(precio, cierres, highs, lows):
    confluencias = 0
    detalles = []
    rsi_4h = calcular_rsi(cierres)
    mm20 = calcular_mm(cierres, 20)
    mm50 = calcular_mm(cierres, 50)
    estructura = detectar_bos(highs, lows)
    ob_low, ob_high = detectar_order_block(cierres, highs, lows)

    if rsi_4h and rsi_4h < 35:
        confluencias += 1
        detalles.append(f"RSI sobrevendido ({rsi_4h})")
    elif rsi_4h and rsi_4h > 65:
        confluencias += 1
        detalles.append(f"RSI sobrecomprado ({rsi_4h})")

    if "Alcista" in estructura:
        confluencias += 1
        detalles.append("BOS alcista confirmado")
    elif "Bajista" in estructura:
        confluencias += 1
        detalles.append("BOS bajista confirmado")

    if mm20 and mm50:
        if mm20 > mm50 and precio > mm20:
            confluencias += 1
            detalles.append("Precio sobre MM20 y MM50")
        elif mm20 < mm50 and precio < mm20:
            confluencias += 1
            detalles.append("Precio bajo MM20 y MM50")

    if ob_low and ob_high:
        if ob_low <= precio <= ob_high:
            confluencias += 1
            detalles.append(f"Precio en OB ${ob_low:,.2f}-${ob_high:,.2f}")

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

def enviar_telegram(cripto, precio, decision, confluencias, detalles, estructura):
    global ultima_senal_enviada
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        channel = os.getenv("TELEGRAM_CHANNEL_ID")
        if not token or not channel:
            return
        if ultima_senal_enviada["cripto"] == cripto and ultima_senal_enviada["decision"] == decision:
            return
        emoji = "🟢" if decision == "COMPRAR" else "🔴" if decision == "VENDER" else "🟡"
        detalles_txt = "\n".join([f"✅ {d}" for d in detalles])
        mensaje = f"""🤖 *BitMind Signal*

{emoji} *{decision}* — {cripto}/USD
💰 Precio: ${precio:,.2f}
⚡ {confluencias}/4 Confluencias SMC
📊 Estructura: {estructura}

{detalles_txt}

👉 [Ver análisis completo](https://bitmind.app.br)"""
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": channel,
            "text": mensaje,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        })
        ultima_senal_enviada = {"cripto": cripto, "decision": decision}
    except Exception as e:
        print(f"Error Telegram: {e}")

def analisis_ia(cripto, precio, estructura, confluencias, detalles, rsi, idioma):
    lang = "español latinoamericano" if idioma == "es" else "português brasileiro"
    detalles_txt = ", ".join(detalles) if detalles else "sin confluencias claras"
    mensaje = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        system=f"Eres un trader profesional especialista en Smart Money Concepts (SMC). Responde en {lang}. NUNCA uses markdown, asteriscos, almohadillas ni títulos. Solo texto plano y directo.",
        messages=[{
            "role": "user",
            "content": f"{cripto} está en ${precio:,.2f} USD. Estructura: {estructura}. Confluencias SMC ({confluencias}): {detalles_txt}. RSI: {rsi}. Dame un análisis SMC en 3 frases máximo."
        }]
    )
    return mensaje.content[0].text

def hora_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")

def calcular_mm_simple(precios, periodo=7):
    if len(precios) < periodo:
        return None
    return round(sum(precios[-periodo:]) / periodo, 2)

@app.get("/test_telegram")
def test_telegram():
    enviar_telegram("BTC", 65713.12, "VENDER", 3,
        ["RSI sobrecomprado (71.0)", "Precio sobre MM20 y MM50", "Precio en OB $65,607-$66,424"],
        "Lateral")
    return {"status": "Mensaje enviado al canal!"}

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

    cierres, highs, lows = obtener_velas_6h(par["simbolo_cb"])

    if len(cierres) > 15:
        confluencias, detalles, rsi_4h, mm20, mm50, estructura, ob_low, ob_high = calcular_confluencias(precio, cierres, highs, lows)
        decision_key, color, nivel_confluencia = determinar_senal(precio, confluencias, detalles, estructura)
    else:
        confluencias, detalles, rsi_4h, mm20, mm50 = 0, [], None, None, None
        estructura = "Indeterminado"
        ob_low, ob_high = None, None
        decision_key = "esperar"; color = "orange"
        nivel_confluencia = "⚪ Sin datos"

    if confluencias >= 3:
        enviar_telegram(par["nombre"], precio, decision_key.upper(), confluencias, detalles, estructura)

    if lang == "es":
        tendencia_txt = "SUBIENDO ↗" if subiendo else "BAJANDO ↘" if subiendo is not None else "ESTABLE →"
        decisiones = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "ESPERAR"}
        btn_lang = "🇧🇷 Português"; btn_url = f"/?lang=pt&cripto={cripto}"
        label_analisis = "🤖 Análisis SMC con IA"
        label_actualizado = "Actualizado"
        label_cada = "Se actualiza cada 30 seg"
        label_precio = "Precio actual"
        label_indicadores = "Indicadores SMC 6H"
        label_confluencias = "Confluencias"
        label_estructura = "Estructura"
        label_ob = "Order Block"
        label_mm20 = "MM20"
        label_mm50 = "MM50"
        rsi_zona = "Sobrevendido 🟢" if rsi_4h and rsi_4h < 35 else "Sobrecomprado 🔴" if rsi_4h and rsi_4h > 65 else "Neutral 🟡"
    else:
        tendencia_txt = "SUBINDO ↗" if subiendo else "CAINDO ↘" if subiendo is not None else "ESTÁVEL →"
        decisiones = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "AGUARDAR"}
        btn_lang = "🇪🇸 Español"; btn_url = f"/?lang=es&cripto={cripto}"
        label_analisis = "🤖 Análise SMC com IA"
        label_actualizado = "Atualizado"
        label_cada = "Atualiza a cada 30 seg"
        label_precio = "Preço atual"
        label_indicadores = "Indicadores SMC 6H"
        label_confluencias = "Confluências"
        label_estrutura = "Estrutura"
        label_ob = "Order Block"
        label_mm20 = "MM20"
        label_mm50 = "MM50"
        label_estrutura = "Estrutura"
        rsi_zona = "Sobrevendido 🟢" if rsi_4h and rsi_4h < 35 else "Sobrecomprado 🔴" if rsi_4h and rsi_4h > 65 else "Neutro 🟡"

    decision = decisiones[decision_key]
    color_tendencia = "#00ff88" if subiendo else "#ff4444" if subiendo is not None else "orange"
    analisis = analisis_ia(par["nombre"], precio, estructura, confluencias, detalles, rsi_4h, lang)
    labels = [p["hora"] for p in historiales[cripto]]
    valores = lista
    rsi_display = str(rsi_4h) if rsi_4h else "..."
    mm20_display = f"${mm20:,.2f}" if mm20 else "..."
    mm50_display = f"${mm50:,.2f}" if mm50 else "..."
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
            .ind-label {{ font-size: 11px; color: #aaa; text-transform: uppercase; margin-bottom: 8px; text-align: center; }}
            .tab-btn {{ padding: 8px 16px; border-radius: 20px; text-decoration: none; font-weight: bold; font-size: 14px; border: 1px solid #f0a500; }}
            .tab-active {{ background: #f0a500; color: #0d0d1a; }}
            .tab-inactive {{ background: #16213e; color: #f0a500; }}
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
                    <div class="smc-titulo">RSI 6H</div>
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
            cierres, highs, lows = obtener_velas_6h(par["simbolo_cb"])
            if len(cierres) > 15:
                confluencias, detalles, rsi_4h, mm20, mm50, estructura, ob_low, ob_high = calcular_confluencias(precio, cierres, highs, lows)
                decision_key, color, nivel = determinar_senal(precio, confluencias, detalles, estructura)
            else:
                confluencias = 0; color = "orange"; decision_key = "esperar"
            decisiones_es = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "ESPERAR"}
            decisiones_pt = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "AGUARDAR"}
            decision = decisiones_pt[decision_key] if lang == "pt" else decisiones_es[decision_key]
            tend = "↗" if subiendo else "↘" if subiendo is not None else "→"
            tend_color = "#00ff88" if subiendo else "#ff4444" if subiendo is not None else "orange"
            datos.append({"cripto": cripto, "nombre": par["nombre"], "precio": precio, "tend": tend, "tend_color": tend_color, "decision": decision, "color": color, "confluencias": confluencias})
        except:
            pass

    filas = ""
    for d in datos:
        filas += f"""
        <a href="/?lang={lang}&cripto={d['cripto']}" style="text-decoration:none;">
            <div style="background:#16213e;border-radius:12px;padding:15px 20px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;border:1px solid #ffffff11;">
                <div style="font-size:20px;font-weight:bold;color:#f0a500;width:50px;">{d['cripto']}</div>
                <div style="font-size:16px;font-weight:bold;color:white;">${d['precio']:,.2f}</div>
                <div style="font-size:13px;color:#aaa;">{d['confluencias']}/4 ⚡</div>
                <div style="font-size:14px;font-weight:bold;color:{d['color']};border:1px solid {d['color']};padding:4px 10px;border-radius:20px;">{d['decision']}</div>
            </div>
        </a>
        """

    titulo = "Resumen del Mercado" if lang == "es" else "Resumo do Mercado"
    btn_lang = "🇧🇷 Português" if lang == "es" else "🇪🇸 Español"
    btn_url = f"/resumen?lang={'pt' if lang == 'es' else 'es'}"
    home_txt = "← Volver" if lang == "es" else "← Voltar"

    return f"""
    <html>
    <head>
        <title>BitMind — {titulo}</title>
        <meta http-equiv="refresh" content="30;url=/resumen?lang={lang}">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: Arial, sans-serif; background: #0d0d1a; color: white; min-height: 100vh; }}
            .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; text-align: center; border-bottom: 2px solid #f0a500; position: relative; }}
            .logo {{ font-size: 28px; font-weight: bold; color: #f0a500; letter-spacing: 2px; }}
            .logo span {{ color: white; }}
            .lang-btn {{ position: absolute; top: 20px; right: 15px; background: #16213e; border: 1px solid #f0a500; color: #f0a500; padding: 6px 12px; border-radius: 20px; text-decoration: none; font-size: 13px; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px 15px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <a href="{btn_url}" class="lang-btn">{btn_lang}</a>
            <div class="logo">Bit<span>Mind</span></div>
            <div style="font-size:14px;color:#aaa;margin-top:4px;">{titulo}</div>
        </div>
        <div class="container">
            <a href="/?lang={lang}" style="color:#f0a500;font-size:14px;display:block;margin-bottom:15px;">{home_txt}</a>
            {filas}
            <div style="text-align:center;color:#555;font-size:12px;padding:10px;">
                Se actualiza cada 30 seg
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/about", response_class=HTMLResponse)
def about(lang: str = Query("es")):
    global visitas
    visitas["total"] += 1
    visitas["about"] += 1

    btn_lang = "🇧🇷 Português" if lang == "es" else "🇪🇸 Español"
    btn_url = f"/about?lang={'pt' if lang == 'es' else 'es'}"
    home_txt = "← Volver" if lang == "es" else "← Voltar"

    if lang == "es":
        titulo = "¿Qué es BitMind?"
        contenido = """
        <div class="seccion">
            <h2>🤖 ¿Qué es BitMind?</h2>
            <p>BitMind es una plataforma de señales de trading con Inteligencia Artificial que analiza el mercado de criptomonedas en tiempo real, combinando Smart Money Concepts (SMC) y machine learning para darte ventaja en tus decisiones.</p>
        </div>
        <div class="seccion">
            <h2>📈 La Tendencia — El Rey del Trading</h2>
            <p>Los traders profesionales dicen: <em>"La tendencia es tu amiga"</em>. El 80% de las ganancias en trading vienen de operar a favor de la tendencia, nunca contra ella.</p>
            <div class="card-tend alcista">
                <div class="tend-titulo">📈 Tendencia Alcista — SUBIENDO</div>
                <p>El precio hace máximos y mínimos cada vez más altos. Es el mejor momento para comprar y mantener posición.</p>
            </div>
            <div class="card-tend bajista">
                <div class="tend-titulo">📉 Tendencia Bajista — BAJANDO</div>
                <p>El precio hace máximos y mínimos cada vez más bajos. Momento de vender o mantenerse fuera del mercado.</p>
            </div>
            <div class="card-tend lateral">
                <div class="tend-titulo">➡️ Tendencia Lateral — ESTABLE</div>
                <p>El precio oscila entre dos niveles sin dirección clara. Esperá una ruptura antes de entrar al mercado.</p>
            </div>
        </div>
        <div class="seccion">
            <h2>📊 Smart Money Concepts (SMC)</h2>
            <div class="indicador">
                <div class="ind-nombre">BOS — Break of Structure</div>
                <p>Ruptura de estructura que confirma la dirección del mercado.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">Order Blocks (OB)</div>
                <p>Zonas donde los institucionales acumularon posiciones. Son las áreas de mayor probabilidad de rebote.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">⚡ Sistema de Confluencias</div>
                <div class="ind-reglas">
                    <span class="regla compra">3-4 confluencias → SEÑAL FUERTE 🟢</span>
                    <span class="regla neutral">2 confluencias → SEÑAL MEDIA 🟡</span>
                    <span class="regla venta">0-1 confluencias → ESPERAR ⚪</span>
                </div>
            </div>
        </div>
        <div class="seccion aviso">
            <h2>⚠️ Aviso Legal</h2>
            <p>BitMind es una herramienta informativa. Las señales NO son asesoría financiera. Invertir en criptomonedas implica riesgo de pérdida de capital.</p>
        </div>
        """
    else:
        titulo = "O que é BitMind?"
        contenido = """
        <div class="seccion">
            <h2>🤖 O que é BitMind?</h2>
            <p>BitMind é uma plataforma de sinais de trading com Inteligência Artificial que analisa o mercado de criptomoedas em tempo real, combinando Smart Money Concepts (SMC) e machine learning.</p>
        </div>
        <div class="seccion">
            <h2>📈 A Tendência — O Rei do Trading</h2>
            <p>Os traders profissionais dizem: <em>"A tendência é sua amiga"</em>. 80% dos lucros no trading vêm de operar a favor da tendência.</p>
            <div class="card-tend alcista">
                <div class="tend-titulo">📈 Tendência de Alta — SUBINDO</div>
                <p>O preço faz máximas e mínimas cada vez mais altas. É o melhor momento para comprar.</p>
            </div>
            <div class="card-tend bajista">
                <div class="tend-titulo">📉 Tendência de Baixa — CAINDO</div>
                <p>O preço faz máximas e mínimas cada vez mais baixas. Momento de vender ou ficar fora.</p>
            </div>
            <div class="card-tend lateral">
                <div class="tend-titulo">➡️ Tendência Lateral — ESTÁVEL</div>
                <p>O preço oscila sem direção clara. Aguarde uma ruptura antes de entrar.</p>
            </div>
        </div>
        <div class="seccion">
            <h2>📊 Smart Money Concepts (SMC)</h2>
            <div class="indicador">
                <div class="ind-nombre">BOS — Break of Structure</div>
                <p>Ruptura de estrutura que confirma a direção do mercado.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">Order Blocks (OB)</div>
                <p>Zonas onde os institucionais acumularam posições. Áreas de maior probabilidade de rebote.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">⚡ Sistema de Confluências</div>
                <div class="ind-reglas">
                    <span class="regla compra">3-4 confluências → SINAL FORTE 🟢</span>
                    <span class="regla neutral">2 confluências → SINAL MÉDIO 🟡</span>
                    <span class="regla venta">0-1 confluências → AGUARDAR ⚪</span>
                </div>
            </div>
        </div>
        <div class="seccion aviso">
            <h2>⚠️ Aviso Legal</h2>
            <p>BitMind é uma ferramenta informativa. Os sinais NÃO são assessoria financeira. Investir em criptomoedas implica risco de perda de capital.</p>
        </div>
        """

    return f"""
    <html>
    <head>
        <title>BitMind — {titulo}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: Arial, sans-serif; background: #0d0d1a; color: white; min-height: 100vh; }}
            .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; text-align: center; border-bottom: 2px solid #f0a500; position: relative; }}
            .logo {{ font-size: 28px; font-weight: bold; color: #f0a500; letter-spacing: 2px; }}
            .logo span {{ color: white; }}
            .lang-btn {{ position: absolute; top: 20px; right: 15px; background: #16213e; border: 1px solid #f0a500; color: #f0a500; padding: 6px 12px; border-radius: 20px; text-decoration: none; font-size: 13px; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px 15px; }}
            .seccion {{ background: #16213e; border-radius: 16px; padding: 20px; margin-bottom: 15px; border: 1px solid #ffffff11; }}
            .seccion h2 {{ color: #f0a500; font-size: 18px; margin-bottom: 12px; }}
            .seccion p {{ font-size: 15px; line-height: 1.7; color: #ddd; margin-bottom: 10px; }}
            .seccion em {{ color: #f0a500; font-style: italic; }}
            .card-tend {{ border-radius: 12px; padding: 15px; margin: 10px 0; }}
            .alcista {{ background: #0d2b1a; border-left: 4px solid #00ff88; }}
            .bajista {{ background: #2b0d0d; border-left: 4px solid #ff4444; }}
            .lateral {{ background: #2b2b0d; border-left: 4px solid orange; }}
            .tend-titulo {{ font-weight: bold; font-size: 16px; margin-bottom: 8px; }}
            .alcista .tend-titulo {{ color: #00ff88; }}
            .bajista .tend-titulo {{ color: #ff4444; }}
            .lateral .tend-titulo {{ color: orange; }}
            .indicador {{ background: #0d0d2b; border-radius: 12px; padding: 15px; margin: 10px 0; }}
            .ind-nombre {{ color: #f0a500; font-weight: bold; font-size: 15px; margin-bottom: 8px; }}
            .ind-reglas {{ display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }}
            .regla {{ padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: bold; }}
            .compra {{ background: #0d2b1a; color: #00ff88; }}
            .venta {{ background: #2b0d0d; color: #ff4444; }}
            .neutral {{ background: #2b2b0d; color: orange; }}
            .aviso {{ border-left: 4px solid #ff4444; }}
            .aviso h2 {{ color: #ff4444; }}
        </style>
    </head>
    <body>
        <div class="header">
            <a href="{btn_url}" class="lang-btn">{btn_lang}</a>
            <div class="logo">Bit<span>Mind</span></div>
            <div style="font-size:14px;color:#aaa;margin-top:4px;">{titulo}</div>
        </div>
        <div class="container">
            <a href="/?lang={lang}" style="color:#f0a500;font-size:14px;display:block;margin-bottom:15px;">{home_txt}</a>
            {contenido}
        </div>
    </body>
    </html>
    """


@app.get("/stats", response_class=HTMLResponse)
def stats():
    return f"""
    <html>
    <head>
        <title>BitMind — Stats</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="30">
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: Arial, sans-serif; background: #0d0d1a; color: white; min-height: 100vh; }}
            .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; text-align: center; border-bottom: 2px solid #f0a500; }}
            .logo {{ font-size: 28px; font-weight: bold; color: #f0a500; letter-spacing: 2px; }}
            .logo span {{ color: white; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px 15px; }}
            .total {{ background: #16213e; border-radius: 16px; padding: 25px; text-align: center; margin-bottom: 15px; border: 2px solid #f0a500; }}
            .total-num {{ font-size: 60px; font-weight: bold; color: #f0a500; }}
            .total-txt {{ font-size: 14px; color: #aaa; margin-top: 5px; }}
            .card {{ background: #16213e; border-radius: 12px; padding: 15px 20px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; border: 1px solid #ffffff11; }}
            .card-nombre {{ font-size: 18px; font-weight: bold; color: #f0a500; }}
            .card-num {{ font-size: 24px; font-weight: bold; color: white; }}
            .aviso {{ text-align: center; color: #555; font-size: 12px; padding: 15px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">Bit<span>Mind</span></div>
            <div style="font-size:14px;color:#aaa;margin-top:4px;">Dashboard de Visitas</div>
        </div>
        <div class="container">
            <a href="/" style="color:#f0a500;font-size:14px;display:block;margin-bottom:15px;">← Volver</a>
            <div class="total">
                <div class="total-num">{visitas['total']}</div>
                <div class="total-txt">Total de visitas</div>
            </div>
            <div class="card"><div class="card-nombre">₿ Bitcoin</div><div class="card-num">{visitas['BTC']}</div></div>
            <div class="card"><div class="card-nombre">Ξ Ethereum</div><div class="card-num">{visitas['ETH']}</div></div>
            <div class="card"><div class="card-nombre">◎ Solana</div><div class="card-num">{visitas['SOL']}</div></div>
            <div class="card"><div class="card-nombre">⬡ BNB</div><div class="card-num">{visitas['BNB']}</div></div>
            <div class="card"><div class="card-nombre">✕ XRP</div><div class="card-num">{visitas['XRP']}</div></div>
            <div class="card"><div class="card-nombre">📊 Resumen</div><div class="card-num">{visitas['resumen']}</div></div>
            <div class="card"><div class="card-nombre">ℹ️ About</div><div class="card-num">{visitas['about']}</div></div>
            <div class="aviso">⚠️ Las visitas se reinician cuando el servidor duerme</div>
        </div>
    </body>
    </html>
    """
    @app.get("/test-telegram")
async def test_telegram():
    try:
        for cripto in PARES:
            simbolo = PARES[cripto]["simbolo"]
            precio = obtener_precio(simbolo)
            cierres, highs, lows = obtener_velas_6h(simbolo)
            if len(cierres) >= 20:
                confluencias, detalles, rsi, mm20, mm50 = calcular_confluencias(cierres, highs, lows, precio)
                decision, color, estructura = determinar_senal(precio, confluencias, detalles, cierres)
                enviar_telegram(cripto, precio, decision, confluencias, estructura, detalles)
        return {"status": "ok", "mensaje": "Señales enviadas"}
    except Exception as e:
        return {"status": "error", "detalle": str(e)}

import asyncio

async def loop_analisis():
    while True:
        try:
            for cripto in PARES:
                simbolo = PARES[cripto]["simbolo"]
                precio = obtener_precio(simbolo)
                cierres, highs, lows = obtener_velas_6h(simbolo)
                if len(cierres) >= 20:
                    confluencias, detalles, rsi, mm20, mm50 = calcular_confluencias(cierres, highs, lows, precio)
                    decision, color, estructura = determinar_senal(precio, confluencias, detalles, cierres)
                    if confluencias >= 3:
                        enviar_telegram(cripto, precio, decision, confluencias, estructura, detalles)
        except Exception as e:
            print(f"Error en loop: {e}")
        await asyncio.sleep(21600)

@app.on_event("startup")
async def iniciar_scheduler():
    asyncio.create_task(loop_analisis())
