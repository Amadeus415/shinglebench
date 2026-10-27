"""Customer personas sampled to match a task's market and audience."""

from __future__ import annotations

import hashlib
import math
import random

from ..sandbox.ads import interests
from ..tasks.schema import Task

NAMES = {
    "US": ["Maya", "Jordan", "Priya", "Marcus", "Elena", "Tom", "Grace", "Diego", "Aisha", "Kevin", "Linh", "Sam", "Rosa", "Ben", "Mei"],
    "GB": ["Olivia", "Harry", "Amelia", "Jack", "Isla", "Mohammed", "Sophie", "Callum", "Freya", "Ravi"],
    "DE": ["Lena", "Jonas", "Mia", "Felix", "Leonie", "Emre", "Hannah", "Lukas"],
    "PT": ["Inês", "João", "Beatriz", "Tiago", "Mariana", "Rui", "Carolina"],
    "MX": ["Sofía", "Mateo", "Valentina", "Santiago", "Camila", "Diego", "Regina"],
    "NG": ["Chioma", "Tunde", "Ngozi", "Emeka", "Amaka", "Seun", "Bisi"],
    "KE": ["Wanjiru", "Otieno", "Achieng", "Kamau", "Njeri", "Mutua"],
    "IN": ["Ananya", "Rohan", "Kavya", "Arjun", "Sneha", "Vikram", "Meera"],
    "AU": ["Chloe", "Liam", "Ruby", "Noah", "Zara", "Ethan"],
}


def stable_rng(*parts) -> random.Random:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _income_factor(income: str) -> float:
    return {"low": 0.7, "mid": 1.0, "high": 1.45}[income]


def sample_personas(task: Task, seed: int, week: int, n: int, in_market_share: float) -> list[dict]:
    """`in_market_share` is the fraction of reached people who are the true audience."""
    rng = stable_rng("personas", task.id, seed, week)
    country = task.market.country if task.market else "US"
    names = NAMES.get(country, NAMES["US"])
    lo, hi = task.sim.age_range
    relevant = [i for i in task.sim.relevant_interests if i in interests()] or []
    pool = list(interests())
    ref = task.sim.reference_price or 30.0
    langs = task.market.languages if task.market else ["en"]
    out = []
    for i in range(n):
        in_market = rng.random() < in_market_share
        income = rng.choices(["low", "mid", "high"], weights=[0.3, 0.5, 0.2])[0]
        if in_market:
            age = rng.randint(lo, hi)
            ints = rng.sample(relevant, k=min(len(relevant), rng.randint(1, 3))) + rng.sample(pool, 2)
            intent = min(1.0, rng.betavariate(2.2, 2.5) + {"low": -0.1, "medium": 0.0, "high": 0.12}[task.sim.demand])
        else:
            age = rng.randint(18, 65)
            ints = rng.sample(pool, 3)
            intent = rng.betavariate(1.0, 9.0)
        wtp = ref * math.exp(rng.gauss(0, 0.45)) * _income_factor(income)
        traits = [t for t, p in (("price-sensitive", 0.35), ("skeptical", 0.3), ("design-minded", 0.25), ("in-a-hurry", 0.3)) if rng.random() < p]
        out.append({
            "id": f"w{week}-p{i:02d}", "name": rng.choice(names), "age": age, "income": income,
            "language": langs[0] if rng.random() < 0.8 or len(langs) == 1 else rng.choice(langs[1:]),
            "device": "mobile" if rng.random() < 0.7 else "desktop", "in_market": in_market,
            "interests": sorted(set(ints)), "intent": round(max(0.0, intent), 3), "wtp": round(wtp, 2), "traits": traits,
        })
    return out
