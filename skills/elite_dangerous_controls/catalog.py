"""The Elite controls that become Wingman commands.

Only discrete presses: one key press does one thing. Movement, firing, held
inputs, chat and menus are left out, as is ejecting all cargo (too destructive
for a misheard sentence; the user can still build that command by hand).

Each entry is (Elite binding tag, command name). The command name is what the
model sees in execute_command and what the user says for instant activation,
so it reads like an order. The catalog started from S-Foxx's (wingman-ai#442).
"""

SHIP = (
    ("LandingGearToggle", "Toggle Landing Gear"),
    ("ToggleCargoScoop", "Toggle Cargo Scoop"),
    ("DeployHardpointToggle", "Toggle Hardpoints"),
    ("ShipSpotLightToggle", "Toggle Ship Lights"),
    ("NightVisionToggle", "Toggle Night Vision"),
    ("ToggleFlightAssist", "Toggle Flight Assist"),
    ("ToggleButtonUpInput", "Toggle Silent Running"),
    ("SetSpeedZero", "Zero Throttle"),
    ("SetSpeed25", "Quarter Throttle"),
    ("SetSpeed50", "Half Throttle"),
    ("SetSpeed75", "Three Quarter Throttle"),
    ("SetSpeed100", "Full Throttle"),
    ("SetSpeedMinus100", "Full Reverse Throttle"),
    ("HyperSuperCombination", "Engage Frame Shift Drive"),
    ("Supercruise", "Engage Supercruise"),
    ("Hyperspace", "Hyperspace Jump"),
    ("UseBoostJuice", "Boost"),
    ("DeployHeatSink", "Deploy Heat Sink"),
    ("FireChaffLauncher", "Deploy Chaff"),
    ("UseShieldCell", "Use Shield Cell"),
    ("SelectTarget", "Target Ahead"),
    ("CycleNextTarget", "Next Target"),
    ("CyclePreviousTarget", "Previous Target"),
    ("SelectHighestThreat", "Target Highest Threat"),
    ("CycleNextHostileTarget", "Next Hostile Target"),
    ("CyclePreviousHostileTarget", "Previous Hostile Target"),
    ("CycleNextSubsystem", "Next Subsystem"),
    ("CyclePreviousSubsystem", "Previous Subsystem"),
    ("TargetNextRouteSystem", "Target Next Route System"),
    ("TargetWingman0", "Target Wingman One"),
    ("TargetWingman1", "Target Wingman Two"),
    ("TargetWingman2", "Target Wingman Three"),
    ("SelectTargetsTarget", "Target Wingman's Target"),
    ("WingNavLock", "Toggle Wing Nav Lock"),
    ("CycleFireGroupNext", "Next Fire Group"),
    ("CycleFireGroupPrevious", "Previous Fire Group"),
    ("IncreaseEnginesPower", "Power To Engines"),
    ("IncreaseWeaponsPower", "Power To Weapons"),
    ("IncreaseSystemsPower", "Power To Systems"),
    ("ResetPowerDistribution", "Balance Power"),
    ("PlayerHUDModeToggle", "Switch HUD Mode"),
    ("GalaxyMapOpen", "Open Galaxy Map"),
    ("SystemMapOpen", "Open System Map"),
    ("FocusLeftPanel", "Open Navigation Panel"),
    ("FocusRightPanel", "Open Internal Panel"),
    ("FocusRadarPanel", "Open Role Panel"),
    ("FocusCommsPanel", "Open Comms Panel"),
    ("ExplorationFSSEnter", "Open Full Spectrum Scanner"),
    ("ExplorationFSSQuit", "Close Full Spectrum Scanner"),
    ("OrderRequestDock", "Fighter Return To Ship"),
    ("OrderDefensiveBehaviour", "Fighter Defend"),
    ("OrderAggressiveBehaviour", "Fighter Engage At Will"),
    ("OrderFocusTarget", "Fighter Attack My Target"),
    ("OrderHoldFire", "Fighter Hold Fire"),
    ("OrderHoldPosition", "Fighter Hold Position"),
    ("OrderFollow", "Fighter Follow Me"),
)

SRV = (
    ("HeadlightsBuggyButton", "SRV Lights"),
    ("ToggleBuggyTurretButton", "Toggle SRV Turret"),
    ("ToggleDriveAssist", "Toggle SRV Drive Assist"),
    ("ToggleCargoScoop_Buggy", "Toggle SRV Cargo Scoop"),
    ("AutoBreakBuggyButton", "Toggle SRV Handbrake"),
    ("SelectTarget_Buggy", "SRV Target Ahead"),
    ("IncreaseEnginesPower_Buggy", "SRV Power To Engines"),
    ("IncreaseWeaponsPower_Buggy", "SRV Power To Weapons"),
    ("IncreaseSystemsPower_Buggy", "SRV Power To Systems"),
    ("ResetPowerDistribution_Buggy", "SRV Balance Power"),
    ("PlayerHUDModeToggle_Buggy", "SRV Switch HUD Mode"),
    ("RecallDismissShip", "Recall Or Dismiss Ship"),
    ("GalaxyMapOpen_Buggy", "SRV Open Galaxy Map"),
    ("SystemMapOpen_Buggy", "SRV Open System Map"),
)

ON_FOOT = (
    ("HumanoidToggleFlashlightButton", "Toggle Flashlight"),
    ("HumanoidToggleNightVisionButton", "Toggle Suit Night Vision"),
    ("HumanoidToggleShieldsButton", "Toggle Suit Shields"),
    ("HumanoidHealthPack", "Use Medkit"),
    ("HumanoidBattery", "Use Energy Cell"),
    ("HumanoidReloadButton", "Reload Weapon"),
    ("HumanoidSwitchWeapon", "Switch Weapon"),
    ("HumanoidSelectPrimaryWeaponButton", "Select Primary Weapon"),
    ("HumanoidSelectSecondaryWeaponButton", "Select Secondary Weapon"),
    ("HumanoidSelectUtilityWeaponButton", "Select Sidearm"),
    ("HumanoidHideWeaponButton", "Holster Weapon"),
    ("HumanoidSelectFragGrenade", "Select Frag Grenade"),
    ("HumanoidSelectEMPGrenade", "Select EMP Grenade"),
    ("HumanoidSelectShieldGrenade", "Select Shield Projector"),
    ("HumanoidSwitchToRechargeTool", "Select Energylink"),
    ("HumanoidSwitchToCompAnalyser", "Select Profile Analyser"),
    ("HumanoidSwitchToSuitTool", "Select Suit Tool"),
    ("GalaxyMapOpen_Humanoid", "On Foot Open Galaxy Map"),
    ("SystemMapOpen_Humanoid", "On Foot Open System Map"),
)

# Elite's StartPreset file names one preset per line in this order. The
# general line covers menus, none of which are in the catalog.
MODES = ("general", "ship", "srv", "on_foot")
CATALOG = {"ship": SHIP, "srv": SRV, "on_foot": ON_FOOT}
CATEGORIES = {"ship": "Elite Ship", "srv": "Elite SRV", "on_foot": "Elite On Foot"}
NAMES = frozenset(name for rows in CATALOG.values() for _, name in rows)
