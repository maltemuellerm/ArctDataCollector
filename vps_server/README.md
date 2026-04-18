# VPS Server

This folder contains the software that runs on the VPS server.

## Responsibilities

- Fetch ship observation CSVs from EUMETNET eSurfMar every 4 hours
- Deduplicate and store the last 30 days of data per ship
- Keep logs and runtime data in a predictable layout

## Next Steps

1. Deploy with `scripts/bootstrap_vps.sh` then enable `systemd/fetch-ship-data.timer`.
2. Add new ships in `config/ships.yaml`.

## Note on the RockBLOCK decoder

The hex-payload decoder (Flask endpoint, `/opt/decoder` on the VPS) is managed
separately and is not part of this repository.
