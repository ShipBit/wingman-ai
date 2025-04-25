import json
import time
import traceback
import random
import asyncio

from services.printr import Printr
from services.secret_keeper import SecretKeeper
from wingmen.open_ai_wingman import OpenAiWingman

from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.keybindings import SCKeybindings
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.functions.uex_v2 import uex_api_module
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.function_manager import StarCitizensAiFunctionsManager, FunctionManager

DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


printr = Printr()
try:
    import pydirectinput as key_module
    print_debug("pydirectinput imported")
except AttributeError:
    # TODO: Instead of creating a banner make this an icon in the header
    # printr.print_warn(
    #     "pydirectinput is only supported on Windows. Falling back to pyautogui which might not work in games.",
    #     wait_for_gui=True
    # )
    import pyautogui as key_module
    print_debug("pyautogui imported")


class StarCitizenWingman(OpenAiWingman):
    """This Wingman uses the OpenAiWingman as basis, but has some major differences:

    1. It has Multi-Wingman Capabilities
    - Execute instant Actions as of OpenAiWingman using the standard configuration -> Great for this!
    - Execute command chains as of OpenAiWingman (combining a series of key presses) -> Great for this!
    
    Big differences starts now:
    - Execute star-citizen commands as specified by your current keybinding-settings for a given release and your custom keybind settings. All it needs is the default keybinding file + your exported keybinds overwrites. You only need to config complex commands or your own instant activation phrases.
    - All ingame commands are available. Instant Activation commands are provided for each of them dynamically. Commands can be filtered. Per Default, commands without keybinds are discarded. All commands can be checked in generated files.
    - incorporates UEX trading API letting you ask for best trade route (1 stop) between locations, best trade route from a given location, best sell option for a commodity, best selling option for a commodity at a location
    - DONE incorporates Galactepedia-Wiki search to get more detailed information about the game world and lore in game
    - DONE incorporates Delivery Mission Management: based on delivery missionS (yes multiple) you are interested in, it will analyse the mission text, extract the payout, the locations from where you have to retrieve a package and the associated delivery location, calculates the best collection and delivery route to have to travel the least possible stops + incorporates profitable trade routes between the stops to earn an extra money on the trip.
    - DONE based on a given trading consoles it will extract the location, commodity prices and stock levels and update the prices automatically in the UEX database
    
    2. smart Action selection with reduced context size
    - The system will get your command and will first ask GPT what kind of Action the user wants to execute (one of the above)
    - The response will be used, to make another call to GPT now with the appropriate context information (commands for keypresses, trading calls, wiki calls, box mission calls...)

    3. TODO Context-Logic cache: depending on your tasks, it will have different conversation-caches that will be selected on demand. Examples
    - If you execute a simple command, there is no need for a history, every gpt call can be fresh, effectively reducing cost of api usage. 
    - If you do a box mission, it will keep the history until you have completed your box mission(s), beeing able to guide you from box to box
    - If you do a trade, it will keep the history until it understands that you start your trading route from a complete different location.
    
    3. TODO Cache-Logic for text-to-speech responses to reduce cost with config parameters to specify the ammount of responses to be cached vs. dropped vs. renewed
    """

    def __init__(
        self,
        name: str,
        config: dict[str, any],
        secret_keeper: SecretKeeper,
        app_root_dir: str,
    ):
        super().__init__(
            name=name,
            config=config,
            secret_keeper=secret_keeper,
            app_root_dir=app_root_dir,
        )
        
        self.contexts_history = {}  # Dictionary to store the state of different conversion contexts
        self.current_context: AIContext = AIContext.CORA  # Name of the current context
        self.current_user_request: str = None  # saves the current user request
        self.switch_context_executed = False  # used to identify multiple switch executions that would be incorrect -> Error
        self.sc_keybinding_service: SCKeybindings = None  # initialised in validate
        self.uex2_api_key = None  # set in validate()
        self.uex2_secret_key = None # set in validate()
        self.uex_service: UEXApi2 = None  # set in validate()
        self.messages_buffer = 10
        self.current_tools = None # init in validate
        tdd_voices = set(self.config["openai"]["contexts"]["tdd_voices"].split(","))
        self.tdd_voice = random.choice(list(tdd_voices))
        self.config["openai"]["contexts"]["tdd_voice"] = self.tdd_voice
        self.config["openai"]["tts_voice"] = self.config["openai"]["contexts"]["cora_voice"]
        self.config["sound"]["play_beep"] = False
        self.config["sound"]["effects"] = ["ROBOT"]
        self.config["openai"]["conversation_model"] = self.config["openai"]["contexts"][f"context-{AIContext.CORA.name}"]["conversation_model"]
        self.overlay = None # init in validate
        self.ai_functions = {} # init in validate
        self.ai_functions_manager: StarCitizensAiFunctionsManager = None  # init in validate
        
        # init the configuration dynamically based on current star citizen settings.
        # the config is dynamically expanded for all mapped keybinds.
        # the user only configures special commands i.e. combination of keybindings to press

    def validate(self):
        errors = super().validate()
    
        try:
            # every conversation starts with the "context" that the user has configured
            self.sc_keybinding_service = SCKeybindings(self.config, self.secret_keeper)
            self.sc_keybinding_service.parse_and_create_files()

            self.uex2_api_key = self.secret_keeper.retrieve(
                requester="Cora SC",
                key="uex2_api_key",
                friendly_key_name="UEX2 API key",
                prompt_if_missing=False
            )
            self.uex2_secret_key = self.secret_keeper.retrieve(
                requester="Cora SC",
                key="uex2_secret_key",
                friendly_key_name="UEX2 secret user key",
                prompt_if_missing=False
            )
            self.uex_service = UEXApi2.init(
                uex_api_key=self.uex2_api_key,
                user_secret_key=self.uex2_secret_key
            )

            self.ai_functions_manager = StarCitizensAiFunctionsManager(self.config, self.secret_keeper)

            self.current_tools = self._get_context_tools(self.current_context)
            self.overlay = StarCitizenOverlay()
            self._set_current_context(AIContext.CORA, new=True)

            printr.print_err(
                ("IMPORTANT INFORMATION about this WingmenAI extension! \n"
                "This tool requires an OpenAI API. Data is transmitted to OpenAI. This incures costs. You cannot use this tool without valid API keys. \n"
                "This tool takes Screenshots of ingame elements. It will only make screenshots on given commands and only if the active window is 'Star Citizen'. \n"
                "BUT IT TAKES THEM. Do not use this tool if you are not trusting the source. \n"
                "This tool is open source and comes as is and without waranty. Use at your own risk. \n"
                "With that said, I hope you enjoy the tool and that it will make your game experience in star citizen even better. "
            ), wait_for_gui=True)

        except Exception as e:
            print(e)
            traceback.print_exc()
            errors.append(f"Initialisation Error: {e}. Check console for more information")

    def _set_current_context(self, new_context: AIContext, new: bool = False):
        """Set the current context to the specified context name."""
        self.current_context = new_context

        if new:
            # initialise a new context conversation history
            self.current_tools = self._get_context_tools(current_context=new_context)
            self.current_context = new_context
            context_prompt = f'{self.config["openai"]["contexts"].get(f"context-{new_context.name}")}'

            outpost_names = self.uex_service.get_category_names(uex_api_module.CATEGORY_OUTPOSTS)
            planet_names = self.uex_service.get_category_names(uex_api_module.CATEGORY_ORBITS)
            satellite_names = self.uex_service.get_category_names(uex_api_module.CATEGORY_MOONS)
            commodity_names = self.uex_service.get_category_names(uex_api_module.CATEGORY_COMMODITIES)
            cities_names = self.uex_service.get_category_names(uex_api_module.CATEGORY_CITIES)
            terminal_names = self.uex_service.get_category_names(uex_api_module.CATEGORY_TERMINALS)
            station_names = self.uex_service.get_category_names(uex_api_module.CATEGORY_STATIONS)

            context_prompt += (
                " Whenever you need to provide or reference the name of a location it must be one of the available tradeport-, planet-, satellite / moon or city names that matches best the player request. "
                "The same applies to commodity names. Identify the correct names among the following values: "
                f"Available outpost names: {outpost_names}. "
                f"Available planet and orbit names: {planet_names}. "
                f"Available satellite names: {satellite_names}. "
                f"Available city names: {cities_names}. "
                f"Available commodity names: {commodity_names}. "
                f"Available terminal names: {terminal_names}. "
                f"Available station names: {station_names}. "
            )

            functions_prompt = " "

            context_switch_prompt = ""
            if new_context == AIContext.CORA:
                context_prompt += (
                    f' The character you are supporting is named "{self.config["openai"]["player_name"]}". '
                    f'His title is {self.config["openai"]["player_title"]}. His ship call id is {self.config["openai"]["ship_name"]}. '
                    f'He wants you to respond in {self.config["openai"]["player_language"]}'
                )
                
                context_switch_prompt += f" Switch to context {AIContext.TDD}, if the player is calling a specific Trading Division, like 'Hurston Trading Division, this is Delta 7, Over'."

            if new_context == AIContext.TDD:
                context_switch_prompt += (
                    f" Whenever the player adresses a new Trading Division Location, switch the employee "
                    f"by calling the function switch_tdd_employee and select a different employee_id. "
                    f"If the current user request does not fit the current context, switch to an appropriate context "
                    f"by calling the switch_context function. Do switch to context {AIContext.CORA}, "
                    f"if the player adresses 'Cora' or using words like 'computer' or demanding a specific player or ship action or mission related actions. "
                    "Do switch as well, if the user is asking non trade related questions. "
                    f'He wants you to respond in {self.config["openai"]["player_language"]}. '
                )
            
            initial_user_message = ""
            for ai_function_manager in self.ai_functions_manager.get_managers(new_context):
                ai_function_manager: FunctionManager
                functions_prompt += ai_function_manager.get_function_prompt()
                start_info = ai_function_manager.cora_start_information()
                if len(start_info) > 0:
                    initial_user_message += json.dumps(start_info)
            
            context_prompt += functions_prompt

            self.messages = [{"role": "system", "content": f'{context_prompt}. On a request of the Player you will identify the context of his request. The current context is: {new_context.value}. Follow these rules to switch context: {context_switch_prompt}'}]

            if len(initial_user_message) > 0:
                print(f"Initial user message: {initial_user_message}")
                initial_user_message = "Follow these instructions: 1. welcome me. 2. summarize in a natural conversational way suitable for a tts engine the following information: " + initial_user_message
                self._add_user_message(initial_user_message)
            
                azure_config = None
                if self.conversation_provider == "azure":
                    azure_config = self._get_azure_config("conversation")

                completion = self.openai.ask(
                    messages=self.messages,
                    model=self.config["openai"].get("conversation_model"),
                    azure_config=azure_config,
                )

                if completion is None:
                    return None, None

                response_message, tool_calls = self._process_completion(completion)

                # do not tamper with this message as it will lead to 400 errors!
                self.messages.append(response_message)

                if response_message.content:
                    printr.print(f"Initialised Cora with: \n {response_message.content} ", wait_for_gui=True, tags="info")
                    asyncio.run(self._play_to_user(str(response_message.content)))

                printr.print("Cora is ready.", wait_for_gui=True, tags="info")

            # if len(initial_user_message) > 0:
            #     initial_user_message = "Hello, please get me information about the following questions. When you respond, greet me first and respond in my language: " + initial_user_message
            #     process_result, instant_response = self._get_response_for_transcript(initial_user_message, locale=None)

            #     actual_response = instant_response or process_result
            #     printr.print(f"<< ({self.name}): {actual_response}", tags="green")

            #     # the last step in the chain. You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.
            #     if process_result:
            #         self._play_to_user(str(process_result))
        else:
            # get the saved context history
            tmp_new_context_history = self.contexts_history[new_context]
            self.current_tools = tmp_new_context_history.get("tools").copy()
            self.messages = tmp_new_context_history.get("messages").copy()
            self.current_context = new_context

        if new_context == AIContext.CORA:
            self.messages_buffer = 10 # we don't need much memory for a given action
            self.current_tools = self._get_context_tools(current_context=new_context)  # recalculate tools
        elif new_context == AIContext.TDD:
            self.messages_buffer = 20 # dealing on the journey of the player to trade might require more context-information in the conversation
        
    def _save_current_context(self):
        """Save the current conversation history under the current context."""
        if self.current_context is not None:
            self.contexts_history[self.current_context] = { "messages": self.messages.copy(),
                                                            "tools": self.current_tools
                                                        }

    def _switch_context(self, new_context_name):    
        """Switch to a different context, saving the current one."""
        try:
            # Versuche, den Kontext basierend auf dem Namen zu finden
            # context_to_switch_to = AIContext(new_context_name)
            context_to_switch_to = next((context for context in AIContext if context.value == new_context_name), None)

            if context_to_switch_to is None:
                # Handle the case where the context is not found
                # For example, log an error or notify the user
                print(f"Context '{new_context_name}' not found.")
                return

            # Überprüfe, ob der Kontext im Dictionary existiert
            if context_to_switch_to in self.contexts_history:
                # Logik für den Fall, dass der Kontext existiert
                printr.print(f"Lade context {context_to_switch_to}.", tags="info")
                self._save_current_context()
                self._set_current_context(new_context=context_to_switch_to)
                
            else:
                # Logik für den Fall, dass der Kontext nicht existiert
                printr.print(f"Erstelle context {context_to_switch_to}.", tags="info")
                self._save_current_context()
                self._set_current_context(new_context=context_to_switch_to, new=True)

        except AttributeError:
            # Fehlerbehandlung, falls der Kontextname nicht existiert
            print_debug(f"Kontext {new_context_name} ist kein gültiger Kontext.")

    def _get_context_tools(self, current_context: AIContext):
        if current_context == AIContext.CORA:
            return self._get_cora_tools()
        elif current_context == AIContext.TDD:
            tdd_tools = []
            for ai_function_manager in self.ai_functions_manager.get_managers(current_context):
                ai_function_manager: FunctionManager
                tdd_tools.extend(ai_function_manager.get_function_tools())
            tdd_tools.append(self._context_switch_tool(current_context=AIContext.TDD))
            return tdd_tools
        else:
            return self._context_switch_tool()
       
    def _cleanup_conversation_history(self):
        """
        Overwritten from openai_ai_wingman to deal with context switches, as every context has his own message buffer.
        Cleans up the conversation history by removing messages that are too old.
        Overwritten with context switch sensitive message buffers"""
        remember_messages = self.messages_buffer

        if remember_messages is None or len(self.messages) == 0:
            return 0  # Configuration not set, nothing to delete.

        # The system message aka `context` does not count
        context_offset = (
            1 if self.messages and self.messages[0]["role"] == "system" else 0
        )

        # Find the cutoff index where to end deletion, making sure to only count 'user' messages towards the limit starting with newest messages.
        cutoff_index = len(self.messages) - 1
        user_message_count = 0
        for message in reversed(self.messages):
            if self._get_message_role(message) == "user":
                user_message_count += 1
                if user_message_count == remember_messages:
                    break  # Found the cutoff point.
            cutoff_index -= 1

        # If messages below the keep limit, don't delete anything.
        if user_message_count < remember_messages:
            return 0

        total_deleted_messages = cutoff_index - context_offset  # Messages to delete.

        # Remove the messages before the cutoff index, exclusive of the system message.
        del self.messages[context_offset:cutoff_index]

        # Optional debugging printout.
        if self.debug and total_deleted_messages > 0:
            printr.print(
                f"Deleted {total_deleted_messages} messages from the conversation history.",
                tags="warn",
            )

        return total_deleted_messages

    def _build_tools(self) -> list[dict]:
        """
        Overwritten. We calculate the tools when we switch contexts.

        Returns:
            list[dict]: A list of tool descriptors in OpenAI format.
        """
        return self.current_tools

    async def _execute_command_by_function_call(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str]:
        """
        Overwritten to allow in game commands to be executed by command-name reference.

        Uses an OpenAI function call to execute a command. If it's an instant activation_command, one if its reponses will be played.

        Args:
            function_name (str): The name of the function to be executed.
            function_args (dict[str, any]): The arguments to pass to the function being executed.

        Returns:
            A tuple containing two elements:
            - function_response (str): The text response or result obtained after executing the function.
            - instant_response (str): An immediate response or action to be taken, if any (e.g., play audio).
        """
        if self.debug or DEBUG:
            printr.print(
                f"Executing function call: {function_name} with arguments: {function_args}",
                tags="debug",
            )
        function_response = ""
        instant_reponse = ""
        # our context switcher. If this is called by GPT, we switch to this context (with its own memory).
        # we have to repeat the user request on this switched context, to get a valid response.
        if function_name == "switch_context":
            return self._execute_switch_context_function(function_args)
        
        if function_name == "execute_command":
            # get the command from config file based on the argument passed by GPT
            command = self._get_command(function_args["command_name"])
            # execute the command
            if command:
                function_response = self._execute_command(command)
            else:
                function_response, instant_reponse = self._execute_star_citizen_keymapping_command(function_args["command_name"])

            # if the command has responses, we have to play one of them
            if command and command.get("responses"):
                instant_reponse = self._select_command_response(command)
                await self._play_to_user(instant_reponse)

        # finally, check for any function managers implementing the called function
        if function_name in self.ai_functions_manager.get_function_registry():
            function_to_call = self.ai_functions_manager.get_function(function_name)
            if callable(function_to_call):
                function_response = function_to_call(function_args)

        instructions = self.config["openai"].get("summarize_instructions")
        if instructions and isinstance(function_response, dict):
            function_response["summarize_instructions"] = instructions

        return json.dumps(function_response), instant_reponse

    def _execute_switch_context_function(self, function_args):
        print_debug(f'switching context call: {function_args["context_name"]}')
        # if self.switch_context_executed is True:
        #     # ups, there has already been a context switch before. We do avoid infinite loops here...
        #     printr.print(
        #         "   GPT trying to make multiple context switches, this is not allowed.",
        #         tags="warn",
        #     )
        #     self.switch_context_executed = False
        #     return "Error", None
        # first, we have to remove from the current context old information from the "old" request history, as it belongs to the context that we switch to
        context_messages = None
        if len(self.messages) >= 3:  # bis hierhin wurde hinzugefügt: benutzerrequest und gpt response (tool_call: switch!). Mit der system message,  müssen also mindestens 3 nachrichten vorhanden sein
            # wir entfernen die neuesten 2 nachrichten: user request + tool_call
            context_messages = self.messages[-2:]
            del self.messages[-2:]

            # get the command based on the argument passed by GPT
        context_name_to_switch_to = function_args["context_name"]
        self._switch_context(context_name_to_switch_to)
        if self.current_context == AIContext.CORA:
            self.config["openai"]["tts_voice"] = self.config["openai"]["contexts"]["cora_voice"]
            self.config["sound"]["play_beep"] = False
            self.config["sound"]["effects"] = ["ROBOT"]
            self.config["openai"]["conversation_model"] = self.config["openai"]["contexts"][f"context-{AIContext.CORA.name}"]["conversation_model"]
        elif self.current_context == AIContext.TDD:
            self.config["openai"]["tts_voice"] = self.tdd_voice
            self.config["sound"]["play_beep"] = True
            self.config["sound"]["effects"] = ["RADIO", "INTERIOR_HELMET"]
            self.config["openai"]["conversation_model"] = self.config["openai"]["contexts"][f"context-{AIContext.TDD.name}"]["conversation_model"]
        self.messages.extend(context_messages)  # we readd the messages to the switched context.
        # self._add_user_message(self.current_user_request) # we readd the user message to the new context to make the same user request in the new context
        # context has been switched, so we can return the contexts swtich request
        # self.switch_context_executed = True
        function_response = f"switched to context {context_name_to_switch_to}, reevaluate the previous user request in the new context. "
        instant_reponse = None
        return function_response, instant_reponse

    def _execute_star_citizen_keymapping_command(self, command_name: str):
        """This method will execute a keystroke as defined in the keybinding settings of the game"""
        command = self.sc_keybinding_service.get_command(command_name)

        if not command:
            print_debug(f"Command not found '{command_name}'")
            return {"success": False, "error": f"Command not found '{command_name}'"}, f"Command not found '{command_name}'"

        avoid_filter_names = self.config.get("avoid-commands", [])
        avoid_filter_names_set = set(avoid_filter_names)
        if command_name in avoid_filter_names_set:
            print_debug(f"Command not allowed {command_name}")
            return {"success": False, "error": f"Command not allowed '{command_name}'"}, f"Command not allowed '{command_name}'"

        # Definiere eine Reihenfolge für die Modifiertasten
        order = ["alt", "ctrl", "shift", "altleft", "ctrlleft", "shiftleft", "altright", "ctrlright", "shiftright"]
        modifiers = set(order)
        keys = command.get("keyboard-mapping").split("+")
        
        actionname = command.get("actionname")
        category = command.get("category")

        sc_activation_mode = command.get("activationMode")
        
        # we check, if the command is overwritten in the config
        overwrite_commands = self.config["sc-keybind-mappings"].get("overwrite_sc_command_execution",{})
        overwrite_command = overwrite_commands.get(command_name)
        if overwrite_command and overwrite_command.get("hold"):
            old_sc_activation_mode = sc_activation_mode
            sc_activation_mode = overwrite_command.get("hold")
            print_debug(f"overwritten activationMode: was {old_sc_activation_mode} -> {sc_activation_mode}")

        hold = self.config["sc-keybind-mappings"]["key-press-mappings"].get(sc_activation_mode)

        command_desc = None
        if not command.get("action-description-en"):
            if not command.get("action-label-en"):
                command_desc = actionname
            else:
                command_desc = command.get("action-label-en")
        else:
            command_desc = command.get("action-description-en")
        
        command_message = f'{command_desc}: {command.get("keyboard-mapping-en")}'
        
        printr.print(
                f"   Executing command: {command_message}",
                tags="info",
            )
        print_debug(
                f"   Executing command: {command_message}"
            )

        try: 
            if len(keys) > 1:
                keys = sorted(keys, key=lambda x: order.index(x) if x in order else len(order))
            elif hold == "double_tap":  # double tab is only one key always
                print_debug(f"double tab {keys[0]}")
                
                is_mouse = False
                key = self.config["sc-keybind-mappings"]["key-mappings"].get(keys[0])  # not all star citizen key names are  equal to key_modul names, therefore we do a mapping
                if not key:  # if there is no mapping, key names are identical
                    key = keys[0]
                elif "mouse" in key:
                    is_mouse = True

                if is_mouse:
                    key_module.click(button=key.split("mouse_")[-1], duration=0.1)
                else:
                    key_module.press(keys[0])
                
                time.sleep(0.050)

                if is_mouse:
                    key_module.click(button=key.split("mouse_")[-1], duration=0.1)
                else:
                    key_module.press(keys[0])

                return "Ok", "Ok"
        
            if hold == "notSupported":
                return {"success": "False", "message": f"{command_message}", "error": f"activation mode not supported {sc_activation_mode}"}, None

            active_modifiers = []

            for sc_key in keys:
                is_mouse = False
                key = self.config["sc-keybind-mappings"]["key-mappings"].get(sc_key)  # not all star citizen key names are  equal to key_modul names, therefore we do a mapping
                if not key:  # if there is no mapping, key names are identical
                    key = sc_key
                elif "mouse" in key:
                    is_mouse = True

                if key in modifiers:
                    key_module.keyDown(key)
                    print_debug("modifier down: " + key)
                    active_modifiers.append(key)
                    continue

                if hold == "unknown":
                    print_debug("unknown activationMode assuming press: " + key)
                    if is_mouse:
                        key_module.click(button=key.split("mouse_")[-1], duration=0.1)
                    else: 
                        key_module.press(key)
                    continue

                if hold > 1:
                    print_debug("hold and release: " + key)
                    if is_mouse:
                        key_module.mouseDown(button=key.split("mouse_")[-1])
                    else: 
                        key_module.keyDown(key)  # apart of modifiers, we assume, that there is always only one further key that can be pressed ....
                    
                    time.sleep(hold / 1000)  # transform in seconds
                    
                    if is_mouse:
                        key_module.mouseUp(button=key.split("mouse_")[-1])
                    else: 
                        key_module.keyUp(key)
                else:
                    print_debug("press: " + key)
                    if is_mouse:
                        key_module.click(button=key.split("mouse_")[-1], duration=0.1)
                    else: 
                        key_module.press(key)
            
            active_modifiers.reverse()  # Kehrt die Liste in-place um

            for modifier_key in active_modifiers:  # release modifiers in inverse order
                print_debug("modifier up: " + modifier_key)
                key_module.keyUp(modifier_key) 

            return "Ok", "Ok"
        except Exception as e:
            # Genereller Fehlerfang
            print_debug(f"Ein Fehler ist aufgetreten: {e.__class__.__name__}, {e}")
            return {"success": False, "error": f"{e}"}, None
      
    def _execute_command(self, command: dict):
        """Triggers the execution of a command. This implementation executes the defined star citizen commands.

        Args:
            command (dict): The command object from the config to execute

        Returns:
            str: the selected response from the command's responses list in the config. "Ok" if there are none.
        """
        if not command:
            return "Command not found"

        printr.print(f"-> Executing sc-command: {command.get('name')}", tags="info")

        if self.debug:
            printr.print(
                "Skipping actual keypress execution in debug_mode...", tags="warn"
            )

        response = None
        if len(command.get("sc_commands", [])) > 0 and not self.debug:
            for sc_command in command.get("sc_commands"):
                self._execute_star_citizen_keymapping_command(sc_command["sc_command"])
                if sc_command.get("wait"):
                    time.sleep(sc_command["wait"])
            if command.get("responses") is not False:
                response = self._select_command_response(command)

        if len(command.get("sc_commands", [])) == 0:  # is a default configuration
            return super()._execute_command(command)

        if not response:
            response = json.dumps({"success": True, "instruction": "Don't make any function call!"})
        return response

    def _context_switch_tool(self, current_context: AIContext = None) -> list[dict]:
        ai_context_values = [context.value for context in AIContext if context != current_context]

        tools = {
                "type": "function",
                "function": {
                    "name": "switch_context",
                    "description": "Switch to a different context of conversation. Only switch, if the player initiate the context switch.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "context_name": {
                                "type": "string",
                                "description": "The available context the player conversion can be switched to",
                                "enum": ai_context_values
                            }
                        },
                        "required": ["context_name"]
                    }
                }
            }
        return tools
    
    def _get_keybinding_commands(self) -> list[dict]:
        # get defined commands in config
        commands = [
            command["name"]
            for command in self.config.get("commands", [])
        ]

        command_set = set(commands)
        sc_commands = set(self.sc_keybinding_service.get_bound_keybinding_names())

        command_set.update(sc_commands)  # manually defined commands overwrites sc_keybindings

        tools = {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "description": "Executes a player command. Select among the list of available commands the one that best matches the player request. On response, follow the provided instructions. ",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command_name": {
                                "type": "string",
                                "description": "The command to execute",
                                "enum": list(command_set)
                            },
                            "command_excerpt": {
                                "type": "string",
                                "description": "The main aspect of the command in the player request. From the sentence 'Please open the door' the command_excerpt would be 'open door'",
                            }
                        },
                        "required": ["command_name", "command_excerpt"]
                    }
                }
            }
        return tools
    
    def _play_with_openai(self, text):

        voice_instructions = self.config["openai"].get("tts_voice_instructions") if self.current_context == AIContext.CORA else ""
        response = self.openai.speak(text, 
                                     self.config["openai"].get("tts_model"), 
                                     self.config["openai"].get("tts_voice"),
                                     voice_instructions,
                                     self.config["openai"].get("player_language"))
        if response is not None:
            self.audio_player.stream_with_effects(response.content, self.config)
        
    def _get_cora_tools(self) -> list[dict]:
        tools = []
        tools.append(self._get_keybinding_commands())
        for ai_function_manager in self.ai_functions_manager.get_managers(AIContext.CORA):
            ai_function_manager: FunctionManager
            tools.extend(ai_function_manager.get_function_tools())
        tools.append(self._context_switch_tool(current_context=AIContext.CORA))

        return tools
