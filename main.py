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

def detectar_choch(highs, lows, cierres):
    """CHoCH real con swing highs/lows — detecta cambio de tendencia"""
    if len(highs) < 10:
        return "Indeterminado", False
    h = highs[-10:]
    l = lows[-10:]
    swing_highs = []
    swing_lows = []
    for i in range(1, len(h)-1):
        if h[i] > h[i-1] and h[i] > h[i+1]:
            swing_highs.append((i, h[i]))
        if l[i] < l[i-1] and l[i] < l[i+1]:
            swing_lows.append((i, l[i]))
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        # Fallback a BOS simple
        ultimo_max = max(highs[-5:-1])
        ultimo_min = min(lows[-5:-1])
        precio_actual = cierres[-1]
        if precio_actual > ultimo_max:
            return "Alcista (BOS ↗)", False
        elif precio_actual < ultimo_min:
            return "Bajista (BOS ↘)", False
        return "Lateral", False
    ultimo_sh = swing_highs[-1][1]
    penultimo_sh = swing_highs[-2][1]
    ultimo_sl = swing_lows[-1][1]
    penultimo_sl = swing_lows[-2][1]
    precio_actual = cierres[-1]
    choch_detectado = False
    if precio_actual > ultimo_sh and ultimo_sh > penultimo_sh:
        estructura = "Alcista (BOS ↗)"
    elif precio_actual < ultimo_sl and ultimo_sl < penultimo_sl:
        estructura = "Bajista (BOS ↘)"
    elif precio_actual > ultimo_sh and ultimo_sh < penultimo_sh:
        estructura = "CHoCH Alcista 🔄"
        choch_detectado = True
    elif precio_actual < ultimo_sl and ultimo_sl > penultimo_sl:
        estructura = "CHoCH Bajista 🔄"
        choch_detectado = True
    else:
        estructura = "Lateral"
    return estructura, choch_detectado

def detectar_order_block(cierres, highs, lows):
    if len(cierres) < 10:
        return None, None
    for i in range(len(cierres)-2, max(len(cierres)-10, 0), -1):
        if cierres[i] < cierres[i-1] and cierres[i+1] > cierres[i]:
            return round(lows[i], 2), round(highs[i], 2)
    return None, None

def detectar_fvg(highs, lows, cierres):
    """Fair Value Gap — desequilibrio institucional entre 3 velas"""
    if len(cierres) < 5:
        return None, None, None
    for i in range(len(cierres)-3, max(len(cierres)-12, 1), -1):
        if lows[i+1] > highs[i-1]:
            return "Alcista", round(highs[i-1], 2), round(lows[i+1], 2)
        elif highs[i+1] < lows[i-1]:
            return "Bajista", round(highs[i+1], 2), round(lows[i-1], 2)
    return None, None, None

def calcular_sl_tp(precio, estructura, ob_low, ob_high):
    """Stop Loss y Take Profit dinámicos basados en SMC"""
    sl = tp1 = tp2 = None
    if "Alcista" in estructura or "CHoCH Alcista" in estructura:
        sl = round(ob_low * 0.998, 2) if ob_low else round(precio * 0.98, 2)
        riesgo = precio - sl
        tp1 = round(precio + (riesgo * 1.5), 2)
        tp2 = round(precio + (riesgo * 3), 2)
    elif "Bajista" in estructura or "CHoCH Bajista" in estructura:
        sl = round(ob_high * 1.002, 2) if ob_high else round(precio * 1.02, 2)
        riesgo = sl - precio
        tp1 = round(precio - (riesgo * 1.5), 2)
        tp2 = round(precio - (riesgo * 3), 2)
    return sl, tp1, tp2

def calcular_confluencias(precio, cierres, highs, lows):
    confluencias = 0
    detalles = []

    rsi_4h = calcular_rsi(cierres)
    mm20 = calcular_mm(cierres, 20)
    mm50 = calcular_mm(cierres, 50)
    estructura, choch = detectar_choch(highs, lows, cierres)
    ob_low, ob_high = detectar_order_block(cierres, highs, lows)
    fvg_tipo, fvg_low, fvg_high = detectar_fvg(highs, lows, cierres)

    # Confluencia 1: RSI
    if rsi_4h and rsi_4h < 35:
        confluencias += 1
        detalles.append(f"RSI sobrevendido ({rsi_4h})")
    elif rsi_4h and rsi_4h > 65:
        confluencias += 1
        detalles.append(f"RSI sobrecomprado ({rsi_4h})")

    # Confluencia 2: Estructura BOS / CHoCH
    if "Alcista" in estructura:
        confluencias += 1
        detalles.append("CHoCH Alcista — cambio de tendencia 🔄" if choch else "BOS alcista confirmado")
    elif "Bajista" in estructura:
        confluencias += 1
        detalles.append("CHoCH Bajista — cambio de tendencia 🔄" if choch else "BOS bajista confirmado")

    # Confluencia 3: Media Móvil
    if mm20 and mm50:
        if mm20 > mm50 and precio > mm20:
            confluencias += 1
            detalles.append("Precio sobre MM20 y MM50")
        elif mm20 < mm50 and precio < mm20:
            confluencias += 1
            detalles.append("Precio bajo MM20 y MM50")

    # Confluencia 4: Order Block o Fair Value Gap
    if ob_low and ob_high and ob_low <= precio <= ob_high:
        confluencias += 1
        detalles.append(f"Precio en OB ${ob_low}-${ob_high}")
    elif fvg_tipo and fvg_low and fvg_high and fvg_low <= precio <= fvg_high:
        confluencias += 1
        detalles.append(f"FVG {fvg_tipo} detectado ${fvg_low}-${fvg_high}")

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
                <p>Ruptura de estructura que confirma la dirección del mercado. El precio rompe un máximo o mínimo previo, indicando la tendencia dominante.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">Order Blocks (OB)</div>
                <p>Zonas donde los institucionales (bancos, fondos) acumularon posiciones. Son las áreas de mayor probabilidad de rebote del precio.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">⚡ Sistema de Confluencias</div>
                <p>BitMind analiza 4 factores simultáneamente. Cuantas más confluencias, más fuerte es la señal:</p>
                <div class="ind-reglas">
                    <span class="regla compra">3-4 confluencias → SEÑAL FUERTE 🟢</span>
                    <span class="regla neutral">2 confluencias → SEÑAL MEDIA 🟡</span>
                    <span class="regla venta">0-1 confluencias → ESPERAR ⚪</span>
                </div>
            </div>
        </div>
        <div class="seccion">
            <h2>🚦 ¿Qué significan las señales?</h2>
            <div class="senal compra-card">🟢 COMPRAR — Alta confluencia alcista confirmada</div>
            <div class="senal venta-card">🔴 VENDER — Alta confluencia bajista confirmada</div>
            <div class="senal espera-card">🟡 ESPERAR — Confluencia insuficiente, aguardar</div>
        </div>
        <div class="seccion aviso">
            <h2>⚠️ Aviso Legal</h2>
            <p>BitMind es una herramienta informativa basada en análisis técnico e inteligencia artificial. Las señales NO son asesoría financiera. Toda decisión de inversión es responsabilidad del usuario. Invertir en criptomonedas implica riesgo de pérdida de capital.</p>
        </div>
        """
    else:
        titulo = "O que é BitMind?"
        contenido = """
        <div class="seccion">
            <h2>🤖 O que é BitMind?</h2>
            <p>BitMind é uma plataforma de sinais de trading com Inteligência Artificial que analisa o mercado de criptomoedas em tempo real, combinando Smart Money Concepts (SMC) e machine learning para te dar vantagem nas suas decisões.</p>
        </div>
        <div class="seccion">
            <h2>📈 A Tendência — O Rei do Trading</h2>
            <p>Os traders profissionais dizem: <em>"A tendência é sua amiga"</em>. 80% dos lucros no trading vêm de operar a favor da tendência, nunca contra ela.</p>
            <div class="card-tend alcista">
                <div class="tend-titulo">📈 Tendência de Alta — SUBINDO</div>
                <p>O preço faz máximas e mínimas cada vez mais altas. É o melhor momento para comprar e manter posição.</p>
            </div>
            <div class="card-tend bajista">
                <div class="tend-titulo">📉 Tendência de Baixa — CAINDO</div>
                <p>O preço faz máximas e mínimas cada vez mais baixas. Momento de vender ou ficar fora do mercado.</p>
            </div>
            <div class="card-tend lateral">
                <div class="tend-titulo">➡️ Tendência Lateral — ESTÁVEL</div>
                <p>O preço oscila entre dois níveis sem direção clara. Aguarde uma ruptura antes de entrar no mercado.</p>
            </div>
        </div>
        <div class="seccion">
            <h2>📊 Smart Money Concepts (SMC)</h2>
            <div class="indicador">
                <div class="ind-nombre">BOS — Break of Structure</div>
                <p>Ruptura de estrutura que confirma a direção do mercado. O preço rompe uma máxima ou mínima anterior, indicando a tendência dominante.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">Order Blocks (OB)</div>
                <p>Zonas onde os institucionais (bancos, fundos) acumularam posições. São as áreas de maior probabilidade de rebote do preço.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">⚡ Sistema de Confluências</div>
                <p>BitMind analisa 4 fatores simultaneamente. Quanto mais confluências, mais forte é o sinal:</p>
                <div class="ind-reglas">
                    <span class="regla compra">3-4 confluências → SINAL FORTE 🟢</span>
                    <span class="regla neutral">2 confluências → SINAL MÉDIO 🟡</span>
                    <span class="regla venta">0-1 confluências → AGUARDAR ⚪</span>
                </div>
            </div>
        </div>
        <div class="seccion">
            <h2>🚦 O que significam os sinais?</h2>
            <div class="senal compra-card">🟢 COMPRAR — Alta confluência alcista confirmada</div>
            <div class="senal venta-card">🔴 VENDER — Alta confluência baixista confirmada</div>
            <div class="senal espera-card">🟡 AGUARDAR — Confluência insuficiente, esperar</div>
        </div>
        <div class="seccion aviso">
            <h2>⚠️ Aviso Legal</h2>
            <p>BitMind é uma ferramenta informativa baseada em análise técnica e inteligência artificial. Os sinais NÃO são assessoria financeira. Toda decisão de investimento é responsabilidade do usuário. Investir em criptomoedas implica risco de perda de capital.</p>
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
            .senal {{ padding: 12px 16px; border-radius: 12px; margin: 8px 0; font-weight: bold; font-size: 15px; }}
            .compra-card {{ background: #0d2b1a; color: #00ff88; border: 1px solid #00ff88; }}
            .venta-card {{ background: #2b0d0d; color: #ff4444; border: 1px solid #ff4444; }}
            .espera-card {{ background: #2b2b0d; color: orange; border: 1px solid orange; }}
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


import asyncio

ultima_senal_enviada = {"cripto": "", "decision": ""}

def enviar_telegram(cripto, precio, decision, confluencias, estructura, detalles):
    global ultima_senal_enviada
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        channel = os.getenv("TELEGRAM_CHANNEL_ID")
        if not token or not channel:
            print("ERROR: Variables TELEGRAM_BOT_TOKEN o TELEGRAM_CHANNEL_ID no configuradas")
            return
        if ultima_senal_enviada["cripto"] == cripto and ultima_senal_enviada["decision"] == decision:
            return
        emoji = "🟢" if decision == "COMPRAR" else "🔴"
        detalles_txt = "\n".join([f"✅ {d}" for d in detalles])
        # Calcular SL/TP dinámico
        ob_low = ob_high = None
        for d in detalles:
            if "OB $" in d:
                try:
                    partes = d.replace("Precio en OB $","").split("-$")
                    ob_low = float(partes[0].replace(",",""))
                    ob_high = float(partes[1].replace(",",""))
                except:
                    pass
        sl, tp1, tp2 = calcular_sl_tp(precio, estructura, ob_low, ob_high)
        sl_txt = f"\n🛑 *Stop Loss:* ${sl:,.2f}" if sl else ""
        tp_txt = f"\n🎯 *TP1:* ${tp1:,.2f} | *TP2:* ${tp2:,.2f}" if tp1 and tp2 else ""
        choch_txt = "\n🔄 *CHoCH detectado — posible reversión*" if "CHoCH" in estructura else ""
        mensaje = f"""🤖 *BitMind Signal*

{emoji} *{decision}* — {cripto}/USD
💰 *Precio:* ${precio:,.2f}
⚡ *{confluencias}/4* Confluencias SMC
📊 *Estructura:* {estructura}{choch_txt}

{detalles_txt}{sl_txt}{tp_txt}

👉 [Ver análisis completo](https://bitmind.app.br)"""
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": channel,
            "text": mensaje,
            "parse_mode": "Markdown"
        })
        ultima_senal_enviada = {"cripto": cripto, "decision": decision}
        print(f"✅ Señal enviada a Telegram: {cripto} {decision}")
    except Exception as e:
        print(f"Error enviando Telegram: {e}")



@app.get("/landing", response_class=HTMLResponse)
async def landing_page():
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BitMind — Sinais SMC em Tempo Real</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

  :root {
    --black: #080B10;
    --surface: #0E1117;
    --card: #141920;
    --border: #1E2732;
    --green: #00FF88;
    --green-dim: #00CC6A;
    --red: #FF4444;
    --gold: #FFB800;
    --white: #F0F4F8;
    --muted: #6B7A8D;
    --font-display: 'Space Mono', monospace;
    --font-body: 'Space Grotesk', sans-serif;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--black);
    color: var(--white);
    font-family: var(--font-body);
    line-height: 1.6;
    overflow-x: hidden;
  }

  /* ── TICKER ── */
  .ticker {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 8px 0;
    overflow: hidden;
    white-space: nowrap;
  }
  .ticker-inner {
    display: inline-block;
    animation: ticker 30s linear infinite;
  }
  .ticker-inner span {
    font-family: var(--font-display);
    font-size: 11px;
    color: var(--muted);
    margin: 0 32px;
    letter-spacing: 0.05em;
  }
  .ticker-inner span b { color: var(--green); }
  .ticker-inner span.red b { color: var(--red); }
  @keyframes ticker {
    from { transform: translateX(0); }
    to { transform: translateX(-50%); }
  }

  /* ── NAV ── */
  nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 24px;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    background: rgba(8,11,16,0.95);
    backdrop-filter: blur(12px);
    z-index: 100;
  }
  .logo {
    font-family: var(--font-display);
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .logo span { color: var(--green); }
  nav a {
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
    font-weight: 500;
    transition: color 0.2s;
  }
  nav a:hover { color: var(--white); }
  .nav-links { display: flex; gap: 24px; align-items: center; }
  .btn-nav {
    background: var(--green);
    color: var(--black) !important;
    padding: 8px 18px;
    border-radius: 6px;
    font-weight: 700 !important;
    font-size: 13px !important;
  }

  /* ── HERO ── */
  .hero {
    padding: 80px 24px 64px;
    text-align: center;
    position: relative;
    overflow: hidden;
  }
  .hero::before {
    content: '';
    position: absolute;
    top: -100px;
    left: 50%;
    transform: translateX(-50%);
    width: 600px;
    height: 600px;
    background: radial-gradient(circle, rgba(0,255,136,0.06) 0%, transparent 70%);
    pointer-events: none;
  }
  .hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(0,255,136,0.08);
    border: 1px solid rgba(0,255,136,0.2);
    border-radius: 100px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 600;
    color: var(--green);
    margin-bottom: 32px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .hero-badge::before {
    content: '';
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.8); }
  }
  .hero h1 {
    font-family: var(--font-display);
    font-size: clamp(32px, 8vw, 64px);
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.03em;
    margin-bottom: 24px;
  }
  .hero h1 em {
    font-style: normal;
    color: var(--green);
  }
  .hero p {
    font-size: clamp(16px, 3vw, 20px);
    color: var(--muted);
    max-width: 560px;
    margin: 0 auto 48px;
  }
  .hero-cta {
    display: flex;
    gap: 16px;
    justify-content: center;
    flex-wrap: wrap;
  }
  .btn-primary {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: var(--green);
    color: var(--black);
    padding: 14px 28px;
    border-radius: 8px;
    font-weight: 700;
    font-size: 15px;
    text-decoration: none;
    transition: transform 0.2s, box-shadow 0.2s;
  }
  .btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(0,255,136,0.25);
  }
  .btn-secondary {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: transparent;
    color: var(--white);
    padding: 14px 28px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 15px;
    text-decoration: none;
    border: 1px solid var(--border);
    transition: border-color 0.2s;
  }
  .btn-secondary:hover { border-color: var(--muted); }

  /* ── SIGNAL PREVIEW ── */
  .signal-preview {
    margin: 64px auto 0;
    max-width: 360px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    text-align: left;
    position: relative;
  }
  .signal-preview::before {
    content: '🤖 BitMind Signal';
    display: block;
    font-family: var(--font-display);
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 16px;
  }
  .signal-header {
    font-size: 22px;
    font-weight: 700;
    margin-bottom: 16px;
  }
  .signal-header .buy { color: var(--green); }
  .signal-row {
    display: flex;
    justify-content: space-between;
    font-size: 14px;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
  }
  .signal-row:last-child { border-bottom: none; }
  .signal-row .label { color: var(--muted); }
  .signal-row .value { font-weight: 600; font-family: var(--font-display); }
  .confluencia-bar {
    display: flex;
    gap: 6px;
    margin-top: 4px;
  }
  .confluencia-bar span {
    width: 28px;
    height: 6px;
    border-radius: 3px;
    background: var(--green);
  }
  .confluencia-bar span.empty {
    background: var(--border);
  }
  .signal-tag {
    position: absolute;
    top: -12px;
    right: 20px;
    background: var(--green);
    color: var(--black);
    font-size: 11px;
    font-weight: 700;
    padding: 4px 12px;
    border-radius: 100px;
    letter-spacing: 0.05em;
  }

  /* ── STATS ── */
  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: var(--border);
    margin: 64px 0 0;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
  }
  .stat {
    background: var(--black);
    padding: 32px 24px;
    text-align: center;
  }
  .stat-num {
    font-family: var(--font-display);
    font-size: 36px;
    font-weight: 700;
    color: var(--green);
    line-height: 1;
    margin-bottom: 8px;
  }
  .stat-label {
    font-size: 13px;
    color: var(--muted);
    font-weight: 500;
  }

  /* ── SECTION ── */
  section {
    padding: 80px 24px;
    max-width: 900px;
    margin: 0 auto;
  }
  .section-label {
    font-family: var(--font-display);
    font-size: 11px;
    color: var(--green);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 16px;
  }
  .section-title {
    font-family: var(--font-display);
    font-size: clamp(24px, 5vw, 40px);
    font-weight: 700;
    line-height: 1.2;
    margin-bottom: 16px;
    letter-spacing: -0.02em;
  }
  .section-sub {
    color: var(--muted);
    font-size: 16px;
    max-width: 520px;
    margin-bottom: 48px;
  }

  /* ── SMC FEATURES ── */
  .features {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
  }
  .feature-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    transition: border-color 0.2s;
  }
  .feature-card:hover { border-color: rgba(0,255,136,0.3); }
  .feature-icon {
    font-size: 28px;
    margin-bottom: 16px;
  }
  .feature-card h3 {
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 700;
    margin-bottom: 8px;
    letter-spacing: -0.01em;
  }
  .feature-card p {
    font-size: 14px;
    color: var(--muted);
    line-height: 1.5;
  }

  /* ── PLANS ── */
  .plans {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
    margin-top: 0;
  }
  .plan-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px 24px;
    position: relative;
    transition: border-color 0.2s, transform 0.2s;
  }
  .plan-card:hover { transform: translateY(-4px); }
  .plan-card.featured {
    border-color: var(--green);
    background: linear-gradient(135deg, rgba(0,255,136,0.05), var(--card));
  }
  .plan-badge {
    position: absolute;
    top: -12px;
    left: 24px;
    background: var(--green);
    color: var(--black);
    font-size: 11px;
    font-weight: 700;
    padding: 4px 14px;
    border-radius: 100px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .plan-name {
    font-family: var(--font-display);
    font-size: 13px;
    color: var(--muted);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 12px;
  }
  .plan-price {
    font-family: var(--font-display);
    font-size: 40px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 4px;
  }
  .plan-price span {
    font-size: 16px;
    font-weight: 400;
    color: var(--muted);
  }
  .plan-period {
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 24px;
  }
  .plan-features {
    list-style: none;
    margin-bottom: 32px;
  }
  .plan-features li {
    font-size: 14px;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .plan-features li:last-child { border-bottom: none; }
  .plan-features li::before {
    content: '✓';
    color: var(--green);
    font-weight: 700;
    flex-shrink: 0;
  }
  .plan-features li.locked::before { content: '✗'; color: var(--muted); }
  .plan-features li.locked { color: var(--muted); }
  .btn-plan {
    display: block;
    text-align: center;
    padding: 12px;
    border-radius: 8px;
    font-weight: 700;
    font-size: 14px;
    text-decoration: none;
    transition: all 0.2s;
  }
  .btn-plan.green {
    background: var(--green);
    color: var(--black);
  }
  .btn-plan.green:hover { box-shadow: 0 4px 20px rgba(0,255,136,0.3); }
  .btn-plan.outline {
    border: 1px solid var(--border);
    color: var(--white);
  }
  .btn-plan.outline:hover { border-color: var(--muted); }

  /* ── BILINGUAL NOTE ── */
  .bilingual {
    text-align: center;
    font-size: 13px;
    color: var(--muted);
    margin-top: 16px;
  }

  /* ── HOW IT WORKS ── */
  .steps {
    display: grid;
    gap: 16px;
  }
  .step {
    display: flex;
    gap: 20px;
    align-items: flex-start;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
  }
  .step-num {
    font-family: var(--font-display);
    font-size: 13px;
    color: var(--green);
    font-weight: 700;
    flex-shrink: 0;
    padding-top: 2px;
  }
  .step h3 {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 4px;
  }
  .step p { font-size: 14px; color: var(--muted); }

  /* ── CTA FINAL ── */
  .cta-final {
    text-align: center;
    padding: 80px 24px;
    background: var(--surface);
    border-top: 1px solid var(--border);
  }
  .cta-final h2 {
    font-family: var(--font-display);
    font-size: clamp(24px, 5vw, 40px);
    font-weight: 700;
    margin-bottom: 16px;
    letter-spacing: -0.02em;
  }
  .cta-final p { color: var(--muted); margin-bottom: 40px; font-size: 16px; }

  /* ── FOOTER ── */
  footer {
    background: var(--black);
    border-top: 1px solid var(--border);
    padding: 32px 24px;
    text-align: center;
    font-size: 13px;
    color: var(--muted);
  }
  footer a { color: var(--muted); text-decoration: none; }
  footer a:hover { color: var(--white); }

  @media (max-width: 600px) {
    .stats { grid-template-columns: 1fr; }
    .nav-links { gap: 12px; }
    .nav-links a:not(.btn-nav) { display: none; }
  }
</style>
</head>
<body>

<!-- TICKER -->
<div class="ticker">
  <div class="ticker-inner">
    <span>BTC/USD <b>$97,420</b> ▲ 2.3%</span>
    <span class="red">ETH/USD <b>$1,744</b> ▼ 0.8%</span>
    <span>SOL/USD <b>$71.94</b> ▲ 1.1%</span>
    <span>BNB/USD <b>$601</b> ▲ 0.5%</span>
    <span class="red">XRP/USD <b>$0.58</b> ▼ 1.2%</span>
    <span>BTC/USD <b>$97,420</b> ▲ 2.3%</span>
    <span class="red">ETH/USD <b>$1,744</b> ▼ 0.8%</span>
    <span>SOL/USD <b>$71.94</b> ▲ 1.1%</span>
    <span>BNB/USD <b>$601</b> ▲ 0.5%</span>
    <span class="red">XRP/USD <b>$0.58</b> ▼ 1.2%</span>
  </div>
</div>

<!-- NAV -->
<nav>
  <div class="logo">Bit<span>Mind</span></div>
  <div class="nav-links">
    <a href="#como-funciona">Como funciona</a>
    <a href="#planos">Planos</a>
    <a href="https://bitmind.app.br" target="_blank">Plataforma</a>
    <a href="https://t.me/bitmind_signals_br" target="_blank" class="btn-nav">↗ Entrar grátis</a>
  </div>
</nav>

<!-- HERO -->
<div class="hero">
  <div class="hero-badge">🟢 Sinais ao vivo · Señales en vivo</div>
  <h1>
    Inteligência SMC<br>
    para seu <em>próximo trade</em>
  </h1>
  <p>
    Análise automática de BTC, ETH, SOL, BNB e XRP com Smart Money Concepts. 
    Receba sinais de alta confluência direto no Telegram — grátis.
  </p>
  <div class="hero-cta">
    <a href="https://t.me/bitmind_signals_br" target="_blank" class="btn-primary">
      📲 Entrar no canal grátis
    </a>
    <a href="https://bitmind.app.br" target="_blank" class="btn-secondary">
      Ver plataforma →
    </a>
  </div>

  <!-- Signal preview card -->
  <div class="signal-preview">
    <div class="signal-tag">AO VIVO</div>
    <div class="signal-header">
      <span class="buy">🟢 COMPRAR</span> — BTC/USD
    </div>
    <div class="signal-row">
      <span class="label">💰 Precio</span>
      <span class="value">$97,420</span>
    </div>
    <div class="signal-row">
      <span class="label">⚡ Confluências SMC</span>
      <span class="value">
        <div class="confluencia-bar">
          <span></span><span></span><span></span><span class="empty"></span>
        </div>
      </span>
    </div>
    <div class="signal-row">
      <span class="label">📊 Estructura</span>
      <span class="value">Alcista</span>
    </div>
    <div class="signal-row">
      <span class="label">✅ BOS detectado</span>
      <span class="value" style="color:var(--green)">Sim</span>
    </div>
    <div class="signal-row">
      <span class="label">✅ Order Block</span>
      <span class="value" style="color:var(--green)">$95,800–$96,200</span>
    </div>
  </div>
</div>

<!-- STATS -->
<div class="stats">
  <div class="stat">
    <div class="stat-num">5</div>
    <div class="stat-label">Criptos monitoradas</div>
  </div>
  <div class="stat">
    <div class="stat-num">6h</div>
    <div class="stat-label">Análise automática</div>
  </div>
  <div class="stat">
    <div class="stat-num">4</div>
    <div class="stat-label">Indicadores SMC</div>
  </div>
</div>

<!-- COMO FUNCIONA -->
<section id="como-funciona">
  <div class="section-label">// Como funciona · Cómo funciona</div>
  <h2 class="section-title">Do mercado ao seu Telegram<br>em segundos</h2>
  <p class="section-sub">O motor BitMind analisa o mercado a cada 6 horas e envia sinais apenas quando há alta confluência de indicadores SMC.</p>

  <div class="steps">
    <div class="step">
      <div class="step-num">01</div>
      <div>
        <h3>Coleta de dados via Coinbase</h3>
        <p>Velas de 6 horas para BTC, ETH, SOL, BNB e XRP — dados reais do mercado em tempo real.</p>
      </div>
    </div>
    <div class="step">
      <div class="step-num">02</div>
      <div>
        <h3>Análise SMC com 4 indicadores</h3>
        <p>RSI, Médias Móveis MM20/MM50, Order Blocks e BOS/CHoCH — confluência de 0 a 4.</p>
      </div>
    </div>
    <div class="step">
      <div class="step-num">03</div>
      <div>
        <h3>Sinal enviado com 3+ confluências</h3>
        <p>Apenas alertas de alta qualidade chegam ao canal. Sem ruído, sem spam.</p>
      </div>
    </div>
    <div class="step">
      <div class="step-num">04</div>
      <div>
        <h3>Análise detalhada na plataforma</h3>
        <p>Acesse bitmind.app.br para ver o dashboard completo com todos os indicadores.</p>
      </div>
    </div>
  </div>
</section>

<!-- SMC FEATURES -->
<section style="padding-top: 0;">
  <div class="section-label">// Motor SMC</div>
  <h2 class="section-title">Smart Money Concepts<br>no piloto automático</h2>
  <p class="section-sub">Os mesmos conceitos usados por traders institucionais, agora automatizados.</p>

  <div class="features">
    <div class="feature-card">
      <div class="feature-icon">📈</div>
      <h3>RSI 6H</h3>
      <p>Identifica sobrecompra e sobrevenda em velas de 6 horas para filtrar entradas precisas.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">〰️</div>
      <h3>MM20 / MM50</h3>
      <p>Médias móveis para confirmar tendência e estrutura de mercado antes de qualquer sinal.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">🧱</div>
      <h3>Order Blocks</h3>
      <p>Detecta zonas de liquidez institucional — onde o dinheiro grande entra no mercado.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">🔄</div>
      <h3>BOS / CHoCH</h3>
      <p>Break of Structure e Change of Character para identificar reversões e continuações.</p>
    </div>
  </div>
</section>

<!-- PLANOS -->
<section id="planos">
  <div class="section-label">// Planos · Planes</div>
  <h2 class="section-title">Comece grátis.<br>Escale quando quiser.</h2>
  <p class="section-sub">Acesso ao canal Telegram sem custo. VIP e plataforma completa em breve.</p>

  <div class="plans">
    <!-- FREE -->
    <div class="plan-card">
      <div class="plan-name">Free · Grátis</div>
      <div class="plan-price">R$ 0<span>/mês</span></div>
      <div class="plan-period">Para sempre gratuito</div>
      <ul class="plan-features">
        <li>Canal Telegram @bitmind_signals</li>
        <li>Sinais BTC, ETH, SOL, BNB, XRP</li>
        <li>Análise a cada 6 horas</li>
        <li>Alertas com 3+ confluências SMC</li>
        <li class="locked">Plataforma web completa</li>
        <li class="locked">Sinais VIP prioritários</li>
        <li class="locked">Suporte direto</li>
      </ul>
      <a href="https://t.me/bitmind_signals_br" target="_blank" class="btn-plan outline">
        📲 Entrar no canal
      </a>
    </div>

    <!-- VIP -->
    <div class="plan-card featured">
      <div class="plan-badge">EM BREVE</div>
      <div class="plan-name">VIP · Pro</div>
      <div class="plan-price">R$ 47<span>/mês</span></div>
      <div class="plan-period">Acesso completo · Acceso completo</div>
      <ul class="plan-features">
        <li>Tudo do plano Free</li>
        <li>Plataforma bitmind.app.br</li>
        <li>Sinais prioritários antes do canal</li>
        <li>Análise detalhada por cripto</li>
        <li>Scalping 1m/5m/15m (em breve)</li>
        <li>Suporte via Telegram</li>
        <li>Atualizações exclusivas</li>
      </ul>
      <a href="https://t.me/bitmind_signals_br" target="_blank" class="btn-plan green">
        🔔 Entrar na lista VIP
      </a>
    </div>
  </div>
  <p class="bilingual">🇧🇷 Português · 🇪🇸 Español — Sinais disponíveis nos dois idiomas</p>
</section>

<!-- CTA FINAL -->
<div class="cta-final">
  <h2>Pronto para operar<br>com inteligência?</h2>
  <p>Entre no canal gratuito e receba o próximo sinal SMC direto no seu Telegram.</p>
  <div class="hero-cta">
    <a href="https://t.me/bitmind_signals_br" target="_blank" class="btn-primary">
      📲 Entrar grátis no Telegram
    </a>
    <a href="https://bitmind.app.br" target="_blank" class="btn-secondary">
      Ver plataforma →
    </a>
  </div>
</div>

<!-- FOOTER -->
<footer>
  <p style="margin-bottom:12px;">
    <strong style="color:var(--white);">BitMind</strong> — Análise SMC automatizada
  </p>
  <p>
    <a href="https://bitmind.app.br">Plataforma</a> · 
    <a href="https://t.me/bitmind_signals_br">Telegram</a>
  </p>
  <p style="margin-top:16px; font-size:12px;">
    ⚠️ Não é consultoria financeira. Opere com responsabilidade. · No es asesoría financiera.
  </p>
</footer>

</body>
</html>
""")

@app.get("/ping")
async def ping():
    return {"status": "ok", "message": "BitMind alive!"}


@app.get("/test-telegram")
async def test_telegram():
    try:
        resultados = []
        for cripto in PARES:
            simbolo = PARES[cripto]["simbolo"]
            precio = obtener_precio(simbolo)
            cierres, highs, lows = obtener_velas_4h(simbolo)
            if len(cierres) >= 20:
                confluencias, detalles, rsi, mm20, mm50, estructura, ob_low, ob_high = calcular_confluencias(precio, cierres, highs, lows)
                decision_key, color, etiqueta = determinar_senal(precio, confluencias, detalles, estructura)
                decision = "COMPRAR" if decision_key == "comprar" else "VENDER" if decision_key == "vender" else "ESPERAR"
                if confluencias >= 3:
                    enviar_telegram(cripto, precio, decision, confluencias, estructura, detalles)
                resultados.append(f"{cripto}: {decision} ({confluencias}/4)")
        return {"status": "ok", "resultados": resultados}
    except Exception as e:
        return {"status": "error", "detalle": str(e)}


async def loop_analisis():
    while True:
        try:
            for cripto in PARES:
                simbolo = PARES[cripto]["simbolo"]
                precio = obtener_precio(simbolo)
                cierres, highs, lows = obtener_velas_4h(simbolo)
                if len(cierres) >= 20:
                    confluencias, detalles, rsi, mm20, mm50, estructura, ob_low, ob_high = calcular_confluencias(precio, cierres, highs, lows)
                    decision_key, color, etiqueta = determinar_senal(precio, confluencias, detalles, estructura)
                    decision = "COMPRAR" if decision_key == "comprar" else "VENDER" if decision_key == "vender" else "ESPERAR"
                    if confluencias >= 3:
                        enviar_telegram(cripto, precio, decision, confluencias, estructura, detalles)
        except Exception as e:
            print(f"Error en loop_analisis: {e}")
        await asyncio.sleep(21600)


@app.on_event("startup")
async def iniciar_scheduler():
    asyncio.create_task(loop_analisis())
