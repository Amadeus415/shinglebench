"""One episode's sandboxed world: every service the agent can touch, all simulated or test-mode."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .market.simulator import Market
from .sandbox.ads import AdPlatform
from .sandbox.hosting import Hosting
from .sandbox.images import make_images
from .sandbox.payments import make_payments
from .sandbox.research import Research
from .sandbox.suppliers import Ledger, Suppliers
from .sandbox.workspace import Workspace, make_shell
from .tasks.schema import Task


class World:
    def __init__(self, run_dir: Path, task: Task, seed: int, settings: Settings, market_llm=None):
        self.run_dir = run_dir
        self.task = task
        self.seed = seed
        self.settings = settings
        self.state_dir = run_dir / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._clock_path = self.state_dir / "clock.json"
        self.clock = json.loads(self._clock_path.read_text()) if self._clock_path.exists() else {"week": 0, "finished": False}
        self.ws = Workspace(run_dir / "workspace")
        self._shell = None
        self.payments = make_payments(settings.payments_provider, settings.key("STRIPE_SECRET_KEY"), self.state_dir / "payments.json")
        self.hosting = Hosting(self.ws.root, run_dir, self.payments)
        if self.hosting.current_dir:
            self.hosting.start()
        self.images = make_images(settings.image_provider, settings.key("OPENAI_API_KEY"))
        self.ads = AdPlatform(self.state_dir / "ads.json", self.ws.root, self.week)
        self.ledger = Ledger(self.state_dir / "ledger.json", task.budget.total_usd, self.week)
        self.suppliers = Suppliers(self.state_dir / "suppliers.json", self.ledger, self.week,
                                   task.market.country if task.market else "US")
        self.research = Research(settings.research_mode, settings.key("SEARCH_API_KEY"))
        self.market = Market(self, llm=market_llm)
        self.inbox_cursor = self.clock.get("inbox_cursor", 0)

    def week(self) -> int:
        return self.clock["week"]

    def save_clock(self) -> None:
        self.clock["inbox_cursor"] = self.inbox_cursor
        self._clock_path.write_text(json.dumps(self.clock))

    @property
    def shell(self):
        if self._shell is None:
            self._shell = make_shell(self.ws, self.settings.sandbox_backend, self.settings.sandbox_image)
        return self._shell

    @property
    def isolation(self) -> str:
        return self.shell.isolation

    def close(self) -> None:
        self.hosting.close()
        if self._shell:
            self._shell.close()
