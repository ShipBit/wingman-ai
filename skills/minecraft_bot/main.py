from typing import TYPE_CHECKING
from api.enums import LogType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill

from javascript import require, On
mineflayer = require('mineflayer')
pathfinder = require('mineflayer-pathfinder')

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

class MinecraftBot(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.bot = None

        self.player_name = "Yoda3001"

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "join_spawn_game",
                {
                    "type": "function",
                    "function": {
                        "name": "join_spawn_game",
                        "description": "Join a minecraft game and spawn as character.",
                    },
                },
            ),
            (
                "go_to_player",
                {
                    "type": "function",
                    "function": {
                        "name": "go_to_player",
                        "description": "Go to the player.",
                    },
                },
            ),
            (
                "follow_the_player",
                {
                    "type": "function",
                    "function": {
                        "name": "follow_the_player",
                        "description": "Endlessly follow the player.",
                    },
                },
            ),
        ]
        return tools
    
    async def init_mineflayer(self):
        self.bot = mineflayer.createBot({
            'host': '127.0.0.1',
            'port': 57440,
            'username': 'Steve'
        })
        self.bot.loadPlugin(pathfinder.pathfinder)

    async def go_to_player(self):
        movements = pathfinder.Movements(self.bot)
        player = self.bot.players[self.player_name]
        target = player.entity
        if not target:
            self.bot.chat("I don't see you !")
            return

        pos = target.position
        self.bot.pathfinder.setMovements(movements)
        self.bot.pathfinder.setGoal(pathfinder.goals.GoalNear(pos.x, pos.y, pos.z, 1))

    async def follow_the_player(self):
        player = self.bot.players[self.player_name]
        move = pathfinder.Movements(self.bot)
        self.bot.pathfinder.setMovements(move);
        self.bot.pathfinder.setGoal(pathfinder.goals.GoalFollow(player, 4), True);

    async def execute_tool(self, tool_name: str, parameters: dict[str, any]) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name == "join_spawn_game":
            await self.init_mineflayer()
            function_response = "Joined your game."

        if tool_name == "go_to_player":
            await self.go_to_player()
            function_response = "On my way."

        if tool_name == "follow_the_player":
            await self.follow_the_player()
            function_response = "Ok I'll follow you."

        if self.settings.debug_mode:
            await self.printr.print_async(f"Executed {tool_name} with parameters {parameters}. Result: {function_response}", color=LogType.INFO)

        return function_response, instant_response