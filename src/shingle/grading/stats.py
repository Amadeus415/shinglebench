"""Statistics: hierarchical bootstrap, Bradley-Terry + Elo, Krippendorff's alpha, rank correlation."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from itertools import combinations


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def hier_bootstrap(by_task: dict[str, list[float]], reps: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float | None, float | None, float | None]:
    """Mean over tasks of the per-task mean over seeds; CI by resampling tasks, then seeds within each task."""
    tasks = [t for t, v in by_task.items() if v]
    if not tasks:
        return None, None, None
    point = mean([mean(by_task[t]) for t in tasks])
    rng = random.Random(seed)
    stats = []
    for _ in range(reps):
        ts = [rng.choice(tasks) for _ in tasks]
        stats.append(mean([mean([rng.choice(by_task[t]) for _ in by_task[t]]) for t in ts]))
    stats.sort()
    lo, hi = stats[int(alpha / 2 * reps)], stats[min(reps - 1, int((1 - alpha / 2) * reps))]
    return point, lo, hi


def bradley_terry(comparisons: list[tuple[str, str, float]], iters: int = 500, prior: float = 0.5) -> dict[str, float]:
    """comparisons: (i, j, s) with s = 1 if i beat j, 0 if j beat i, 0.5 tie. MM algorithm with a small
    symmetric prior (one virtual tie against every other item) so perfect records stay finite."""
    items = sorted({x for c in comparisons for x in c[:2]})
    if len(items) < 2:
        return {i: 1.0 for i in items}
    wins: dict[str, float] = defaultdict(float)
    n: dict[tuple[str, str], float] = defaultdict(float)
    for i, j, s in comparisons:
        wins[i] += s
        wins[j] += 1 - s
        n[(i, j)] += 1
        n[(j, i)] += 1
    for i, j in combinations(items, 2):
        wins[i] += prior / 2
        wins[j] += prior / 2
        n[(i, j)] += prior
        n[(j, i)] += prior
    p = {i: 1.0 for i in items}
    for _ in range(iters):
        new = {}
        for i in items:
            denom = sum(n[(i, j)] / (p[i] + p[j]) for j in items if j != i and n[(i, j)])
            new[i] = wins[i] / denom if denom else p[i]
        g = math.exp(mean([math.log(v) for v in new.values()]))
        p = {k: v / g for k, v in new.items()}
    return p


def elo_from_bt(p: dict[str, float], base: float = 1000.0) -> dict[str, float]:
    return {k: base + 400 * math.log10(v) for k, v in p.items()}


def bt_bootstrap(comparisons, reps: int = 500, seed: int = 0) -> dict[str, tuple[float, float]]:
    rng = random.Random(seed)
    samples = defaultdict(list)
    for _ in range(reps):
        boot = [rng.choice(comparisons) for _ in comparisons]
        for k, v in elo_from_bt(bradley_terry(boot, iters=200)).items():
            samples[k].append(v)
    out = {}
    for k, v in samples.items():
        v.sort()
        out[k] = (v[int(0.025 * len(v))], v[min(len(v) - 1, int(0.975 * len(v)))])
    return out


def krippendorff_alpha(units: dict[str, list[float]], metric: str = "interval") -> float | None:
    """units: item -> ratings by different coders (missing omitted). Interval or ordinal metric."""
    units = {u: v for u, v in units.items() if len(v) >= 2}
    if not units:
        return None
    values = sorted({x for v in units.values() for x in v})
    if metric == "ordinal":
        counts = defaultdict(float)
        for v in units.values():
            for x in v:
                counts[x] += 1

        def delta(a, b):
            lo, hi = min(a, b), max(a, b)
            s = sum(counts[g] for g in values if lo <= g <= hi) - (counts[lo] + counts[hi]) / 2
            return s * s
    else:
        def delta(a, b):
            return (a - b) ** 2
    n = sum(len(v) for v in units.values())
    do = sum(sum(delta(a, b) for i, a in enumerate(v) for j, b in enumerate(v) if i != j) / (len(v) - 1) for v in units.values()) / n
    allv = [x for v in units.values() for x in v]
    de = sum(delta(a, b) for i, a in enumerate(allv) for j, b in enumerate(allv) if i != j) / (n * (n - 1))
    if de == 0:
        return 1.0 if do == 0 else None
    return 1 - do / de


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None
