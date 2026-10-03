"""Reviewed discrete controls. XML discovery never grants execution authority."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    id: str
    tag: str
    vehicle: str
    phrase: str
    contexts: frozenset[int] = frozenset({0})
    aliases: tuple[str, ...] = ()
    flight_only: bool = False
    explicit: bool = False
    supercruise_only: bool = False

    @property
    def description(self):
        return self.phrase.removeprefix("toggle ")


_entries = []


def add(vehicle, rows, *, contexts=(0,), flight=False, explicit=False, supercruise=False):
    for row in rows.strip().splitlines():
        tag, phrase, *aliases = row.strip().split("|")
        _entries.append(Action(phrase.removeprefix("toggle ").replace(" ", "_"), tag,
                               vehicle, phrase, frozenset(contexts), tuple(aliases),
                               flight, explicit, supercruise))


add("ship", """
LandingGearToggle|toggle landing gear|gear|undercarriage
ToggleCargoScoop|toggle cargo scoop|scoop
DeployHardpointToggle|toggle hardpoints|weapons out
SetSpeedMinus100|full reverse throttle
SetSpeedMinus75|three quarter reverse throttle
SetSpeedMinus50|half reverse throttle
SetSpeedMinus25|quarter reverse throttle
SetSpeed25|quarter throttle
SetSpeed50|half throttle
SetSpeed75|three quarter throttle|blue zone
SetSpeed100|full throttle
HyperSuperCombination|toggle frame shift drive|FSD
Supercruise|toggle supercruise|low wake
Hyperspace|request hyperspace jump|high wake|jump to next system
UseBoostJuice|boost|boost engines
ToggleFlightAssist|toggle flight assist|FA
DeployHeatSink|deploy heat sink|dump heat|heatsink
FireChaffLauncher|deploy chaff|chaff
UseShieldCell|use shield cell|SCB|shield cell bank
""", flight=True)
add("ship", """
ShipSpotLightToggle|toggle lights|headlights
NightVisionToggle|toggle night vision|NV
SetSpeedZero|zero throttle|cut throttle
SelectTarget|target ahead|target in front
CycleNextTarget|next target
CyclePreviousTarget|previous target
SelectHighestThreat|target highest threat
CycleNextHostileTarget|next hostile target
CyclePreviousHostileTarget|previous hostile target
TargetWingman0|target wing one
TargetWingman1|target wing two
TargetWingman2|target wing three
SelectTargetsTarget|target wing target
WingNavLock|toggle wing nav lock
CycleNextSubsystem|next subsystem
CyclePreviousSubsystem|previous subsystem
TargetNextRouteSystem|target next route system
CycleFireGroupNext|next fire group
CycleFireGroupPrevious|previous fire group
IncreaseEnginesPower|increase engine power|pips to engines
IncreaseWeaponsPower|increase weapon power|pips to weapons
IncreaseSystemsPower|increase system power|pips to systems
ResetPowerDistribution|reset power distribution|balance pips
PlayerHUDModeToggle|toggle hud mode|analysis mode|combat mode
OrderRequestDock|order fighter dock
OrderDefensiveBehaviour|order fighter defend
OrderAggressiveBehaviour|order fighter aggressive
OrderFocusTarget|order fighter attack target
OrderHoldFire|order fighter hold fire
OrderHoldPosition|order fighter hold position
OrderFollow|order fighter follow
""")
add("srv", """
HeadlightsBuggyButton|toggle lights
ToggleBuggyTurretButton|toggle turret
ToggleDriveAssist|toggle drive assist
ToggleCargoScoop_Buggy|toggle cargo scoop
SelectTarget_Buggy|target ahead
IncreaseEnginesPower_Buggy|increase engine power
IncreaseWeaponsPower_Buggy|increase weapon power
IncreaseSystemsPower_Buggy|increase system power
ResetPowerDistribution_Buggy|reset power distribution
BuggyCycleFireGroupNext|next fire group
BuggyCycleFireGroupPrevious|previous fire group
RecallDismissShip|recall dismiss ship|recall ship|dismiss ship
PlayerHUDModeToggle_Buggy|toggle hud mode
""")
add("on_foot", """
HumanoidToggleFlashlightButton|toggle flashlight|torch
HumanoidToggleNightVisionButton|toggle night vision
HumanoidToggleShieldsButton|toggle shields
HumanoidHealthPack|use health pack|medkit
HumanoidBattery|use energy cell|suit battery
HumanoidReloadButton|reload weapon|reload
HumanoidSwitchWeapon|switch weapon
HumanoidSelectPrimaryWeaponButton|select primary weapon
HumanoidSelectSecondaryWeaponButton|select secondary weapon
HumanoidSelectUtilityWeaponButton|select utility weapon
HumanoidSelectNextWeaponButton|next weapon
HumanoidSelectPreviousWeaponButton|previous weapon
HumanoidHideWeaponButton|holster weapon
HumanoidSelectNextGrenadeTypeButton|next grenade type
HumanoidSelectPreviousGrenadeTypeButton|previous grenade type
HumanoidSelectFragGrenade|select frag grenade
HumanoidSelectEMPGrenade|select emp grenade
HumanoidSelectShieldGrenade|select shield grenade
HumanoidSwitchToRechargeTool|select recharge tool|energy link
HumanoidSwitchToCompAnalyser|select profile analyser
HumanoidSwitchToSuitTool|select suit tool|arc cutter|genetic sampler
HumanoidToggleToolModeButton|toggle tool mode
HumanoidPrimaryInteractButton|primary interact
HumanoidSecondaryInteractButton|secondary interact
HumanoidToggleMissionHelpPanelButton|toggle mission help
HumanoidPing|ping
""")
for vehicle, suffix in (("ship", ""), ("srv", "_Buggy"), ("on_foot", "_Humanoid")):
    add(vehicle, f"GalaxyMapOpen{suffix}|toggle galaxy map", contexts=(0, 6))
    add(vehicle, f"SystemMapOpen{suffix}|toggle system map", contexts=(0, 7))
    if vehicle != "on_foot":
        for tag, name, focus, aliases in (("FocusLeftPanel", "navigation panel", 2, "left hand panel|left panel|external panel"),
                                 ("FocusRadarPanel", "role panel", 4, "bottom panel|fighter panel"),
                                 ("FocusRightPanel", "internal panel", 1, "right hand panel|right panel|ship panel")):
            add(vehicle, f"{tag}{suffix}|toggle {name}|{aliases}", contexts=(0, focus))
    # General bindings are read from the GENERAL selector, even with split presets.
    add(vehicle, """
UI_Up|menu up
UI_Down|menu down
UI_Left|menu left
UI_Right|menu right
UI_Select|menu select
UI_Back|menu back
UI_Toggle|menu toggle
CycleNextPanel|next panel tab
CyclePreviousPanel|previous panel tab
CycleNextPage|next panel page
CyclePreviousPage|previous panel page
""", contexts=(1, 2, 4, 5, 6, 7, 8))
    add(vehicle, "GalaxyMapHome|galaxy map home", contexts=(6,))
add("ship", "ExplorationFSSEnter|enter fss|full spectrum scanner", supercruise=True)
add("ship", """
ExplorationFSSZoomIn|fss zoom in
ExplorationFSSZoomOut|fss zoom out
ExplorationFSSMiniZoomIn|fss step zoom in
ExplorationFSSMiniZoomOut|fss step zoom out
ExplorationFSSQuit|exit fss
ExplorationFSSTarget|fss target
ExplorationFSSShowHelp|fss help
""", contexts=(9,))
add("ship", """
ExplorationSAAChangeScannedAreaViewToggle|toggle surface scan view
ExplorationSAAExitThirdPerson|exit surface scanner
ExplorationSAANextGenus|next surface genus
ExplorationSAAPreviousGenus|previous surface genus
""", contexts=(10,))
add("ship", "EjectAllCargo|eject all cargo", explicit=True, flight=True)
add("srv", "EjectAllCargo_Buggy|eject all cargo", explicit=True)

CATALOG = tuple(_entries)
BY_MODE_TAG = {(a.vehicle, a.tag): a for a in CATALOG}
ACTIONS = {mode: {a.tag: a.phrase for a in CATALOG if a.vehicle == mode}
           for mode in ("ship", "srv", "on_foot")}
ACTION_IDS = tuple(sorted({a.id for a in CATALOG} | {"status"}))
GENERAL_TAGS = frozenset(a.tag for a in CATALOG if a.phrase.startswith("menu ") or
                         a.tag.startswith("CycleNextP") or a.tag.startswith("CyclePreviousP") or a.tag == "GalaxyMapHome")


def source_mode(mode, tag):
    return "general" if tag in GENERAL_TAGS else mode


def exclusion(tag):
    if tag in {"ChargeECM", "TriggerFieldNeutraliser", "ExplorationFSSDiscoveryScan"}:
        return "Requires a held or charged input"
    if "Fire" in tag or "ThrowGrenade" in tag or "Melee" in tag:
        return "Sustained fire, aiming or combat input outside discrete catalog"
    if any(s in tag for s in ("Axis", "Raw", "Thrust", "Pitch", "Yaw", "Roll", "Steer", "Forward", "Backward", "Strafe", "Sprint", "Walk", "Jump")):
        return "Continuous movement, axis or held input"
    if any(s in tag for s in ("Comms", "TextEntry", "Chat")):
        return "Chat/text entry is excluded"
    if tag.startswith(("Cam", "FreeCam", "Vanity", "Store", "MultiCrew", "CommanderCreator")) or "Placement" in tag:
        return "Required camera, multicrew or editor context cannot be established"
    return "Not a reviewed discrete command (setting, hold action or unobservable context)"
