#!/usr/bin/env python3
"""Forecast GTA VI trophy earn rates at a future target time.

For every trophy we look at how its Exophase earn rate (the percent of
tracked players who hold it) has moved over the recorded history, fit a
straight-line trend on the logit scale against a log-time axis, and
project that trend to the target time.  Each trophy's slope is shrunk
toward the cross-trophy average and the extrapolation is damped and
anchored on the last observed rate, so a noisy series cannot sprint
away from what was actually seen.  Working on the logit scale keeps the
forecast inside 0..100 and matches the way rarity actually grows: fast
when a trophy is rare and players are flooding in, slower as it
saturates.  Uncertainty is expressed as five quantiles of a logistic
distribution centred on the trend value, with a spread that grows with
the forecast horizon and with how noisy the trophy's own history was.

Standard library only, no network, fully deterministic.
"""

import glob
import json
import math
import os
from datetime import datetime, timezone

# Launch midnight: the log-time axis is anchored at the game's release.
EPOCH = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)

# Standard-normal quantiles for the five requested levels
# (0.05, 0.25, 0.5, 0.75, 0.95).
ZVALS = (-1.645, -0.674, 0.0, 0.674, 1.645)

RATE_LO = 0.01    # scoring clamps rates into this range before logit
RATE_HI = 99.99
HALF_LIFE_H = 18.0  # recency weighting half-life, in hours


def parse_time(text):
    """Parse an ISO-8601 UTC timestamp into an aware datetime."""
    s = str(text).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hours_since_epoch(dt):
    return (dt - EPOCH).total_seconds() / 3600.0


def log_time(hours):
    """x(t) = ln(1 + hours since launch); guarded for pre-launch reads."""
    return math.log(max(1.0 + hours, 1e-6))


def clamp_rate(rate):
    if rate < RATE_LO:
        return RATE_LO
    if rate > RATE_HI:
        return RATE_HI
    return rate


def logit_of_rate(rate):
    p = clamp_rate(rate) / 100.0
    return math.log(p / (1.0 - p))


def rate_of_logit(y):
    """Inverse logit, returning a rate in percent; overflow-safe."""
    if y >= 0.0:
        return 100.0 / (1.0 + math.exp(-y))
    e = math.exp(y)
    return 100.0 * e / (1.0 + e)


def round4(value):
    """Round a non-negative number to 4 decimals, half-up."""
    return math.floor(value * 10000.0 + 0.5) / 10000.0


def clip(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def fit_trophy(points, ref_hours):
    """Weighted least squares of logit(rate) on log-time.

    points: list of (hours, x, rate) with at least one entry, oldest
    first.  ref_hours is the checkpoint time used for recency weights.
    Returns a dict describing the fit, or None when there are too few
    usable points to fit a line.
    """
    n = len(points)
    last_rate = points[-1][2]
    last_logit = logit_of_rate(last_rate)
    x_last = points[-1][1]
    if n < 3:
        return None

    sw = 0.0
    sx = 0.0
    sy = 0.0
    weights = []
    ys = []
    for hours, x, rate in points:
        age = ref_hours - hours
        if age < 0.0:
            age = 0.0
        w = 0.5 ** (age / HALF_LIFE_H)
        y = logit_of_rate(rate)
        weights.append(w)
        ys.append(y)
        sw += w
        sx += w * x
        sy += w * y
    xbar = sx / sw
    ybar = sy / sw

    sxx = 0.0
    sxy = 0.0
    for (hours, x, rate), w, y in zip(points, weights, ys):
        dx = x - xbar
        sxx += w * dx * dx
        sxy += w * dx * (y - ybar)
    if sxx <= 1e-12:
        slope = 0.0
        intercept = ybar
    else:
        slope = sxy / sxx
        intercept = ybar - slope * xbar

    # Weighted residual spread of the fit, kept in a sane band.
    sse = 0.0
    for (hours, x, rate), w, y in zip(points, weights, ys):
        r = y - (intercept + slope * x)
        sse += w * r * r
    resid = clip(math.sqrt(sse / sw), 0.05, 0.8)

    return {
        "n": n,
        "intercept": intercept,
        "slope": slope,
        "resid": resid,
        "x_last": x_last,
        "xbar": xbar,
        "ybar": ybar,
        "last_logit": last_logit,
        "last_rate": last_rate,
    }


def quantile_row(median_logit, sigma):
    qs = []
    for z in ZVALS:
        q = rate_of_logit(median_logit + z * sigma)
        q = clip(round4(q), RATE_LO, RATE_HI)
        if qs and q < qs[-1]:
            q = qs[-1]
        qs.append(q)
    return qs


def persistence_rows(trophies, last_rates, horizon_days):
    """Fallback rows: median = last rate, plain random-walk spread."""
    sigma = clip(max(0.5 * math.sqrt(horizon_days), 0.6), 0.5, 2.3)
    rows = []
    for tr, rate in zip(trophies, last_rates):
        rows.append({"id": tr["id"], "q": quantile_row(logit_of_rate(rate), sigma)})
    rows.sort(key=lambda r: r["id"])
    return rows


def forecast_case(case):
    trophies = case["trophies"]
    history = case.get("history") or []

    # Horizon: prefer the explicit minute count, else derive it.
    horizon_minutes = case.get("horizon_minutes")
    if isinstance(horizon_minutes, (int, float)) and horizon_minutes > 0:
        horizon_days = float(horizon_minutes) / 1440.0
    else:
        horizon_days = 1.0

    # Parse the read timestamps once; each read gives (hours, x).
    read_times = []
    for read in history:
        dt = parse_time(read["at"])
        h = hours_since_epoch(dt)
        read_times.append((h, log_time(h)))

    # Reference time for recency weights: the checkpoint time.
    try:
        ref_hours = hours_since_epoch(parse_time(case["at"]))
    except Exception:
        ref_hours = read_times[-1][0] if read_times else 0.0

    # Target on the log-time axis.
    try:
        x_target = log_time(hours_since_epoch(parse_time(case["target"])))
    except Exception:
        x_target = read_times[-1][1] if read_times else 0.0

    walk = 0.5 * math.sqrt(horizon_days)  # random-walk spread component

    # First pass: gather each trophy's usable points and fit its trend.
    prepared = []
    for j, tr in enumerate(trophies):
        points = []
        for i, read in enumerate(history):
            rates = read.get("rates") or []
            if j >= len(rates):
                continue
            rate = rates[j]
            if isinstance(rate, bool) or not isinstance(rate, (int, float)):
                continue
            if not math.isfinite(rate):
                continue
            h, x = read_times[i]
            points.append((h, x, float(rate)))

        if points:
            last_rate = points[-1][2]
        else:
            last_rate = 0.05  # trophy never observed: assume very rare
        fit = fit_trophy(points, ref_hours) if points else None
        prepared.append((tr, last_rate, fit))

    # The average trend across trophies, weighted by how much data backs
    # each fit.  Individual slopes are shrunk toward this mean below:
    # with only a couple of days of reads, one trophy's wild slope is
    # more likely noise than signal.
    slope_num = 0.0
    slope_den = 0.0
    for tr, last_rate, fit in prepared:
        if fit is not None:
            slope_num += fit["slope"] * fit["n"]
            slope_den += fit["n"]
    mean_slope = slope_num / slope_den if slope_den > 0 else 0.0

    rows = []
    last_rates = []
    for tr, last_rate, fit in prepared:
        last_rates.append(last_rate)
        last_logit = logit_of_rate(last_rate)
        if fit is None:
            median = last_logit
            sigma = clip(max(walk, 0.6), 0.5, 2.3)
        else:
            n = fit["n"]
            shrink = n / (n + 8.0)
            slope = mean_slope + (fit["slope"] - mean_slope) * shrink
            # Re-anchor the shrunk line through the fit's weighted
            # centroid so shrinking the slope does not shift the level.
            intercept = fit["ybar"] - slope * fit["xbar"]
            fitted_target = intercept + slope * x_target
            fitted_last = intercept + slope * fit["x_last"]
            # Damp the extrapolation and anchor it partly on the last
            # observed value, so a bad fit cannot run away; then blend
            # with the fitted value itself and bound the result.
            travelled = last_logit + (fitted_target - fitted_last) * 0.85
            median = 0.7 * travelled + 0.3 * fitted_target
            median = clip(median, last_logit - 1.25, last_logit + 4.0)
            slope_term = 0.35 * abs(slope) * (x_target - fit["x_last"])
            sigma = clip(
                math.sqrt(walk * walk + fit["resid"] ** 2 + slope_term ** 2),
                0.5,
                2.3,
            )
        rows.append({"id": tr["id"], "q": quantile_row(median, sigma)})

    rows.sort(key=lambda r: r["id"])
    return rows


def fallback_rows(case):
    """Persistence-style rows built with minimal assumptions.

    Used when the full model fails on a case, so the case still gets a
    well-formed answer file instead of nothing.
    """
    trophies = case.get("trophies") or []
    history = case.get("history") or []
    horizon_minutes = case.get("horizon_minutes")
    if isinstance(horizon_minutes, (int, float)) and horizon_minutes > 0:
        horizon_days = float(horizon_minutes) / 1440.0
    else:
        horizon_days = 1.0
    last_rates = []
    for j in range(len(trophies)):
        rate = 0.05
        for read in history:
            try:
                rates = read.get("rates") or []
                v = rates[j]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if math.isfinite(v):
                        rate = float(v)
            except Exception:
                continue
        last_rates.append(rate)
    safe_trophies = []
    for tr in trophies:
        try:
            safe_trophies.append({"id": tr["id"]})
        except Exception:
            continue
    return persistence_rows(safe_trophies, last_rates, horizon_days)


def process_file(in_path, out_dir):
    with open(in_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    case_id = case.get("id")
    if not isinstance(case_id, (str, int)):
        case_id = os.path.splitext(os.path.basename(in_path))[0]
    try:
        rows = forecast_case(case)
    except Exception:
        rows = fallback_rows(case)
    payload = {"trophies": rows}
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    out_path = os.path.join(out_dir, str(case_id) + ".out")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(in_dir, "*.in")))
    for path in paths:
        process_file(path, out_dir)


if __name__ == "__main__":
    main()
