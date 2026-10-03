"""Wingman lifecycle adapter for verified Elite control requests."""

import asyncio
from collections import OrderedDict
from contextlib import suppress
from importlib import import_module, util
import json
import os
from pathlib import Path
import platform
import sys
from typing import Literal

from api.enums import LogType
from skills.skill_base import Skill, tool
from services.tool_execution import current_turn, current_call, ControlAuthorization, SkillRoute
from services.elite_runtime_identity import capture, CONTROL_FILES, PROCESS_INSTANCE


# Custom skills are loaded by filename. Give bundled siblings a real package
# without changing sys.path or relying on the source checkout being installed.
_package = "_wingman_elite_controls"
if _package not in sys.modules:
    _spec = util.spec_from_file_location(_package, Path(__file__).with_name("__init__.py"),
                                       submodule_search_locations=[str(Path(__file__).parent)])
    _module = util.module_from_spec(_spec)
    sys.modules[_package] = _module
    _spec.loader.exec_module(_module)
runtime = import_module(_package + ".runtime")
inputs = import_module(_package + ".input")
observation = import_module(_package + ".observation")
workflow_module = import_module(_package + ".workflows")
speech_module = import_module(_package + ".speech")
routing = import_module(_package + ".routing")
_spec = util.spec_from_file_location("_elite_control_telemetry", Path(__file__).parent.parent / "elite_dangerous/telemetry.py")
telemetry = util.module_from_spec(_spec)
_spec.loader.exec_module(telemetry)
LOADED_FILES = {"controls/" + name: capture(Path(__file__).with_name(name)) for name in CONTROL_FILES}
LOADED_FILES["telemetry/telemetry.py"] = capture(Path(telemetry.__file__))


class EliteDangerousControls(Skill):
    def __init__(self, config, settings, wingman):
        super().__init__(config, settings, wingman)
        self._engine = None
        self._reader = None
        self._routing_reader = None
        self._watcher = None
        self._settings_key = None
        self._revision = None
        self._stopping = False
        self._requests = OrderedDict()
        self._request_turn = None
        self.loaded_files = LOADED_FILES
        self._cancel_hook = None
        self._workflow = None
        # Core injects llm_call after constructing a skill; resolve it at call time.
        self._speech = speech_module.CompanionSpeech(
            lambda messages, tools=None: self.llm_call(messages, tools=tools), self._persona, self._log)
        self._router = routing.IntentRouter(
            lambda messages, tools=None: self.llm_call(messages, tools=tools), self._log)

    def _persona(self):
        prompts = getattr(getattr(self.wingman, "config", None), "prompts", None)
        return getattr(prompts, "backstory", "") or "A concise, capable companion for an Elite Dangerous commander."

    def _property(self, name):
        return self.retrieve_custom_property_value(name, [])

    async def _on_loop(self, callback):
        loop = self.wingman.audio_player.event_loop
        if loop is None or not loop.is_running():
            raise ValueError("Wingman runtime is unavailable.")
        if loop is asyncio.get_running_loop():
            return await callback()
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(callback(), loop))

    async def prepare(self):
        await super().prepare()
        self._stopping = False
        await self._on_loop(self._start)

    async def _start(self):
        if self._stopping:
            return
        if self._watcher is None or self._watcher.done():
            self._watcher = asyncio.create_task(self._watch())
        if platform.system() == "Windows" and self._cancel_hook is None:
            from keyboard import keyboard
            # A local, single physical Escape press only cancels; never injects.
            loop = asyncio.get_running_loop()
            self._cancel_hook = keyboard.on_press_key("esc", lambda _: loop.call_soon_threadsafe(self._cancel))

    def _cancel(self):
        # Also invalidate a request still awaiting routing/model output.
        self.wingman.latest_user_turn_id = None
        self._router.clear()
        if self._workflow:
            self._workflow.cancel()
        if self._engine:
            self._engine.cancel()

    async def _watch(self):
        while not self._stopping:
            if self._engine:
                try:
                    snapshot = await self._engine.resolver.stable()
                    if self._revision != snapshot["revision"]:
                        self._revision = snapshot["revision"]
                        self._log({"event": "bindings_reloaded", "revision": self._revision,
                                   "configured": len(snapshot["available"]), "unavailable": len(snapshot["unavailable"])})
                except (OSError, ValueError, runtime.ET.ParseError):
                    self._revision = None  # Never keep a stale usable mapping.
                if self._workflow:
                    await self._workflow.monitor()
            await asyncio.sleep(1)

    def _log(self, event):
        self.printr.print("Elite controls: " + json.dumps(event, sort_keys=True), color=LogType.SYSTEM, server_only=True)
        # Explicitly armed by the acceptance CLI. Records stay local and private.
        directory = os.environ.get("WINGMAN_ELITE_ACCEPTANCE_DIR")
        if directory and event.get("request_id"):
            from uuid import uuid4
            try:
                target = Path(directory)
                target.mkdir(parents=True, exist_ok=True)
                armed_path = target.parent / "armed.json"
                armed = json.loads(armed_path.read_text(encoding="utf-8")) if armed_path.is_file() else {}
                with (target / (uuid4().hex + ".json")).open("x", encoding="utf-8") as handle:
                    json.dump({"path": armed.get("path", "voice"), "case": armed.get("case"), **event}, handle, indent=2)
            except (OSError, ValueError) as exc:
                self.printr.print("Elite acceptance evidence could not be saved: " + str(exc), server_only=True)

    async def _observe(self):
        return await observation.observe_status(self._reader, telemetry)

    def _journal_directory(self):
        journal = self._property("journal_directory")
        if not journal:
            for skill in getattr(self.wingman, "skills", []):
                if skill.config.name == "EliteDangerous":
                    journal = skill.retrieve_custom_property_value("journal_directory", [])
                    break
        return Path(journal or telemetry.default_journal_dir())

    async def _routing_context(self):
        if platform.system() != "Windows":
            return {}
        try:
            process = inputs.WindowsInput().context()
            directory = self._journal_directory()
            if self._routing_reader is None or self._routing_reader.directory != directory:
                self._routing_reader = telemetry.JournalReader(directory)
            observed = await observation.observe_status(self._routing_reader, telemetry)
            return runtime.routing_context(process, observed)
        except (ValueError, OSError, KeyError):
            return {}  # Interpretation remains possible; execution rechecks everything.

    async def route_request(self, text):
        """Cold-safe, optional semantic hook. No input or activation occurs here."""
        if self._stopping or self._property("semantic_routing") is not True:
            self._router.clear()
            return None
        turn = current_turn.get()
        if not turn:
            return SkillRoute("clarify", reply=routing.RETRY)
        if self.name in turn.routes:
            return turn.routes[self.name]
        # Deny model tool execution while a classification is pending or fails.
        turn.routes[self.name] = SkillRoute("conversation")
        if self._router.pending and self._router.pending.get("turn_id") != turn.previous_id:
            self._router.clear()  # An intervening request may have used another exact skill.
        if text.casefold().strip(" .!") in {"cancel", "never mind", "nevermind", "cancel that", "forget it"}:
            self._cancel()
            result = SkillRoute("clarify", reply="Cancelled, Commander.")
            turn.routes[self.name] = result
            return result
        is_current = lambda: (not self._stopping and self._property("semantic_routing") is True and
                              getattr(self.wingman, "latest_user_turn_id", None) == turn.id)
        # Observation is local, read-only and separately bounded; no engine is needed.
        # Install local Escape cancellation even before the first skill activation.
        await self._on_loop(self._start)
        context = await self._on_loop(self._routing_context)
        if not is_current():
            return SkillRoute("clarify", reply="")
        decision = await self._router.route(text, context, is_current)
        if self._router.pending:
            self._router.pending["turn_id"] = turn.id
        if not is_current():
            self._router.clear()
            result = SkillRoute("clarify", reply="")
        elif decision.kind == "execute":
            authorization = ControlAuthorization(turn.id, decision.action, decision.state, decision.mode, context)
            result = SkillRoute("execute", ("elite_control", {"action": decision.action,
                "state": decision.state, "mode": decision.mode}), authorization=authorization)
        else:
            result = SkillRoute(decision.kind, reply=decision.reply)
        turn.routes[self.name] = result
        return result

    async def _execute(self, action, state, mode, request=None, workflow=None):
        def blocked(reason):
            result = runtime.ControlResult((request or {}).get("request_id", "unrouted"),
                                           {"action": action, "state": state, "mode": mode},
                                           "blocked", reason, "prerequisites")
            self._log(result.to_dict())
            return result.speech
        if self._stopping:
            return blocked("Elite controls are disabled.")
        if platform.system() != "Windows":
            return blocked("Elite controls require Windows; telemetry remains available.")
        try:
            if request and request["still_current"]():
                turn_id = request["request_id"].split(":", 1)[0]
                if turn_id != self._request_turn:
                    self._requests.clear()
                    self._request_turn = turn_id
            backend = inputs.WindowsInput()
            context = backend.context()
            directory = self._property("bindings_directory") or str(runtime.default_bindings())
            presets = self._property("presets_directory") or context["presets"]
            journal = self._property("journal_directory")
            if not journal:
                # Honor the telemetry skill's directory override as well.
                for skill in getattr(self.wingman, "skills", []):
                    if skill.config.name == "EliteDangerous":
                        journal = skill.retrieve_custom_property_value("journal_directory", [])
                        break
            journal = journal or str(telemetry.default_journal_dir())
            profile = self.wingman.config.model_dump()
            ptt = {key: profile.get(key) for key in ("record_key", "record_key_codes", "record_mouse_button")}
            settings_key = (directory, presets, journal, json.dumps(ptt, sort_keys=True))
            if self._engine is None or settings_key != self._settings_key:
                if self._workflow:
                    await self._workflow.close()
                    self._workflow = None
                if self._engine:
                    await self._engine.close()
                self._reader = telemetry.JournalReader(Path(journal))
                self._engine = runtime.ControlEngine(backend, runtime.BindingResolver(
                    directory, presets, lambda: self.wingman.config.model_dump()), self._observe, self._log,
                    identity={"pid": os.getpid(), "instance": PROCESS_INSTANCE, "files": self.loaded_files},
                    requests=self._requests)
                self._settings_key = settings_key
            if workflow is not None:
                if self._workflow is None:
                    self._workflow = workflow_module.WorkflowRunner(self._engine, self._log)
                return await self._workflow.handle(**workflow, request_id=request["request_id"],
                                                   still_current=request["still_current"])
            if self._workflow and self._workflow.active:
                self._workflow.cancel("Workflow ended for your individual control request, Commander.")
            record = await self._engine.run_result(action, state, mode, **(request or {}))
            # Execution has finished. This call has no tools and cannot replay it.
            return await self._speech.acknowledge(record)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return blocked(str(exc)[:220])

    def resolve_direct_request(self, text):
        """Let Core route exact control phrases before model/instant-command replies."""
        workflow = workflow_module.parse_workflow(text)
        if workflow is not None:
            return "elite_workflow", workflow
        try:
            action, state, mode = runtime.parse_turn(text)
        except runtime.InvalidRequest:
            return None
        return "elite_control", {"action": action.replace(" ", "_"), "state": state, "mode": mode}

    @tool(description="Press one Elite control binding once per request. On/off words still press toggle keys once. Never skip using remembered state. Status reports readiness.", summarize=False)
    async def elite_control(self, action: str, state: Literal["on", "off", "toggle"],
                            mode: Literal["auto", "ship", "srv", "on_foot"] = "auto") -> tuple[str, str]:
        """Args:
            action: Catalog action ID, such as lights or night_vision; runtime routing authorizes it.
            state: On/off/toggle wording from the request; each sends one press.
            mode: Auto uses current vehicle telemetry.
        """
        turn, call = current_turn.get(), current_call.get()
        request_id = (turn.id + ":" + call) if turn and call else "missing-provenance"
        try:
            if not turn or not call:
                raise runtime.InvalidRequest("No originating user turn is available. Please repeat the request.")
            if getattr(self.wingman, "latest_user_turn_id", None) != turn.id:
                raise runtime.InvalidRequest("A newer user request arrived. No input sent.")
            route = turn.routes.get(self.name)
            if route is None:
                action, state, mode = runtime.validate_turn(turn.text, action, state, mode, require_state=False)
                if action in {"eject all cargo", "ejectallcargo", "ejectallcargo buggy"} and not routing.explicit_cargo_order(turn.text):
                    raise runtime.InvalidRequest("Please explicitly order eject all cargo, Commander.")
                self._router.clear()
                authorization = ControlAuthorization(turn.id, action.replace(" ", "_"), state, mode)
                route = SkillRoute("execute", authorization=authorization)
                turn.routes[self.name] = route
            if route.kind != "execute" or route.authorization is None:
                raise runtime.InvalidRequest("This turn did not authorize an Elite control. Please make a new request.")
            action, state, mode = runtime.normalize_request(action, state, mode)
            authorization = route.authorization
            authorization.validate(turn.id, action, state, mode, call)
        except ValueError as exc:
            record = runtime.ControlResult(request_id, {"action": action, "state": state, "mode": mode},
                                           "invalid", str(exc), "user_intent")
            self._log(record.to_dict())
            result = record.speech
        else:
            request = {"request_id": request_id, "user_text": turn.text,
                       "authorization": authorization,
                       "still_current": lambda: getattr(self.wingman, "latest_user_turn_id", None) == turn.id}
            try:
                result = await self._on_loop(lambda: self._execute(action, state, mode, request))
            except asyncio.CancelledError:
                result = "Unverified: control cancelled. Check the game; no retry was sent."
        if self._stopping or (turn and getattr(self.wingman, "latest_user_turn_id", None) != turn.id):
            self._log({"event": "speech_superseded", "request_id": request_id})
            return "", ""
        self._log({"event": "speech_requested", "request_id": request_id,
                   "turn_id": turn.id if turn else None,
                   "transcript": turn.text if turn else "", "speech": result})
        await self.printr.print_async(result, color=LogType.INFO, source_name=self.wingman.name)
        return result, result  # Final skill response; Core must not rewrite it again.

    @tool(description="Run a named supervised Elite checklist. Start, status, continue at a player checkpoint, or cancel. No piloting, aiming or automatic consumable retries.", summarize=False)
    async def elite_workflow(self, operation: Literal["start", "status", "continue", "cancel"],
                             workflow: Literal["", *workflow_module.WORKFLOWS] = "") -> tuple[str, str]:
        """Args:
            operation: Requested workflow operation.
            workflow: Named workflow for start; otherwise leave empty.
        """
        turn, call = current_turn.get(), current_call.get()
        request_id = turn.id + ":" + call if turn and call else "missing-provenance"
        expected = workflow_module.parse_workflow(turn.text) if turn else None
        route = turn.routes.get(self.name) if turn else None
        if (route is not None or not call or expected != {"operation": operation, "workflow": workflow}
                or getattr(self.wingman, "latest_user_turn_id", None) != getattr(turn, "id", None)):
            result = "Please specify the workflow request, Commander. No step was started."
        else:
            self._router.clear()
            request = {"request_id": request_id,
                       "still_current": lambda: self.wingman.latest_user_turn_id == turn.id}
            async def execute():
                # Local cancellation/status do not depend on current game focus.
                if operation in ("cancel", "status"):
                    if self._workflow:
                        return await self._workflow.handle(operation, request_id=request_id)
                    return "No workflow is active, Commander."
                return await self._execute("status", "toggle", "auto", request,
                                           {"operation": operation, "workflow": workflow})
            result = await self._on_loop(execute)
        self._log({"event": "workflow_speech_requested", "request_id": request_id,
                   "transcript": turn.text if turn else "", "speech": result})
        await self.printr.print_async(result, color=LogType.INFO, source_name=self.wingman.name)
        return result, result

    async def get_prompt(self):
        return (await super().get_prompt() or "") + (
            "\nEvery requested Elite control must call elite_control, even for repeated requests. "
            "Each individual command presses its binding once; on/off wording does not suppress a toggle key. "
            "Pass the request's on/off/toggle wording explicitly. Never answer that a control is already set from memory. "
            "Successful input gets one brief varied AI acknowledgment after execution, without a game-state claim. "
            "Map controls instead report observed opening/closing, or an unverified result if no transition is observed. "
            "Natural-language routing owns the compact control catalog. Conversation or clarification "
            "does not authorize a control; never reinterpret those decisions through tool calls. "
            "Use elite_workflow only for an explicitly requested named workflow or checkpoint operation. "
            "Launch and docking automation are unavailable. The tools speak their own final results; do not repeat them.")

    async def unload(self):
        self._stopping = True
        self._router.clear()
        if self._cancel_hook is not None:
            from keyboard import keyboard
            keyboard.unhook(self._cancel_hook)
            self._cancel_hook = None
        async def stop():
            if self._workflow:
                await self._workflow.close()
                self._workflow = None
            if self._engine:
                await self._engine.close()
                self._engine = None
                self._settings_key = None
            if self._watcher:
                self._watcher.cancel()
                with suppress(asyncio.CancelledError):
                    await self._watcher
                self._watcher = None
        await self._on_loop(stop)
        await super().unload()
