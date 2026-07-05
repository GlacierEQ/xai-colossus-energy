# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""
ELECTRICITY ⇔ XAI COLOSSAL COOLING DASH DASHBOARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Real-time Dash visualization:
- Live constraint mode + available power
- GPU thermal distribution (violin plots)
- Throttle activity timeline
- Power forecast vs actual
- Alert heatmap

Migrated from GlacierEQ/electricity (now archived).
Canonical home: xai-colossus-energy/electricity/
"""

import dash
from dash import dcc, html, Input, Output, State, callback
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import deque
import json


class DashDataStore:
    """In-memory data store for dashboard state (use Redis for production)."""

    def __init__(self, max_history=500):
        self.thermal_history = deque(maxlen=max_history)
        self.power_history = deque(maxlen=max_history)
        self.throttle_events = deque(maxlen=100)
        self.constraint_mode = "NORMAL"
        self.available_power = 150000
        self.gpu_count = 8
        self.gpu_temps = [45.0] * self.gpu_count

    def add_thermal(self, timestamp, avg_temp, max_temp, gpu_temps, cooling_load):
        self.thermal_history.append({"timestamp": timestamp, "avg_temp": avg_temp, "max_temp": max_temp, "gpu_temps": gpu_temps, "cooling_load": cooling_load})
        self.gpu_temps = gpu_temps

    def add_power(self, timestamp, available, constraint_mode, throttle_pct):
        self.power_history.append({"timestamp": timestamp, "available_power": available, "constraint_mode": constraint_mode, "throttle_pct": throttle_pct})
        self.constraint_mode = constraint_mode
        self.available_power = available

    def add_throttle_event(self, gpu_ids, throttle_pct, reason):
        self.throttle_events.append({"timestamp": datetime.utcnow().isoformat(), "gpu_ids": gpu_ids, "throttle_pct": throttle_pct, "reason": reason})

    def get_thermal_df(self):
        return pd.DataFrame(self.thermal_history) if self.thermal_history else pd.DataFrame()

    def get_power_df(self):
        return pd.DataFrame(self.power_history) if self.power_history else pd.DataFrame()


DARK_THEME = {"background": "#0d1117", "surface": "#161b22", "accent": "#58a6ff", "success": "#3fb950", "warning": "#f0883e", "danger": "#f85149", "text": "#e6edf3"}

app = dash.Dash(__name__)
store = DashDataStore()

# Seed demo data
np.random.seed(42)
for i in range(100):
    ts = (datetime.utcnow() - timedelta(seconds=100 - i)).isoformat()
    temps = [45 + 10 * np.sin(i / 20) + np.random.normal(0, 2) for _ in range(8)]
    store.add_thermal(ts, np.mean(temps), np.max(temps), temps, int(500 + np.mean(temps) * 5))
    c = "NORMAL" if np.mean(temps) < 55 else "WARNING" if np.mean(temps) < 65 else "CONSTRAINED"
    store.add_power(ts, 150000 - int(np.mean(temps) * 1000), c, 0 if c == "NORMAL" else 20 if c == "WARNING" else 50)

app.layout = html.Div([
    dcc.Interval(id="interval-component", interval=2000, n_intervals=0),
    html.Div([
        html.H1("⚡ ELECTRICITY ⇔ XAI COLOSSAL COOLING", style={"margin": 0}),
        html.P("Real-Time Power Constraint & Thermal Feedback Loop", style={"color": DARK_THEME["accent"]}),
    ], style={"background": DARK_THEME["surface"], "padding": "20px", "borderBottom": f"3px solid {DARK_THEME['accent']}", "marginBottom": "20px"}),
    html.Div([
        html.Div([html.H3("CONSTRAINT MODE", style={"fontSize": "12px", "color": DARK_THEME["accent"]}), html.Div(id="metric-constraint-mode", style={"fontSize": "32px", "fontWeight": "bold"})]),
        html.Div([html.H3("AVAILABLE POWER", style={"fontSize": "12px", "color": DARK_THEME["accent"]}), html.Div(id="metric-available-power", style={"fontSize": "28px", "fontWeight": "bold"})]),
        html.Div([html.H3("MAX GPU TEMP", style={"fontSize": "12px", "color": DARK_THEME["accent"]}), html.Div(id="metric-max-temp", style={"fontSize": "28px", "fontWeight": "bold"})]),
        html.Div([html.H3("ACTIVE THROTTLES", style={"fontSize": "12px", "color": DARK_THEME["accent"]}), html.Div(id="metric-throttles", style={"fontSize": "28px", "fontWeight": "bold"})]),
    ], style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "15px", "marginBottom": "20px", "padding": "0 20px"}),
    html.Div([
        html.Div([dcc.Graph(id="chart-thermal-timeline")], style={"flex": 1}),
        html.Div([dcc.Graph(id="chart-power-timeline")], style={"flex": 1}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px", "padding": "0 20px"}),
    html.Div([
        html.Div([dcc.Graph(id="chart-gpu-distribution")], style={"flex": 1}),
        html.Div([dcc.Graph(id="chart-constraint-heatmap")], style={"flex": 1}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px", "padding": "0 20px"}),
    html.Div([
        html.H3("Recent Throttle Events", style={"color": DARK_THEME["accent"]}),
        html.Table(id="table-throttle-events", style={"width": "100%", "borderCollapse": "collapse", "color": DARK_THEME["text"]}),
    ], style={"padding": "0 20px", "marginBottom": "20px"}),
], style={"background": DARK_THEME["background"], "padding": "20px 0", "fontFamily": "system-ui"})


@callback([Output("metric-constraint-mode", "children"), Output("metric-available-power", "children"), Output("metric-max-temp", "children"), Output("metric-throttles", "children")], Input("interval-component", "n_intervals"))
def update_metrics(n):
    df_p = store.get_power_df()
    df_t = store.get_thermal_df()
    mode = df_p["constraint_mode"].iloc[-1] if len(df_p) else "—"
    power = f"{df_p['available_power'].iloc[-1]/1000:.0f} kW" if len(df_p) else "—"
    temp = f"{df_t['max_temp'].iloc[-1]:.1f}°C" if len(df_t) else "—"
    throttles = f"{len(store.throttle_events)} events" if store.throttle_events else "None"
    return mode, power, temp, throttles


@callback(Output("chart-thermal-timeline", "figure"), Input("interval-component", "n_intervals"))
def update_thermal_timeline(n):
    df = store.get_thermal_df()
    if df.empty:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["timestamp"], y=df["avg_temp"], name="Avg Temp", line=dict(color=DARK_THEME["accent"], width=2), fill="tozeroy"))
    fig.add_trace(go.Scatter(x=df["timestamp"], y=df["max_temp"], name="Max Temp", line=dict(color=DARK_THEME["danger"], width=2)))
    fig.update_layout(title="GPU Thermal Timeline", xaxis_title="Time", yaxis_title="Temp (°C)", plot_bgcolor=DARK_THEME["surface"], paper_bgcolor=DARK_THEME["background"], font=dict(color=DARK_THEME["text"]), template="plotly_dark")
    return fig


@callback(Output("chart-power-timeline", "figure"), Input("interval-component", "n_intervals"))
def update_power_timeline(n):
    df = store.get_power_df()
    if df.empty:
        return go.Figure()
    color_map = {"NORMAL": DARK_THEME["success"], "WARNING": DARK_THEME["warning"], "CONSTRAINED": DARK_THEME["danger"], "CRITICAL": "#ff0000"}
    colors = [color_map.get(m, DARK_THEME["accent"]) for m in df["constraint_mode"]]
    fig = go.Figure(go.Bar(x=df["timestamp"], y=df["available_power"] / 1000, name="Available Power", marker=dict(color=colors)))
    fig.update_layout(title="Available Power Over Time", xaxis_title="Time", yaxis_title="Power (kW)", plot_bgcolor=DARK_THEME["surface"], paper_bgcolor=DARK_THEME["background"], font=dict(color=DARK_THEME["text"]), template="plotly_dark")
    return fig


@callback(Output("chart-gpu-distribution", "figure"), Input("interval-component", "n_intervals"))
def update_gpu_distribution(n):
    df = store.get_thermal_df()
    if df.empty:
        return go.Figure()
    all_temps, gpu_labels = [], []
    for gid in range(8):
        temps = [row[gid] for row in df["gpu_temps"].tail(50)]
        all_temps.extend(temps)
        gpu_labels.extend([f"GPU {gid}"] * len(temps))
    fig = px.violin(pd.DataFrame({"Temperature": all_temps, "GPU": gpu_labels}), x="GPU", y="Temperature", points="outliers", title="GPU Temperature Distribution")
    fig.update_layout(plot_bgcolor=DARK_THEME["surface"], paper_bgcolor=DARK_THEME["background"], font=dict(color=DARK_THEME["text"]), template="plotly_dark")
    return fig


@callback(Output("chart-constraint-heatmap", "figure"), Input("interval-component", "n_intervals"))
def update_constraint_heatmap(n):
    df = store.get_power_df()
    if df.empty:
        return go.Figure()
    mode_map = {"NORMAL": 0, "WARNING": 1, "CONSTRAINED": 2, "CRITICAL": 3}
    values = [mode_map.get(m, 0) for m in df["constraint_mode"]]
    heatmap_data = [values[i:i + 50] for i in range(0, len(values), 50)]
    fig = go.Figure(data=go.Heatmap(z=heatmap_data, colorscale=[[0, DARK_THEME["success"]], [0.33, DARK_THEME["accent"]], [0.66, DARK_THEME["warning"]], [1, DARK_THEME["danger"]]], colorbar=dict(tickvals=[0, 1, 2, 3], ticktext=["NORMAL", "WARNING", "CONSTRAINED", "CRITICAL"])))
    fig.update_layout(title="Constraint Severity Timeline", plot_bgcolor=DARK_THEME["surface"], paper_bgcolor=DARK_THEME["background"], font=dict(color=DARK_THEME["text"]), template="plotly_dark")
    return fig


@callback(Output("table-throttle-events", "children"), Input("interval-component", "n_intervals"))
def update_throttle_table(n):
    if not store.throttle_events:
        return html.Tr(html.Td("No throttle events yet"))
    rows = [html.Tr([html.Th(h, style={"borderBottom": f"1px solid {DARK_THEME['accent']}"})
                    for h in ("Timestamp", "GPUs", "Throttle %", "Reason")])]
    for e in list(store.throttle_events)[-10:]:
        rows.append(html.Tr([html.Td(e["timestamp"][-8:]), html.Td(str(e["gpu_ids"][:3])), html.Td(f"{e['throttle_pct']:.0f}%"), html.Td(e["reason"])]))
    return rows


if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=8050)
