from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import requests
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta
from fastapi import Request, Response, Form

app = FastAPI()
client = Anthropic()

historiales = {"BTC": [], "ETH": [], "SOL": [], "BNB": [], "XRP": []}
visitas = {"total": 0, "BTC": 0, "ETH": 0, "SOL": 0, "BNB": 0, "XRP": 0, "resumen": 0, "about": 0}

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
    lang = "español latinoamericano" if idioma == "es" else "português brasileiro"
    rsi_txt = f"RSI={rsi}" if rsi else "RSI insuficiente"
    mensaje = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=120,
        system=f"Eres un analista de criptomonedas. Responde SIEMPRE en exactamente 2 frases cortas en {lang}. NUNCA uses markdown, asteriscos, almohadillas ni títulos. Solo texto plano y directo.",
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
            decision_key = "vender"; color = "#ff4444"
        else:
            decision_key = "esperar"; color = "orange"
    else:
        if precio < par["comprar"]:
            decision_key = "comprar"; color = "#00ff88"
        elif precio > par["vender"]:
            decision_key = "vender"; color = "#ff4444"
        else:
            decision_key = "esperar"; color = "orange"

    if lang == "es":
        tendencia_txt = "SUBIENDO ↗" if subiendo else "BAJANDO ↘" if subiendo is not None else "ESTABLE →"
        decisiones = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "ESPERAR"}
        btn_lang = "🇧🇷 Português"; btn_url = f"/?lang=pt&cripto={cripto}"
        label_analisis = "🤖 Análisis IA"
        label_actualizado = "Actualizado"
        label_cada = "Se actualiza cada 30 seg"
        label_precio = "Precio actual"
        label_rsi = "RSI"
        label_mm = "Media Móvil 7"
        label_indicadores = "Indicadores Técnicos"
        rsi_zona = "Sobrevendido 🟢" if rsi and rsi < 30 else "Sobrecomprado 🔴" if rsi and rsi > 70 else "Neutral 🟡"
    else:
        tendencia_txt = "SUBINDO ↗" if subiendo else "CAINDO ↘" if subiendo is not None else "ESTÁVEL →"
        decisiones = {"comprar": "COMPRAR", "vender": "VENDER", "esperar": "AGUARDAR"}
        btn_lang = "🇪🇸 Español"; btn_url = f"/?lang=es&cripto={cripto}"
        label_analisis = "🤖 Análise IA"
        label_actualizado = "Atualizado"
        label_cada = "Atualiza a cada 30 seg"
        label_precio = "Preço atual"
        label_rsi = "RSI"
        label_mm = "Média Móvel 7"
        label_indicadores = "Indicadores Técnicos"
        rsi_zona = "Sobrevendido 🟢" if rsi and rsi < 30 else "Sobrecomprado 🔴" if rsi and rsi > 70 else "Neutro 🟡"

    decision = decisiones[decision_key]
    color_tendencia = "#00ff88" if subiendo else "#ff4444" if subiendo is not None else "orange"
    analisis = analisis_ia(par["nombre"], precio, tendencia_txt, rsi, lang)
    labels = [p["hora"] for p in historiales[cripto]]
    valores = lista
    rsi_display = str(rsi) if rsi else "..."
    mm7_display = f"${mm7:,.2f}" if mm7 else "..."

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
            .indicadores {{ display: flex; gap: 10px; margin-bottom: 15px; }}
            .ind-card {{ flex: 1; background: #16213e; border-radius: 12px; padding: 15px; text-align: center; border: 1px solid #ffffff11; }}
            .ind-titulo {{ font-size: 11px; color: #aaa; text-transform: uppercase; margin-bottom: 6px; }}
            .ind-valor {{ font-size: 22px; font-weight: bold; color: #f0a500; }}
            .ind-zona {{ font-size: 12px; color: #aaa; margin-top: 4px; }}
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
            <div class="tagline">AI-Powered Crypto Trading Signal</div>
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
            </div>

            <div class="ind-label">{label_indicadores}</div>
            <div class="indicadores">
                <div class="ind-card">
                    <div class="ind-titulo">{label_rsi}</div>
                    <div class="ind-valor">{rsi_display}</div>
                    <div class="ind-zona">{rsi_zona}</div>
                </div>
                <div class="ind-card">
                    <div class="ind-titulo">{label_mm}</div>
                    <div class="ind-valor" style="font-size:16px">{mm7_display}</div>
                    <div class="ind-zona">{'↗' if mm7 and precio > mm7 else '↘' if mm7 else '...'}</div>
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
                <a href="https://wa.me/?text=🤖 BitMind - Crypto Trading con IA%0A💰 {par['nombre']}: ${precio:,.2f}%0A📊 Señal: {decision}%0A👉 https://bot-traiding-btc.onrender.com"
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
            lista = [p["precio"] for p in hist]
            rsi = calcular_rsi(lista)
            if rsi is not None:
                if rsi < 30: decision = "COMPRAR"; color = "#00ff88"
                elif rsi > 70: decision = "VENDER"; color = "#ff4444"
                else: decision = "ESPERAR"; color = "orange"
            else:
                if precio < par["comprar"]: decision = "COMPRAR"; color = "#00ff88"
                elif precio > par["vender"]: decision = "VENDER"; color = "#ff4444"
                else: decision = "ESPERAR"; color = "orange"
            if lang == "pt" and decision == "ESPERAR":
                decision = "AGUARDAR"
            tend = "↗" if subiendo else "↘" if subiendo is not None else "→"
            tend_color = "#00ff88" if subiendo else "#ff4444" if subiendo is not None else "orange"
            datos.append({"cripto": cripto, "nombre": par["nombre"], "precio": precio, "tend": tend, "tend_color": tend_color, "decision": decision, "color": color})
        except:
            pass

    filas = ""
    for d in datos:
        filas += f"""
        <a href="/?lang={lang}&cripto={d['cripto']}" style="text-decoration:none;">
            <div style="background:#16213e;border-radius:12px;padding:15px 20px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;border:1px solid #ffffff11;">
                <div style="font-size:20px;font-weight:bold;color:#f0a500;width:50px;">{d['cripto']}</div>
                <div style="font-size:18px;font-weight:bold;color:white;">${d['precio']:,.2f}</div>
                <div style="font-size:18px;color:{d['tend_color']};font-weight:bold;">{d['tend']}</div>
                <div style="font-size:16px;font-weight:bold;color:{d['color']};border:1px solid {d['color']};padding:4px 12px;border-radius:20px;">{d['decision']}</div>
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
            <p>BitMind es una plataforma de señales de trading con Inteligencia Artificial que analiza el mercado de criptomonedas en tiempo real, combinando análisis técnico y machine learning para darte ventaja en tus decisiones.</p>
        </div>
        <div class="seccion">
            <h2>📈 La Tendencia — El Rey del Trading</h2>
            <p>Los traders profesionales dicen: <em>"La tendencia es tu amiga"</em>. El 80% de las ganancias en trading vienen de operar a favor de la tendencia, nunca contra ella.</p>
            <div class="card-tend alcista">
                <div class="tend-titulo">📈 Tendencia Alcista — SUBIENDO</div>
                <p>El precio hace máximos y mínimos cada vez más altos. Es el mejor momento para comprar y mantener posición. El mercado tiene fuerza compradora.</p>
            </div>
            <div class="card-tend bajista">
                <div class="tend-titulo">📉 Tendencia Bajista — BAJANDO</div>
                <p>El precio hace máximos y mínimos cada vez más bajos. Momento de vender o mantenerse fuera del mercado. Los vendedores tienen el control.</p>
            </div>
            <div class="card-tend lateral">
                <div class="tend-titulo">➡️ Tendencia Lateral — ESTABLE</div>
                <p>El precio oscila entre dos niveles sin dirección clara. Esperá una ruptura antes de entrar al mercado.</p>
            </div>
        </div>
        <div class="seccion">
            <h2>📊 Indicadores que usamos</h2>
            <div class="indicador">
                <div class="ind-nombre">RSI — Índice de Fuerza Relativa</div>
                <p>Mide si el mercado está sobrecomprado o sobrevendido.</p>
                <div class="ind-reglas">
                    <span class="regla compra">RSI &lt; 30 → Sobrevendido → Oportunidad de COMPRA</span>
                    <span class="regla venta">RSI &gt; 70 → Sobrecomprado → Señal de VENTA</span>
                    <span class="regla neutral">RSI 30-70 → Zona Neutral → ESPERAR</span>
                </div>
            </div>
            <div class="indicador">
                <div class="ind-nombre">Media Móvil de 7 períodos</div>
                <p>Suaviza las fluctuaciones del precio para identificar la tendencia real. Si el precio está por encima de la media móvil, la tendencia es alcista. Si está por debajo, es bajista.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">🧠 IA + Tendencia</div>
                <p>Nuestra IA combina la dirección del precio con el RSI y la Media Móvil para confirmar si la tendencia es real o una trampa del mercado, generando un análisis claro en segundos.</p>
            </div>
        </div>
        <div class="seccion">
            <h2>🚦 ¿Qué significan las señales?</h2>
            <div class="senal compra-card">🟢 COMPRAR — Precio en zona de valor, buena oportunidad de entrada</div>
            <div class="senal venta-card">🔴 VENDER — Precio sobrevaluado, momento de tomar ganancias</div>
            <div class="senal espera-card">🟡 ESPERAR — Mercado indeciso, aguardar confirmación</div>
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
            <p>BitMind é uma plataforma de sinais de trading com Inteligência Artificial que analisa o mercado de criptomoedas em tempo real, combinando análise técnica e machine learning para te dar vantagem nas suas decisões.</p>
        </div>
        <div class="seccion">
            <h2>📈 A Tendência — O Rei do Trading</h2>
            <p>Os traders profissionais dizem: <em>"A tendência é sua amiga"</em>. 80% dos lucros no trading vêm de operar a favor da tendência, nunca contra ela.</p>
            <div class="card-tend alcista">
                <div class="tend-titulo">📈 Tendência de Alta — SUBINDO</div>
                <p>O preço faz máximas e mínimas cada vez mais altas. É o melhor momento para comprar e manter posição. O mercado tem força compradora.</p>
            </div>
            <div class="card-tend bajista">
                <div class="tend-titulo">📉 Tendência de Baixa — CAINDO</div>
                <p>O preço faz máximas e mínimas cada vez mais baixas. Momento de vender ou ficar fora do mercado. Os vendedores estão no controle.</p>
            </div>
            <div class="card-tend lateral">
                <div class="tend-titulo">➡️ Tendência Lateral — ESTÁVEL</div>
                <p>O preço oscila entre dois níveis sem direção clara. Aguarde uma ruptura antes de entrar no mercado.</p>
            </div>
        </div>
        <div class="seccion">
            <h2>📊 Indicadores que usamos</h2>
            <div class="indicador">
                <div class="ind-nombre">RSI — Índice de Força Relativa</div>
                <p>Mede se o mercado está sobrecomprado ou sobrevendido.</p>
                <div class="ind-reglas">
                    <span class="regla compra">RSI &lt; 30 → Sobrevendido → Oportunidade de COMPRA</span>
                    <span class="regla venta">RSI &gt; 70 → Sobrecomprado → Sinal de VENDA</span>
                    <span class="regla neutral">RSI 30-70 → Zona Neutra → AGUARDAR</span>
                </div>
            </div>
            <div class="indicador">
                <div class="ind-nombre">Média Móvel de 7 períodos</div>
                <p>Suaviza as flutuações do preço para identificar a tendência real. Se o preço está acima da média móvel, a tendência é de alta. Se está abaixo, é de baixa.</p>
            </div>
            <div class="indicador">
                <div class="ind-nombre">🧠 IA + Tendência</div>
                <p>Nossa IA combina a direção do preço com o RSI e a Média Móvel para confirmar se a tendência é real ou uma armadilha do mercado, gerando uma análise clara em segundos.</p>
            </div>
        </div>
        <div class="seccion">
            <h2>🚦 O que significam os sinais?</h2>
            <div class="senal compra-card">🟢 COMPRAR — Preço em zona de valor, boa oportunidade de entrada</div>
            <div class="senal venta-card">🔴 VENDER — Preço sobrevalorizado, momento de realizar lucros</div>
            <div class="senal espera-card">🟡 AGUARDAR — Mercado indeciso, esperar confirmação</div>
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
            <div class="card">
                <div class="card-nombre">₿ Bitcoin</div>
                <div class="card-num">{visitas['BTC']}</div>
            </div>
            <div class="card">
                <div class="card-nombre">Ξ Ethereum</div>
                <div class="card-num">{visitas['ETH']}</div>
            </div>
            <div class="card">
                <div class="card-nombre">◎ Solana</div>
                <div class="card-num">{visitas['SOL']}</div>
            </div>
            <div class="card">
                <div class="card-nombre">⬡ BNB</div>
                <div class="card-num">{visitas['BNB']}</div>
            </div>
            <div class="card">
                <div class="card-nombre">✕ XRP</div>
                <div class="card-num">{visitas['XRP']}</div>
            </div>
            <div class="card">
                <div class="card-nombre">📊 Resumen</div>
                <div class="card-num">{visitas['resumen']}</div>
            </div>
            <div class="card">
                <div class="card-nombre">ℹ️ About</div>
                <div class="card-num">{visitas['about']}</div>
            </div>
            <div class="aviso">⚠️ Las visitas se reinician cuando el servidor duerme</div>
        </div>
    </body>
    </html>
    """
