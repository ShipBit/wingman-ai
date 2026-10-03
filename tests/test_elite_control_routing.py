"""Routing and authorization regressions. Model/OS doubles do not measure language accuracy."""
import asyncio
from dataclasses import replace
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.tool_execution import begin_turn, tool_call_scope, ControlAuthorization, SkillRoute
from skills.elite_dangerous_controls.routing import IntentRouter, parse_decision, RETRY
import test_elite_control_skill as skill_fixture
import test_elite_control_press as engine_fixture
from test_tool_execution_context import method


def completion(kind="execute", action="lights", state="off", mode="auto", choices=(), reply=""):
    data = {"kind": kind}
    if kind == "execute":
        data.update(action=action, state=state, mode=mode)
        if choices:
            data["choices"] = list(choices)
    elif kind == "clarify":
        data.update(choices=list(choices), reply=reply)
    elif kind == "unsupported":
        data["reply"] = reply
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content=json.dumps(data)))])



class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_transcript_context_catalog_and_no_tools(self):
        model = AsyncMock(return_value=completion())
        router = IntentRouter(model)
        text = "Would you kill the bloody headlights for me?"
        result = await router.route(text, {"mode": "ship", "ui": 0})
        self.assertEqual(("execute", "lights", "off"), (result.kind, result.action, result.state))
        model.assert_awaited_once()
        messages = model.await_args.args[0]
        data = json.loads(messages[1]["content"])
        self.assertEqual(text, data["transcript"])
        self.assertEqual({"mode": "ship", "ui": 0}, data["context"])
        self.assertIn("reload_weapon", data["catalog"])
        self.assertIsNone(model.await_args.kwargs["tools"])
        self.assertNotIn("Key_", json.dumps(messages))

    async def test_clarification_followup_expiry_unrelated_and_context_changes(self):
        now = [100]
        ask = completion("clarify", "", choices=("boost", "supercruise", "request_hyperspace_jump"),
                         reply="Boost, supercruise, or hyperspace, Commander?")
        model = AsyncMock(return_value=ask)
        router = IntentRouter(model, clock=lambda: now[0])
        context = {"session": "one", "mode": "ship", "ui": 0}
        await router.route("Get us out of here", context)
        self.assertIsNotNone(router.pending)
        model.return_value = completion(action="request_hyperspace_jump", state="toggle")
        await router.route("the jump", context)
        self.assertEqual("Get us out of here", json.loads(model.await_args.args[0][1]["content"])["pending"]["transcript"])
        self.assertIsNone(router.pending)
        for change in ("expiry", "context", "unrelated"):
            model.return_value = ask
            await router.route("Get us out of here", context)
            if change == "expiry":
                now[0] += 31
            changed = {**context, "ui": 6} if change == "context" else context
            model.return_value = completion("conversation", "")
            await router.route("What a beautiful star", changed)
            self.assertIsNone(router.pending)
            if change != "unrelated":
                self.assertIsNone(json.loads(model.await_args.args[0][1]["content"])["pending"])

    async def test_deadline_handles_synchronous_provider_and_discards_late_result(self):
        def slow():
            time.sleep(.2)
            return completion()
        async def model(*args, **kwargs):
            return slow()
        router = IntentRouter(model, timeout=.025)
        start = time.monotonic()
        result = await router.route("kill the lights", {})
        self.assertLess(time.monotonic() - start, .15)
        self.assertEqual(RETRY, result.reply)
        self.assertEqual(RETRY, (await router.route("again", {})).reply)
        await asyncio.sleep(.25)
        self.assertIsNone(router.pending)

    async def test_malformed_responses_failure_and_cancellation_never_execute(self):
        malformed = [None, SimpleNamespace(choices=[]), completion(action="unknown"), completion(choices=("boost",))]
        extra = completion()
        extra.choices[0].message.content = extra.choices[0].message.content[:-1] + ', "keys":"L"}'
        malformed.append(extra)
        for response in malformed:
            result = await IntentRouter(AsyncMock(return_value=response)).route("lights please", {})
            self.assertEqual(RETRY, result.reply)
        result = await IntentRouter(AsyncMock(side_effect=RuntimeError("provider offline"))).route("lights", {})
        self.assertEqual(RETRY, result.reply)
        result = await IntentRouter(AsyncMock(return_value=completion())).route("lights", {}, lambda: False)
        self.assertNotEqual("execute", result.kind)

    def test_negation_questions_quotes_hypotheticals_and_escape_are_fail_closed(self):
        for text in ("Don't kill the lights", "Do not turn lights on", "Are my lights on?",
                     'He said "turn off the lights"', "If we leave, boost", "Never boost",
                     "What does flight assist do?"):
            self.assertEqual("conversation", parse_decision(completion(), text).kind)
        self.assertEqual("clarify", parse_decision(completion(action="boost"), "Get us out of here").kind)
        self.assertEqual("clarify", parse_decision(completion(action="eject_all_cargo"), "Dump some weight").kind)
        self.assertEqual("execute", parse_decision(completion(action="eject_all_cargo"), "Jettison all cargo").kind)
        self.assertEqual("clarify", parse_decision(completion(), "Turn on lights and lower the gear").kind)


class SemanticSkillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await skill_fixture.SkillTests.asyncSetUp(self)
        self.skill._start = AsyncMock()  # No real global keyboard hooks in tests.

    async def test_first_cold_paraphrase_authorizes_one_action_and_one_call(self):
        begin_turn(self.wingman, "Kill the bloody lights")
        self.skill.llm_call = AsyncMock(return_value=completion())
        self.skill._routing_context = AsyncMock(return_value={})
        self.assertFalse(self.skill.is_prepared)
        route = await self.skill.route_request("Kill the bloody lights")
        self.assertEqual("execute", route.kind)
        with patch.object(self.skill, "_execute", new=AsyncMock(return_value="Copy that.")) as execute:
            with tool_call_scope("direct"):
                await self.skill.elite_control("lights", "off")
            with tool_call_scope("second-model-path"):
                await self.skill.elite_control("lights", "off")
            execute.assert_awaited_once()
            self.assertIs(route.authorization, execute.await_args.args[3]["authorization"])

    async def test_conversation_and_clarification_cannot_be_overruled_by_tools(self):
        for kind in ("conversation", "clarify", "unsupported"):
            begin_turn(self.wingman, "turn on lights")
            self.skill.llm_call = AsyncMock(return_value=completion(kind, "", reply="Please clarify, Commander."))
            self.skill._routing_context = AsyncMock(return_value={})
            await self.skill.route_request("turn on lights")
            with patch.object(self.skill, "_execute", new=AsyncMock()) as execute:
                with tool_call_scope("model"):
                    await self.skill.elite_control("lights", "on")
                execute.assert_not_awaited()

    async def test_disabled_routing_preserves_exact_controls(self):
        self.skill._property = lambda name: False
        self.skill.llm_call = AsyncMock()
        self.assertIsNone(await self.skill.route_request("kill the lights"))
        self.assertIsNotNone(self.skill.resolve_direct_request("turn lights off"))
        self.skill.llm_call.assert_not_awaited()

    async def test_cancel_clears_clarification_and_invalidates_turn(self):
        begin_turn(self.wingman, "cancel")
        self.skill._router.pending = {"choices": ["boost"]}
        result = await self.skill.route_request("cancel")
        self.assertEqual("Cancelled, Commander.", result.reply)
        self.assertIsNone(self.skill._router.pending)
        self.assertIsNone(self.wingman.latest_user_turn_id)

    async def test_intervening_request_invalidates_pending_even_if_it_bypassed_semantic_hook(self):
        first = begin_turn(self.wingman, "Get us out of here")
        self.skill._router.pending = {"turn_id": first.id}
        begin_turn(self.wingman, "some other skill's exact command")
        begin_turn(self.wingman, "the jump")
        self.skill._routing_context = AsyncMock(return_value={})
        self.skill.llm_call = AsyncMock(return_value=completion("conversation", ""))
        await self.skill.route_request("the jump")
        payload = json.loads(self.skill.llm_call.await_args.args[0][1]['content'])
        self.assertIsNone(payload['pending'])


class EngineAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = engine_fixture.KeyCommandTests.asyncSetUp

    async def test_authorization_replaces_phrase_gate_but_is_bound_to_turn_and_identity(self):
        auth = ControlAuthorization("turn", "lights", "off", "auto")
        result = await self.engine.run_result("lights", "off", request_id="turn:direct",
            user_text="Kill the bloody lights", authorization=auth)
        self.assertEqual("input_sent", result.outcome)
        for action, state, request_id in (("lights", "on", "turn:other"),
                                         ("night_vision", "off", "turn:third"), ("lights", "off", "new:direct")):
            result = await self.engine.run_result(action, state, request_id=request_id, authorization=auth)
            self.assertNotEqual("input_sent", result.outcome)
        self.assertEqual(1, self.backend.send.await_count)

    async def test_binding_context_or_cancellation_changes_after_routing_block_input(self):
        from skills.elite_dangerous_controls.runtime import routing_context
        context = routing_context(self.context, self.status)
        auth = ControlAuthorization("turn", "lights", "off", "auto", context)
        self.status["data"]["GuiFocus"] = 6
        result = await self.engine.run_result("lights", "off", request_id="turn:a", authorization=auth)
        self.assertEqual("blocked", result.outcome)
        self.backend.send.assert_not_awaited()
        self.status["data"]["GuiFocus"] = 0
        result = await self.engine.run_result("lights", "off", request_id="turn:b",
            authorization=replace(auth, call_id=""), still_current=lambda: False)
        self.assertEqual("invalid", result.outcome)
        self.backend.send.assert_not_awaited()


class CoreRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_execute_activates_and_conversation_never_dispatches(self):
        skill = SimpleNamespace(name="EliteDangerousControls", resolve_direct_request=lambda _: None,
            route_request=AsyncMock(return_value=SkillRoute("execute", ("elite_control", {"action": "lights"}))),
            ensure_activated=AsyncMock(return_value=(True, "ready")),
            execute_tool=AsyncMock(return_value=("Copy.", "Copy.")))
        wingman = SimpleNamespace(skills=[skill],
            skill_registry=SimpleNamespace(activate_skill=AsyncMock(return_value=(True, "ready", True))))
        result = await method("_try_direct_skill_request")(wingman, "kill the lights", Mock())
        self.assertEqual(("Copy.", skill), result)
        skill.route_request.return_value = SkillRoute("conversation")
        result = await method("_try_direct_skill_request")(wingman, "Are the lights on?", Mock())
        self.assertEqual((None, skill), result)
        skill.execute_tool.assert_awaited_once()

    async def test_any_exact_phrase_precedes_semantic_calls(self):
        semantic = SimpleNamespace(route_request=AsyncMock(side_effect=AssertionError("should not route")))
        exact = SimpleNamespace(name="Exact", resolve_direct_request=lambda _: ("control", {}),
            ensure_activated=AsyncMock(return_value=(True, "ready")), execute_tool=AsyncMock(return_value=("Copy.", "Copy.")))
        wingman = SimpleNamespace(skills=[semantic, exact],
            skill_registry=SimpleNamespace(activate_skill=AsyncMock(return_value=(True, "ready", True))))
        self.assertEqual(("Copy.", exact), await method("_try_direct_skill_request")(wingman, "lights", Mock()))
        semantic.route_request.assert_not_awaited()
