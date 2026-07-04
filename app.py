import streamlit as st
import pandas as pd
import time
import base64
import requests
import math
import folium
from streamlit_folium import st_folium

st.set_page_config(
    page_title="DMi Copilot — BYD Atto 2 DM-i Boost",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CHIAVE API INTEGRATA DIRETTAMENTE
API_KEY = "EyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjBmYWI5ZGM4N2JhOTQwOGNhMzhjOTg5MGIwMWM3ZWI1IiwiaCI6Im11cm11cjY0In0="

# --- COSTANTI VEICOLO (BYD ATTO 2 DM-i BOOST) ---
BATTERY_CAPACITY_KWH = 18.3  # Blade Battery da 18.3 kWh
FUEL_TANK_LITERS = 60.0      # Serbatoio da 60 litri
MOTOR_POWER_KW = 160.0       # Motore elettrico da 160 kW (218 CV)

if "coeff_ev_urban" not in st.session_state:
    st.session_state.coeff_ev_urban = 0.150  # 15.0 kWh/100km (Base urbana)
if "coeff_ev_extra" not in st.session_state:
    st.session_state.coeff_ev_extra = 0.175  # 17.5 kWh/100km (Base extraurbana)
if "coeff_ev_highway" not in st.session_state:
    st.session_state.coeff_ev_highway = 0.220  # 22.0 kWh/100km (Base autostrada)
if "coeff_hev_fuel" not in st.session_state:
    st.session_state.coeff_hev_fuel = 0.049  # 4.9 L/100km (Consumo termico standard)

if "current_step" not in st.session_state:
    st.session_state.current_step = 0
if "trip_active" not in st.session_state:
    st.session_state.trip_active = False

if "km_u" not in st.session_state:
    st.session_state.km_u = 15.0
if "km_e" not in st.session_state:
    st.session_state.km_e = 25.0
if "km_h" not in st.session_state:
    st.session_state.km_h = 40.0

if "route_coords" not in st.session_state:
    st.session_state.route_coords = []
if "start_coords" not in st.session_state:
    st.session_state.start_coords = [44.307, 8.481]  # Default Savona
if "end_coords" not in st.session_state:
    st.session_state.end_coords = [45.070, 7.686]    # Default Torino

def trigger_speech_html(text):
    """Genera ed esegue un comando SpeechSynthesis nativo HTML5 nel browser del telefono/PC."""
    b64_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')
    js_code = f"""
    <iframe src="javascript:void(0)" allow="autoplay" id="audio_iframe" style="display:none;"></iframe>
    <script>
        window.speechSynthesis.cancel();
        var msg = new SpeechSynthesisUtterance(atob('{b64_text}'));
        msg.lang = 'it-IT';
        msg.volume = 1;
        msg.rate = 1.0;
        window.speechSynthesis.speak(msg);
    </script>
    """
    st.components.v1.html(js_code, height=0, width=0)

# --- CALCOLO GEOMETRICO DISTANZE (Haversine) ---
def haversine(lon1, lat1, lon2, lat2):
    """Calcola la distanza tra due coordinate geografiche in km."""
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371.0 # Raggio terrestre medio in chilometri
    return c * r

def geocode_city(city_name, api_key):
    """Converte il nome di una città in coordinate [lon, lat] con strategie di fallback avanzate."""
    # Strategia 1: OpenRouteService con autenticazione via parametro query
    url_ors = "https://api.openrouteservice.org/geocode/search"
    params_ors = {
        "text": city_name,
        "size": 1,
        "api_key": api_key
    }
    try:
        res = requests.get(url_ors, params=params_ors, timeout=8)
        if res.status_code == 200:
            data = res.json()
            if "features" in data and len(data["features"]) > 0:
                return data["features"][0]["geometry"]["coordinates"] # [lon, lat]
    except Exception:
        pass

    # Strategia 2: Fallback d'emergenza gratuito con Nominatim (OSM)
    url_osm = "https://nominatim.openstreetmap.org/search"
    params_osm = {
        "q": city_name,
        "format": "json",
        "limit": 1
    }
    headers_osm = {
        "User-Agent": "dmi-copilot-byd-application"
    }
    try:
        res = requests.get(url_osm, params=params_osm, headers=headers_osm, timeout=8)
        if res.status_code == 200:
            data = res.json()
            if len(data) > 0:
                lon = float(data[0]["lon"])
                lat = float(data[0]["lat"])
                return [lon, lat]
    except Exception:
        pass
        
    return None

def calculate_route_breakdown(coord_start, coord_end, api_key):
    """Invia richiesta di routing ed estrae le distanze stradali reali e la traccia geometrica."""
    endpoints = [
        {"url": "https://api.heigit.org/ors/v2/directions/driving-car", "auth_mode": "header"},
        {"url": "https://api.openrouteservice.org/v2/directions/driving-car", "auth_mode": "param"}
    ]
    
    for ep in endpoints:
        url = ep["url"]
        auth_mode = ep["auth_mode"]
        
        params = {
            "start": f"{coord_start[0]},{coord_start[1]}", # lon, lat
            "end": f"{coord_end[0]},{coord_end[1]}",     # lon, lat
            "extra_info": "waytypes"
        }
        headers = {}
        
        if auth_mode == "header":
            headers["Authorization"] = api_key
            headers["X-Api-Key"] = api_key
        else:
            params["api_key"] = api_key
            
        try:
            res = requests.get(url, params=params, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                if "features" in data and len(data["features"]) > 0:
                    route = data["features"][0]
                    coords = route["geometry"]["coordinates"]
                    
                    # Salva le coordinate per la mappa (invertendo l'ordine lon/lat in lat/lon per Folium)
                    st.session_state.route_coords = [[pt[1], pt[0]] for pt in coords]
                    
                    # Calcola le distanze intermedie tra tutti i punti GPS
                    step_distances = []
                    for i in range(len(coords) - 1):
                        step_distances.append(haversine(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1]))
                    
                    extras = route.get("properties", {}).get("extras", {})
                    waytypes = extras.get("waytypes", {})
                    values = waytypes.get("values", [])
                    
                    km_u, km_e, km_h = 0.0, 0.0, 0.0
                    for val in values:
                        start_idx, end_idx, w_type = val
                        segment_distance = sum(step_distances[start_idx:end_idx])
                        
                        if w_type == 1:
                            km_h += segment_distance
                        elif w_type in [2, 3, 4]:
                            km_e += segment_distance
                        else:
                            km_u += segment_distance
                            
                    if km_u == 0 and km_e == 0 and km_h == 0:
                        total_dist = sum(step_distances)
                        km_u = total_dist * 0.15
                        km_e = total_dist * 0.25
                        km_h = total_dist * 0.60
                        
                    return km_u, km_e, km_h
        except Exception:
            pass
            
    # Strategia di backup se le API falliscono
    dist_lineare = haversine(coord_start[0], coord_start[1], coord_end[0], coord_end[1])
    dist_stradale_stimata = dist_lineare * 1.20
    st.session_state.route_coords = [
        [coord_start[1], coord_start[0]],
        [coord_end[1], coord_end[0]]
    ]
    
    km_u = dist_stradale_stimata * 0.15 
    km_e = dist_stradale_stimata * 0.25 
    km_h = dist_stradale_stimata * 0.60 
    
    return km_u, km_e, km_h

def calcola_strategia_viaggio(starting_soc, starting_fuel, d_urban, d_extra, d_highway, is_round_trip, charge_at_dest):
    segmenti = []
    
    if d_urban > 0: segmenti.extend([{"type": "Urbano", "env": "urban"}] * int(d_urban))
    if d_extra > 0: segmenti.extend([{"type": "Extraurbano", "env": "extra"}] * int(d_extra))
    if d_highway > 0: segmenti.extend([{"type": "Autostradale", "env": "highway"}] * int(d_highway))
    
    if is_round_trip and charge_at_dest:
        segmenti.append({"type": "Pausa Ricarica (Destinazione)", "env": "charge"})
        
    if is_round_trip:
        if d_highway > 0: segmenti.extend([{"type": "Autostradale (Rientro)", "env": "highway"}] * int(d_highway))
        if d_extra > 0: segmenti.extend([{"type": "Extraurbano (Rientro)", "env": "extra"}] * int(d_extra))
        if d_urban > 0: segmenti.extend([{"type": "Urbano (Rientro)", "env": "urban"}] * int(d_urban))

    storia_soc = []
    storia_fuel = []
    modalita_suggerita = []
    motore_attivo = []
    
    current_soc = float(starting_soc)
    current_energy = (current_soc / 100.0) * BATTERY_CAPACITY_KWH
    current_fuel = float(starting_fuel)
    
    for idx, seg in enumerate(segmenti):
        env = seg["env"]
        
        if env == "charge":
            current_soc = 100.0
            current_energy = BATTERY_CAPACITY_KWH
            storia_soc.append(current_soc)
            storia_fuel.append(current_fuel)
            modalita_suggerita.append("CHARGE")
            motore_attivo.append("Ricarica")
            continue
            
        if env == "urban":
            if current_soc > 15.0:
                modo = "EV"
                motore = "Elettrico"
                cons_kwh = st.session_state.coeff_ev_urban
                cons_l = 0.0
            else:
                modo = "HEV ECO"
                motore = "Termico"
                cons_kwh = -0.01
                cons_l = st.session_state.coeff_hev_fuel * 0.90
        
        elif env == "extra":
            if current_soc > 25.0:
                modo = "EV"
                motore = "Elettrico"
                cons_kwh = st.session_state.coeff_ev_extra
                cons_l = 0.0
            else:
                modo = "HEV NORMAL"
                motore = "Termico"
                cons_kwh = 0.0
                cons_l = st.session_state.coeff_hev_fuel
                
        elif env == "highway":
            if current_soc > 20.0:
                modo = "HEV SAVE"
                motore = "Termico"
                cons_kwh = st.session_state.coeff_ev_highway * 0.02
                cons_l = st.session_state.coeff_hev_fuel * 1.25
            else:
                modo = "HEV POWER"
                motore = "Entrambi"
                cons_kwh = -0.02
                cons_l = st.session_state.coeff_hev_fuel * 1.50
                
        current_energy -= cons_kwh
        current_fuel -= cons_l
        
        current_energy = max(0.15 * BATTERY_CAPACITY_KWH, min(current_energy, BATTERY_CAPACITY_KWH))
        current_fuel = max(0.0, current_fuel)
        current_soc = (current_energy / BATTERY_CAPACITY_KWH) * 100.0
        
        storia_soc.append(current_soc)
        storia_fuel.append(current_fuel)
        modalita_suggerita.append(modo)
        motore_attivo.append(motore)
        
    return segmenti, storia_soc, storia_fuel, modalita_suggerita, motore_attivo

# --- INTERFACCIA UTENTE ---
st.title("🚗 DMi Copilot — BYD Atto 2 DM-i Boost")
st.subheader("Pianificatore energetico intelligente e copilota vocale attivo")

col_main, col_sidebar = st.columns([2.5, 1.5])

with col_sidebar:
    st.header("⚙️ Impostazioni Auto")
    soc_in = st.slider("SOC Batteria alla partenza (%)", min_value=15, max_value=100, value=85, step=1)
    carburante_in = st.slider("Benzina alla partenza (L)", min_value=1, max_value=60, value=45, step=1)
    
    st.markdown("---")
    st.header("📊 Calibrazione Modello")
    cal_km = st.number_input("Chilometri percorsi reali", min_value=0.0, value=0.0, step=1.0)
    cal_soc_end = st.number_input("SOC finale reale sul cruscotto (%)", min_value=15.0, max_value=100.0, value=20.0)
    cal_alpha = st.slider("Fattore di Smoothing (α)", min_value=0.1, max_value=0.5, value=0.2, step=0.05)
    
    if st.button("Ricalibra Modello Boost", type="secondary", use_container_width=True):
        if cal_km > 0:
            kwh_consumati_reali = ((soc_in - cal_soc_end) / 100.0) * BATTERY_CAPACITY_KWH
            consumo_medio_reale = kwh_consumati_reali / cal_km
            st.session_state.coeff_ev_extra = (cal_alpha * consumo_medio_reale) + ((1 - cal_alpha) * st.session_state.coeff_ev_extra)
            st.success(f"Modello ricalibrato! Nuovo EV medio: {st.session_state.coeff_ev_extra * 100:.1f} kWh/100km")
        else:
            st.warning("Inserisci i chilometri reali per la ricalibrazione.")

with col_main:
    st.header("🌐 Calcolo Automatico Tratta")
    col_api1, col_api2 = st.columns(2)
    with col_api1:
        citta_partenza = st.text_input("Partenza", value="Savona")
    with col_api2:
        citta_arrivo = st.text_input("Arrivo", value="Torino")
        
    if st.button("Ottieni Tratta Automaticamente", type="primary", use_container_width=True):
        with st.spinner("Calcolo del tragitto e scomposizione autostradale in corso..."):
            coord_start = geocode_city(citta_partenza, API_KEY)
            coord_end = geocode_city(citta_arrivo, API_KEY)
            
            if coord_start and coord_end:
                st.session_state.start_coords = [coord_start[1], coord_start[0]]
                st.session_state.end_coords = [coord_end[1], coord_end[0]]
                breakdown = calculate_route_breakdown(coord_start, coord_end, API_KEY)
                if breakdown:
                    km_u_calcolati, km_e_calcolati, km_h_calcolati = breakdown
                    st.session_state.km_u = float(round(km_u_calcolati, 1))
                    st.session_state.km_e = float(round(km_e_calcolati, 1))
                    st.session_state.km_h = float(round(km_h_calcolati, 1))
                    
                    st.success(f"Tratta rilevata! Urbani: {st.session_state.km_u}km | Extraurbani: {st.session_state.km_e}km | Autostrada: {st.session_state.km_h}km")
                    st.rerun()

    st.markdown("---")
    
    st.subheader("🗺️ Mappa del Percorso")
    center_lat = (st.session_state.start_coords[0] + st.session_state.end_coords[0]) / 2
    center_lon = (st.session_state.start_coords[1] + st.session_state.end_coords[1]) / 2
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=8, tiles="CartoDB dark_matter")
    
    # Disegna la linea del percorso se presente
    if st.session_state.route_coords:
        folium.PolyLine(st.session_state.route_coords, color="#00f2fe", weight=5, opacity=0.8).add_to(m)
        
    # Aggiungi marcatore di partenza e arrivo
    folium.Marker(st.session_state.start_coords, popup="Partenza", icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker(st.session_state.end_coords, popup="Arrivo", icon=folium.Icon(color="red", icon="stop")).add_to(m)
    
    # Renderizza la mappa nello schermo
    st_folium(m, width="100%", height=350, key="byd_copilot_map")

    st.markdown("---")
    st.header("🧭 Copilota Attivo in Guida")
    
    km_u = st.number_input("Distanza Urbana [km]", min_value=0.0, key="km_u", step=1.0)
    km_e = st.number_input("Distanza Extraurbana [km]", min_value=0.0, key="km_e", step=1.0)
    km_h = st.number_input("Distanza Autostradale [km]", min_value=0.0, key="km_h", step=1.0)
    
    rt_enabled = st.checkbox("Viaggio di Andata e Ritorno", value=False)
    charge_dest = st.checkbox("Ricarica alla meta prima del rientro (100% SOC)", value=True, disabled=not rt_enabled)

    segmenti, storia_soc, storia_fuel, modalita_suggerita, motore_attivo = calcola_strategia_viaggio(
        soc_in, carburante_in, km_u, km_e, km_h, rt_enabled, charge_dest
    )
    
    km_totali = len(storia_soc)
    soc_finale_stimato = storia_soc[-1] if km_totali > 0 else soc_in
    benzina_consumata = (carburante_in - storia_fuel[-1]) if km_totali > 0 else 0.0

    st.markdown("### 📈 Riepilogo Strategia ed Efficienza")
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    col_stat1.metric("Chilometri Totali", f"{km_totali} km")
    col_stat2.metric("SOC Finale Stimato", f"{soc_finale_stimato:.0f}%")
    col_stat3.metric("Carburante Stimato", f"{benzina_consumata:.1f} L")

    opzione_guida = st.radio("Seleziona modalità copilota:", ["Simulazione di prova", "Viaggio Reale (Usa mentre guidi)"], horizontal=True)
    
    if opzione_guida == "Simulazione di prova":
        start_sim = st.button("🚀 AVVIA SIMULAZIONE VELOCE")
        if start_sim and km_totali > 0:
            hud_placeholder = st.empty()
            audio_placeholder = st.empty()
            last_announced_mode = ""
            
            for km in range(0, km_totali, max(1, km_totali // 15)):
                current_seg_type = segmenti[km]["type"]
                current_soc_sim = storia_soc[km]
                current_fuel_sim = storia_fuel[km]
                current_suggested = modalita_suggerita[km]
                
                if current_suggested != last_announced_mode:
                    msg = f"Imposta modalità {current_suggested} sul display."
                    with audio_placeholder:
                        trigger_speech_html(msg)
                    last_announced_mode = current_suggested
                
                with hud_placeholder.container():
                    st.markdown(f"#### 🛣️ Tratta corrente: **{current_seg_type}**")
                    col_hud1, col_hud2 = st.columns(2)
                    col_hud1.metric("SOC", f"{current_soc_sim:.1f}%")
                    col_hud2.metric("Carburante", f"{current_fuel_sim:.1f} L")
                    
                    st.markdown(
                        f"""
                        <div style="background-color:#1e293b; border-radius:15px; padding:20px; text-align:center; border: 2px solid #00f2fe;">
                            <h2 style="color:#00f2fe; margin-top:5px; font-weight:800; font-size:32px;">{current_suggested}</h2>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                time.sleep(1.0)
    else:
        # Viaggio Reale
        if km_totali == 0:
            st.info("Calcola la tratta per avviare il copilota reale.")
        else:
            macro_segmenti = []
            km_accumulati = 0
            attuale_tipo = None
            for idx, seg in enumerate(segmenti):
                if seg["type"] != attuale_tipo:
                    macro_segmenti.append({
                        "id": len(macro_segmenti),
                        "type": seg["type"],
                        "start_km": km_accumulati,
                        "soc": storia_soc[idx],
                        "fuel": storia_fuel[idx],
                        "suggested": modalita_suggerita[idx]
                    })
                    attuale_tipo = seg["type"]
                km_accumulati += 1
                
            total_steps = len(macro_segmenti)
            
            if not st.session_state.trip_active:
                if st.button("🏁 INIZIA VIAGGIO REALE SULLA BYD", type="primary", use_container_width=True):
                    st.session_state.trip_active = True
                    st.session_state.current_step = 0
                    primo_suggerimento = macro_segmenti[0]["suggested"]
                    trigger_speech_html(f"Pianificazione avviata. Seleziona {primo_suggerimento} sul display BYD.")
                    st.rerun()
            else:
                current_idx = st.session_state.current_step
                if current_idx < total_steps:
                    tappa_corrente = macro_segmenti[current_idx]
                    
                    st.markdown(
                        f"""
                        <div style="background-color:#0f172a; border-radius:20px; padding:25px; border: 3px solid #10b981; margin-bottom:15px; text-align:center;">
                            <span style="color:#34d399; font-size:12px; font-weight:800; tracking-widest:2px;">📍 TAPPA ({current_idx + 1} di {total_steps})</span>
                            <h2 style="color:#ffffff; margin:0; font-size:28px;">{tappa_corrente['type']}</h2>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    st.markdown(
                        f"""
                        <div style="background-color:#1e293b; border-radius:15px; padding:20px; text-align:center; border: 2px solid #00f2fe; margin-top:15px; margin-bottom:20px;">
                            <span style="color:#94a3b8; font-size:12px; font-weight:bold;">Impostazione Consigliata sul Display BYD</span>
                            <h1 style="color:#00f2fe; margin-top:5px; font-size:42px; font-weight:900;">{tappa_corrente['suggested']}</h1>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                    
                    if current_idx + 1 < total_steps:
                        prossima_tappa = macro_segmenti[current_idx + 1]
                        if st.button(f"➡️ SONO ENTRATO NEL TRATTO: {prossima_tappa['type'].upper()}", type="primary", use_container_width=True):
                            st.session_state.current_step += 1
                            trigger_speech_html(f"Passa alla modalità {prossima_tappa['suggested']}.")
                            st.rerun()
                    else:
                        if st.button("🏁 CONCLUDI IL VIAGGIO", type="primary", use_container_width=True):
                            st.session_state.trip_active = False
                            st.session_state.current_step = 0
                            trigger_speech_html("Viaggio concluso con successo.")
                            st.balloons()
                            st.rerun()
