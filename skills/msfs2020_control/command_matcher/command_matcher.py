import os
import sys
from rapidfuzz import process, fuzz, utils
from SimConnect.EventList import AircraftEvents
from SimConnect.RequestList import AircraftRequests

# Mock SimConnect to avoid instantiating additional SimConnect for no reason
class MockSimConnect:
    def new_request_id(self):
        class ID: value = 0
        return ID()
    def new_def_id(self):
        class ID: value = 0
        return ID()
    def map_to_sim_event(self, deff): return 0
    def send_event(self, event, value): pass
    def get_data(self, request): return False
    def IsHR(self, err, val): return True
    def new_event_id(self): return 0
    @property
    def dll(self):
        class DLL:
            def ClearDataDefinition(self, *args): pass
            def AddToDataDefinition(self, *args): pass
            def GetLastSentPacketID(self, *args): pass
        return DLL()
    def __init__(self):
        self.Requests = {}
        self.Facilities = []
        self.hSimConnect = 0

# Class that attempt to provide a list of SimConnectcommands to the LLM that may match user intent
class CommandMatcher:
    def __init__(self):
        self.all_commands = self._load_commands()
        # Pre-calculate search strings to make matching faster
        self.match_pool = [
            f"{c['name']} {c['description']}".lower() 
            for c in self.all_commands
        ]

    def _load_commands(self):
        commands = []
        sm = MockSimConnect()
        
        # 1. Extract Events
        try:
            events_obj = AircraftEvents(sm)
            for category in events_obj.list:
                cat_name = category.__class__.__name__.replace("_AircraftEvents__", "")
                for entry in category.list:
                    name = entry[0].decode() if isinstance(entry[0], bytes) else str(entry[0])
                    commands.append({
                        "name": name, "description": entry[1], 
                        "type": "Event", "category": cat_name
                    })
        except Exception: 
            pass

        # 2. Extract Requests
        try:
            requests_obj = AircraftRequests(sm)
            for category in requests_obj.list:
                cat_name = category.__class__.__name__.replace("_AircraftRequests__", "")
                for name, entry in category.list.items():
                    commands.append({
                        "name": name, "description": entry[0], 
                        "type": "SimVar", "category": cat_name
                    })
        except Exception: 
            pass
        
        return commands

    def find_matches(self, user_input, threshold=40, limit=15):
        if not user_input:
            return []

        # Perform Fuzzy Match using token_set_ratio ignores word order and handles extra words (like numbers) better
        results = process.extract(
            user_input,
            self.match_pool,
            scorer=fuzz.token_set_ratio,
            processor=utils.default_process,
            limit=limit,
        )

        final_results = []
        for _, score, idx in results:
            
            # Create a shallow copy to avoid any "mutability trap"
            cmd = self.all_commands[idx].copy()
            cmd["match_score"] = score
            final_results.append(cmd)

        matches = sorted(final_results, key=lambda x: x['match_score'], reverse=True)
        return matches

    def matches_as_string(self, matches=[]):
        matches_string = ""
        for i, m in enumerate(matches, 1):
            matches_string+=f"{i}. [{m['type']}] {m['name']}\n"
            matches_string+=f"   Desc: {m['description']}\n\n"
        return matches_string