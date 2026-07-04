import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static

st.set_page_config(page_title="DMi Copilot - BYD Atto 2", layout="wide")

if 'trip_data' not in st.session_state:
    st.session_state.trip_data = None

st.title("🔋 DMi Copilot - BYD Atto 2 Boost")

def get_route(start, end):
    url = f"http://router.project-osrm.org/route/v1/driving/{start[1]},{start[0]};{end[1]},{end[0]}?overview=full&geometries=geojson"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

def geocode(location_name):
    url = f"https://nominatim.openstreetmap.org/search?q={location_name}&format=json&limit=1"
    response = requests.get(url, headers={'User-Agent': 'DMiCopilotApp'})
    if response.status_code == 200:
        data = response.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    return None

def calculate_strategy(dist_urban, dist_extra, dist_highway, initial_soc):
    # Consumi stimati (riferimenti per BYD DM-i)
    # EV: ca 14-16 kWh/100km | HEV: ca 4.5-5.5 L/100km
    
    segments = []
    if dist_urban > 0: segments.append({"type": "Urbano", "dist": dist_urban, "env": "urban"})
    if dist_extra > 0: segments.append({"type": "Extraurbano", "dist": dist_extra, "env": "extra"})
    if dist_highway > 0: segments.append({"type": "Autostradale", "dist": dist_highway, "env": "highway"})
    
    current_soc = initial_soc
    strategy = []
    
    for seg in segments:
        mode = "EV MODE"
        target_save = None
        stima_consumo_energia = 0
        stima_consumo_benzina = 0
        
        if seg['env'] == "highway":
            # LOGICA SAVE: Limite massimo 75% come da specifiche BYD
            target_save = min(int(current_soc), 75)
            mode = f"HEV SAVE (Target: {target_save}%)"
            stima_consumo_benzina = seg['dist'] * 0.055 # 5.5L/100km in autostrada
            current_soc -= (seg['dist'] * 0.01) # Lieve erosione batteria in HEV
        elif seg['env'] == "urban":
            mode = "EV MODE"
            stima_consumo_energia = seg['dist'] * 0.14 # 14kWh/100km
            current_soc -= (seg['dist'] * 0.02)
        else:
            mode = "HEV ECO"
            stima_consumo_benzina = seg['dist'] * 0.045 # 4.5L/100km in extraurbano
            current_soc -= (seg['dist'] * 0.01)
            
        strategy.append({
            "segmento": seg['type'],
            "distanza": seg['dist'],
            "modalita": mode,
            "target_save": target_save,
            "consumo_benzina": round(stima_consumo_benzina, 2)
        })
        
    return strategy

with st.sidebar:
    st.header("⚙️ Configurazione Viaggio")
    partenza = st.text_input("Da:", "Savona")
    arrivo = st.text_input("A:", "Torino")
    initial_soc = st.slider("SOC Batteria Iniziale (%)", 15, 100, 80)
    
    if st.button("🚀 Calcola Percorso"):
        coords_p = geocode(partenza)
        coords_a = geocode(arrivo)
        if coords_p and coords_a:
            route = get_route(coords_p, coords_a)
            if route:
                st.session_state.trip_data = {
                    "dist": route['routes'][0]['distance'] / 1000,
                    "coords": route['routes'][0]['geometry']['coordinates'],
                    "coords_p": coords_p,
                    "coords_a": coords_a
                }
        else:
            st.error("Impossibile trovare le coordinate.")

if st.session_state.trip_data:
    data = st.session_state.trip_data
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("🗺️ Mappa Percorso")
        m = folium.Map(location=data['coords_p'], zoom_start=9)
        path = [(c[1], c[0]) for c in data['coords']]
        folium.PolyLine(path, color="blue", weight=5, opacity=0.8).add_to(m)
        folium_static(m)
        
    with col2:
        st.subheader("📋 Strategia Boost")
        # Suddivisione proporzionale per la simulazione
        strat = calculate_strategy(data['dist']*0.2, data['dist']*0.3, data['dist']*0.5, initial_soc)
        
        for step in strat:
            with st.container(border=True):
                st.write(f"### {step['segmento']} ({step['distanza']:.1f} km)")
                st.info(f"Modalità Consigliata: **{step['modalita']}**")
                if step['target_save']:
                    st.warning(f"⚠️ **IMPOSTA SAVE AL {step['target_save']}%** sul display BYD!")
                if step['consumo_benzina'] > 0:
                    st.write(f"⛽ Consumo benzina stimato: ~{step['consumo_benzina']} L")

st.divider()
st.subheader("🏁 Modalità Guida Reale")
if st.button("Avvia Assistente Vocale/Visivo"):
    st.success("Copilota Attivo! Segui le istruzioni che appaiono in base alla tua tratta.")
    st.balloons()
