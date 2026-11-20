# gta6-trophy-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/dap204/gta6-trophy-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/dap204/gta6-trophy-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

This program forecasts how common each of GTA VI's 55 PlayStation trophies will be a few days after launch. It reads the recorded history of each trophy's earn rate — the percent of tracked players who hold it — and projects it to a target time. The projection is a trend fitted on the logit scale against a log-time axis, with recent reads weighted more heavily than old ones because launch week moves fast. Each trophy's trend slope is shrunk toward the average slope across all trophies so one noisy series cannot sprint away on its own, and the extrapolation is damped and anchored partly on the last observed rate. The answer for each trophy is five quantiles whose spread widens honestly with the forecast horizon, the noisiness of that trophy's history, and how far its trend has to travel.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=tedem4sj&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
