"""Episode loop: one model, one task, one seed.

Identical scaffolding for every model: same system prompt, tools, notes file, summarizer and
caps. Every model turn and tool call is appended to trajectory.jsonl; a checkpoint is written
after every step so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..config import HARNESS_VERSION, PROMPT_VERSION, Settings
from ..market.simulator import render_report
from ..tasks.schema import Task
from ..world import World
from .prompts import system_prompt, task_message
from .providers import ModelConfig, ProviderError, Usage, make_provider
from .tools import NOTES, TOOLS, TOOLSET_VERSION, run_tool

FINAL_STEPS = 8
SUMMARIZE_AT = 0.6  # fraction of the model's context window
MAX_IDLE_TURNS = 3


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Trajectory:
    def __init__(self, path: Path):
        self.path = path

    def log(self, step: int, type_: str, **data) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps({"ts": now(), "t": time.time(), "step": step, "type": type_, **data}, default=str) + "\n")


class Episode:
    def __init__(self, run_dir: Path, task: Task, model: ModelConfig, seed: int, settings: Settings, market_llm=None):
        self.run_dir = run_dir
        self.task = task
        self.model = model
        self.seed = seed
        self.settings = settings
        self.market_llm = market_llm
        run_dir.mkdir(parents=True, exist_ok=True)
        self.ckpt_path = run_dir / "checkpoint.json"
        self.traj = Trajectory(run_dir / "trajectory.jsonl")
        self.tools = [t.schema() for t in TOOLS]

    # ----------------------------------------------------------------- state
    def _load(self) -> dict:
        if self.ckpt_path.exists():
            return json.loads(self.ckpt_path.read_text())
        return {"messages": [{"role": "user", "content": task_message(self.task)}], "step": 0,
                "usage": asdict(Usage()), "cost_usd": 0.0, "wall_s": 0.0, "finished": False, "final_steps_left": None,
                "idle_turns": 0, "summaries": 0, "stop_reason": None, "provider_errors": 0}

    def _save(self, st: dict) -> None:
        tmp = self.ckpt_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, default=str))
        tmp.replace(self.ckpt_path)

    def _manifest(self, world: World, st: dict, status: str) -> dict:
        m = {
            "run_id": self.run_dir.name, "task_id": self.task.id, "task_version": self.task.version, "split": self.task.split,
            "category": self.task.category.value, "tier": self.task.tier, "model": self.model.name, "model_family": self.model.family,
            "provider": self.model.provider, "provider_model": self.model.model, "seed": self.seed,
            "harness_version": HARNESS_VERSION, "prompt_version": PROMPT_VERSION, "toolset_version": TOOLSET_VERSION,
            "sandbox_isolation": world.isolation if world._shell else "not-started",
            "image_provider": world.images.name, "payments_provider": world.payments.name, "research_mode": world.research.mode,
            "simulator": self.settings.simulator_model, "status": status, "stop_reason": st.get("stop_reason"),
            "steps": st["step"], "weeks_completed": world.week(), "usage": st["usage"], "cost_usd": round(st["cost_usd"], 4),
            "wall_clock_s": round(st["wall_s"], 1), "summaries": st["summaries"], "updated_at": now(),
        }
        (self.run_dir / "run.json").write_text(json.dumps(m, indent=2))
        return m

    # ----------------------------------------------------------------- weeks
    def _end_week(self, world: World, st: dict, auto: bool = False) -> str:
        world.clock["week"] += 1
        world.save_clock()
        rep = world.market.run_week()
        text = render_report(rep)
        if world.week() >= self.task.episode.simulated_weeks:
            text += f"\n\nThis was the final simulated week. You have up to {FINAL_STEPS} more steps to finalize your deliverables, then call finish."
            if st["final_steps_left"] is None:
                st["final_steps_left"] = FINAL_STEPS
        self.traj.log(st["step"], "week_report", week=world.week(), auto=auto, totals=rep["totals"])
        return text

    # ----------------------------------------------------------------- context
    def _maybe_summarize(self, provider, st: dict, world: World) -> None:
        chars = sum(len(json.dumps(m, default=str)) for m in st["messages"])
        if chars / 4 < self.model.context_window * SUMMARIZE_AT:
            return
        transcript = "\n".join(f"[{m['role']}] {str(m.get('content', ''))[:2000]} {json.dumps(m.get('tool_calls', ''))[:500]}" for m in st["messages"][1:])
        t = provider.complete("SUMMARIZE_CONVERSATION. You are summarizing an agent's work log so it can continue. Keep ids, prices, decisions, results and open to-dos. Be concise.",
                              [{"role": "user", "content": transcript[-400_000:]}], [])
        notes = world.ws.read(NOTES) if world.ws.exists(NOTES) else ""
        st["usage"] = self._add_usage(st, t.usage)
        st["summaries"] += 1
        # restart the conversation (append-only history; nothing earlier is edited)
        st["messages"] = [st["messages"][0], {"role": "user", "content":
                          f"[Context was summarized to save space.]\nSummary of your work so far:\n{t.text}\n\nYour NOTES.md:\n{notes}\n\nContinue from where you left off (current week {world.week()})."}]
        self.traj.log(st["step"], "summarized", summary=t.text, chars_before=chars)

    def _add_usage(self, st: dict, u: Usage) -> dict:
        tot = Usage(**st["usage"])
        tot.add(u)
        st["cost_usd"] += self.model.cost(u)
        return asdict(tot)

    # ----------------------------------------------------------------- main
    def run(self) -> dict:
        st = self._load()
        world = World(self.run_dir, self.task, self.seed, self.settings, market_llm=self.market_llm)
        provider = make_provider(self.model, seed=self.seed)
        ep = self.task.episode
        resumed = st["step"] > 0
        self.traj.log(st["step"], "episode_start" if not resumed else "episode_resume", model=self.model.name, task=self.task.id, seed=self.seed)
        self._manifest(world, st, "running")
        sys_prompt = system_prompt(self.task)
        t0 = time.time() - st["wall_s"]
        try:
            while not st["finished"]:
                tok = st["usage"]["input_tokens"] + st["usage"]["output_tokens"]
                caps = [(st["step"] >= ep.max_steps, "max_steps"), (tok >= ep.max_tokens, "max_tokens"),
                        (st["cost_usd"] >= ep.max_cost_usd, "max_cost"), (time.time() - t0 >= ep.max_wall_clock_min * 60, "max_wall_clock"),
                        (st["final_steps_left"] is not None and st["final_steps_left"] <= 0, "completed")]
                hit = next((r for c, r in caps if c), None)
                if hit:
                    st["stop_reason"] = hit
                    break
                self._maybe_summarize(provider, st, world)
                try:
                    turn = self._call(provider, sys_prompt, st)
                except ProviderError as e:
                    st["stop_reason"] = "provider_error"
                    self.traj.log(st["step"], "provider_error", error=str(e))
                    break
                st["usage"] = self._add_usage(st, turn.usage)
                st["step"] += 1
                if st["final_steps_left"] is not None:
                    st["final_steps_left"] -= 1
                msg = {"role": "assistant", "content": turn.text, "tool_calls": [asdict(c) for c in turn.tool_calls]}
                if turn.raw is not None:
                    msg["raw"] = {"provider": self.model.provider, "content": turn.raw}
                st["messages"].append(msg)
                self.traj.log(st["step"], "model_turn", text=turn.text, tool_calls=msg["tool_calls"], stop_reason=turn.stop_reason,
                              usage=asdict(turn.usage), model_reported=turn.raw_model)
                if turn.stop_reason == "refusal":
                    self.traj.log(st["step"], "refusal")
                if not turn.tool_calls:
                    st["idle_turns"] += 1
                    if st["idle_turns"] >= MAX_IDLE_TURNS:
                        st["stop_reason"] = "no_tool_calls"
                        break
                    st["messages"].append({"role": "user", "content": "Continue working with your tools. Call end_week when ready for the next simulated week, or finish when done."})
                    self._save(st)
                    continue
                st["idle_turns"] = 0
                for call in turn.tool_calls:
                    t1 = time.time()
                    if call.name == "end_week":
                        if world.week() >= ep.simulated_weeks:
                            out, err = "ERROR: all simulated weeks are complete; finalize deliverables and call finish.", True
                        else:
                            out, err = self._end_week(world, st), False
                    elif call.name == "finish":
                        st["finished"], st["stop_reason"] = True, "finished"
                        out, err = "Episode finished. Remaining simulated weeks will run with your final setup.", False
                    else:
                        out, err = run_tool(world, call.name, call.args)
                    left = ep.max_steps - st["step"]
                    if left in (20, 10, 5):
                        out += f"\n\n[harness] {left} steps remain in this episode (week {world.week()} of {ep.simulated_weeks})."
                    st["messages"].append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": out, "is_error": err})
                    self.traj.log(st["step"], "tool_call", name=call.name, args=call.args, output=out, is_error=err, duration_s=round(time.time() - t1, 3))
                st["wall_s"] = time.time() - t0
                self._save(st)
            # remaining weeks run on autopilot so market data is comparable across models
            while world.week() < ep.simulated_weeks:
                self._end_week(world, st, auto=True)
            st["finished"] = True
            st["stop_reason"] = st["stop_reason"] or "completed"
            st["wall_s"] = time.time() - t0
            self._save(st)
            self.traj.log(st["step"], "episode_end", stop_reason=st["stop_reason"], cost_usd=st["cost_usd"])
            return {"manifest": self._manifest(world, st, "complete"), "world": world}
        except Exception as e:
            st["wall_s"] = time.time() - t0
            self._save(st)
            self.traj.log(st["step"], "harness_error", error=f"{type(e).__name__}: {e}")
            self._manifest(world, st, "error")
            world.close()
            raise

    def _call(self, provider, sys_prompt: str, st: dict):
        delay = 5.0
        for attempt in range(3):
            try:
                return provider.complete(sys_prompt, st["messages"], self.tools)
            except ProviderError as e:
                st["provider_errors"] += 1
                if not e.retryable or attempt == 2:
                    raise
                self.traj.log(st["step"], "provider_retry", error=str(e), attempt=attempt + 1)
                time.sleep(delay)
                delay *= 3
        raise ProviderError("unreachable")
