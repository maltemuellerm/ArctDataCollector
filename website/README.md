# Website

This folder contains the static website (HTML/CSS/JS) that visualizes the generated CSV data.

## Responsibilities

- Show data points from the last 30 days
- Allow click-through on a point to render detailed plots with Plotly
- Support incremental addition of new observation/data formats

## Data Flow

1. VPS writes CSV files under `vps_server/data/processed/csv/`.
2. A conversion script can generate GeoJSON/JSON for frontend consumption.
3. Frontend loads data and renders overview + detail plots.
