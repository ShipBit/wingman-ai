import pkgutil
import importlib
import re
import inspect
from difflib import SequenceMatcher
from abc import ABC, abstractmethod
from openai import OpenAI, APIStatusError, AzureOpenAI

from services.open_ai import AzureConfig
from services.printr import Printr

from wingmen.star_citizen_services.ai_context_enum import AIContext

DEBUG = False

printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class StarCitizensAiFunctionsManager:
    PHRASE_MATCH_THRESHOLD = 0.84

    def __init__(self, config, secret_keeper):
        self.config = config
        self.secret_keeper = secret_keeper
        self.managers = {}
        """ 
            Every function manager is associated to a specific AIContext. Per AI Context, you get a list of all registered managers for this context.
            { AIContext: [list of associated managers]}
        """
        self.function_registry = {}
        """ 
            defines the method that needs to be executed when openAI is making a function call of the given name
            openai.function.name: manager.function(openai.function.function_args)
        """
        self.manager_classes = {}
        self.manager_instances = {}
        self.manager_context = {}
        self.manager_states = {}
        self.manager_metadata = {}
        self.manager_registered_functions = {}
        self.function_to_manager = {}
        self.command_phrases = {}
        self.initialize_function_managers(config, secret_keeper)

    def register_manager(self, ai_context: AIContext, manager):
        ai_context_managers = self.managers.get(ai_context, [])
        if manager not in ai_context_managers:
            ai_context_managers.append(manager)
        self.managers[ai_context] = ai_context_managers

    def unregister_manager(self, ai_context: AIContext, manager):
        ai_context_managers = self.managers.get(ai_context, [])
        if manager in ai_context_managers:
            ai_context_managers.remove(manager)
            self.managers[ai_context] = ai_context_managers

    def register_function(self, function_name, function):
        self.function_registry[function_name] = function

    def get_function_registry(self):
        return self.function_registry
    
    def get_function(self, function_name):
        return self.function_registry.get(function_name)

    def initialize_function_managers(self, config, secret_keeper):
        # Define the package name where the managers are located
        package_name = 'wingmen.star_citizen_services.functions'
        
        # Import the package
        package = importlib.import_module(package_name)
        print_debug(f"Scanning package {package.__name__} for FunctionManagers")
        
        # Recursively import all modules and submodules
        def import_submodules(package):
            for loader, module_name, is_pkg in pkgutil.iter_modules(package.__path__, package.__name__ + '.'):
                # Import the module
                module = importlib.import_module(module_name)
                print_debug(f"  Scanning module {module.__name__} for FunctionManagers")
                
                # Iterate through attributes of the module
                for attribute_name in dir(module):
                    attribute = getattr(module, attribute_name)
                    print_debug(f"    Checking if {attribute_name} is a FunctionManager")

                    if isinstance(attribute, type) and issubclass(attribute, FunctionManager) and attribute is not FunctionManager:
                        if attribute.__module__ != module.__name__:
                            continue
                        print_debug(f"     -> YES")
                        manager_name = attribute.__name__
                        if manager_name in self.manager_classes:
                            continue
                        self.manager_classes[manager_name] = attribute
                        self.manager_metadata[manager_name] = self._extract_manager_metadata(attribute)
                        self.command_phrases[manager_name] = self._resolve_manager_command_phrases(manager_name)
                        self.manager_states[manager_name] = False

                        activate_module = self._resolve_feature_enabled(manager_name)
                        if activate_module:
                            activation_result = self.activate_manager(manager_name, source="config")
                            if not activation_result.get("success", False):
                                printr.print_warn(
                                    f"Could not activate {manager_name} from config: {activation_result.get('message')}"
                                )
                        else:
                            print(f"Skipping {manager_name} as it is not activated in the config.")
                    else:
                        print_debug(f"     -> NO")
                        
                # If it's a package, we need to import its submodules as well
                if is_pkg:
                    subpackage = importlib.import_module(module_name)
                    import_submodules(subpackage)
        
        # Start the import process from the root package
        import_submodules(package)

    def get_managers(self, ai_context: AIContext) -> list:
        return self.managers.get(ai_context, [])

    def get_manager_names(self) -> list[str]:
        return sorted(self.manager_classes.keys())

    def get_manager_for_function(self, function_name: str):
        return self.function_to_manager.get(function_name)

    def is_manager_enabled(self, manager_name: str) -> bool:
        resolved_name = self.resolve_manager_name(manager_name)
        if not resolved_name:
            return False
        return self.manager_states.get(resolved_name, False)

    def _extract_manager_metadata(self, manager_class):
        class_doc = inspect.getdoc(manager_class) or ""
        first_doc_line = class_doc.splitlines()[0] if class_doc else ""
        description = (
            getattr(manager_class, "MANAGER_DESCRIPTION", None)
            or first_doc_line
            or f"{manager_class.__name__} runtime manager."
        )
        capabilities = getattr(manager_class, "MANAGER_CAPABILITIES", None) or []
        context = getattr(manager_class, "MANAGER_CONTEXT", None)
        context = self._normalize_context(context)
        return {
            "description": description,
            "capabilities": capabilities,
            "context": context,
        }

    def _split_manager_name(self, manager_name: str) -> str:
        words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", manager_name)
        if words:
            return " ".join(words)
        return manager_name

    @staticmethod
    def _normalize_text(text: str) -> str:
        lowered = (text or "").lower().strip()
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9äöüß ]+", " ", lowered)).strip()

    def _build_default_manager_phrases(self, manager_name: str):
        spoken_name = self._split_manager_name(manager_name).lower()
        short_name = spoken_name.replace(" manager", "").strip()
        activate = [
            f"aktiviere {spoken_name}",
            f"{spoken_name} aktivieren",
            f"schalte {spoken_name} ein",
            f"{spoken_name} einschalten",
            f"activate {spoken_name}",
            f"{spoken_name} activate",
            f"enable {spoken_name}",
            f"{spoken_name} enable",
            f"turn on {spoken_name}",
            f"{spoken_name} turn on",
        ]
        deactivate = [
            f"deaktiviere {spoken_name}",
            f"{spoken_name} deaktivieren",
            f"schalte {spoken_name} aus",
            f"{spoken_name} ausschalten",
            f"deactivate {spoken_name}",
            f"{spoken_name} deactivate",
            f"disable {spoken_name}",
            f"{spoken_name} disable",
            f"turn off {spoken_name}",
            f"{spoken_name} turn off",
        ]
        if short_name and short_name != spoken_name:
            activate.extend(
                [
                    f"aktiviere {short_name}",
                    f"{short_name} aktivieren",
                    f"schalte {short_name} ein",
                    f"{short_name} einschalten",
                    f"activate {short_name}",
                    f"{short_name} activate",
                    f"enable {short_name}",
                    f"{short_name} enable",
                    f"turn on {short_name}",
                    f"{short_name} turn on",
                ]
            )
            deactivate.extend(
                [
                    f"deaktiviere {short_name}",
                    f"{short_name} deaktivieren",
                    f"schalte {short_name} aus",
                    f"{short_name} ausschalten",
                    f"deactivate {short_name}",
                    f"{short_name} deactivate",
                    f"disable {short_name}",
                    f"{short_name} disable",
                    f"turn off {short_name}",
                    f"{short_name} turn off",
                ]
            )

        return {
            "activate": activate,
            "deactivate": deactivate,
        }

    @staticmethod
    def _extract_action_hint(normalized_transcript: str):
        if not normalized_transcript:
            return None

        # Important: check deactivate first, because "deaktivieren" contains "aktivieren".
        if (
            "deaktivier" in normalized_transcript
            or "ausschalt" in normalized_transcript
            or "turn off" in normalized_transcript
            or "disable" in normalized_transcript
            or "deactivate" in normalized_transcript
        ):
            return "deactivate"

        if (
            "aktivier" in normalized_transcript
            or "einschalt" in normalized_transcript
            or "turn on" in normalized_transcript
            or "enable" in normalized_transcript
            or "activate" in normalized_transcript
        ):
            return "activate"

        return None

    def _resolve_manager_command_phrases(self, manager_name: str):
        phrases = self._build_default_manager_phrases(manager_name)
        configured_phrases = self.config.get("features", {}).get("manager_command_phrases", {}).get(manager_name, {})

        manager_feature_entry = self.config.get("features", {}).get(manager_name, None)
        if isinstance(manager_feature_entry, dict):
            entry_phrases = manager_feature_entry.get("command_phrases", {})
            if isinstance(entry_phrases, dict):
                configured_phrases = {**configured_phrases, **entry_phrases}

        if not isinstance(configured_phrases, dict):
            configured_phrases = {}

        activate_config = configured_phrases.get("activate", configured_phrases.get("enable", []))
        deactivate_config = configured_phrases.get("deactivate", configured_phrases.get("disable", []))
        if isinstance(activate_config, str):
            activate_config = [activate_config]
        if isinstance(deactivate_config, str):
            deactivate_config = [deactivate_config]

        phrases["activate"] = self._dedupe_phrases([*phrases["activate"], *activate_config])
        phrases["deactivate"] = self._dedupe_phrases([*phrases["deactivate"], *deactivate_config])
        return phrases

    def _dedupe_phrases(self, phrases: list[str]) -> list[str]:
        deduped = []
        seen = set()
        for phrase in phrases:
            normalized = self._normalize_text(phrase)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _resolve_feature_enabled(self, manager_name: str) -> bool:
        value = self.config.get("features", {}).get(manager_name, False)
        if isinstance(value, dict):
            return bool(value.get("enabled", False))
        return bool(value)

    def _normalize_context(self, context):
        if isinstance(context, AIContext):
            return context
        if isinstance(context, str):
            by_name = next((ctx for ctx in AIContext if ctx.name == context), None)
            if by_name:
                return by_name
            by_value = next((ctx for ctx in AIContext if ctx.value == context), None)
            return by_value
        return None

    def resolve_manager_name(self, manager_name: str):
        if manager_name in self.manager_classes:
            return manager_name

        normalized_input = self._normalize_text(manager_name)
        if not normalized_input:
            return None

        exact_lower_match = next(
            (known for known in self.manager_classes if known.lower() == manager_name.lower()),
            None,
        )
        if exact_lower_match:
            return exact_lower_match

        for known in self.manager_classes:
            split_name = self._split_manager_name(known)
            if self._normalize_text(known) == normalized_input or self._normalize_text(split_name) == normalized_input:
                return known

        return None

    @staticmethod
    def _function_belongs_to_manager(function_ref, manager_instance):
        return callable(function_ref) and getattr(function_ref, "__self__", None) is manager_instance

    def _register_manager_functions(self, manager_name: str, manager_instance):
        before_registry = self.function_registry.copy()
        manager_instance.register_functions(self.function_registry)

        registered_functions = []
        for function_name, function_ref in self.function_registry.items():
            previous_ref = before_registry.get(function_name)
            if previous_ref is None and self._function_belongs_to_manager(function_ref, manager_instance):
                registered_functions.append(function_name)
                continue
            if previous_ref is not function_ref and self._function_belongs_to_manager(function_ref, manager_instance):
                registered_functions.append(function_name)

        if not registered_functions and manager_name in self.manager_registered_functions:
            registered_functions = self.manager_registered_functions[manager_name]

        self.manager_registered_functions[manager_name] = registered_functions
        for function_name in registered_functions:
            self.function_to_manager[function_name] = manager_name

    def _unregister_manager_functions(self, manager_name: str, manager_instance):
        registered_functions = self.manager_registered_functions.get(manager_name, [])
        for function_name in registered_functions:
            function_ref = self.function_registry.get(function_name)
            if self._function_belongs_to_manager(function_ref, manager_instance):
                self.function_registry.pop(function_name, None)

    @staticmethod
    def _collect_manager_start_information(manager_instance):
        try:
            start_information = manager_instance.cora_start_information()
            if start_information is None:
                start_information = ""
            return start_information, None
        except Exception as e:
            return "", str(e)

    def activate_manager(self, manager_name: str, source: str = "manual"):
        resolved_name = self.resolve_manager_name(manager_name)
        if not resolved_name:
            return {"success": False, "changed": False, "message": f"Unknown manager '{manager_name}'."}

        if self.manager_states.get(resolved_name, False):
            return {
                "success": True,
                "changed": False,
                "manager_name": resolved_name,
                "enabled": True,
                "message": f"{resolved_name} is already active.",
            }

        manager_class = self.manager_classes.get(resolved_name)
        if manager_class is None:
            return {"success": False, "changed": False, "message": f"Manager class '{resolved_name}' not found."}

        first_initialization = False
        manager_instance = self.manager_instances.get(resolved_name)
        if manager_instance is None:
            first_initialization = True
            try:
                manager_instance = manager_class(self.config, self.secret_keeper)
            except Exception as e:
                return {
                    "success": False,
                    "changed": False,
                    "manager_name": resolved_name,
                    "enabled": False,
                    "message": f"Failed to initialize {resolved_name}: {e}",
                    "error": str(e),
                }
            self.manager_instances[resolved_name] = manager_instance

        context = self._normalize_context(manager_instance.get_context_mapping())
        if context is None:
            context = self._normalize_context(self.manager_metadata.get(resolved_name, {}).get("context"))

        if context is None:
            return {
                "success": False,
                "changed": False,
                "manager_name": resolved_name,
                "enabled": False,
                "message": f"{resolved_name} has no valid context mapping.",
            }

        self.manager_context[resolved_name] = context
        self.register_manager(context, manager_instance)
        self._register_manager_functions(resolved_name, manager_instance)
        self.manager_states[resolved_name] = True
        if first_initialization:
            manager_instance.after_init()
        try:
            manager_instance.on_manager_enabled(source=source)
        except Exception as e:
            printr.print_warn(f"{resolved_name} on_manager_enabled failed: {e}")

        start_information = ""
        start_information_error = None
        if source != "config":
            start_information, start_information_error = self._collect_manager_start_information(manager_instance)

        print(f"{resolved_name} registered ({source})")
        result = {
            "success": True,
            "changed": True,
            "manager_name": resolved_name,
            "enabled": True,
            "message": f"{resolved_name} enabled.",
        }
        if source != "config":
            result["start_information"] = start_information
            if start_information_error:
                result["start_information_error"] = start_information_error
        return result

    def deactivate_manager(self, manager_name: str, source: str = "manual"):
        resolved_name = self.resolve_manager_name(manager_name)
        if not resolved_name:
            return {"success": False, "changed": False, "message": f"Unknown manager '{manager_name}'."}

        if not self.manager_states.get(resolved_name, False):
            return {
                "success": True,
                "changed": False,
                "manager_name": resolved_name,
                "enabled": False,
                "message": f"{resolved_name} is already inactive.",
            }

        manager_instance = self.manager_instances.get(resolved_name)
        if manager_instance is None:
            self.manager_states[resolved_name] = False
            return {
                "success": True,
                "changed": True,
                "manager_name": resolved_name,
                "enabled": False,
                "message": f"{resolved_name} disabled.",
            }

        try:
            manager_instance.on_manager_disabled(source=source)
        except Exception as e:
            printr.print_warn(f"{resolved_name} on_manager_disabled failed: {e}")

        context = self.manager_context.get(resolved_name)
        if context:
            self.unregister_manager(context, manager_instance)

        self._unregister_manager_functions(resolved_name, manager_instance)
        self.manager_states[resolved_name] = False
        print(f"{resolved_name} unregistered ({source})")
        return {
            "success": True,
            "changed": True,
            "manager_name": resolved_name,
            "enabled": False,
            "message": f"{resolved_name} disabled.",
        }

    def set_manager_enabled(self, manager_name: str, enabled: bool, source: str = "manual"):
        if enabled:
            return self.activate_manager(manager_name=manager_name, source=source)
        return self.deactivate_manager(manager_name=manager_name, source=source)

    def get_manager_overview(self, include_inactive: bool = True, only_context: AIContext = None):
        context_filter = self._normalize_context(only_context) if only_context else None
        managers = []
        for manager_name in self.get_manager_names():
            enabled = self.manager_states.get(manager_name, False)
            if not include_inactive and not enabled:
                continue

            metadata = self.manager_metadata.get(manager_name, {})
            context = self.manager_context.get(manager_name) or self._normalize_context(metadata.get("context"))
            if context_filter and context != context_filter:
                continue

            functions = []
            if enabled:
                functions = self.manager_registered_functions.get(manager_name, [])

            managers.append(
                {
                    "name": manager_name,
                    "enabled": enabled,
                    "context_name": context.name if isinstance(context, AIContext) else None,
                    "context_value": context.value if isinstance(context, AIContext) else None,
                    "description": metadata.get("description", ""),
                    "capabilities": metadata.get("capabilities", []),
                    "registered_functions": functions,
                    "command_phrases": self.command_phrases.get(manager_name, {}),
                }
            )
        return managers

    def match_and_toggle_manager_by_phrase(self, transcript: str):
        normalized_transcript = self._normalize_text(transcript)
        if not normalized_transcript:
            return None
        action_hint = self._extract_action_hint(normalized_transcript)

        best_match = None
        best_score = 0.0

        for manager_name, phrase_config in self.command_phrases.items():
            for action_name in ["activate", "deactivate"]:
                if action_hint and action_name != action_hint:
                    continue
                for phrase in phrase_config.get(action_name, []):
                    if not phrase:
                        continue

                    score = 0.0
                    if normalized_transcript == phrase:
                        score = 1.0
                    elif f" {phrase} " in f" {normalized_transcript} ":
                        score = 0.98
                    else:
                        score = SequenceMatcher(None, normalized_transcript, phrase).ratio()

                    if score > best_score and score >= self.PHRASE_MATCH_THRESHOLD:
                        best_score = score
                        best_match = {
                            "manager_name": manager_name,
                            "action": action_name,
                            "phrase": phrase,
                            "score": round(score, 4),
                        }

        if not best_match:
            return None

        set_enabled = best_match["action"] == "activate"
        result = self.set_manager_enabled(best_match["manager_name"], enabled=set_enabled, source="voice-command")
        result["matched_phrase"] = best_match["phrase"]
        result["match_score"] = best_match["score"]
        result["action"] = best_match["action"]
        return result


class FunctionManager(ABC):
    MANAGER_CONTEXT = None
    MANAGER_DESCRIPTION = ""
    MANAGER_CAPABILITIES = []

    def __init__(self, config, secret_keeper):
        self.config = config
        self.secret_keeper = secret_keeper
        self.conversation_client: OpenAI = None
        self.name = self.__class__.__name__
        self.conversation_model = "gpt-4o"

    @classmethod
    def get_manager_metadata(cls):
        class_doc = inspect.getdoc(cls) or ""
        first_doc_line = class_doc.splitlines()[0] if class_doc else ""
        description = cls.MANAGER_DESCRIPTION or first_doc_line
        return {
            "context": cls.MANAGER_CONTEXT,
            "description": description,
            "capabilities": cls.MANAGER_CAPABILITIES or [],
        }

    def after_init(self):
        """  
            This method can be implemented to execute logic that needs to be run after all initialization steps.
        """
        pass

    def on_manager_enabled(self, source: str = "manual"):
        """Optional lifecycle hook invoked whenever the manager is enabled."""
        pass

    def on_manager_disabled(self, source: str = "manual"):
        """Optional lifecycle hook invoked whenever the manager is disabled."""
        pass

    def cora_start_information(self):
        """  
            This method can be implemented to retrieve information from the manager, that Cora should provide to the user on startup.
        """
        return ""
    
    def ask_ai(self, system_prompt: str, user_prompt: str, max_tokens=512, temperature=0.7, response_format={"type": "json_object"}):
        """
        Ask configured conversation provider for a response to the given prompts.
            Params:
                system_prompt: str - The system prompt to be sent to the conversation provider
                user_prompt: str - The user prompt to be sent to the conversation provider
                max_tokens: int - The maximum number of tokens to generate
                temperature: float - The sampling temperature
                response_format: dict - The response format to be returned. Default is a JSON object.
        """
        self._init_conversation_client()
        try: 
            completion = self.conversation_client.chat.completions.create(
                model=self.conversation_model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
            )
            return completion
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            printr.print_err(
                "The OpenAI API key you provided is invalid. Please check the GUI settings or your 'secrets.yaml'"
            )
            return None
    
    @abstractmethod
    def register_functions(self, function_register):
        """  
            This method is used to register all implemented functions in this manager that the AI can execute.
        """
        pass

    @abstractmethod
    def get_function_tools(self) -> list[dict]:
        """  
            This method returns all OpenAI function definitions that are implemented by this manager.
        """
        pass

    @abstractmethod
    def get_function_prompt(self) -> str:
        """  
            This method allows to append specific instructions to the OpenAI systems message.
        """
        pass

    @abstractmethod
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to
        """
        pass

    def _init_conversation_client(self):
        """
            This method initializes the conversation client for the manager on first use.
        """
        if not self.conversation_client:
            openai_api_key = self.secret_keeper.retrieve(
                requester=self.name,
                key="openai",
                friendly_key_name="OpenAI API key",
                prompt_if_missing=True,
            )
            if not openai_api_key:
                print("Missing 'openai' API key. Please provide a valid key in the settings.")
            else:
                openai_organization = self.config["openai"].get("organization")
                openai_base_url = self.config["openai"].get("base_url")
                self.conversation_client = OpenAI(
                    api_key=openai_api_key,
                    organization=openai_organization,
                    base_url=openai_base_url,
            )
                
            self.conversation_model = self.config["openai"].get("conversation_model")

            if self.config["features"].get(
                "conversation_provider", "openai"
            ) == "azure":
                azure_api_key = self.secret_keeper.retrieve(
                        requester=self.name,
                        key="azure_conversation",
                        friendly_key_name="Azure Conversation API key",
                        prompt_if_missing=True,
                    )
                
                self.conversation_client = AzureOpenAI(
                    api_key=azure_api_key,
                    azure_endpoint=self.config["azure"]
                    .get("conversation", {})
                    .get("api_base_url", None),
                    api_version=self.config["azure"].get("conversation", {}).get("api_version", None),
                    azure_deployment=self.config["azure"]
                    .get("conversation", {})
                    .get("deployment_name", None),
                )

    def _handle_api_error(self, api_response):
        printr.print_err(
            f"The OpenAI API send the following error code {api_response.status_code} ({api_response.type})"
        )
        # get API message from appended JSON object in the "message" part of the exception
        m = re.search(
            r"'message': (?P<quote>['\"])(?P<message>.+?)(?P=quote)",
            api_response.message,
        )
        if m is not None:
            message = m["message"].replace(". ", ".\n")
            printr.print(message, tags="err")
        elif api_response.message:
            printr.print(api_response.message, tags="err")
        else:
            printr.print("The API did not provide further information.", tags="err")

# ─────────────────────────────────── ↓ EXAMPLE ↓ ─────────────────────────────────────────
# from wingmen.star_citizen_services.function_manager import FunctionManager
# from wingmen.star_citizen_services.ai_context_enum import AIContext
# class ExampleManager(FunctionManager):
#     """  
#         This is an example implementation structure that can be copy pasted for new managers.
#     """
#     def __init__(self, config, secret_keeper):
#         super().__init__(config, secret_keeper)
#         # do further initialisation steps here

#     # @abstractmethod - overwritten
#     def get_context_mapping(self) -> AIContext:
#         """  
#             This method returns the context this manager is associated to. This means, that this function will only be callable if the current context matches the defined context here.
#         """
#         return AIContext.CORA         

#     # @abstractmethod - overwritten
#     def register_functions(self, function_register):
#         """  
#             You register a method(s) that can be called by openAI.
#         """
#         function_register[self.example_function.__name__] = self.example_function

#     # @abstractmethod - overwritten
#     def get_function_prompt(self) -> str:
#         """  
#            This is the function definition for OpenAI, provided as a list of tool definitions:
#            Location names (planet, moons, cities, tradeports / outposts) are given in the system context, 
#            so no need to make reference to it here.
#         """
#         return (
#             f"Call the function {self.example_function.__name__} if the user wants an example. Be aware of the following rules that apply:"
#         ) 
        
#     # @abstractmethod - overwritten
#     def get_function_tools(self) -> list[dict]:
#         """  
#             This is the function definition for OpenAI, provided as a list of tool definitions:
#         """
#         tools = [
#             {
#                 "type": "function",
#                 "function": {
#                     "name": "execute_command",
#                     "description": "Executes a command",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "command_name": {
#                                 "type": "string",
#                                 "description": "The command to execute",
#                                 "enum": commands,
#                             },
#                         },
#                         "required": ["command_name"],
#                     },
#                 },
#             },
#         ]
#         return tools

#     def example_function(self, args):
#         # this must always return a json.dumps thing
#         return json.dumps(
#             {"success": True, "instructions": "Provide an example joke about Chuck Norris with the given theme.", "message": {"joke_theme": "coding"}}
#         )
