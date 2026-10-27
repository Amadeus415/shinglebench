"""Task brief schema (versioned).

A task is one business brief. The model under test sees `brief` plus the
`facts_block()` rendering; everything under `grader_notes` and every probe is
hidden from it.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class Category(str, Enum):
    digital_product = "digital_product"
    local_service = "local_service"
    physical_product = "physical_product"
    b2b_service = "b2b_service"
    info_community = "info_community"
    open_ended = "open_ended"


class Deliverable(str, Enum):
    website = "website"
    product = "product"  # working digital product, or a defined service offering
    brand_doc = "brand_doc"
    business_plan = "business_plan"  # offer, pricing, unit economics, customer journey
    launch_plan = "launch_plan"
    ad_campaign = "ad_campaign"
    product_images = "product_images"
    supplier_order = "supplier_order"
    checkout = "checkout"
    booking_flow = "booking_flow"
    contact_form = "contact_form"


class CheckId(str, Enum):
    site_loads = "site_loads"
    links = "links"
    console = "console"
    lighthouse = "lighthouse"
    mobile = "mobile"
    forms = "forms"
    checkout = "checkout"
    product_qa = "product_qa"
    ad_compliance = "ad_compliance"
    integrity = "integrity"
    supplier = "supplier"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Market(_Strict):
    region: str = Field(description="Human-readable market, e.g. 'Mission District, San Francisco, CA, USA'")
    country: str = Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2")
    city: str | None = None
    neighborhood: str | None = None
    lat: float | None = None
    lon: float | None = None
    service_radius_km: float | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    languages: list[str] = Field(default_factory=lambda: ["en"])
    audience_hint: str | None = Field(default=None, description="Shown to the model; may be vague on purpose")


class Budget(_Strict):
    total_usd: float = Field(gt=0, description="Simulated cash for the whole episode")
    ad_budget_usd: float = Field(ge=0, description="Suggested share for paid ads")


class EpisodeBudget(_Strict):
    max_steps: int = Field(default=120, ge=10)
    max_tokens: int = Field(default=2_000_000, ge=10_000)
    max_cost_usd: float = Field(default=25.0, gt=0)
    max_wall_clock_min: int = Field(default=120, ge=1)
    simulated_weeks: int = Field(default=3, ge=1, le=12)


class Constraints(_Strict):
    legal: list[str] = Field(default_factory=list)
    brand: list[str] = Field(default_factory=list)
    scope: list[str] = Field(default_factory=list)


class Probe(_Strict):
    """Deterministic hint so the offline QA agent can test a criterion without an LLM."""

    kind: Literal["page_contains", "element_exists", "interact", "form_submits", "checkout_completes"]
    path: str = "/"
    any_text: list[str] = Field(default_factory=list)
    selector: str | None = None
    inputs: list[str] = Field(default_factory=list, description="Values typed into the first visible inputs")


class AcceptanceCriterion(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    probe: Probe | None = None


class GraderNotes(_Strict):
    great_looks_like: list[str] = Field(min_length=2)
    common_failures: list[str] = Field(min_length=2)
    market_context: str = Field(description="What a grader should know about this place/market")


class SimParams(_Strict):
    """Hidden demand-model anchors for the simulated market. Never shown to the model."""

    reference_price: float | None = Field(default=None, gt=0, description="Typical price a customer expects, in market currency")
    price_unit: Literal["one_time", "per_month", "per_job", "per_session"] = "one_time"
    demand: Literal["low", "medium", "high"] = "medium"
    age_range: tuple[int, int] = (22, 55)
    relevant_interests: list[str] = Field(default_factory=list, description="Ad-interest ids that mark the true audience")
    conversion: Literal["checkout", "inquiry", "booking", "signup"] | None = None


class Task(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")
    version: int = Field(ge=1)
    split: Literal["dev", "heldout"]
    category: Category
    tier: Literal[1, 2, 3]
    title: str = Field(description="Internal title; not shown to the model")
    brief: str = Field(min_length=200, description="The brief exactly as the model sees it")
    market: Market | None = None
    budget: Budget
    deliverables: list[Deliverable] = Field(min_length=3)
    required_pages: list[str] = Field(default_factory=list, description="Slugs of key pages, e.g. pricing, contact")
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=2)
    constraints: Constraints = Field(default_factory=Constraints)
    episode: EpisodeBudget = Field(default_factory=EpisodeBudget)
    grader_notes: GraderNotes
    checks: list[CheckId]
    sim: SimParams = Field(default_factory=SimParams)
    canary: str | None = Field(default=None, description="Contamination canary; required for held-out tasks")
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _category_rules(self) -> "Task":
        d = set(self.deliverables)
        if Deliverable.website not in d:
            raise ValueError("every task must require a website")
        if self.category in (Category.local_service, Category.b2b_service) and not (self.market and self.market.city):
            raise ValueError(f"{self.category.value} tasks need a market with a city")
        if self.category == Category.physical_product:
            missing = {Deliverable.product_images, Deliverable.supplier_order} - d
            if missing:
                raise ValueError(f"physical_product tasks must require {sorted(m.value for m in missing)}")
            if CheckId.supplier not in self.checks:
                raise ValueError("physical_product tasks must run the supplier check")
        if self.split == "heldout" and not self.canary:
            raise ValueError("held-out tasks need a canary string")
        if self.budget.ad_budget_usd > self.budget.total_usd:
            raise ValueError("ad budget exceeds total budget")
        ids = [c.id for c in self.acceptance_criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("acceptance criterion ids must be unique")
        return self

    def facts_block(self) -> str:
        """Structured facts appended to the brief. Every model sees exactly this."""
        lines = [
            f"task_id: {self.id} (v{self.version})",
            f"category: {self.category.value}",
            f"simulated_weeks: {self.episode.simulated_weeks}",
            f"total_budget_usd: {self.budget.total_usd:g}",
            f"suggested_ad_budget_usd: {self.budget.ad_budget_usd:g}",
        ]
        if self.market:
            m = self.market
            lines.append(f"market: {m.region}")
            lines.append(f"country: {m.country}")
            if m.city:
                lines.append(f"city: {m.city}")
            if m.neighborhood:
                lines.append(f"neighborhood: {m.neighborhood}")
            if m.service_radius_km:
                lines.append(f"service_radius_km: {m.service_radius_km:g}")
            lines.append(f"currency: {m.currency}")
            lines.append(f"languages: {', '.join(m.languages)}")
            if m.audience_hint:
                lines.append(f"audience_hint: {m.audience_hint}")
        lines.append("deliverables: " + ", ".join(d.value for d in self.deliverables))
        if self.required_pages:
            lines.append("required_pages: " + ", ".join(self.required_pages))
        lines.append("acceptance_criteria:")
        lines += [f"  - [{c.id}] {c.description}" for c in self.acceptance_criteria]
        for name in ("legal", "brand", "scope"):
            items = getattr(self.constraints, name)
            if items:
                lines.append(f"constraints_{name}:")
                lines += [f"  - {i}" for i in items]
        return "\n".join(lines)
