# ArctDataCollector Project Structure

This scaffold separates server-side data ingestion from web visualization.

```text
ArctDataCollector/
├── example/
├── vps_server/
│   ├── app/
│   │   └── ingestion/
│   │       ├── handlers/
│   │       │   └── ship_handler.py
│   │       └── sources/
│   │           └── eumetnet_ship.py
│   ├── config/
│   │   └── settings.example.yaml
│   ├── data/
│   │   ├── processed/csv/
│   │   └── raw/
│   ├── logs/
│   ├── scripts/
│   │   └── bootstrap_vps.sh
│   ├── systemd/
│   │   └── decoder-flask.service
│   ├── README.md
│   └── requirements.txt
└── website/
    ├── assets/
    │   ├── css/
    │   │   └── styles.css
    │   └── js/
    │       ├── app.js
    │       ├── csv-loader.js
    │       └── plot.js
    ├── data/
    ├── scripts/
    │   ├── cron.example
    │   └── generate_geojson.php
    ├── index.html
    └── README.md
```