"""The engine: drive a scenario through the real Persistent Memory pipeline
under a given Profile, and score every stage.

Reuses the model bootstrap from run_memory_eval so it honours the user's saved
settings (model, backend) and writes to a throwaway database — the real memory
is never touched.
"""

import contextlib
import shutil
import tempfile

import services.persistent_memory as pm_mod
from evals.memory_suite import metrics
from evals.run_memory_eval import _build_local_ai
from services.file import get_prompt
from services.persistent_memory import PersistentMemoryService
from services.skill_local_ai import SamplingPreset


# ── model lifecycle ──────────────────────────────────────────────────────

class ModelHost:
    """Owns the local-AI stack and applies n_ctx / model changes by reloading.

    Two modes:
      * managed  - bootstrap from saved settings and spawn our own llama-servers.
                   Supports n_ctx and model-swap profiles (we control the server).
                   Requires the desktop app to be closed (it holds the ports).
      * attach   - talk to an ALREADY-RUNNING llama-server (e.g. the live desktop
                   app) over its OpenAI API. Zero setup, but n_ctx / model-swap
                   profiles are skipped (we don't own that server). Temperature
                   and similarity sweeps work fine.
    """

    def __init__(self, attach: bool = False,
                 attach_host: str = "http://127.0.0.1",
                 support_port: int = 49172, embed_port: int = 49173):
        self.attached = attach
        self.local_ai, self.provider, self.settings = _build_local_ai()
        self._loaded = False

        if attach:
            from api.enums import LocalAiMode
            from providers.llama_cpp_remote import LlamaCppRemote
            self.settings.mode = LocalAiMode.SERVER
            self.settings.support_remote_host = attach_host
            self.settings.support_remote_port = support_port
            self.settings.embed_remote_host = attach_host
            self.settings.embed_remote_port = embed_port
            detected = LlamaCppRemote.detect_context_size(attach_host, support_port)
            if detected:
                self.settings.n_ctx = detected
            self.local_ai.remote = LlamaCppRemote(settings=self.settings)
            self.local_ai.settings = self.settings

        self._cur_n_ctx = self.settings.n_ctx
        self._cur_model = self.settings.support_model

    def ensure_loaded(self) -> bool:
        if self.settings.mode.value == "local":
            if not self._loaded:
                ok = self.provider.load_support_model() and self.provider.load_embed_model()
                self._loaded = ok
                return ok
            return True
        return self.local_ai.is_ready()

    def apply(self, profile) -> bool:
        """Reload the support model only if n_ctx or the model changed."""
        want_ctx = profile.n_ctx or self.settings.n_ctx
        want_model = profile.support_model or self.settings.support_model
        changed = (want_ctx != self._cur_n_ctx) or (want_model != self._cur_model)
        if changed and self.attached:
            print(f"   ⚠ profile '{profile.id}' changes n_ctx/model but we're attached "
                  "to a running server — that knob is ignored in attach mode.")
        elif changed and self.settings.mode.value == "local":
            self.provider.unload_models()
            self._loaded = False
            self.settings.n_ctx = want_ctx
            self.settings.support_model = want_model
            self._cur_n_ctx, self._cur_model = want_ctx, want_model
        return self.ensure_loaded()

    def shutdown(self):
        if self.settings.mode.value == "local" and not self.attached:
            with contextlib.suppress(Exception):
                self.provider.unload_models()


@contextlib.contextmanager
def _temp_memory_dir():
    tmp = tempfile.mkdtemp(prefix="wingman_mem_suite_")
    orig = pm_mod.get_persistent_memory_dir
    pm_mod.get_persistent_memory_dir = lambda: tmp
    try:
        yield tmp
    finally:
        pm_mod.get_persistent_memory_dir = orig
        shutil.rmtree(tmp, ignore_errors=True)


@contextlib.contextmanager
def _force_extraction_sampling(local_ai, profile):
    """Make the extraction path use this profile's preset/temp/reasoning."""
    orig = local_ai.support

    def wrapped(*args, **kwargs):
        kwargs["preset"] = profile.extract_preset
        if profile.extract_temperature is not None:
            kwargs["temperature"] = profile.extract_temperature
        kwargs["reasoning"] = profile.reasoning
        return orig(*args, **kwargs)

    local_ai.support = wrapped
    try:
        yield
    finally:
        local_ai.support = orig


@contextlib.contextmanager
def _force_min_similarity(value):
    if value is None:
        yield
        return
    orig = pm_mod.MEMORY_MIN_SIMILARITY
    pm_mod.MEMORY_MIN_SIMILARITY = value
    try:
        yield
    finally:
        pm_mod.MEMORY_MIN_SIMILARITY = orig


# ── per-stage runners ────────────────────────────────────────────────────

def _extract_once(svc, local_ai, scenario, profile):
    svc.clear_collection()
    with _force_extraction_sampling(local_ai, profile):
        svc.extract_memories_sync(scenario.messages, generate_summary=True)
    facts = [e.content for e in svc.get_all(entry_type="fact")]
    summaries = svc.get_all(entry_type="session_summary")
    summary = summaries[0].content if summaries else ""
    return facts, summary


def _run_greeting(local_ai, summary):
    if not summary:
        return None
    try:
        template = get_prompt("greeting-returning")
        system = template.format(
            name="Wingman",
            backstory="A helpful in-game companion.",
            session_summary=summary,
        )
    except Exception:
        return None
    res = local_ai.support(
        text="Generate your greeting.",
        system_prompt=system,
        preset=SamplingPreset.CREATIVE,
    )
    return metrics.score_greeting(res.text if res else "", summary)


def run_scenario(local_ai, scenario, profile, samples: int = 1) -> dict:
    """Run one scenario end-to-end under one profile. Returns a JSON-able dict.

    Takes a LocalAiService directly so it works both from the CLI (via ModelHost)
    and from the running desktop app (reusing its live service for the lab view).
    """
    with _temp_memory_dir():
        svc = PersistentMemoryService(wingman_name="__suite__", local_ai_service=local_ai)
        svc.initialize()
        try:
            # 1) extraction (sampled — the support model is stochastic)
            conv_text = "\n".join(
                f"{m['role']}: {m['content']}" for m in scenario.messages)
            ext_samples, last_facts, last_summary = [], [], ""
            for _ in range(max(1, samples)):
                facts, summary = _extract_once(svc, local_ai, scenario, profile)
                ext_samples.append(metrics.score_extraction(facts, scenario, conv_text))
                last_facts, last_summary = facts, summary

            ext = dict(ext_samples[-1])
            ext["score"] = round(sum(s["score"] for s in ext_samples) / len(ext_samples), 3)
            ext["recall"] = round(sum(s["recall"] for s in ext_samples) / len(ext_samples), 3)
            ext["precision"] = round(sum(s["precision"] for s in ext_samples) / len(ext_samples), 3)
            ext["samples"] = len(ext_samples)
            ext["facts"] = last_facts
            ext["summary"] = last_summary

            # 2) recall probes (on the last extraction)
            recall_results = []
            with _force_min_similarity(profile.min_similarity):
                for probe in scenario.recall:
                    ctx = svc.build_memory_context_sync(probe.query)
                    recall_results.append(metrics.score_recall_probe(ctx, probe))

            # 3) greeting from the session summary
            greeting = _run_greeting(local_ai, last_summary)

            # 4) forget probes (these mutate the DB — run last on this extraction)
            forget_results = []
            for probe in scenario.forget:
                deleted = svc.forget_by_query_sync(probe.query)
                facts_after = [e.content for e in svc.get_all(entry_type="fact")]
                forget_results.append(
                    metrics.score_forget_probe(facts_after, probe, deleted))

            # 5) edit probes (fresh extraction so forget didn't remove targets)
            edit_results = []
            if scenario.edits:
                _extract_once(svc, local_ai, scenario, profile)
                with _force_min_similarity(profile.min_similarity):
                    for probe in scenario.edits:
                        hits = svc.search_sync(probe.find_query, limit=1, entry_type="fact")
                        if hits:
                            svc.update_memory_sync(hits[0].id, probe.new_content)
                        ctx = svc.build_memory_context_sync(probe.recall_query)
                        edit_results.append(metrics.score_edit_probe(ctx, probe))

            return {
                "scenario": scenario.id,
                "title": scenario.title,
                "category": scenario.category,
                "profile": profile.id,
                "extraction": ext,
                "recall": recall_results,
                "forget": forget_results,
                "edits": edit_results,
                "greeting": greeting,
            }
        finally:
            svc.close()


def run_suite(host: ModelHost, scenarios, profile, samples: int = 1) -> dict:
    """Run every scenario under one profile and aggregate."""
    if not host.apply(profile):
        raise RuntimeError(
            f"could not load models for profile '{profile.id}' "
            "(is the desktop app closed and are the models downloaded?)")
    results = [run_scenario(host.local_ai, s, profile, samples) for s in scenarios]
    return {
        "profile": profile.id,
        "profile_description": profile.description,
        "n_ctx": profile.n_ctx or host.settings.n_ctx,
        "samples": samples,
        "scenarios": results,
        "summary": metrics.aggregate(results),
    }
