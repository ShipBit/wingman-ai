"""Predefined supervised workflows; no model-written scripts or automatic retries."""
from collections import OrderedDict
from dataclasses import dataclass
import re

from .runtime import ControlEngine, InputBlocked, mode_of, resolve_action, STATE_BITS


@dataclass(frozen=True)
class Step:
    kind: str
    action: str = ''
    state: str = 'toggle'
    prompt: str = ''
    focus: tuple = (0,)


def ensure(action, state):
    return Step('ensure', action, state)


def press(action, prompt):
    return Step('press', action, prompt=prompt)


def checkpoint(prompt, focus=(0,)):
    return Step('checkpoint', prompt=prompt, focus=focus)


@dataclass(frozen=True)
class Workflow:
    mode: str
    steps: tuple
    completion: str


WORKFLOWS = {
    'travel_preparation': Workflow('ship', (
        ensure('landing_gear', 'off'), ensure('cargo_scoop', 'off'), ensure('hardpoints', 'off')),
        'Gear, scoop and hardpoints are stowed. You have the helm, Commander.'),
    'route_target': Workflow('ship', (
        checkpoint('Plot your route in the galaxy map, then close it. Say continue workflow when ready.', (0, 6)),
        press('target_next_route_system', 'Check the selected route system. Say continue workflow only if it is the target you want.')),
        'Route-target check complete. Align and engage the drive when you choose.'),
    'arrival_scanning': Workflow('ship', (
        checkpoint('Handle the arrival and settle at a safe speed. Say continue workflow when you are ready to scan.'),
        checkpoint('Use your discovery scanner and review the system map or FSS. Ask for exploration guidance if needed; close those views and say continue workflow when finished.', (0, 7, 9))),
        'Arrival checklist complete. Choose the next body or destination, Commander.'),
    'landing_preparation': Workflow('ship', (
        ensure('hardpoints', 'off'), ensure('cargo_scoop', 'off'),
        checkpoint('Obtain landing clearance if needed, leave supercruise and make your approach. Say continue workflow when it is safe to lower the gear.'),
        ensure('landing_gear', 'on')),
        'Landing gear is down; scoop and hardpoints are stowed. Approach and touchdown are yours.'),
    'combat_preparation': Workflow('ship', (
        ensure('landing_gear', 'off'), ensure('cargo_scoop', 'off'), ensure('hardpoints', 'on'),
        checkpoint('Check your target, fire group and rules of engagement. Say continue workflow when you are satisfied.')),
        'Combat preparation complete. You control the engagement.'),
    'power_targeting': Workflow('ship', (
        press('reset_power_distribution', 'Check that the power distribution suits a balanced starting point. Say continue workflow to request one increase to weapons.'),
        press('increase_weapon_power', 'Check your pips. Point at your intended target, then say continue workflow to select it.'),
        press('target_ahead', 'Verify the selected target. Say continue workflow if it is correct.')),
        'Power and target checks complete. Fire control is yours.'),
    'defensive_heat_sink': Workflow('ship', (
        press('deploy_heat_sink', 'Check whether the heat sink deployed. Say continue workflow to acknowledge the result; I will not launch another.'),),
        'Heat-sink request handled. No further deployment is queued.'),
    'defensive_chaff': Workflow('ship', (
        press('deploy_chaff', 'Check whether chaff deployed. Say continue workflow to acknowledge the result; I will not fire it again.'),),
        'Chaff request handled. No further deployment is queued.'),
    'srv_configuration': Workflow('srv', (
        ensure('cargo_scoop', 'off'), ensure('turret', 'off'),
        press('reset_power_distribution', 'Check your SRV pips and set drive assist as you prefer. Say continue workflow when ready.')),
        'SRV configuration checklist complete. Steering and driving are yours.'),
    'on_foot_equipment': Workflow('on_foot', (
        checkpoint('Select the suit and equipment you want. Say continue workflow to toggle your suit shields once.'),
        press('shields', 'Check the resulting shield state. Say continue workflow if it suits your situation.')),
        'Equipment check complete. Movement and weapon handling are yours.'),
    'on_foot_health': Workflow('on_foot', (
        press('use_health_pack', 'Check your health-pack result. Say continue workflow to acknowledge it; I will not use another.'),),
        'Health-pack request handled. No further use is queued.'),
    'on_foot_energy': Workflow('on_foot', (
        press('use_energy_cell', 'Check your energy-cell result. Say continue workflow to acknowledge it; I will not use another.'),),
        'Energy-cell request handled. No further use is queued.'),
}

START_ALIASES = {'prepare for travel': 'travel_preparation', 'prepare for landing': 'landing_preparation',
                 'prepare for combat': 'combat_preparation', 'configure srv': 'srv_configuration'}


def parse_workflow(text):
    value = ' '.join(text.casefold().replace('_', ' ').strip(' .!?').split())
    value = value.removeprefix('please ').removesuffix(' please')
    commands = {'workflow status': 'status', 'continue workflow': 'continue', 'cancel workflow': 'cancel'}
    if value in commands:
        return {'operation': commands[value], 'workflow': ''}
    if value in START_ALIASES:
        return {'operation': 'start', 'workflow': START_ALIASES[value]}
    match = re.fullmatch(r'(?:start|begin) (.+?)(?: workflow)?', value)
    if match and match[1].replace(' ', '_') in WORKFLOWS:
        return {'operation': 'start', 'workflow': match[1].replace(' ', '_')}
    return None


class WorkflowRunner:
    def __init__(self, controller, log=lambda event: None):
        self.controller, self.log = controller, log
        self.ensure_controller = ControlEngine(controller.input, controller.resolver, controller.observe,
            log, timeout=controller.timeout, identity=controller.identity, single_press=False)
        self.name, self.state, self.index = '', 'idle', 0
        self.reason, self.anchor, self.expected = '', None, {}
        self.waiting, self.busy, self.generation = False, False, 0
        self.seen = OrderedDict()
        self.current_request = ''

    @property
    def active(self):
        return self.state in ('running', 'waiting')

    def cancel(self, reason='Cancelled, Commander. No further steps are queued.'):
        self.generation += 1
        self.state, self.reason, self.waiting = 'cancelled', reason, False
        self.ensure_controller.cancel()
        # Both engines release only keys they own in the adapter's finally block.
        if self.busy:
            self.controller.cancel()
        self.log({'event': 'workflow_cancelled', 'workflow': self.name, 'request_id': self.current_request,
                  'reason': reason, 'step': self.index})

    async def close(self):
        self.cancel('Workflow ended because the companion was unloaded.')
        await self.ensure_controller.close()

    def status(self):
        if not self.name:
            return 'No workflow is active, Commander.'
        label = self.name.replace('_', ' ')
        if self.state == 'waiting':
            return label.capitalize() + ': ' + WORKFLOWS[self.name].steps[self.index].prompt
        if self.state in ('cancelled', 'stopped', 'complete'):
            return self.reason
        return label.capitalize() + ' is in progress, Commander.'

    async def _snapshot(self, *, check_expected=True):
        context = self.controller.input.context()
        snapshot = await self.controller.observe()
        binding = await self.controller.resolver.stable()
        if self.controller.input.context() != context:
            raise InputBlocked('Game focus changed. Start the workflow again when ready.')
        mode = mode_of(snapshot['data'])
        if mode != WORKFLOWS[self.name].mode or snapshot['observed'] < context['started']:
            raise InputBlocked('The game session or vehicle does not match this workflow.')
        focus = (0,)
        if self.waiting:
            focus = WORKFLOWS[self.name].steps[self.index].focus
        gui_focus = snapshot['data'].get('GuiFocus')
        if type(gui_focus) is not int or gui_focus not in focus or snapshot['data']['Flags'] & (1 << 30):
            raise InputBlocked('The game entered a menu, chat or transition. Start the workflow again when ready.')
        anchor = (context, snapshot['session'], binding['revision'])
        if self.anchor is not None and anchor != self.anchor:
            raise InputBlocked('Game focus, session or bindings changed. Start the workflow again when ready.')
        if check_expected:
            for bit, desired in self.expected.items():
                if bool(snapshot['data']['Flags'] & (1 << bit)) != desired:
                    raise InputBlocked('A previously checked control changed. Start the workflow again when ready.')
        return anchor, snapshot

    async def monitor(self):
        if self.active:
            try:
                await self._snapshot(check_expected=not self.busy)
            except Exception as exc:
                self.cancel(str(exc))

    async def handle(self, operation, workflow='', *, request_id, still_current=lambda: True):
        if request_id in self.seen:
            return 'That request has already been handled, Commander.'
        self.seen[request_id] = True
        if len(self.seen) > 256:
            self.seen.popitem(last=False)
        if operation == 'cancel':
            self.cancel()
            return self.reason
        if operation == 'status':
            return self.status()
        if self.busy:
            return 'A workflow step is still in progress, Commander.'
        if operation not in ('start', 'continue') or (operation == 'start' and workflow not in WORKFLOWS):
            return 'Choose a named companion workflow, Commander.'
        if not still_current():
            return 'That request was superseded. No workflow step was started.'
        if operation == 'start':
            if self.active:
                return 'Finish or cancel the current workflow before starting another, Commander.'
            self.name, self.state, self.index = workflow, 'running', 0
            self.anchor, self.expected, self.waiting = None, {}, False
            self.ensure_controller.requests.clear()
            self.generation += 1
        elif self.state != 'waiting':
            return 'There is no checkpoint to continue. Start a new workflow when ready, Commander.'
        self.busy, self.current_request = True, request_id
        generation = self.generation
        current = lambda: still_current() and generation == self.generation and self.active
        try:
            self.anchor, _ = await self._snapshot()
            if operation == 'continue':
                self.log({'event': 'workflow_player_checkpoint', 'request_id': request_id,
                          'workflow': self.name, 'step': self.index, 'source': 'explicit_continue'})
                self.index += 1
                self.waiting, self.state = False, 'running'
            definition = WORKFLOWS[self.name]
            while self.index < len(definition.steps):
                if not current():
                    raise InputBlocked('Workflow interrupted. Start a new workflow when ready.')
                await self._snapshot()
                step = definition.steps[self.index]
                if step.kind == 'checkpoint':
                    self.waiting, self.state = True, 'waiting'
                    return step.prompt
                engine = self.ensure_controller if step.kind == 'ensure' else self.controller
                result = await engine.run_result(step.action, step.state, definition.mode,
                    request_id=request_id + ':workflow:' + str(self.index), still_current=current)
                if step.kind == 'ensure' and result.outcome in ('confirmed', 'already_set'):
                    bit = STATE_BITS[resolve_action(step.action, definition.mode)]
                    self.expected[bit] = step.state == 'on'
                    self.index += 1
                elif step.kind == 'press' and result.outcome == 'input_sent':
                    self.waiting, self.state = True, 'waiting'
                    return step.prompt
                else:
                    self.state, self.reason = 'stopped', result.speech + ' Workflow stopped; no retry is queued.'
                    return self.reason
            await self._snapshot()
            if not current():
                raise InputBlocked('Workflow interrupted before completion.')
            self.state, self.reason = 'complete', definition.completion
            self.log({'event': 'workflow_complete', 'workflow': self.name, 'request_id': request_id,
                      'evidence': 'observed_prerequisites_and_player_checkpoints'})
            return self.reason
        except BaseException as exc:
            import asyncio
            if isinstance(exc, asyncio.CancelledError):
                self.state, self.reason = 'cancelled', 'Workflow cancelled, Commander. Check any action already underway; no retry is queued.'
            elif isinstance(exc, Exception):
                self.state, self.reason = 'stopped', str(exc)[:220] + ' Workflow stopped; no retry is queued.'
            else:
                raise
            return self.reason
        finally:
            self.busy = False
