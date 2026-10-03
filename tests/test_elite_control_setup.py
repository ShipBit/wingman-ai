"""Portable installation fixtures: preserve controls, receipts and later edits."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import yaml
from integrations.elite_dangerous import control_setup as setup
from integrations.elite_dangerous.bindings import generate
from skills.elite_dangerous_controls.runtime import BindingResolver, conflicting_tags, source_mode


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.bindings=self.root/'bindings'
        self.presets=self.root/'presets'
        self.bindings.mkdir()
        self.presets.mkdir()
        self.selector=self.bindings/'StartPreset.4.start'
        self.selector.write_text('Pad\n'*4)
        self.source=self.presets/'Pad.binds'
        self.source.write_text('<Root PresetName="Pad"><YawAxis><Binding Device="HOTAS" Key="Joy_XAxis"/></YawAxis>'
            '<ShipSpotLightToggle><Primary Device="HOTAS" Key="Joy_1"/><Secondary Device="{NoDevice}" Key=""/></ShipSpotLightToggle>'
            '<NightVisionToggle><Primary Device="HOTAS" Key="Joy_2"/><Secondary Device="GamePad" Key="Joy_3"/></NightVisionToggle>'
            '<GalaxyMapHome><Primary Device="Keyboard" Key="Key_F1"/></GalaxyMapHome></Root>')
        self.profile=self.root/'EliteDangerous-Copilot.yaml'
        self.config={'name':'EliteDangerous-Copilot','record_key':'end','commands':[],
                     'discoverable_skills':['EliteDangerous'],'prompts':{'backstory':'My voice.'},'provider':'keep me'}
        self.profile.write_text(yaml.safe_dump(self.config))
        self.output=self.root/'stage'
        self.resolver=BindingResolver(self.bindings,self.presets,self.config)

    def prepare(self,**kwargs):
        return setup.prepare(self.profile,self.bindings,self.presets,self.output,**kwargs)

    def test_copies_preserve_axes_devices_and_original_files(self):
        original=self.source.read_bytes()
        selector=self.selector.read_bytes()
        plan=self.prepare()
        self.assertEqual(original,self.source.read_bytes())
        self.assertEqual(selector,self.selector.read_bytes())
        self.assertTrue(any(c['action']=='NightVisionToggle' and 'Both slots' in c['reason'] for c in plan['conflicts']))
        ship=next(t for t in plan['targets'][1:] if ' - Ship.' in t['path'])
        root=ET.fromstring((self.output/ship['staged']).read_bytes())
        self.assertEqual('HOTAS',root.find('YawAxis/Binding').get('Device'))
        self.assertEqual('Joy_1',root.find('ShipSpotLightToggle/Primary').get('Key'))
        self.assertEqual('Keyboard',root.find('ShipSpotLightToggle/Secondary').get('Device'))
        self.assertEqual('Joy_3',root.find('NightVisionToggle/Secondary').get('Key'))

    def test_per_conflict_choice_replaces_only_chosen_slot(self):
        roots,changes,conflicts=setup.supplement(self.resolver.read(),self.config,{'ship.NightVisionToggle':'Secondary'})
        self.assertEqual('Joy_2',roots['ship'].find('NightVisionToggle/Primary').get('Key'))
        self.assertEqual('Keyboard',roots['ship'].find('NightVisionToggle/Secondary').get('Device'))
        self.assertFalse(any(c['action']=='NightVisionToggle' for c in conflicts))

    def test_all_allocations_avoid_active_context_and_ptt_conflicts(self):
        snapshot=self.resolver.read()
        roots,changes,_=setup.supplement(snapshot,self.config)
        for change in changes:
            chord=change['chord']
            self.assertNotIn('Key_End',chord)
            for mode in setup.ACTIONS:
                if change['action'] in setup.ACTIONS[mode] and source_mode(mode, change['action']) == change['mode']:
                    self.assertFalse(conflicting_tags(roots, mode, change['action'], chord))

    def test_allocator_prefers_unmodified_and_reports_exhaustion(self):
        _, changes, _ = setup.supplement(self.resolver.read(), self.config)
        self.assertEqual(1, len(changes[0]['chord']))
        with patch.object(setup, 'shortcut_candidates', return_value=iter(())):
            _, changes, conflicts = setup.supplement(self.resolver.read(), self.config)
        self.assertFalse(changes)
        self.assertTrue(any('No conflict-free' in c['reason'] for c in conflicts))

    def test_setup_avoids_standalone_modifier_side_effects(self):
        self.source.write_text(self.source.read_text().replace('</Root>',
            '<UIFocus><Primary Device="Keyboard" Key="Key_LeftShift"/></UIFocus></Root>'))
        candidates = [('Key_LeftShift', 'Key_F10'), ('Key_RightControl', 'Key_F10')]
        with patch.object(setup, 'shortcut_candidates', return_value=iter(candidates)):
            _, changes, _ = setup.supplement(self.resolver.read(), self.config)
        ship = [c for c in changes if c['mode'] == 'ship']
        self.assertTrue(ship)
        self.assertTrue(all('Key_LeftShift' not in c['chord'] for c in ship))

    def install_old_modifier_bindings(self):
        candidates = [c for c in setup.shortcut_candidates() if c[:2] == ('Key_LeftControl', 'Key_LeftShift')]
        with patch.object(setup, 'shortcut_candidates', return_value=iter(candidates)):
            plan = self.prepare(select_presets=True)
        with patch.object(setup, 'game_running', return_value=False):
            setup.apply_plan(self.output / 'plan.json')
        snapshot = self.resolver.read()
        ship_path = Path(snapshot['sources']['ship']['file'])
        root = ET.fromstring(ship_path.read_bytes())
        ET.SubElement(ET.SubElement(root, 'UIFocus'), 'Primary', Device='Keyboard', Key='Key_LeftShift')
        root.find('GalaxyMapOpen/Primary').attrib.update(Device='Keyboard', Key='Key_Numpad_Divide')
        ship_path.write_bytes(ET.tostring(root))
        return plan, ship_path

    def test_receipt_repair_preserves_player_map_primary_and_restores_cleanly(self):
        _, ship_path = self.install_old_modifier_bindings()
        original = ship_path.read_bytes()
        original_profile = self.profile.read_bytes()
        original_selector = self.selector.read_bytes()
        stage = self.root / 'repair'
        plan = setup.prepare(self.profile, self.bindings, self.presets, stage, select_presets=True,
                             repair_from=[self.output / 'plan.json'])
        galaxy = next(c for c in plan['changes'] if c['mode'] == 'ship' and c['action'] == 'GalaxyMapOpen')
        self.assertEqual('Secondary', galaxy['slot'])
        self.assertEqual([], galaxy['chord'])
        with patch.object(setup, 'game_running', return_value=False):
            setup.apply_plan(stage / 'plan.json')
            snapshot = self.resolver.read()
            self.assertEqual(('Key_Numpad_Divide',), snapshot['available'][('ship', 'GalaxyMapOpen')]['chord'])
            self.assertNotIn('Key_LeftShift', snapshot['available'][('ship', 'SystemMapOpen')]['chord'])
            self.assertEqual(original_profile, self.profile.read_bytes())
            self.assertEqual(original, ship_path.read_bytes())
            setup.restore(stage / 'plan.json')
        self.assertEqual(original_selector, self.selector.read_bytes())

    def test_ownership_rejects_edited_slots_and_unapplied_or_tampered_receipts(self):
        plan, ship_path = self.install_old_modifier_bindings()
        root = ET.fromstring(ship_path.read_bytes())
        root.find('SystemMapOpen/Secondary').set('Key', 'Key_Slash')
        ship_path.write_bytes(ET.tostring(root))
        snapshot = self.resolver.read()
        owned, _ = setup.receipt_owned_slots(snapshot, [self.output / 'plan.json'])
        self.assertNotIn(('ship', 'SystemMapOpen', 'Secondary'), owned)
        roots, _, _ = setup.supplement(snapshot, self.config, owned_slots=owned)
        self.assertEqual('Key_Slash', roots['ship'].find('SystemMapOpen/Secondary').get('Key'))
        staged = self.output / next(t['staged'] for t in plan['targets'] if t['path'].endswith('.binds'))
        staged.write_bytes(staged.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'edited'):
            setup.receipt_owned_slots(snapshot, [self.output / 'plan.json'])
        (self.output / 'applied.json').unlink()
        with self.assertRaisesRegex(ValueError, 'applied'):
            setup.receipt_owned_slots(snapshot, [self.output / 'plan.json'])

    def test_inherited_slots_need_original_receipt_and_selected_preset_anchor(self):
        self.install_old_modifier_bindings()
        second = self.root / 'second-install'
        setup.prepare(self.profile, self.bindings, self.presets, second, select_presets=True)
        with patch.object(setup, 'game_running', return_value=False):
            setup.apply_plan(second / 'plan.json')
        snapshot = self.resolver.read()
        key = ('ship', 'GalaxyMapOpen', 'Secondary')
        owned, _ = setup.receipt_owned_slots(snapshot, [self.output / 'plan.json'])
        self.assertNotIn(key, owned)  # An old unrelated preset is not sufficient.
        owned, _ = setup.receipt_owned_slots(snapshot, [second / 'plan.json'])
        self.assertNotIn(key, owned)  # A copied slot is not an original allocation.
        owned, _ = setup.receipt_owned_slots(snapshot, [second / 'plan.json', self.output / 'plan.json'])
        self.assertIn(key, owned)

    def test_receipt_owned_commands_removed_user_commands_kept(self):
        self.source.write_text('<Root PresetName="Pad"><ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_Insert"/></ShipSpotLightToggle></Root>')
        generated=generate(self.bindings,self.presets)['commands']
        custom={'name':'my command','actions':[{'wait':0.1}]}
        self.config['commands']=[*deepcopy(generated),custom]
        result=setup.migrate_profile(self.config,[{'version':1,'commands':generated}])
        self.assertEqual([custom],result['commands'])
        self.assertEqual('keep me',result['provider'])
        self.assertIn('EliteDangerousControls',result['discoverable_skills'])
        self.assertEqual(result,setup.migrate_profile(result,[]))
        self.config['commands'][0]['actions']=[{'wait':0.2}]
        with self.assertRaisesRegex(ValueError,'edited'):
            setup.migrate_profile(self.config,[{'version':1,'commands':generated}])

    def test_apply_restore_and_no_selector_edits(self):
        before=self.profile.read_bytes()
        selected=self.selector.read_bytes()
        plan=self.prepare()
        with patch.object(setup,'game_running',return_value=False):
            setup.apply_plan(self.output/'plan.json')
            self.assertEqual(selected,self.selector.read_bytes())
            for t in plan['targets']:self.assertTrue(Path(t['path']).exists())
            setup.restore(self.output/'plan.json')
        self.assertEqual(before,self.profile.read_bytes())
        self.assertFalse(any(Path(t['path']).exists() for t in plan['targets'][1:]))

    def test_apply_refuses_running_game_and_changed_inputs(self):
        self.prepare()
        before=self.profile.read_bytes()
        with patch.object(setup,'game_running',return_value=True):
            with self.assertRaisesRegex(ValueError,'Close Elite'):setup.apply_plan(self.output/'plan.json')
        self.assertEqual(before,self.profile.read_bytes())
        self.source.write_text('<Root PresetName="Pad"/>')
        with patch.object(setup,'game_running',return_value=False):
            with self.assertRaisesRegex(ValueError,'changed'):setup.apply_plan(self.output/'plan.json')

    def test_selected_upgrade_round_trips_all_four_selectors_and_preserves_routing_opt_out(self):
        before = self.selector.read_bytes()
        self.config['skills'] = [{'module': 'skills.elite_dangerous_controls.main',
            'custom_properties': [{'id': 'semantic_routing', 'value': False}]}]
        self.profile.write_text(yaml.safe_dump(self.config))
        plan = self.prepare(select_presets=True)
        self.assertEqual(3, plan['version'])
        with patch.object(setup, 'game_running', return_value=False):
            setup.apply_plan(self.output / 'plan.json')
            self.assertEqual([plan['select_in_game'][m] for m in ('general','ship','srv','on_foot')],
                             self.selector.read_text().splitlines())
            installed = yaml.safe_load(self.profile.read_text())
            self.assertFalse(installed['skills'][0]['custom_properties'][0]['value'])
            setup.restore(self.output / 'plan.json')
        self.assertEqual(before, self.selector.read_bytes())
        self.assertEqual(self.config, yaml.safe_load(self.profile.read_text()))

    def test_restore_preserves_user_edits_and_active_presets(self):
        plan=self.prepare()
        with patch.object(setup,'game_running',return_value=False):
            setup.apply_plan(self.output/'plan.json')
            self.selector.write_text(next(iter(plan['select_in_game'].values()))+'\n'+'Pad\n'*3)
            with self.assertRaisesRegex(ValueError,'original presets'):setup.restore(self.output/'plan.json')
            self.selector.write_text('Pad\n'*4)
            self.profile.write_text(self.profile.read_text()+'\n# user edit\n')
            with self.assertRaisesRegex(ValueError,'User edits'):setup.restore(self.output/'plan.json')
        self.assertIn('# user edit',self.profile.read_text())

    def test_transaction_rolls_back_on_late_write_failure(self):
        plan=self.prepare()
        before=self.profile.read_bytes()
        real=setup.atomic_write
        calls=[]
        def failing(path,data):
            calls.append(path)
            if len(calls)==2:raise OSError('disk failure')
            real(path,data)
        with patch.object(setup,'game_running',return_value=False),patch.object(setup,'atomic_write',side_effect=failing):
            with self.assertRaises(OSError):setup.apply_plan(self.output/'plan.json')
        self.assertEqual(before,self.profile.read_bytes())
        self.assertFalse(any(Path(t['path']).exists() for t in plan['targets'][1:]))

    def test_default_directory_and_renamed_profile_discovery(self):
        directory=self.root/'configs/_Elite Dangerous'
        directory.mkdir(parents=True)
        renamed=directory/'Renamed.yaml'
        renamed.write_text(yaml.safe_dump(self.config))
        (directory/'.Companion.yaml').write_text(yaml.safe_dump(self.config))
        self.assertEqual(renamed.resolve(),setup.profile_path(self.root/'configs'))

    def test_installed_copies_resolve_all_actions_after_game_selection(self):
        plan=self.prepare(choices={'ship.NightVisionToggle':'Secondary'})
        self.assertFalse(plan['conflicts'])
        with patch.object(setup,'game_running',return_value=False):
            setup.apply_plan(self.output/'plan.json')
        self.selector.write_text('\n'.join(plan['select_in_game'][m] for m in ('general','ship','srv','on_foot'))+'\n')
        resolved=self.resolver.read()
        self.assertFalse(resolved['unavailable'],resolved['unavailable'])
        self.assertEqual(sum(map(len,setup.ACTIONS.values())),len(resolved['available']))

    def test_source_setup_resolves_default_renamed_profile(self):
        from integrations.elite_dangerous.setup import profile_directory, selected_profile_path, merge_profile
        directory=self.root/'configs/_Elite Dangerous'
        directory.mkdir(parents=True)
        renamed=directory/'Copilot.yaml'
        renamed.write_text(yaml.safe_dump(self.config))
        (directory/'.Companion.yaml').write_text(yaml.safe_dump(self.config))
        self.assertEqual(renamed,selected_profile_path(profile_directory(self.root/'configs')))
        merged=merge_profile(self.config,{'discoverable_mcps':[]},{},allow_renamed=True)
        self.assertEqual(self.config['name'],merged['name'])

    def test_control_migration_preserves_inherited_capabilities(self):
        profile=deepcopy(self.config)
        profile.pop('discoverable_skills')
        defaults={'discoverable_skills':['EliteDangerous','OtherSkill']}
        updated=setup.migrate_profile(profile,[],defaults)
        self.assertEqual(['EliteDangerous','OtherSkill','EliteDangerousControls'],updated['discoverable_skills'])
        self.assertEqual(['EliteDangerous','OtherSkill'],defaults['discoverable_skills'])

    def test_friendly_names_preserve_existing_name_collisions(self):
        existing = self.bindings / 'Wingman - Ship.4.0.binds'
        existing.write_bytes(b'player-owned data')
        plan = self.prepare()
        self.assertEqual('Wingman - Ship 2', plan['select_in_game']['ship'])
        self.assertEqual('Wingman - SRV', plan['select_in_game']['srv'])
        self.assertEqual(b'player-owned data', existing.read_bytes())

    def legacy_install(self):
        plan = self.prepare()
        # Reproduce a version-1 installation made by the old hash-name generator.
        for target in plan['targets'][1:]:
            staged = self.output / target['staged']
            root = ET.fromstring(staged.read_bytes())
            mode = next(m for m, name in plan['select_in_game'].items() if name == root.get('PresetName'))
            name = 'Wingman ' + mode.replace('_', ' ') + ' abc1234567'
            root.set('PresetName', name)
            raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            staged.write_bytes(raw)
            target['path'] = str(self.bindings / (name + '.4.0.binds'))
            target['after_sha256'] = setup.digest(raw)
            plan['select_in_game'][mode] = name
        (self.output / 'plan.json').write_text(json.dumps(plan))
        with patch.object(setup, 'game_running', return_value=False):
            setup.apply_plan(self.output / 'plan.json')
        self.selector.write_text('Pad\n' + '\n'.join(plan['select_in_game'][m] for m in ('ship', 'srv', 'on_foot')) + '\n')
        return plan

    def test_rename_selected_presets_preserves_game_edits_and_restores_selector(self):
        previous = self.legacy_install()
        srv = next(Path(t['path']) for t in previous['targets'][1:] if ' srv ' in t['path'])
        root = ET.fromstring(srv.read_bytes())
        ET.SubElement(root.find('ToggleDriveAssist'), 'ToggleOn', Value='0')
        # The game upgrades an installed 4.0 preset to 4.2 when saving controls.
        srv = srv.with_name(srv.name.replace('.4.0.binds', '.4.2.binds'))
        root.set('MinorVersion', '2')
        srv.write_bytes(ET.tostring(root))
        source_raw = srv.read_bytes()
        selector_raw = self.selector.read_bytes()
        stage = self.root / 'renames'
        plan = setup.prepare_preset_names(self.output / 'plan.json', stage)
        self.assertEqual(2, plan['version'])
        self.assertEqual(selector_raw, self.selector.read_bytes())
        with patch.object(setup, 'game_running', return_value=False):
            setup.apply_plan(stage / 'plan.json')
            self.assertEqual(['Pad', 'Wingman - Ship', 'Wingman - SRV', 'Wingman - On Foot'], self.selector.read_text().splitlines())
            new = ET.fromstring((self.bindings / 'Wingman - SRV.4.2.binds').read_bytes())
            self.assertEqual('0', new.find('ToggleDriveAssist/ToggleOn').get('Value'))
            self.assertEqual(source_raw, srv.read_bytes())
            setup.restore(stage / 'plan.json')
        self.assertEqual(selector_raw, self.selector.read_bytes())
        self.assertEqual(source_raw, srv.read_bytes())

    def test_rename_leaves_other_selected_presets_untouched_and_detects_changes(self):
        self.legacy_install()
        names = self.selector.read_text().splitlines()
        names[2] = 'Pad'
        self.selector.write_text('\n'.join(names) + '\n')
        stage = self.root / 'renames'
        plan = setup.prepare_preset_names(self.output / 'plan.json', stage)
        self.assertNotIn('srv', plan['select_in_game'])
        self.selector.write_text('Pad\n' * 4)
        with patch.object(setup, 'game_running', return_value=False), self.assertRaisesRegex(ValueError, 'changed'):
            setup.apply_plan(stage / 'plan.json')
        self.assertFalse((self.bindings / 'Wingman - Ship.4.0.binds').exists())

    def test_rename_rolls_back_when_selector_write_fails(self):
        self.legacy_install()
        stage = self.root / 'renames'
        setup.prepare_preset_names(self.output / 'plan.json', stage)
        before = self.selector.read_bytes()
        original = setup.atomic_write
        def write(path, data):
            if path == self.selector:
                raise OSError('selector locked')
            original(path, data)
        with patch.object(setup, 'game_running', return_value=False), patch.object(setup, 'atomic_write', side_effect=write):
            with self.assertRaises(OSError):
                setup.apply_plan(stage / 'plan.json')
        self.assertEqual(before, self.selector.read_bytes())
        self.assertFalse((self.bindings / 'Wingman - Ship.4.0.binds').exists())


if __name__=='__main__':unittest.main()
