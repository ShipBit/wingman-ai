# Elite control command coverage

108 distinct action IDs; 151 vehicle/action pairs; 127 distinct reviewed bindings.
The staged installed presets provide 125 injectable bindings (149 vehicle/action pairs).
These are binding/readiness counts, not evidence of gameplay delivery.

| Vehicle | Action ID | Binding tag | Allowed UI focus | Staged readiness |
| --- | --- | --- | --- | --- |
| ship | landing_gear | LandingGearToggle | 0 | Configured |
| ship | cargo_scoop | ToggleCargoScoop | 0 | Configured |
| ship | hardpoints | DeployHardpointToggle | 0 | Configured |
| ship | full_reverse_throttle | SetSpeedMinus100 | 0 | Configured |
| ship | three_quarter_reverse_throttle | SetSpeedMinus75 | 0 | Configured |
| ship | half_reverse_throttle | SetSpeedMinus50 | 0 | Configured |
| ship | quarter_reverse_throttle | SetSpeedMinus25 | 0 | Configured |
| ship | quarter_throttle | SetSpeed25 | 0 | Configured |
| ship | half_throttle | SetSpeed50 | 0 | Configured |
| ship | three_quarter_throttle | SetSpeed75 | 0 | Configured |
| ship | full_throttle | SetSpeed100 | 0 | Configured |
| ship | frame_shift_drive | HyperSuperCombination | 0 | Configured |
| ship | supercruise | Supercruise | 0 | Configured |
| ship | request_hyperspace_jump | Hyperspace | 0 | Configured |
| ship | boost | UseBoostJuice | 0 | Configured |
| ship | flight_assist | ToggleFlightAssist | 0 | Configured |
| ship | deploy_heat_sink | DeployHeatSink | 0 | Configured |
| ship | deploy_chaff | FireChaffLauncher | 0 | Configured |
| ship | use_shield_cell | UseShieldCell | 0 | Configured |
| ship | lights | ShipSpotLightToggle | 0 | Configured |
| ship | night_vision | NightVisionToggle | 0 | Configured |
| ship | zero_throttle | SetSpeedZero | 0 | Configured |
| ship | target_ahead | SelectTarget | 0 | Configured |
| ship | next_target | CycleNextTarget | 0 | Configured |
| ship | previous_target | CyclePreviousTarget | 0 | Configured |
| ship | target_highest_threat | SelectHighestThreat | 0 | Configured |
| ship | next_hostile_target | CycleNextHostileTarget | 0 | Configured |
| ship | previous_hostile_target | CyclePreviousHostileTarget | 0 | Configured |
| ship | target_wing_one | TargetWingman0 | 0 | Configured |
| ship | target_wing_two | TargetWingman1 | 0 | Configured |
| ship | target_wing_three | TargetWingman2 | 0 | Configured |
| ship | target_wing_target | SelectTargetsTarget | 0 | Configured |
| ship | wing_nav_lock | WingNavLock | 0 | Configured |
| ship | next_subsystem | CycleNextSubsystem | 0 | Configured |
| ship | previous_subsystem | CyclePreviousSubsystem | 0 | Configured |
| ship | target_next_route_system | TargetNextRouteSystem | 0 | Configured |
| ship | next_fire_group | CycleFireGroupNext | 0 | Configured |
| ship | previous_fire_group | CycleFireGroupPrevious | 0 | Configured |
| ship | increase_engine_power | IncreaseEnginesPower | 0 | Configured |
| ship | increase_weapon_power | IncreaseWeaponsPower | 0 | Configured |
| ship | increase_system_power | IncreaseSystemsPower | 0 | Configured |
| ship | reset_power_distribution | ResetPowerDistribution | 0 | Configured |
| ship | hud_mode | PlayerHUDModeToggle | 0 | Configured |
| ship | order_fighter_dock | OrderRequestDock | 0 | Configured |
| ship | order_fighter_defend | OrderDefensiveBehaviour | 0 | Configured |
| ship | order_fighter_aggressive | OrderAggressiveBehaviour | 0 | Configured |
| ship | order_fighter_attack_target | OrderFocusTarget | 0 | Configured |
| ship | order_fighter_hold_fire | OrderHoldFire | 0 | Configured |
| ship | order_fighter_hold_position | OrderHoldPosition | 0 | Configured |
| ship | order_fighter_follow | OrderFollow | 0 | Configured |
| srv | lights | HeadlightsBuggyButton | 0 | Configured |
| srv | turret | ToggleBuggyTurretButton | 0 | Configured |
| srv | drive_assist | ToggleDriveAssist | 0 | Configured as hold; choose toggle in Elite controls first |
| srv | cargo_scoop | ToggleCargoScoop_Buggy | 0 | Configured |
| srv | target_ahead | SelectTarget_Buggy | 0 | Configured |
| srv | increase_engine_power | IncreaseEnginesPower_Buggy | 0 | Configured |
| srv | increase_weapon_power | IncreaseWeaponsPower_Buggy | 0 | Configured |
| srv | increase_system_power | IncreaseSystemsPower_Buggy | 0 | Configured |
| srv | reset_power_distribution | ResetPowerDistribution_Buggy | 0 | Configured |
| srv | next_fire_group | BuggyCycleFireGroupNext | 0 | Configured |
| srv | previous_fire_group | BuggyCycleFireGroupPrevious | 0 | Configured |
| srv | recall_dismiss_ship | RecallDismissShip | 0 | Configured |
| srv | hud_mode | PlayerHUDModeToggle_Buggy | 0 | Configured |
| on_foot | flashlight | HumanoidToggleFlashlightButton | 0 | Configured |
| on_foot | night_vision | HumanoidToggleNightVisionButton | 0 | Configured |
| on_foot | shields | HumanoidToggleShieldsButton | 0 | Configured |
| on_foot | use_health_pack | HumanoidHealthPack | 0 | Configured |
| on_foot | use_energy_cell | HumanoidBattery | 0 | Configured |
| on_foot | reload_weapon | HumanoidReloadButton | 0 | Configured |
| on_foot | switch_weapon | HumanoidSwitchWeapon | 0 | Configured |
| on_foot | select_primary_weapon | HumanoidSelectPrimaryWeaponButton | 0 | Configured |
| on_foot | select_secondary_weapon | HumanoidSelectSecondaryWeaponButton | 0 | Configured |
| on_foot | select_utility_weapon | HumanoidSelectUtilityWeaponButton | 0 | Configured |
| on_foot | next_weapon | HumanoidSelectNextWeaponButton | 0 | Configured |
| on_foot | previous_weapon | HumanoidSelectPreviousWeaponButton | 0 | Configured |
| on_foot | holster_weapon | HumanoidHideWeaponButton | 0 | Configured |
| on_foot | next_grenade_type | HumanoidSelectNextGrenadeTypeButton | 0 | Configured |
| on_foot | previous_grenade_type | HumanoidSelectPreviousGrenadeTypeButton | 0 | Configured |
| on_foot | select_frag_grenade | HumanoidSelectFragGrenade | 0 | Configured |
| on_foot | select_emp_grenade | HumanoidSelectEMPGrenade | 0 | Configured |
| on_foot | select_shield_grenade | HumanoidSelectShieldGrenade | 0 | Configured |
| on_foot | select_recharge_tool | HumanoidSwitchToRechargeTool | 0 | Configured |
| on_foot | select_profile_analyser | HumanoidSwitchToCompAnalyser | 0 | Configured |
| on_foot | select_suit_tool | HumanoidSwitchToSuitTool | 0 | Configured |
| on_foot | tool_mode | HumanoidToggleToolModeButton | 0 | Configured |
| on_foot | primary_interact | HumanoidPrimaryInteractButton | 0 | Configured |
| on_foot | secondary_interact | HumanoidSecondaryInteractButton | 0 | Configured |
| on_foot | mission_help | HumanoidToggleMissionHelpPanelButton | 0 | Configured |
| on_foot | ping | HumanoidPing | 0 | Configured |
| ship | galaxy_map | GalaxyMapOpen | 0, 6 | Configured |
| ship | system_map | SystemMapOpen | 0, 7 | Configured |
| ship | navigation_panel | FocusLeftPanel | 0, 2 | Configured |
| ship | role_panel | FocusRadarPanel | 0, 4 | Configured |
| ship | internal_panel | FocusRightPanel | 0, 1 | Configured |
| ship | menu_up | UI_Up | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | menu_down | UI_Down | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | menu_left | UI_Left | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | menu_right | UI_Right | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | menu_select | UI_Select | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | menu_back | UI_Back | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | menu_toggle | UI_Toggle | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | next_panel_tab | CycleNextPanel | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | previous_panel_tab | CyclePreviousPanel | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | next_panel_page | CycleNextPage | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | previous_panel_page | CyclePreviousPage | 1, 2, 4, 5, 6, 7, 8 | Configured |
| ship | galaxy_map_home | GalaxyMapHome | 6 | Configured |
| srv | galaxy_map | GalaxyMapOpen_Buggy | 0, 6 | Configured |
| srv | system_map | SystemMapOpen_Buggy | 0, 7 | Configured |
| srv | navigation_panel | FocusLeftPanel_Buggy | 0, 2 | Configured |
| srv | role_panel | FocusRadarPanel_Buggy | 0, 4 | Configured |
| srv | internal_panel | FocusRightPanel_Buggy | 0, 1 | Configured |
| srv | menu_up | UI_Up | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | menu_down | UI_Down | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | menu_left | UI_Left | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | menu_right | UI_Right | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | menu_select | UI_Select | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | menu_back | UI_Back | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | menu_toggle | UI_Toggle | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | next_panel_tab | CycleNextPanel | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | previous_panel_tab | CyclePreviousPanel | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | next_panel_page | CycleNextPage | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | previous_panel_page | CyclePreviousPage | 1, 2, 4, 5, 6, 7, 8 | Configured |
| srv | galaxy_map_home | GalaxyMapHome | 6 | Configured |
| on_foot | galaxy_map | GalaxyMapOpen_Humanoid | 0, 6 | Configured |
| on_foot | system_map | SystemMapOpen_Humanoid | 0, 7 | Configured |
| on_foot | menu_up | UI_Up | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | menu_down | UI_Down | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | menu_left | UI_Left | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | menu_right | UI_Right | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | menu_select | UI_Select | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | menu_back | UI_Back | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | menu_toggle | UI_Toggle | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | next_panel_tab | CycleNextPanel | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | previous_panel_tab | CyclePreviousPanel | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | next_panel_page | CycleNextPage | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | previous_panel_page | CyclePreviousPage | 1, 2, 4, 5, 6, 7, 8 | Configured |
| on_foot | galaxy_map_home | GalaxyMapHome | 6 | Configured |
| ship | enter_fss | ExplorationFSSEnter | 0 | Configured |
| ship | fss_zoom_in | ExplorationFSSZoomIn | 9 | Configured |
| ship | fss_zoom_out | ExplorationFSSZoomOut | 9 | Configured |
| ship | fss_step_zoom_in | ExplorationFSSMiniZoomIn | 9 | Configured |
| ship | fss_step_zoom_out | ExplorationFSSMiniZoomOut | 9 | Configured |
| ship | exit_fss | ExplorationFSSQuit | 9 | Configured |
| ship | fss_target | ExplorationFSSTarget | 9 | Configured |
| ship | fss_help | ExplorationFSSShowHelp | 9 | Configured |
| ship | surface_scan_view | ExplorationSAAChangeScannedAreaViewToggle | 10 | Configured as hold; choose toggle in Elite controls first |
| ship | exit_surface_scanner | ExplorationSAAExitThirdPerson | 10 | Configured |
| ship | next_surface_genus | ExplorationSAANextGenus | 10 | Configured |
| ship | previous_surface_genus | ExplorationSAAPreviousGenus | 10 | Configured |
| ship | eject_all_cargo | EjectAllCargo | 0 | Configured |
| srv | eject_all_cargo | EjectAllCargo_Buggy | 0 | Configured |
