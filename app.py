import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import textwrap
import os
import base64
import requests
import json

# --- HEX COLOR INTERPOLATION FOR PASS GRADIENTS ---
def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))

def interpolate_color(color1, color2, factor):
    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2)
    r = rgb1[0] + (rgb2[0] - rgb1[0]) * factor
    g = rgb1[1] + (rgb2[1] - rgb1[1]) * factor
    b = rgb1[2] + (rgb2[2] - rgb1[2]) * factor
    return rgb_to_hex((r, g, b))

# --- AIRTABLE CONFIGURATION FOR COACH'S NOTES ---
AIRTABLE_PAT = st.secrets["AIRTABLE_PAT"]
AIRTABLE_BASE_ID = "app5rwHaVPKXC5S7S"
AIRTABLE_TABLE_NAME = "Coach_Notes"

def get_saved_notes():
    if AIRTABLE_PAT.startswith("YOUR_"): return {} 
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_PAT}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            records = response.json().get('records', [])
            return {rec['fields'].get('Note_ID'): rec['fields'].get('Notes', '') for rec in records if 'Note_ID' in rec['fields']}
    except Exception:
        pass
    return {}

def save_note_to_airtable(note_id, report_type, period, notes):
    if AIRTABLE_PAT.startswith("YOUR_"):
        st.error("Please add your Airtable PAT and Base ID to the top of app.py to save notes!")
        return False
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_PAT}", "Content-Type": "application/json"}
    fields = {"Note_ID": note_id, "Report_Type": report_type, "Period": period, "Notes": notes}
    if report_type == "Single Match": fields["Match_Link"] = [period] 
    payload = {"performUpsert": {"fieldsToMergeOn": ["Note_ID"]}, "typecast": True, "records": [{"fields": fields}]}
    response = requests.patch(url, headers=headers, data=json.dumps(payload))
    return response.status_code == 200

# 1. Page Configuration
st.set_page_config(page_title="KR Reykjavik | GK Performance", layout="wide")

st.markdown("""
    <style>
    @media print {
        .stApp { background-color: #0E1117 !important; color: white !important; }
        header, .st-emotion-cache-1wmy9hl, [data-testid="stSidebar"], button, .stExpander { display: none !important; }
    }
    [data-testid="stMetricValue"] * {
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.2 !important;
        font-size: 1.5rem !important;
    }
    </style>
    """, unsafe_allow_html=True)

# 2. Security
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.title("🔒 Secure Coaching Portal")
        password = st.text_input("Please enter the staff password to access performance reports:", type="password")
        if password == "KR2026": 
            st.session_state["authenticated"] = True
            st.rerun() 
        elif password != "":
            st.error("Incorrect password. Access denied.")
        return False
    return True

if not check_password():
    st.stop()

if "saved_notes" not in st.session_state:
    st.session_state["saved_notes"] = get_saved_notes()
saved_notes = st.session_state["saved_notes"]

# --- DATA LOADING & SETUP (MATCHES & ACTIONS) ---
def load_data():
    try:
        matches_df = pd.read_csv('Matches.csv')
        actions_df = pd.read_csv('GK_Actions.csv')
    except FileNotFoundError:
        # Fallback for when dummy data is removed
        matches_df = pd.DataFrame(columns=['Match_ID', 'Date', 'Venue', 'Opponent', 'Team_GK', 'Team_Score', 'Opponent_Score', 'Match_Summary_Notes'])
        actions_df = pd.DataFrame(columns=['Match_ID', 'Action_Category', 'Outcome', 'PSxG', 'Goal_Conceded', 'Pass_Start_X', 'Pass_Start_Y', 'Pass_End_X', 'Pass_End_Y', 'Under_Pressure', 'Play_Pattern', 'Match_Minute'])
        
    # Always run this, even if empty, to initialize the required columns for the sidebar
    matches_df['Date_Parsed'] = pd.to_datetime(matches_df['Date'], errors='coerce')
    matches_df['Month_Year'] = matches_df['Date_Parsed'].dt.strftime('%B %Y').fillna('Unknown Month')
    matches_df['Season'] = matches_df['Date_Parsed'].dt.strftime('%Y').fillna('Unknown Season')
    if 'Venue' not in matches_df.columns: matches_df['Venue'] = 'Home'
        
    if not actions_df.empty:
        def categorize_pass(row):
            if str(row.get('Action_Category')) != 'Pass': return row.get('Tactical_Bucket')
            x = pd.to_numeric(row.get('Pass_End_X'), errors='coerce')
            y = pd.to_numeric(row.get('Pass_End_Y'), errors='coerce')
            height = str(row.get('Pass_Height', 'Unknown'))
            if pd.isna(x) or pd.isna(y): return row.get('Tactical_Bucket', 'Uncategorized')
            if x > 80: return 'Play Beyond'
            elif (y < 18 or y > 62) and x > 18: return 'Play Around'
            elif 60 <= x <= 80: 
                if 'High' in height: return 'Play Into'
                return 'Play Through'
            elif 25 <= x < 60: return 'Play Through'
            else: return 'Short / Retain'
                
        actions_df['Tactical_Bucket'] = actions_df.apply(categorize_pass, axis=1)
        if 'Under_Pressure' not in actions_df.columns: actions_df['Under_Pressure'] = 0
        actions_df['Under_Pressure'] = pd.to_numeric(actions_df['Under_Pressure'], errors='coerce').fillna(0)
        if 'Play_Pattern' not in actions_df.columns: actions_df['Play_Pattern'] = 'Unknown'
        actions_df['Play_Pattern'] = actions_df['Play_Pattern'].astype(str)
    else:
        # Initialize empty columns for the fallback
        actions_df['Tactical_Bucket'] = pd.Series(dtype=str)
        actions_df['Under_Pressure'] = pd.Series(dtype=float)
        actions_df['Play_Pattern'] = pd.Series(dtype=str)
        
    return matches_df, actions_df

matches_df, actions_df = load_data()

# --- OPTA LEAGUE JSON PARSER ---
def load_opta_json():
    try:
        with open('GK_2025_all.json', 'r', encoding='utf-8') as f:
            opta_raw = json.load(f)
            
        rows = []
        for team, players in opta_raw.items():
            for p in players:
                if 'stat' in p:
                    stats = {s['name']: float(s['value']) for s in p['stat']}
                    stats['Player'] = p.get('matchName', f"{p.get('firstName')} {p.get('lastName')}")
                    stats['Team'] = team
                    
                    # Calculate Custom Opta Metrics
                    mins = stats.get('Time Played', 0)
                    if mins >= 450:
                        stats['Saves_per_90'] = (stats.get('Saves Made', 0) / mins) * 90
                        stats['GC_per_90'] = (stats.get('Goals Conceded', 0) / mins) * 90
                        stats['Recoveries_per_90'] = (stats.get('Recoveries', 0) / mins) * 90
                        
                        saves = stats.get('Saves Made', 0)
                        gc = stats.get('Goals Conceded', 0)
                        stats['Save_Pct'] = (saves / (saves + gc) * 100) if (saves + gc) > 0 else 0
                        
                        succ_dist = stats.get('GK Successful Distribution', 0)
                        unsucc_dist = stats.get('GK Unsuccessful Distribution', 0)
                        stats['Dist_Pct'] = (succ_dist / (succ_dist + unsucc_dist) * 100) if (succ_dist + unsucc_dist) > 0 else 0
                        
                        rows.append(stats)
        return pd.DataFrame(rows)
    except Exception as e:
        return pd.DataFrame()

opta_df = load_opta_json()

# --- HARDCODED KR GKI LEADERBOARD ---
gki_data = {
    'Goalkeeper': ['H. Georgsson', 'Á. Ólafsson', 'Á. Einarsson', 'A. Einarsson', 'V. Sigurðsson', 'M. Zapytowski', 'S. Auðunsson', 'P. Arinbjornsson', 'I. Jónsson', 'F. Schram', 'W. Tønning', 'M. Rosenørn', 'S. Ágústsson'],
    'Team': ['KR', 'Stjarnan', 'IA', 'Breidablik', 'Fram', 'IBV', 'KA', 'Vikingur', 'Vikingur', 'Valur', 'KA', 'FH', 'Valur'],
    'Shot Stopping': [0.486, 0.681, 0.654, 0.602, 0.807, 0.766, 0.404, 0.389, 0.559, 0.662, 0.002, 0.356, 0.199],
    'Distribution': [0.836, 0.578, 0.524, 0.633, 0.186, 0.195, 0.421, 0.617, 0.398, 0.171, 0.607, 0.220, 0.285],
    'Sweeping': [0.659, 0.645, 0.875, 0.604, 0.764, 0.650, 1.000, 0.341, 0.188, 0.387, 0.469, 0.299, 0.589],
    'Command': [0.573, 0.554, 0.500, 0.518, 0.480, 0.769, 0.577, 0.500, 0.638, 0.495, 0.421, 0.573, 0.367],
    'GKI': [0.643, 0.627, 0.626, 0.605, 0.551, 0.549, 0.517, 0.472, 0.455, 0.432, 0.326, 0.322, 0.304]
}
gki_df = pd.DataFrame(gki_data)

# Add rank columns
gki_df['Rk'] = gki_df['GKI'].rank(ascending=False, method='min').astype(int)
gki_df['SS Rk'] = gki_df['Shot Stopping'].rank(ascending=False, method='min').astype(int)
gki_df['Dist Rk'] = gki_df['Distribution'].rank(ascending=False, method='min').astype(int)
gki_df['Swp Rk'] = gki_df['Sweeping'].rank(ascending=False, method='min').astype(int)
gki_df['Cmd Rk'] = gki_df['Command'].rank(ascending=False, method='min').astype(int)

# Reorder columns to pair the ranks next to their metrics
gki_df = gki_df[['Rk', 'Goalkeeper', 'Team', 'GKI', 'SS Rk', 'Shot Stopping', 'Dist Rk', 'Distribution', 'Swp Rk', 'Sweeping', 'Cmd Rk', 'Command']]

def generate_html_report(figs, title):
    html = f"<html><head><title>{title}</title><script src='https://cdn.plot.ly/plotly-latest.min.js'></script><style>body {{ background-color: #0E1117; color: white; font-family: sans-serif; padding: 20px; }} .chart-container {{ margin-bottom: 40px; border: 1px solid #333; padding: 10px; border-radius: 8px; }} </style></head><body><h1 style='text-align: center;'>{title}</h1>"
    for fig in figs: html += f"<div class='chart-container'>{fig.to_html(full_html=False, include_plotlyjs=False)}</div>"
    html += "</body></html>"
    return html

# --- GLOBAL SEASON FILTER SETUP ---
st.sidebar.header("Global Filters")
available_seasons = sorted([s for s in matches_df['Season'].unique().tolist() if s != 'Unknown Season'])
if "2025" not in available_seasons:
    available_seasons.append("2025")
if "2026" not in available_seasons:
    available_seasons.append("2026")
    
available_seasons = sorted(list(set(available_seasons)))
selected_season = st.sidebar.selectbox("Select Season", available_seasons)

# Filter matches and actions globally based on the selected season
season_matches_df = matches_df[matches_df['Season'] == selected_season]
season_actions_df = actions_df[actions_df['Match_ID'].isin(season_matches_df['Match_ID'])]

if "app_mode" not in st.session_state: st.session_state["app_mode"] = "League Benchmark (Opta)"
if "selected_match" not in st.session_state: 
    st.session_state["selected_match"] = matches_df['Match_ID'].dropna().unique()[0] if not matches_df.empty else None
if "selected_period_month" not in st.session_state: st.session_state["selected_period_month"] = None

def set_match_view(match_id):
    st.session_state["app_mode"] = "Single Match"
    st.session_state["selected_match"] = match_id

st.sidebar.header("Navigation")
modes = ["League Benchmark (Opta)", "Single Match", "Match Hub (Monthly)"]
current_index = modes.index(st.session_state["app_mode"])
selected_mode = st.sidebar.radio("Select Report Level", modes, index=current_index)
if selected_mode != st.session_state["app_mode"]:
    st.session_state["app_mode"] = selected_mode
    st.rerun()
report_mode = st.session_state["app_mode"]

st.sidebar.markdown("---")

def get_dynamic_logo(name):
    clean_name = name.replace(' ', '+')
    return f"https://ui-avatars.com/api/?name={clean_name}&background=0D1117&color=fff&size=150&bold=true&font-size=0.33"

def render_high_res_logo(width_px, align="left"):
    if os.path.exists("kr_logo.png"):
        with open("kr_logo.png", "rb") as img_file: b64_str = base64.b64encode(img_file.read()).decode()
        img_html = f'<img src="data:image/png;base64,{b64_str}" style="width: {width_px}px; height: auto;">'
    else: img_html = f'<img src="{get_dynamic_logo("KR Reykjavik")}" style="width: {width_px}px;">'
    st.markdown(f"<div style='display:flex; justify-content:flex-{'end' if align=='right' else 'start'};'>{img_html}</div>", unsafe_allow_html=True)

# ==========================================
# MODE 1: LEAGUE BENCHMARK (OPTA)
# ==========================================
if report_mode == "League Benchmark (Opta)":
    
    col_logo, col_title = st.columns([1, 8])
    with col_logo: render_high_res_logo(80)
    with col_title: st.markdown("<h1 style='margin-top: 10px;'>Besta Deild - Goalkeeper Index (GKI)</h1>", unsafe_allow_html=True)
    
    st.markdown("*Composite index across Shot Stopping (40%), Distribution (35%), Sweeping (15%), and Command (10%). Min-max normalised against the 2025 Besta deild population (n=13, ≥450 mins). Opta data produced by KR Analytics.*")
    st.markdown("---")

    if selected_season != "2025":
        st.info(f"Besta deild GKI tracking data is not yet available for the {selected_season} season. Please switch to the 2025 season to view the historical benchmark.")
        st.stop()
    else:
        # KR #1 Spotlight
        st.markdown("### 🥇 League Leader: Halldór Georgsson (KR)")
        kr_kpi1, kr_kpi2, kr_kpi3, kr_kpi4 = st.columns(4)
        kr_kpi1.metric(label="Overall GKI", value="0.643", delta="Rank: #1")
        kr_kpi2.metric(label="Distribution %", value="94.5%", delta="Rank: #1")
        kr_kpi3.metric(label="Progressive Carries", value="148")
        kr_kpi4.metric(label="Save %", value="61.3%", delta="Area for Dev", delta_color="inverse")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Visualizations
        col_radar, col_scatter = st.columns([1, 1])
        
        with col_radar:
            st.markdown("#### GKI Profile Comparison")
            
            def format_keeper_label(keeper_name):
                team_name = gki_df.loc[gki_df['Goalkeeper'] == keeper_name, 'Team'].iloc[0]
                return f"{keeper_name} ({team_name})"
                
            compare_keeper = st.selectbox(
                "Compare H. Georgsson to:", 
                gki_df[gki_df['Goalkeeper'] != 'H. Georgsson']['Goalkeeper'],
                format_func=format_keeper_label
            )
            
            kr_stats = gki_df[gki_df['Goalkeeper'] == 'H. Georgsson'].iloc[0]
            comp_stats = gki_df[gki_df['Goalkeeper'] == compare_keeper].iloc[0]
            
            categories = ['Shot Stopping', 'Distribution', 'Sweeping', 'Command']
            
            fig_gki_radar = go.Figure()
            fig_gki_radar.add_trace(go.Scatterpolar(
                r=[kr_stats[cat] for cat in categories] + [kr_stats[categories[0]]],
                theta=categories + [categories[0]],
                fill='toself',
                name='H. Georgsson (KR)',
                line_color='#00BFFF'
            ))
            fig_gki_radar.add_trace(go.Scatterpolar(
                r=[comp_stats[cat] for cat in categories] + [comp_stats[categories[0]]],
                theta=categories + [categories[0]],
                fill='toself',
                name=f"{comp_stats['Goalkeeper']} ({comp_stats['Team']})",
                line_color='#FF3333'
            ))
            
            fig_gki_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=True,
                template="plotly_dark",
                margin=dict(l=40, r=40, t=40, b=40)
            )
            st.plotly_chart(fig_gki_radar, use_container_width=True)

        with col_scatter:
            st.markdown("#### Shot Stopping vs. Workload (League)")
            if not opta_df.empty:
                fig_scatter = px.scatter(
                    opta_df, x="Saves_per_90", y="Save_Pct", 
                    color="Team", text="Player", size="Time Played",
                    title="Save % vs. Saves per 90",
                    labels={"Saves_per_90": "Saves per 90", "Save_Pct": "Save Percentage (%)"},
                    template="plotly_dark"
                )
                fig_scatter.update_traces(textposition='top center')
                fig_scatter.update_layout(margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_scatter, use_container_width=True)
            else:
                st.warning("Please upload 'GK_2025_all.json' to the repository to view dynamic scatter plots.")

        st.markdown("---")
        st.markdown("#### 🏆 2025 Besta deild GKI Leaderboard")
        st.dataframe(gki_df.style.background_gradient(cmap='viridis', subset=['GKI', 'Shot Stopping', 'Distribution', 'Sweeping', 'Command']), use_container_width=True)
        
        st.info("**Analyst Note:** Halldór ranks #1 overall (GKI 0.643) driven primarily by exceptional distribution (0.836 - best in league by a significant margin). His 94.5% distribution accuracy reflects KR's system requirement for an active sweeper-keeper. Shot stopping (0.486) is the weakest sub-score; 61.3% save rate and only 2 clean sheets in 25 appearances are areas for development.")

# ==========================================
# MODE 2: SINGLE MATCH REPORT
# ==========================================
elif report_mode == "Single Match":
    if season_matches_df.empty or season_actions_df.empty:
        st.warning(f"No Single Match Event Data Found for the {selected_season} season. Awaiting Opta match-by-match event pipeline integration into Airtable.")
        st.stop()
        
    def format_match_label(match_id):
        row = season_matches_df[season_matches_df['Match_ID'] == match_id].iloc[0]
        team = row.get('Team_GK', 'Unknown Team')
        opponent = row.get('Opponent', 'Unknown Opponent')
        venue = str(row.get('Venue', 'Home')).strip().title()
        date_val = row.get('Date', '')
        date_str = str(date_val) if pd.notna(date_val) and str(date_val).strip() != "" else 'Unknown Date'
        
        if venue == 'Away':
            return f"{opponent} vs {team} ({date_str})"
        return f"{team} vs {opponent} ({date_str})"

    st.sidebar.subheader("Match Selection")
    match_options = season_matches_df['Match_ID'].dropna().unique()
    selected_match = st.sidebar.selectbox("Select Match", match_options, format_func=format_match_label, key="selected_match")

    match_info = season_matches_df[season_matches_df['Match_ID'] == selected_match].iloc[0]
    match_all_actions = season_actions_df[season_actions_df['Match_ID'] == selected_match]

    match_passes = match_all_actions[match_all_actions['Action_Category'] == 'Pass'].copy()
    valid_passes = match_passes.dropna(subset=['Pass_Start_X', 'Pass_End_X']).copy()
    valid_passes.reset_index(drop=True, inplace=True) 

    is_shot = match_all_actions['Outcome'].astype(str).str.contains('Shot|Goal', case=False, na=False) | match_all_actions['PSxG'].notna()
    match_shots = match_all_actions[is_shot].copy()
    valid_shots = match_shots.dropna(subset=['Pass_Start_X', 'Pass_Start_Y']).copy()
    valid_shots.reset_index(drop=True, inplace=True)

    def_actions = match_all_actions[
        match_all_actions['Outcome'].astype(str).str.contains('Claim|Punch|Clearance|Smother|Sweeper|Interception', case=False, na=False) | 
        match_all_actions['Action_Category'].isin(['Clearance', 'Interception'])
    ].dropna(subset=['Pass_Start_X', 'Pass_Start_Y']).copy()
    def_actions.reset_index(drop=True, inplace=True)

    csv_data = match_all_actions.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(label="📥 Download Match Data (CSV)", data=csv_data, file_name=f"Match_{selected_match}_Data.csv", mime="text/csv")

    team_name = str(match_info.get('Team_GK', 'Home'))
    opp_name = str(match_info.get('Opponent', 'Away'))
    team_score = match_info.get('Team_Score', '-')
    opp_score = match_info.get('Opponent_Score', '-')
    match_venue = str(match_info.get('Venue', 'Home')).strip().title()

    if match_venue == 'Away':
        left_name, left_score = opp_name, opp_score
        right_name, right_score = team_name, team_score
        left_is_team = False
    else:
        left_name, left_score = team_name, team_score
        right_name, right_score = opp_name, opp_score
        left_is_team = True

    head_col1, head_col2, head_col3 = st.columns([1.5, 3, 1.5])
    with head_col1:
        if left_is_team:
            render_high_res_logo(100, align="left")
        else:
            st.markdown(f"<div style='display:flex; justify-content:flex-start;'><img src='{get_dynamic_logo(left_name)}' width='100'></div>", unsafe_allow_html=True)
            
    with head_col2:
        st.markdown(f"<h2 style='text-align: center; margin-bottom: 0px;'>{left_name} vs {right_name}</h2>", unsafe_allow_html=True)
        st.markdown(f"<h1 style='text-align: center; margin-top: 0px; font-size: 4rem;'>{left_score} - {right_score}</h1>", unsafe_allow_html=True)
        
    with head_col3:
        if not left_is_team:
            render_high_res_logo(100, align="right")
        else:
            st.markdown(f"<div style='display:flex; justify-content:flex-end;'><img src='{get_dynamic_logo(right_name)}' width='100'></div>", unsafe_allow_html=True)

    st.markdown("---")

    # SHOT STOPPING
    st.markdown("## 🧤 Shot Stopping")
    total_psxg = match_all_actions['PSxG'].sum()
    total_goals = match_all_actions['Goal_Conceded'].sum()
    goals_prevented = total_psxg - total_goals

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric(label="Total Shots Faced", value=len(valid_shots))
    kpi2.metric(label="Total PSxG Faced", value=f"{total_psxg:.2f}")
    kpi3.metric(label="Goals Conceded", value=int(total_goals))
    kpi4.metric(label="Goals Prevented", value=f"{goals_prevented:+.2f}", delta="Shot Stopping Impact" if goals_prevented >= 0 else "Underperformed Expected", delta_color="normal" if goals_prevented >= 0 else "inverse")

    shot_pitch, shot_video = st.columns([2.5, 1.5]) 
    with shot_pitch:
        selected_shot_idx = None
        if "shot_chart" in st.session_state:
            points = st.session_state.shot_chart.get("selection", {}).get("points", [])
            if points: 
                cd = points[0].get("customdata")
                if isinstance(cd, list) and len(cd) > 0: selected_shot_idx = cd[0]
                elif cd is not None: selected_shot_idx = cd

        fig_shots = go.Figure()
        fig_shots.add_shape(type="rect", x0=0, y0=0, x1=60, y1=80, line=dict(color="white", width=2))
        fig_shots.add_shape(type="rect", x0=0, y0=18, x1=18, y1=62, line=dict(color="white", width=2))
        fig_shots.add_shape(type="rect", x0=0, y0=30, x1=6, y1=50, line=dict(color="white", width=2))
        fig_shots.add_shape(type="circle", x0=50, y0=30, x1=70, y1=50, line=dict(color="white", width=2))
        fig_shots.add_shape(type="rect", x0=-2, y0=36, x1=0, y1=44, line=dict(color="white", width=2), fillcolor="rgba(255,255,255,0.1)")

        for i, row in valid_shots.iterrows():
            is_active = (selected_shot_idx == i)
            if row.get('Goal_Conceded') == 1: base_color = 'red'
            elif 'Save' in str(row.get('Action_Category')) or 'Save' in str(row.get('Outcome')): base_color = '#00FF00' 
            else: base_color = 'lightgray'

            if is_active: line_color, line_width, opacity = '#00BFFF', 5, 1.0
            else: line_color, line_width = base_color, 3; opacity = 0.3 if selected_shot_idx is not None else 1.0

            start_x = pd.to_numeric(row.get('Pass_Start_X'), errors='coerce')
            start_y = pd.to_numeric(row.get('Pass_Start_Y'), errors='coerce')
            end_x = pd.to_numeric(row.get('Pass_End_X'), errors='coerce')
            end_y = pd.to_numeric(row.get('Pass_End_Y'), errors='coerce')

            if pd.isna(start_x): start_x = 0
            if pd.isna(start_y): start_y = 0
            if pd.isna(end_x): end_x = start_x 
            if pd.isna(end_y): end_y = start_y

            distance_str = "Unknown"
            if start_x != end_x or start_y != end_y:
                dist = ((end_x - start_x)**2 + (end_y - start_y)**2)**0.5
                distance_str = f"{dist:.1f} yds"

            raw_notes = row.get('Scout_Analysis', 'No notes.')
            wrapped_notes = "<br>".join(textwrap.wrap(str(raw_notes), width=50))
            hover_text = f"<b>Minute: {row.get('Match_Minute')}</b><br>PSxG: {row.get('PSxG', 0)}<br>Distance: {distance_str}<br>---<br><i>{wrapped_notes}</i>"

            if start_x > 60:
                start_x = 120 - start_x
                start_y = 80 - start_y
                end_x = 120 - end_x
                end_y = 80 - end_y

            fig_shots.add_trace(go.Scatter(x=[start_x, end_x], y=[start_y, end_y], mode='lines+markers', line=dict(color=line_color, width=line_width), marker=dict(size=6, color=line_color), opacity=opacity, hoverinfo='text', hovertext=[hover_text, hover_text], customdata=[i, i], showlegend=False))
            
            if start_x != end_x or start_y != end_y:
                fig_shots.add_annotation(x=end_x, y=end_y, ax=start_x, ay=start_y, xref='x', yref='y', axref='x', ayref='y', showarrow=True, arrowhead=2, arrowsize=0.6, arrowwidth=line_width, arrowcolor=line_color, opacity=opacity)

        if selected_shot_idx is not None and selected_shot_idx < len(valid_shots):
            selected_row = valid_shots.iloc[selected_shot_idx]
            gk_x = pd.to_numeric(selected_row.get('GK_Position_X'), errors='coerce')
            gk_y = pd.to_numeric(selected_row.get('GK_Position_Y'), errors='coerce')
            
            if pd.notna(gk_x) and pd.notna(gk_y):
                if gk_x > 60:
                    gk_plot_x, gk_plot_y = 120 - gk_x, 80 - gk_y
                else:
                    gk_plot_x, gk_plot_y = gk_x, gk_y
                    
                fig_shots.add_trace(go.Scatter(
                    x=[gk_plot_x], y=[gk_plot_y],
                    mode='markers',
                    marker=dict(size=14, color='#39FF14', line=dict(color='white', width=2)),
                    hoverinfo='text', hovertext="Goalkeeper Position", showlegend=False
                ))

        fig_shots.update_layout(xaxis=dict(range=[-3, 45], showgrid=False, zeroline=False, visible=False), yaxis=dict(range=[10, 70], showgrid=False, zeroline=False, visible=False, scaleanchor="x", scaleratio=1), height=550, margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', clickmode='event+select')
        st.plotly_chart(fig_shots, width="stretch", on_select="rerun", selection_mode="points", key="shot_chart")

        with st.expander("📥 Download Shot Map & Data"):
            col_dl1, col_dl2 = st.columns(2)
            col_dl1.download_button("Download Map (HTML)", data=fig_shots.to_html(include_plotlyjs='cdn'), file_name="Shot_Map.html", mime="text/html")
            col_dl2.download_button("Download Data (CSV)", data=valid_shots.to_csv(index=False).encode('utf-8'), file_name="Shot_Data.csv", mime="text/csv")

    with shot_video:
        st.markdown("### Shot Video Clip")
        if selected_shot_idx is not None and selected_shot_idx < len(valid_shots):
            if st.button("🔙 Clear Shot Selection", key="clear_shot"):
                st.session_state.shot_chart = {"selection": {"points": [], "box": [], "lasso": []}}; st.rerun()

            selected_row = valid_shots.iloc[selected_shot_idx]
            vid_url = selected_row.get("Video_URL")
            if pd.notna(vid_url) and str(vid_url).strip() != "": st.video(str(vid_url).strip())
            else: st.warning("No Video URL logged for this shot.")
                
            with st.container(height=150, border=True):
                notes = selected_row.get("Scout_Analysis", "")
                if pd.notna(notes) and str(notes).strip() != "": st.write(notes)
                else: st.info("No detailed analysis for this shot.")

            sel_start_x = pd.to_numeric(selected_row.get('Pass_Start_X'), errors='coerce')
            sel_start_y = pd.to_numeric(selected_row.get('Pass_Start_Y'), errors='coerce')
            sel_end_x = pd.to_numeric(selected_row.get('Pass_End_X'), errors='coerce')
            sel_end_y = pd.to_numeric(selected_row.get('Pass_End_Y'), errors='coerce')
            raw_end_z = pd.to_numeric(selected_row.get('Pass_End_Z'), errors='coerce')
            raw_gk_y = pd.to_numeric(selected_row.get('GK_Position_Y'), errors='coerce')

            sel_dist_str = "Unknown"
            if pd.notna(sel_start_x) and pd.notna(sel_start_y) and pd.notna(sel_end_x) and pd.notna(sel_end_y):
                sel_dist = ((sel_end_x - sel_start_x)**2 + (sel_end_y - sel_start_y)**2)**0.5
                sel_dist_str = f"{sel_dist:.1f} yds"

            if pd.notna(sel_end_y) and pd.notna(raw_end_z):
                st.markdown("#### Goal Placement")
                
                if pd.notna(sel_start_x) and sel_start_x > 60:
                    y_centered = sel_end_y - 40
                else:
                    y_centered = 40 - sel_end_y
                
                fig_goal = go.Figure()
                
                fig_goal.add_shape(type="rect", x0=-4, y0=0, x1=4, y1=2.67, line=dict(color="white", width=4))
                fig_goal.add_shape(type="line", x0=-6, y0=0, x1=6, y1=0, line=dict(color="#4CAF50", width=3))
                
                if pd.notna(raw_gk_y):
                    if pd.notna(sel_start_x) and sel_start_x > 60:
                        gk_y_centered = raw_gk_y - 40
                    else:
                        gk_y_centered = 40 - raw_gk_y
                        
                    fig_goal.add_trace(go.Scatter(
                        x=[gk_y_centered], y=[0.1], mode='markers',
                        name='Goalkeeper',
                        marker=dict(size=22, color='#00FFFF', symbol='triangle-up', line=dict(color='white', width=1)),
                        hoverinfo='text', hovertext="Goalkeeper Position", showlegend=True
                    ))

                point_color = 'red' if selected_row.get('Goal_Conceded') == 1 else '#00FF00'
                fig_goal.add_trace(go.Scatter(
                    x=[y_centered], y=[raw_end_z], mode='markers',
                    name='Shot',
                    marker=dict(size=14, color=point_color, symbol='circle', line=dict(color='white', width=2)),
                    hoverinfo='text', hovertext=f"Ball Height: {raw_end_z} yds", showlegend=True
                ))
                
                fig_goal.update_layout(
                    xaxis=dict(range=[-6, 6], visible=False),
                    yaxis=dict(range=[-0.5, 3.5], visible=False, scaleanchor="x", scaleratio=1, constraintoward="bottom"),
                    height=200, margin=dict(l=0, r=0, t=10, b=0),
                    legend=dict(
                        orientation="v", yanchor="top", y=0.95, xanchor="right", x=0.95,
                        font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.5)", bordercolor="white", borderwidth=1
                    ),
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', hovermode="closest"
                )
                st.plotly_chart(fig_goal, width="stretch", key="goal_mouth_chart")

            sel_outcome = str(selected_row.get('Outcome', 'Unknown'))
            sel_psxg = pd.to_numeric(selected_row.get('PSxG'), errors='coerce')
            sel_psxg_str = f"{sel_psxg:.2f}" if pd.notna(sel_psxg) else "N/A"
            sel_minute = str(selected_row.get('Match_Minute', 'N/A'))

            st.markdown("#### Shot Details")
            mc1, mc2 = st.columns(2)
            mc1.metric("Minute", f"{sel_minute}'")
            mc2.metric("Outcome", sel_outcome)
            
            mc3, mc4 = st.columns(2)
            mc3.metric("PSxG", sel_psxg_str)
            mc4.metric("Distance", sel_dist_str)

        else:
            st.info("👆 Click on any shot line to load the video.")

    # --- SWEEPER KEEPER MAP (Left-Aligned) ---
    st.markdown("---")
    st.markdown("## 🧹 Box Control & Sweeping")
    swp_kpi1, swp_kpi2, swp_kpi3 = st.columns(3)
    swp_kpi1.metric("Total Defensive Actions", len(def_actions))
    swp_kpi2.metric("High Claims", len(def_actions[def_actions['Outcome'].astype(str).str.contains('Claim', case=False, na=False)]))
    swp_kpi3.metric("Sweeping / Clearances", len(def_actions[def_actions['Outcome'].astype(str).str.contains('Clearance|Sweeper', case=False, na=False)]))
    
    swp_pitch, swp_info = st.columns([2.5, 1.5])
    with swp_pitch:
        selected_swp_idx = None
        if "swp_chart" in st.session_state:
            points = st.session_state.swp_chart.get("selection", {}).get("points", [])
            if points: 
                cd = points[0].get("customdata")
                if isinstance(cd, list) and len(cd) > 0: selected_swp_idx = cd[0]
                elif cd is not None: selected_swp_idx = cd

        fig_sweeper = go.Figure()
        fig_sweeper.add_shape(type="rect", x0=0, y0=0, x1=60, y1=80, line=dict(color="white", width=2))
        fig_sweeper.add_shape(type="rect", x0=0, y0=18, x1=18, y1=62, line=dict(color="white", width=2))
        fig_sweeper.add_shape(type="rect", x0=0, y0=30, x1=6, y1=50, line=dict(color="white", width=2))
        fig_sweeper.add_shape(type="circle", x0=50, y0=30, x1=70, y1=50, line=dict(color="white", width=2))
        
        for i, row in def_actions.iterrows():
            is_active = (selected_swp_idx == i)
            sx, sy = row.get('Pass_Start_X', 0), row.get('Pass_Start_Y', 0)
            
            if sx > 60: 
                sx, sy = 120 - sx, 80 - sy 
                
            outcome = str(row.get('Outcome', 'Unknown'))
            if 'Clearance' in outcome: base_color = '#FFEA00'
            elif 'Claim' in outcome: base_color = '#B0008E'
            elif 'Interception' in outcome: base_color = '#FF5500'
            else: base_color = '#00BFFF'
            
            size = 18 if is_active else 12
            opacity = 1.0 if not selected_swp_idx or is_active else 0.3
            
            hover = f"Minute: {row.get('Match_Minute')}<br>Action: {outcome}"
            fig_sweeper.add_trace(go.Scatter(
                x=[sx], y=[sy], mode='markers', 
                marker=dict(size=size, color=base_color, line=dict(color='white', width=1)), 
                opacity=opacity, hoverinfo='text', hovertext=hover, customdata=[i], showlegend=False
            ))
            
        fig_sweeper.update_layout(xaxis=dict(range=[-5, 55], visible=False), yaxis=dict(range=[85, -5], visible=False, scaleanchor="x"), height=550, margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', clickmode='event+select')
        st.plotly_chart(fig_sweeper, width="stretch", on_select="rerun", selection_mode="points", key="swp_chart")

    with swp_info:
        st.markdown("### Action Context")
        if selected_swp_idx is not None and selected_swp_idx < len(def_actions):
            if st.button("🔙 Clear Selection", key="clear_swp"):
                st.session_state.swp_chart = {"selection": {"points": []}}; st.rerun()

            sel_swp = def_actions.iloc[selected_swp_idx]
            st.metric("Action Type", sel_swp.get('Outcome', 'Unknown'))
            st.metric("Match Minute", f"{sel_swp.get('Match_Minute', 'N/A')}'")
            
            vid_url = sel_swp.get("Video_URL")
            if pd.notna(vid_url) and str(vid_url).strip() != "": st.video(str(vid_url).strip())
            else: st.warning("No Video URL logged for this action.")
            
            with st.container(height=150, border=True):
                notes = sel_swp.get("Scout_Analysis", "")
                if pd.notna(notes) and str(notes).strip() != "": st.write(notes)
                else: st.info("No detailed analysis for this action.")
        else:
            st.info("👆 Click on any defensive action on the pitch to see details.")


    # DISTRIBUTION & PASSING
    st.markdown("---")
    st.markdown("## 👟 Distribution & Passing")
    
    valid_passes['Is_Dead_Ball'] = valid_passes['Play_Pattern'].astype(str).str.contains('Goal Kick|Free Kick|Corner|Penalty', case=False)
    valid_passes['Play_State'] = valid_passes['Is_Dead_Ball'].map({True: 'Dead Ball', False: 'Open Play'})
    
    total_passes = len(valid_passes)
    completed_passes = len(valid_passes[valid_passes['Outcome'] == 'Complete'])
    pass_accuracy = (completed_passes / total_passes * 100) if total_passes > 0 else 0

    p_kpi1, p_kpi2, p_kpi3 = st.columns(3)
    p_kpi1.metric(label="Passing Accuracy", value=f"{pass_accuracy:.1f}%")
    p_kpi2.metric(label="Total Passes Attempted", value=total_passes)
    p_kpi3.metric(label="Passes Completed", value=completed_passes)

    pass_pitch, pass_video = st.columns([2.5, 1.5]) 
    with pass_pitch:
        selected_pass_idx = None
        if "pitch_chart" in st.session_state:
            points = st.session_state.pitch_chart.get("selection", {}).get("points", [])
            if points: 
                cd = points[0].get("customdata")
                if isinstance(cd, list) and len(cd) > 0: selected_pass_idx = cd[0]
                elif cd is not None: selected_pass_idx = cd
        
        st.markdown("""
        <div style='background-color: rgba(255,255,255,0.05); padding: 12px; border-radius: 8px; margin-bottom: 15px;'>
            <div style='font-size: 0.85rem; color: #ccc; margin-bottom: 10px;'><b>Tactical Height Logic:</b> Categorization is based on pitch zone and pass height labels. <b>Play Into</b> requires a lofted/high ball over the defense.</div>
            <div style='display: flex; flex-wrap: wrap; gap: 15px; font-size: 0.85rem;'>
                <div style='display: flex; align-items: center; gap: 5px;'><span style='width: 12px; height: 12px; border-radius: 50%; background-color: #00FF00;'></span> Complete (Base)</div>
                <div style='display: flex; align-items: center; gap: 5px;'><span style='width: 12px; height: 12px; border-radius: 50%; background-color: #FF3333;'></span> Incomplete (Base)</div>
                <div style='border-left: 1px solid #555; height: 16px; margin: 0 5px;'></div>
                <div style='display: flex; align-items: center; gap: 5px;'><span style='width: 12px; height: 12px; border-radius: 50%; background-color: #0066FF;'></span> Play Through</div>
                <div style='display: flex; align-items: center; gap: 5px;'><span style='width: 12px; height: 12px; border-radius: 50%; background-color: #B0008E;'></span> Play Into</div>
                <div style='display: flex; align-items: center; gap: 5px;'><span style='width: 12px; height: 12px; border-radius: 50%; background-color: #FFEA00;'></span> Play Around</div>
                <div style='display: flex; align-items: center; gap: 5px;'><span style='width: 12px; height: 12px; border-radius: 50%; background-color: #FF5500;'></span> Play Beyond</div>
                <div style='display: flex; align-items: center; gap: 5px;'><span style='width: 12px; height: 12px; border-radius: 50%; background-color: #FFFFFF;'></span> Short/Retain</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        fig_passes = go.Figure()
        fig_passes.add_shape(type="rect", x0=0, y0=0, x1=120, y1=80, line=dict(color="white", width=2))
        fig_passes.add_shape(type="line", x0=60, y0=0, x1=60, y1=80, line=dict(color="white", width=2))
        fig_passes.add_shape(type="circle", x0=50, y0=30, x1=70, y1=50, line=dict(color="white", width=2))
        fig_passes.add_shape(type="rect", x0=0, y0=18, x1=18, y1=62, line=dict(color="white", width=2))
        fig_passes.add_shape(type="rect", x0=0, y0=30, x1=6, y1=50, line=dict(color="white", width=2))
        fig_passes.add_shape(type="rect", x0=102, y0=18, x1=120, y1=62, line=dict(color="white", width=2))
        fig_passes.add_shape(type="rect", x0=114, y0=30, x1=120, y1=50, line=dict(color="white", width=2))

        def get_intent_color(bucket):
            if bucket == 'Play Through': return '#0066FF'
            if bucket == 'Play Around': return '#FFEA00'
            if bucket == 'Play Into': return '#B0008E'
            if bucket == 'Play Beyond': return '#FF5500'
            if bucket == 'Short / Retain': return '#FFFFFF'
            return '#FFFFFF'

        for i, row in valid_passes.iterrows():
            is_active = (selected_pass_idx == i)
            base_color = '#00FF00' if row['Outcome'] == 'Complete' else '#FF3333'
            tip_color = get_intent_color(row['Tactical_Bucket'])
            
            if is_active: line_width, opacity = 5, 1.0          
            else: line_width, opacity = 3, (0.3 if selected_pass_idx is not None else 1.0)

            pressure_txt = "Pressured" if row.get('Under_Pressure') == 1 else "Uncontested"
            hover_text = f"<b>Minute: {row.get('Match_Minute')}</b><br>Intent: {row.get('Tactical_Bucket')}<br>Height: {row.get('Pass_Height', 'Unknown')}<br>Context: {row.get('Play_State')} ({pressure_txt})<br>Outcome: {row.get('Outcome')}"

            x0 = pd.to_numeric(row.get('Pass_Start_X'), errors='coerce')
            y0 = pd.to_numeric(row.get('Pass_Start_Y'), errors='coerce')
            x1 = pd.to_numeric(row.get('Pass_End_X'), errors='coerce')
            y1 = pd.to_numeric(row.get('Pass_End_Y'), errors='coerce')

            if pd.isna(x0) or pd.isna(y0) or pd.isna(x1) or pd.isna(y1): continue

            num_segments = 15
            for step in range(num_segments):
                f0 = step / num_segments
                f1 = (step + 1) / num_segments
                seg_x = [x0 + (x1 - x0) * f0, x0 + (x1 - x0) * f1]
                seg_y = [y0 + (y1 - y0) * f0, y0 + (y1 - y0) * f1]
                color = interpolate_color(base_color, tip_color, f0)
                
                fig_passes.add_trace(go.Scatter(
                    x=seg_x, y=seg_y, mode='lines',
                    line=dict(color=color, width=line_width),
                    customdata=[i, i], hoverinfo='text', hovertext=[hover_text, hover_text],
                    showlegend=False, opacity=opacity
                ))

            fig_passes.add_trace(go.Scatter(
                x=[x1], y=[y1], mode='markers',
                marker=dict(size=8, color=tip_color, line=dict(color='white', width=1)),
                customdata=[i], hoverinfo='text', hovertext=[hover_text],
                showlegend=False, opacity=opacity
            ))

        fig_passes.update_layout(xaxis=dict(range=[-5, 125], showgrid=False, zeroline=False, visible=False), yaxis=dict(range=[85, -5], showgrid=False, zeroline=False, visible=False, scaleanchor="x", scaleratio=1), height=550, margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', clickmode='event+select')
        st.plotly_chart(fig_passes, width="stretch", on_select="rerun", selection_mode="points", key="pitch_chart")

        with st.expander("📥 Download Pass Map & Data"):
            col_dl3, col_dl4 = st.columns(2)
            col_dl3.download_button("Download Map (HTML)", data=fig_passes.to_html(include_plotlyjs='cdn'), file_name="Pass_Map.html", mime="text/html")
            col_dl4.download_button("Download Data (CSV)", data=valid_passes.to_csv(index=False).encode('utf-8'), file_name="Pass_Data.csv", mime="text/csv")

    with pass_video:
        st.markdown("### Pass Context")
        if selected_pass_idx is not None and selected_pass_idx < len(valid_passes):
            if st.button("🔙 Clear Pass Selection", key="clear_pass"):
                st.session_state.pitch_chart = {"selection": {"points": []}}; st.rerun()

            sel_row = valid_passes.iloc[selected_pass_idx]
            
            st.metric("Play Phase", sel_row.get('Play_State', 'Unknown'))
            st.metric("Under Pressure", "Yes" if sel_row.get('Under_Pressure') == 1 else "No")
            
            vid_url = sel_row.get("Video_URL")
            if pd.notna(vid_url) and str(vid_url).strip() != "": st.video(str(vid_url).strip())
            else: st.warning("No Video URL logged for this pass.")
            
            with st.container(height=150, border=True):
                notes = sel_row.get("Scout_Analysis", "")
                if pd.notna(notes) and str(notes).strip() != "": st.write(notes)
                else: st.info("No detailed analysis for this pass.")
                
        else:
            st.info("👆 Click on any pass on the pitch to load its context.")

    # --- RESTORED: DISTRIBUTION ANALYTICS AND RADAR CHART ---
    st.markdown("### Distribution Analytics & Overall Involvement")
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        if not valid_passes.empty:
            tactical_df = valid_passes.groupby(['Tactical_Bucket', 'Outcome']).size().reset_index(name='Count')
            fig_bar = px.bar(tactical_df, x='Tactical_Bucket', y='Count', color='Outcome', title="Passes by Tactical Intent", color_discrete_map={'Complete': '#00FF00', 'Incomplete': '#FF3333'}, template="plotly_dark")
            st.plotly_chart(fig_bar, width="stretch")
            
    with chart_col2:
        if not match_all_actions.empty:
            actions_df_counts = match_all_actions['Action_Category'].value_counts().reset_index()
            actions_df_counts.columns = ['Action', 'Count']
            
            actions_df_counts['Action'] = actions_df_counts['Action'].replace({'Pass': 'Distribution'})
            
            max_val = actions_df_counts['Count'].max()
            
            fig_radar = px.line_polar(
                actions_df_counts, r='Count', theta='Action', line_close=True,
                title="Overall Goalkeeper Involvement Radar", template="plotly_dark",
                color_discrete_sequence=['#00BFFF']
            )
            fig_radar.update_traces(fill='toself')
            
            fig_radar.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, max_val * 1.1] 
                    )
                )
            )
            
            st.plotly_chart(fig_radar, width="stretch")

    st.markdown("### Situational Breakdown")
    c1, c2 = st.columns(2)
    with c1:
        if not valid_passes.empty:
            pressure_df = valid_passes.groupby(['Under_Pressure', 'Outcome']).size().reset_index(name='Count')
            pressure_df['Pressure Label'] = pressure_df['Under_Pressure'].map({1: 'Pressured', 0: 'Uncontested'})
            st.plotly_chart(px.bar(pressure_df, x='Pressure Label', y='Count', color='Outcome', title="Accuracy Under Pressure", color_discrete_map={'Complete': '#00FF00', 'Incomplete': '#FF3333'}, template="plotly_dark"), width="stretch")
    with c2:
        if not valid_passes.empty:
            phase_df = valid_passes.groupby(['Play_State', 'Outcome']).size().reset_index(name='Count')
            st.plotly_chart(px.bar(phase_df, x='Play_State', y='Count', color='Outcome', title="Dead Ball vs Open Play", color_discrete_map={'Complete': '#00FF00', 'Incomplete': '#FF3333'}, template="plotly_dark"), width="stretch")

    st.markdown("---")
    st.markdown("## 📝 Overall Match Analysis")
    match_notes = match_info.get('Match_Summary_Notes', '')
    if pd.notna(match_notes) and str(match_notes).strip() != "": st.info(match_notes)
    else: st.warning("No overall summary notes logged for this match yet.")

    st.markdown("---")
    st.markdown("### 📝 Coach's Post-Match Notes")
    st.markdown("*Use this space to log your internal coaching notes, training focus areas, and development feedback for the upcoming sessions.*")
    
    note_key = f"SingleMatch_{selected_match}"
    existing_note = saved_notes.get(note_key, "")
    
    with st.form(key=f"form_{note_key}"):
        coach_note = st.text_area("Coach's Summary Notes:", value=existing_note, height=200, placeholder="Log your post-match training focus areas here...")
        submit_btn = st.form_submit_button("💾 Save Notes to Airtable")
        if submit_btn:
            if save_note_to_airtable(note_key, "Single Match", str(selected_match), coach_note):
                st.session_state["saved_notes"][note_key] = coach_note
                st.success("Notes successfully synced to database!")
            else:
                st.error("Failed to save notes. Check your Airtable credentials.")

# ==========================================
# MODE 3: MATCH HUB (MONTHLY)
# ==========================================
else:
    if season_matches_df.empty or season_actions_df.empty:
        st.warning(f"No Match Event Data Found for the {selected_season} season yet. Awaiting Opta match-by-match event pipeline integration into Airtable.")
        st.stop()
        
    st.sidebar.subheader("Select Month")
    available_periods = [m for m in season_matches_df['Month_Year'].unique() if m != 'Unknown Month']
    if not available_periods:
        st.error(f"No valid match dates found for the {selected_season} season.")
        st.stop()
        
    if st.session_state["selected_period_month"] not in available_periods:
        st.session_state["selected_period_month"] = available_periods[0]
        
    selected_period = st.sidebar.selectbox("Month", available_periods, key="selected_period_month")
    agg_matches = season_matches_df[season_matches_df['Month_Year'] == selected_period]
    report_title = f"{selected_period} Performance Report"
    analysis_title = "Monthly Performance Analysis"

    agg_match_ids = agg_matches['Match_ID'].tolist()
    agg_actions = season_actions_df[season_actions_df['Match_ID'].isin(agg_match_ids)]

    total_matches = len(agg_matches)
    clean_sheets = agg_matches['Opponent_Score'].apply(lambda x: 1 if pd.to_numeric(x, errors='coerce') == 0 else 0).sum()
    
    total_psxg = agg_actions['PSxG'].sum()
    total_goals_conceded = agg_actions['Goal_Conceded'].sum()
    goals_prevented = total_psxg - total_goals_conceded
    
    is_shot = agg_actions['Outcome'].astype(str).str.contains('Shot|Goal', case=False, na=False) | agg_actions['PSxG'].notna()
    shots_df = agg_actions[is_shot]
    total_shots_faced = len(shots_df)
    
    total_saves = len(shots_df[shots_df['Outcome'].astype(str).str.contains('Save', case=False, na=False)])
    save_pct = (total_saves / total_shots_faced * 100) if total_shots_faced > 0 else 0

    claim_sweep_actions = agg_actions[(agg_actions['Action_Category'] == 'Goal Keeper') & (agg_actions['Outcome'].astype(str).str.contains('Claim|Punch|Clearance|Sweeper', case=False, na=False))]
    total_high_claims = len(claim_sweep_actions)

    passes_df = agg_actions[agg_actions['Action_Category'] == 'Pass']
    total_passes = len(passes_df)
    completed_passes = len(passes_df[passes_df['Outcome'] == 'Complete'])
    pass_pct = (completed_passes / total_passes * 100) if total_passes > 0 else 0

    long_balls = passes_df[passes_df['Tactical_Bucket'] == 'Play Beyond']
    total_long_balls = len(long_balls)
    completed_long_balls = len(long_balls[long_balls['Outcome'] == 'Complete'])
    long_ball_pct = (completed_long_balls / total_long_balls * 100) if total_long_balls > 0 else 0

    col_logo, col_title = st.columns([1, 8])
    with col_logo: render_high_res_logo(80)
    with col_title: st.markdown(f"<h1 style='margin-top: 10px;'>{report_title}</h1>", unsafe_allow_html=True)
    
    st.markdown("---")

    st.markdown("### 🧤 Shot Stopping & Box Control")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Matches Played", total_matches)
    col2.metric("Clean Sheets", clean_sheets)
    col3.metric("Total Saves", total_saves, delta=f"{save_pct:.1f}% Save Pct", delta_color="off")
    col4.metric("Expected Goals Prevented", f"{goals_prevented:+.2f}", delta="Positive Impact" if goals_prevented > 0 else "Underperformed", delta_color="normal" if goals_prevented > 0 else "inverse")
    col5.metric("PSxG Faced", f"{total_psxg:.2f}")
    col6.metric("High Claims/Sweeps", total_high_claims)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 👟 Distribution Mastery")
    d_col1, d_col2, d_col3, d_col4 = st.columns(4)
    d_col1.metric("Total Passes", total_passes)
    d_col2.metric("Passing Accuracy", f"{pass_pct:.1f}%")
    d_col3.metric("Long Balls Attempted", total_long_balls)
    d_col4.metric("Long Ball Accuracy", f"{long_ball_pct:.1f}%")

    st.markdown("---")
    st.markdown("### 📈 Form Tracker: PSxG Prevented")
    
    if not agg_actions.empty:
        match_agg_trend = agg_actions.groupby('Match_ID').agg(PSxG=('PSxG', 'sum'), Goals_Conceded=('Goal_Conceded', 'sum')).reset_index()
        match_agg_trend['PSxG_Prevented'] = (match_agg_trend['PSxG'] - match_agg_trend['Goals_Conceded']).round(2)
        trend_df = pd.merge(match_agg_trend, agg_matches[['Match_ID', 'Date_Parsed', 'Opponent', 'Venue', 'Month_Year']], on='Match_ID', how='left')
        
        trend_df = trend_df.sort_values('Date_Parsed')
        def format_ha(row):
            ha_str = "(H)" if str(row.get('Venue', 'Home')).strip().title() != "Away" else "(A)"
            return f"{row['Opponent']} {ha_str}"
        trend_df['X_Label'] = trend_df.apply(format_ha, axis=1)
        x_data, y_data, custom_data = trend_df['X_Label'], trend_df['PSxG_Prevented'], trend_df['Match_ID']
        title, min_y_scale = "Game-by-Game Form (PSxG Prevented)", 3 

        fig_trend = go.Figure()
        fig_trend.add_shape(type="line", x0=-0.5, x1=len(x_data)-0.5, y0=0, y1=0, line=dict(color="gray", width=2, dash="dash"))
        fig_trend.add_trace(go.Scatter(x=x_data, y=y_data, mode='lines+markers', marker=dict(size=14, color=['#00FF00' if val >= 0 else 'red' for val in y_data], line=dict(color='white', width=2)), line=dict(color='#00BFFF', width=3), customdata=custom_data, hovertemplate="<b>%{x}</b><br>PSxG Prevented: %{y:+.2f}<extra></extra>"))
        current_max = max(min_y_scale, (y_data.abs().max() if not y_data.empty else 0) * 1.2)
        
        fig_trend.update_layout(title=title, yaxis=dict(range=[-current_max, current_max], title="PSxG Prevented", zeroline=False), xaxis=dict(title="Match"), template='plotly_dark', height=350, clickmode='event+select', margin=dict(l=20, r=20, t=40, b=20))
        
        st.info("👆 Click on any marker to jump to that specific report.")
        trend_selection = st.plotly_chart(fig_trend, width="stretch", on_select="rerun", selection_mode="points", key="trend_chart_monthly")
        
        if trend_selection and "selection" in trend_selection and "points" in trend_selection["selection"]:
            points = trend_selection["selection"]["points"]
            if len(points) > 0 and points[0].get("pointIndex") is not None:
                clicked_idx = points[0]["pointIndex"]
                st.session_state["app_mode"], st.session_state["selected_match"] = "Single Match", trend_df.iloc[clicked_idx]['Match_ID']
                st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📅 Monthly Match Log")
    
    if agg_matches.empty:
        st.info("No matches scheduled or played in this month yet.")
    else:
        for _, match_row in agg_matches.sort_values('Date_Parsed').iterrows():
            date_str = match_row['Date_Parsed'].strftime('%Y-%m-%d') if pd.notna(match_row['Date_Parsed']) else 'Unknown Date'
            team, opp, t_score, o_score, m_id = str(match_row.get('Team_GK', 'KR Reykjavik')), str(match_row.get('Opponent', 'Opponent')), str(match_row.get('Team_Score', '-')), str(match_row.get('Opponent_Score', '-')), match_row['Match_ID']
            
            col_text, col_btn = st.columns([6, 2])
            with col_text:
                match_str = f"<b>[{date_str}]</b> &nbsp; {opp} &nbsp;<b>{o_score} - {t_score}</b>&nbsp; {team}" if str(match_row.get('Venue', 'Home')).strip().title() == 'Away' else f"<b>[{date_str}]</b> &nbsp; {team} &nbsp;<b>{t_score} - {o_score}</b>&nbsp; {opp}"
                st.markdown(f"<div style='padding-top: 10px; font-size: 1.1rem;'>{match_str}</div>", unsafe_allow_html=True)
            with col_btn:
                st.button("🔍 Go to Report", key=f"btn_{m_id}", on_click=set_match_view, args=(m_id,))

    st.markdown("---")
    st.markdown("### Profile Breakdowns")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        match_agg = agg_actions.groupby('Match_ID').agg(PSxG=('PSxG', 'sum'), Goals_Conceded=('Goal_Conceded', 'sum')).reset_index()
        merge_cols = ['Match_ID', 'Date_Parsed', 'Opponent']
        if 'Venue' in agg_matches.columns: merge_cols.append('Venue')
        match_agg = pd.merge(match_agg, agg_matches[merge_cols], on='Match_ID', how='left')
        
        def create_match_label(row):
            d, v = row['Date_Parsed'].strftime('%m/%d'), str(row.get('Venue', 'Home')).strip().title()
            return f"{d} {'@' if v == 'Away' else 'vs'} {row['Opponent']}"
            
        match_agg['Match_Label'] = match_agg.apply(create_match_label, axis=1)
        match_agg = match_agg.sort_values('Date_Parsed')

        fig_bar = go.Figure(data=[go.Bar(name='PSxG Faced', x=match_agg['Match_Label'], y=match_agg['PSxG'], marker_color='#00BFFF'), go.Bar(name='Goals Conceded', x=match_agg['Match_Label'], y=match_agg['Goals_Conceded'], marker_color='red')])
        fig_bar.update_layout(barmode='group', title='PSxG vs Goals Conceded per Match', template='plotly_dark')
        st.plotly_chart(fig_bar, width="stretch")

    with chart_col2:
        if not passes_df.empty:
            dist_agg = passes_df['Tactical_Bucket'].value_counts().reset_index()
            dist_agg.columns = ['Tactical Focus', 'Count']
            st.plotly_chart(px.pie(dist_agg, names='Tactical Focus', values='Count', title="Passing Distribution Profile", template='plotly_dark', hole=0.4), width="stretch")

    with st.expander("📥 Download Trend Data"):
        col_c1, col_c2 = st.columns(2)
        col_c1.download_button("Download PSxG/Goals (CSV)", data=match_agg.to_csv(index=False).encode('utf-8'), file_name="PSxG_Goals.csv", mime="text/csv")
        if not passes_df.empty: col_c2.download_button("Download Pass Split (CSV)", data=dist_agg.to_csv(index=False).encode('utf-8'), file_name="Pass_Split.csv", mime="text/csv")

    st.markdown("---")
    analysis_text = ""
    if 'Monthly_Analysis' in agg_matches.columns:
        valid_notes = agg_matches['Monthly_Analysis'].dropna()
        if not valid_notes.empty: analysis_text = valid_notes.iloc[0]

    if analysis_text and str(analysis_text).strip() != "": st.info(analysis_text)
    else: st.warning(f"No monthly analysis logged in the database yet.")

    st.markdown("---")
    st.markdown("### 📝 Coach's Training Notes")
    note_key = f"{report_mode.replace(' ', '')}_{str(selected_period).replace(' ', '_')}"
    
    with st.form(key=f"form_{note_key}"):
        coach_note = st.text_area("Coach's Summary Notes:", value=saved_notes.get(note_key, ""), height=200)
        if st.form_submit_button("💾 Save Notes to Airtable"):
            if save_note_to_airtable(note_key, report_mode, str(selected_period), coach_note):
                st.session_state["saved_notes"][note_key] = coach_note
                st.success("Notes successfully synced to database!")
            else: st.error("Failed to save notes.")

# ==========================================
# EXPORT REPORT BUTTONS
# ==========================================
st.sidebar.markdown("---")
st.sidebar.subheader("📥 Export Full Report")
st.sidebar.markdown('<a href="javascript:window.print()" style="display:block; width:100%; text-align:center; padding:0.5rem; background-color:#FF4B4B; color:white; border-radius:4px; text-decoration:none; font-weight:bold; margin-bottom: 0.5rem;">🖨️ Save as PDF</a>', unsafe_allow_html=True)
st.sidebar.download_button("🌐 Download Interactive HTML", data=generate_html_report([fig_shots, fig_sweeper, fig_passes] if report_mode == "Single Match" else ([fig_gki_radar, fig_scatter] if report_mode == "League Benchmark (Opta)" else [fig_trend, fig_bar]), "Report"), file_name=f"Report.html", mime="text/html", width="stretch")