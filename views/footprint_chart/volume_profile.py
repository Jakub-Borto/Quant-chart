"""Peak-based volume profile.

Direct port of the algorithm used in the existing footprint chart. Produces
tighter value areas than expand-from-global-max on bimodal profiles.

Steps:
  1. Aggregate tick_volume across the selected bar range into price levels.
  2. Smooth volumes with a 3-tick rolling average.
  3. Find local maxima (peaks).
  4. Cluster peaks within 4 ticks; keep top 5 by smoothed volume.
  5. Refine each cluster to the true raw-volume peak (POC candidate).
  6. Expand each candidate to 70% value area (always add the heavier side).
  7. Pick the candidate with the tightest VA.
  8. Refine POC to the highest raw-volume level inside the winning VA.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Profile:
    start_idx: int
    end_idx: int
    levels: dict          # int_key -> {"p","total","buy","sell"}
    poc: float
    vah: float
    val: float
    max_total: float
    total: float


def compute_profile(data, start_idx: int, end_idx: int, tick_size: float) -> Optional[Profile]:
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx
    start_idx = max(0, start_idx)
    end_idx = min(len(data) - 1, end_idx)

    # 1. aggregate
    level_map: dict = {}
    for i in range(start_idx, end_idx + 1):
        tv = data.tick_volume[i]
        if not tv:
            continue
        for price, (buy, sell) in tv.items():
            key = round(price / tick_size)  # robust integer grid key
            e = level_map.get(key)
            if e is None:
                e = {"p": price, "total": 0, "buy": 0, "sell": 0}
                level_map[key] = e
            e["total"] += buy + sell
            e["buy"] += buy
            e["sell"] += sell

    entries = list(level_map.values())
    if not entries:
        return None
    entries.sort(key=lambda e: e["p"])
    prices = [e["p"] for e in entries]
    volumes = [e["total"] for e in entries]
    n = len(prices)
    total = sum(volumes)
    if total == 0:
        return None

    # 2. smooth
    smoothed = [0.0] * n
    for i in range(n):
        lo, hi = max(0, i - 1), min(n - 1, i + 1)
        s = count = 0
        for j in range(lo, hi + 1):
            s += volumes[j]
            count += 1
        smoothed[i] = s / count

    # 3. local maxima
    peaks = [i for i in range(1, n - 1)
             if smoothed[i] > smoothed[i - 1] and smoothed[i] > smoothed[i + 1]]
    if n >= 2 and smoothed[0] > smoothed[1]:
        peaks.insert(0, 0)
    if n >= 2 and smoothed[n - 1] > smoothed[n - 2]:
        peaks.append(n - 1)
    if n == 1:
        peaks.append(0)
    if not peaks:
        peaks.append(volumes.index(max(volumes)))

    # 4. cluster (within 4 indices)
    peaks.sort()
    clusters: list = []
    for idx in peaks:
        if clusters and idx - clusters[-1]["best"] <= 4:
            if smoothed[idx] > smoothed[clusters[-1]["best"]]:
                clusters[-1]["best"] = idx
        else:
            clusters.append({"best": idx})
    clusters.sort(key=lambda c: smoothed[c["best"]], reverse=True)
    top = clusters[:5]

    # 5. refine to raw peak
    candidates = []
    for cl in top:
        lo, hi = max(0, cl["best"] - 3), min(n - 1, cl["best"] + 3)
        best = lo
        for j in range(lo + 1, hi + 1):
            if volumes[j] > volumes[best]:
                best = j
        candidates.append(best)

    # 6. expand value area to 70%
    target = total * 0.70

    def expand(poc_idx):
        lo = hi = poc_idx
        cum = volumes[poc_idx]
        while cum < target:
            down = volumes[lo - 1] if lo > 0 else 0
            up = volumes[hi + 1] if hi < n - 1 else 0
            if not down and not up:
                break
            if (not down) or (up and up >= down):
                hi += 1
                cum += up
            else:
                lo -= 1
                cum += down
        return lo, hi

    # 7. pick tightest, 8. refine POC inside VA
    best_result = None
    tightest = float("inf")
    for poc_idx in candidates:
        lo, hi = expand(poc_idx)
        rng = prices[hi] - prices[lo]
        if rng < tightest:
            tightest = rng
            true_poc, true_vol = prices[poc_idx], 0
            for j in range(lo, hi + 1):
                if volumes[j] > true_vol:
                    true_vol, true_poc = volumes[j], prices[j]
            best_result = Profile(
                start_idx=start_idx, end_idx=end_idx, levels=level_map,
                poc=true_poc, vah=prices[hi], val=prices[lo],
                max_total=max(volumes), total=total,
            )
    return best_result
