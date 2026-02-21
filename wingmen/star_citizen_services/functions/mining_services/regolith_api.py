import time
import json
import webbrowser
import traceback
import os
import base64
import re
from collections import defaultdict

from datetime import datetime
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

from wingmen.star_citizen_services.helper import time_string_converter


DEBUG = False
TEST = False
SHIP_CLUSTER_TYPES = [
    'CTYPE',
    'ETYPE',
    'ITYPE',
    'MTYPE',
    'PTYPE',
    'QTYPE',
    'STYPE',
    'ATACAMITE',
    'FELSIC',
    'GNEISS',
    'GRANITE',
    'IGNEOUS',
    'OBSIDIAN',
    'QUARTZITE',
    'SHALE',
]

VEHICLE_CLUSTER_TYPES = [
    'FEYNMALINE',
    'BERADOM',
    'GLACOSITE',
]

FPS_CLUSTER_TYPES = [
    'JANALITE',
    'HADANITE',
    'APHORITE',
    'DOLIVINE',
    'CARINITE',
    'JACLIUM',
    'SALDYNIUM'
]


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class RegolithAPI:

    def __init__(self, config, x_api_key):
        self.config = config

        # Initialize your instance here, if not already initialized
        if not hasattr(self, "is_initialized"):
            self.root_data_path = f'{self.config["data-root-directory"]}mining-data'

            self.base_api_url = (
                "https://api.regolith.rocks/staging/"
                if TEST
                else "https://api.regolith.rocks"
            )
            self.url = (
                "https://staging.regolith.rocks" if TEST else "https://regolith.rocks"
            )

            print_debug("Initializing RegolithAPI instance")
            self.is_initialized = True
        else:
            print_debug("RegolithAPI instance already initialized")

        self.transport = RequestsHTTPTransport(
            url=self.base_api_url,
            use_json=True,
            headers={
                "Content-Type": "application/json",
                "x-api-key": x_api_key,
            },
            retries=3,
            retry_backoff_factor=2,
            timeout=300,
        )

        self.client = Client(
            transport=self.transport, fetch_schema_from_transport=False
        )
        self.active_session_id = None
        self.active_session = None
        self.sc_name = None
        self.user_id = None
        self.refineries = None
        self.refinery_methods = None
        self.gravity_wells_names = None
        self.gravity_wells_mapping = None
        self.locations = None
        self.ship_ores = None
        self.activities = None
        self.lookups = None

    def open_session_in_browser(self):
        session_id = self.get_last_active_session()
        return webbrowser.open(f"{self.url}/session/{session_id}/dash")

    def delete_mining_session(self, session_id):
        mutation = gql(
            """
            mutation DeleteSession($sessionId: ID!) {
            deleteSession(sessionId: $sessionId)
            }
        """
        )

        variables = {"sessionId": session_id}

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return False
            else:
                print_debug("Mining Session deleted")
                self.active_session_id = None
                return True
        except Exception as e:
            print(
                f"Error trying to delete mining session: {str(e)}:\n{traceback.print_stack()}"
            )
            return False

    def get_graphql_for_names(self, object_name):
        return (
            f'{object_name}: __type(name: "{object_name}") {{'
            " name"
            " enumValues {"
            "  name"
            "  description"
            " }"
            "}"
        )

    def initialize_all_names(self):
        # Erstelle die Queries für RefineryEnum und RefineryMethodEnum
        list_of_name_fields = []
        list_of_name_fields.append(self.get_graphql_for_names("RefineryEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("RefineryMethodEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("ActivityEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("LocationEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("ShipOreEnum"))

        # Kombiniere die beiden Queries zu einer einzigen Query
        combined_query = "{" + " ".join(list_of_name_fields) + "}"

        # Führe die Mutation aus
        try:
            response = self.client.execute(gql(combined_query))

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return
            else:
                print_debug("retrieved all entity names from regolith")
                self.refineries = [
                    value["name"] for value in response["RefineryEnum"]["enumValues"]
                ]
                self.refinery_methods = [
                    value["name"]
                    for value in response["RefineryMethodEnum"]["enumValues"]
                ]
                self.activities = [
                    value["name"] for value in response["ActivityEnum"]["enumValues"]
                ]
                self.locations = [
                    value["name"] for value in response["LocationEnum"]["enumValues"]
                ]
                self.ship_ores = [
                    value["name"] for value in response["ShipOreEnum"]["enumValues"]
                ]
                return
        except Exception as e:
            print(
                f"Error during entity name retrieval from regolith: {str(e)}:\n{traceback.print_stack()}"
            )
            return
    
    def get_cluster_types(self):
        return SHIP_CLUSTER_TYPES + VEHICLE_CLUSTER_TYPES + FPS_CLUSTER_TYPES
    
    def get_refinery_names(self):
        if self.refineries is not None:
            return self.refineries

        enum_type = gql("{" + self.get_graphql_for_names("RefineryEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug(f"Refineries retrieved")
                self.refineries = [
                    value["name"] for value in response["RefineryEnum"]["enumValues"]
                ]
                return self.refineries
        except Exception as e:
            print(
                f"Error during refinery name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []
        
    def retrieve_user_info(self):
        if self.sc_name is not None and self.user_id is not None:
            return self.sc_name
        
        get_profile = gql(
            """
            query getUserProfile {
                profile {
                    ...UserProfileFragment
                }
                }

                fragment UserProfileFragment on UserProfile {
                userId
                scName
                }
            """
        )

        try:
            response = self.client.execute(get_profile)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return None
            else:
                print_debug("User-Info retrieved")
                self.sc_name = response.get("profile", {}).get("scName", None)
                self.user_id = response.get("profile", {}).get("userId", None)

                return self.sc_name
    
        except Exception as e:
            print(
                f"Error trying to retrieve user information: {str(e)}:\n{traceback.print_stack()}"
            )
            return None


    def get_refinery_method_names(self):
        if self.refinery_methods is not None:
            return self.refinery_methods
        enum_type = gql("{" + self.get_graphql_for_names("RefineryMethodEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("Refinery methods retrieved")
                self.refinery_methods = [
                    value["name"]
                    for value in response["RefineryMethodEnum"]["enumValues"]
                ]
                return self.refinery_methods
        except Exception as e:
            print(
                f"Error during retrieval refinery methods: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_gravity_wells(self):
        if self.gravity_wells_names is not None:
            return self.gravity_wells_names

        gravity_wells = gql("""query getPublicLookups {
            lookups {
                UEX {
                bodies 
                }
            }
            }""")

        try:
            response = self.client.execute(gravity_wells)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("Gravity wells name retrieved")
                self.gravity_wells_names = [
                    value["label"] for value in response["lookups"]["UEX"]["bodies"]
                ]
                self.gravity_wells_mapping = {
                    value["label"]: value["id"] for value in response["lookups"]["UEX"]["bodies"]
                }
                return self.gravity_wells_names
        except Exception as e:
            print(
                f"Error during gravity wells retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_activity_names(self):
        if self.activities is not None:
            return self.activities

        enum_type = gql("{" + self.get_graphql_for_names("ActivityEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("Activity name retrieved")
                self.activities = [
                    value["name"] for value in response["ActivityEnum"]["enumValues"]
                ]
                return self.activities
        except Exception as e:
            print(
                f"Error during activity name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_location_names(self):
        if self.locations is not None:
            return self.locations
        enum_type = gql("{" + self.get_graphql_for_names("LocationEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("locations name retrieved")
                self.locations = [
                    value["name"] for value in response["LocationEnum"]["enumValues"]
                ]
                return self.locations
        except Exception as e:
            print(
                f"Error during locations name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_ship_ore_names(self):
        if self.ship_ores is not None:
            return self.ship_ores
        enum_type = gql("{" + self.get_graphql_for_names("ShipOreEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("ship_ores name retrieved")
                self.ship_ores = [
                    value["name"] for value in response["ShipOreEnum"]["enumValues"]
                ]
                return self.ship_ores
        except Exception as e:
            print(
                f"Error during ship_ores name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_last_active_session(self):
        if self.active_session_id is not None:
            return self.active_session_id
        enum_type = gql(
            """
            query getMyUserSessions($nextToken: String, ) {
                profile {
                    mySessions(nextToken: $nextToken) {
                    items {
                        ...SessionListFragment
                    }
                    nextToken
                    }
                }
                }

                fragment SessionListFragment on Session {
                sessionId
                name
                createdAt
                finishedAt
                state
                sessionSettings {
                        ...SessionSettingFragment
                    }
                }

                fragment SessionSettingFragment on SessionSettings {
                gravityWell
                }

        """
        )

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("active_sessions retrieved")
                active_sessions = [
                    session
                    for session in response["profile"]["mySessions"]["items"]
                    if session["state"] == "ACTIVE"
                ]

                if active_sessions:
                    newest_active_session = max(
                        active_sessions, key=lambda x: x["createdAt"]
                    )
                    print_debug(
                        f'newest session: {newest_active_session["name"]} with id: {newest_active_session["sessionId"]}'
                    )
                else:
                    print_debug("No active sessions found.")
                    self.active_session_id = None
                    return None

                self.active_session_id = newest_active_session["sessionId"]
                self.active_session = newest_active_session
                return self.active_session_id

        except Exception as e:
            print(
                f"Error trying to retrieve an active session: {str(e)}:\n{traceback.print_stack()}"
            )
            self.active_session_id = None
            return None

    def get_or_create_mining_session(self, name, activity, refinery):
        self.retrieve_user_info()
        session_id = self.get_last_active_session()
        if session_id is None:
            session_id = self.create_mining_session(name, activity, refinery)
        return session_id

    def create_mining_session(self, name, activity, refinery, location=None, start_poi=None, direction=None):
        now = datetime.now()
        # Zuerst das Datum mit führenden Nullen formatieren
        formatted_date_with_zero = now.strftime("%A, %b %d, %I %p")

        # Führende Null von der Stunde entfernen, falls vorhanden
        formatted_date = formatted_date_with_zero.replace(" 0", " ")

        # GraphQL-Mutation als String, minimiert auf erforderliche Felder
        mutation = gql(
            """
        mutation createSession($session: SessionInput!, $sessionSettings: SessionSettingsInput, $workOrderDefaults: WorkOrderDefaultsInput) {
            createSession(
            session: $session
            sessionSettings: $sessionSettings
            workOrderDefaults: $workOrderDefaults
            ) {
                sessionId
                name
                createdAt
                finishedAt
                state
                sessionSettings {
                gravityWell
                }
            }
        }
        """
        )
        notes = {
            "info": "This session has been created by Cora - your AI Compagnion. ",
            "location": location,
            "start_poi": start_poi,
            "direction": direction,
        }

        variables = {
            "session": {
                "name": f"C-Session: {name if name else ''} {formatted_date}",
                "note": json.dumps(notes, indent=2),
            },
            "sessionSettings": {
                "activity": activity if activity else "SHIP_MINING",
                "specifyUsers": True,
                "allowUnverifiedUsers": False,
                "usersCanAddUsers": True,
                "usersCanInviteUsers": True,
                "gravityWell": self.gravity_wells_mapping.get(location, None),
            },
        }

        if activity == "SHIP_MINING":
            variables["workOrderDefaults"] = {
                "includeTransferFee": True,
                "method": "DINYX_SOLVENTATION",
                "shareRefinedValue": False,
                "isRefined": True,
            }

            if refinery:
                variables["workOrderDefaults"]["refinery"] = refinery

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return None
            else:
                print_debug("Mining Session created")
                self.active_session = response.get("createSession", {})
                self.active_session_id = self.active_session.get(
                    "sessionId", None
                )
                return self.active_session_id
        except Exception as e:
            print(
                f"Error trying to create mining session: {str(e)}:\n{traceback.print_stack()}"
            )
            return None

    def create_work_order(self, work_order_details):
        print_debug(
            f"creating work order with: \n{json.dumps(work_order_details, indent=2)}"
        )

        mutation = gql(
            """
            mutation createWorkOrder($sessionId: ID!, $workOrder: WorkOrderInput!, $shipOres: [RefineryRowInput!], $shares: [CrewShareInput!]!) {
                createWorkOrder(
                    sessionId: $sessionId
                    workOrder: $workOrder
                    shipOres: $shipOres
                    shares: $shares
                ) {
                    ...WorkOrderFragment
                }
                }

                fragment WorkOrderFragment on WorkOrderInterface {
                ...WorkOrderBaseFragment
                state
                }

                fragment WorkOrderBaseFragment on WorkOrderInterface {
                orderId
                sessionId
                createdAt
                updatedAt
                ownerId
                isSold
                sellerscName
                sellerUserId
                failReason
                includeTransferFee
                orderType
                note
                shareAmount
                sellStore
                expenses {
                    amount
                    name
                    ownerScName
                }
                isSold
                ... on ShipMiningOrder {
                    isRefined
                    shareRefinedValue
                    refinery
                    method
                    processStartTime
                    processDurationS
                    shipOres {
                    amt
                    ore
                    }
                }
                }
        """
        )

        try:
            response = self.client.execute(mutation, variable_values=work_order_details)

            if "errors" in response:
                print("Fehler bei der GraphQL-Anfrage:")
                for error in response["errors"]:
                    print(error["message"])
                return {
                    "success": False,
                    "message": "There was an error when I tried to create the session. I'm very sorry. ",
                }
            else:
                print_debug(
                    f'Work order created: {response["createWorkOrder"]["orderId"]}'
                )
                return {
                    "success": True,
                    "message": "Work order created. Do you want to open the session in the browser?",
                    "sessionId": work_order_details["sessionId"],
                }
        except Exception as e:
            print(
                f"Error during work order creation {str(e)}: \n{traceback.print_stack()}"
            )
            return {
                "success": False,
                "message": "Sorry, but regolith seems not to be available currently. ",
            }

    def get_active_work_orders(self):
        print_debug("getting active work orders: ")

        query = self.get_active_work_session_query()

        try:
            response = self.client.execute(query)

            if "errors" in response:
                print("Errors during Graph-QL request:")
                for error in response["errors"]:
                    print(error["message"])
                return {
                    "success": False,
                    "message": "There was an error when I tried to retrieve active work orders. I'm very sorry. ",
                }
            else:
                work_order_data = self.process_work_orders(response)
                print_debug(
                    f"Work orders retrieved. {json.dumps(work_order_data, indent=2)}"
                )

                instructions = "Give a narrative summary (that can be read out) focussing on: "
                result = {
                    "success": False,
                    "data": None,
                    "response_instructions": None
                }

                if work_order_data is None:
                    result["message"] = "No work orders available."
                    return result

                if "total_finished_refinery_orders" in work_order_data and work_order_data["total_finished_refinery_orders"] > 0:
                    result["success"] = True
                    result["data"] = work_order_data
                    instructions += (
                        "total refinery work orders finished and where they can be picked up. "
                    )

                if "total_refinery_orders_in_processing" in work_order_data and work_order_data["total_refinery_orders_in_processing"] > 0:
                    result["success"] = True
                    result["data"] = work_order_data
                    instructions += (
                        "total refinery work orders in processing and when the next one will be finished. "
                    )
                   
                if result["success"]:
                    instructions += (
                        " Also ask if he wants to open the session in the browser. "
                    ) 
                    result["response_instructions"] = instructions
                    return result
                
                return None

        except Exception as e:
            print(
                f"Error during work order retrieval {str(e)}: \n{traceback.print_stack() if traceback else ''}"
            )
            return {
                "success": False,
                "message": "Sorry, but regolith seems not to be available currently. ",
            }

    def get_active_work_session_query(self):
        query = gql(
            """
            query getUserProfil($nextToken: String) {
            profile {
                ...UserProfileFragment
                __typename
            }
            }
            fragment UserProfileFragment on UserProfile {
            workOrders(nextToken: $nextToken) {
                items {
                    ...WorkOrderFragment
                    __typename
                }
                nextToken
            }
            __typename
            }
            fragment WorkOrderFragment on WorkOrderInterface {
                orderId
                sessionId
                state
                isSold
                ... on ShipMiningOrder {
                    isRefined
                    refinery
                    processStartTime
                    processDurationS
                    processEndTime
                    shipOres {
                    ore
                    }
                    __typename
                }
            }
        """
        )

        return query

    def get_or_create_scouting_cluster(self, session_id):
        query = gql(
            """
                    query getSession($sessionId: ID!) {
                        session(sessionId: $sessionId) {
                            ...SessionFragment
                        }
                        }

                        fragment SessionFragment on Session {
                        scouting {
                            items {
                            ...ScoutingFindFragment
                            }
                            nextToken
                        }
                        }

                        fragment ScoutingFindFragment on ScoutingFindInterface {
                        ...ScoutingFindBaseFragment
                        state
                        }

                        fragment ScoutingFindBaseFragment on ScoutingFindInterface {
                        scoutingFindId
                        createdAt
                        clusterType
                        clusterCount
                        gravityWell
                        includeInSurvey
                        note
                        ... on ShipClusterFind {
                            shipRocks {
                            ...ShipRockFragment
                            }
                        }  
                        }

                        fragment ShipRockFragment on ShipRock {
                        mass
                        inst
                        res
                        state
                        rockType
                        ores {
                            ore
                            percent
                        }
                        }
        """
        )

        variables = {"sessionId": session_id}

        try:
            response = self.client.execute(query, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return False
            else:
                scouting_items = response["session"]["scouting"]["items"]

                if not scouting_items:
                    # Keine Einträge vorhanden
                    cluster = self.create_scouting_cluster(session_id)
                    print_debug(f"Created new scouting item: {cluster}")
                    return cluster
                else:
                    # Es existiert bereits mindestens ein Eintrag
                    # Sortiere absteigend nach createdAt:
                    cluster = sorted(
                        scouting_items, key=lambda i: i["createdAt"], reverse=True
                    )[0]
                    return cluster
        except Exception as e:
            print(
                f"Error trying to delete mining session: {str(e)}:\n{traceback.print_stack()}"
            )
            return False

    def create_scouting_cluster(self, session_id, cluster_count=0, cluster_type=None):
        
        mutation = ""
        variables = {}
        is_vehicle_like_cluster = cluster_type in VEHICLE_CLUSTER_TYPES or cluster_type in FPS_CLUSTER_TYPES
        if is_vehicle_like_cluster:
            mutation = gql(
                """mutation addScoutingFind($sessionId: ID!, $scoutingFind: ScoutingFindInput!, $vehicleRocks: [VehicleRockInput!]) {
                    addScoutingFind(
                        sessionId: $sessionId
                        scoutingFind: $scoutingFind
                        vehicleRocks: $vehicleRocks
                    ) {
                        ...ScoutingFindFragment
                    }
                    }

                    fragment ScoutingFindFragment on ScoutingFindInterface {
                    ...ScoutingFindBaseFragment
                    state
                    }

                    fragment ScoutingFindBaseFragment on ScoutingFindInterface {
                    scoutingFindId
                    createdAt
                    clusterType
                    clusterCount
                    gravityWell
                    includeInSurvey
                    note
                    ... on VehicleClusterFind {
                        vehicleRocks {
                        mass
                        inst
                        res
                        ores {
                            ore
                            percent
                        }
                        }
                    }
                }
            """
            )

            variables = {
                "sessionId": session_id,
                "scoutingFind": {
                    "state": "DISCOVERED",
                    "clusterCount": cluster_count,
                    "gravityWell": self.active_session["sessionSettings"]["gravityWell"],
                    "includeInSurvey": True,
                    "note": "{'info': 'This cluster has been discovered by Cora - your AI Compagnion.'"
                            + (f", 'cluster_type': '{cluster_type}'" if cluster_type else "")
                            + "}",
                },
                "vehicleRocks": [
                    {
                        "mass": 0.15,
                        "ores": [
                            {
                                "percent": 1,
                                "ore": cluster_type
                            }
                        ]
                    }
                    for _ in range(cluster_count)
                ],
            }
        else:
            mutation = gql(
                """mutation addScoutingFind($sessionId: ID!, $scoutingFind: ScoutingFindInput!, $shipRocks: [ShipRockInput!]) {
                    addScoutingFind(
                        sessionId: $sessionId
                        scoutingFind: $scoutingFind
                        shipRocks: $shipRocks
                    ) {
                        ...ScoutingFindFragment
                    }
                    }

                    fragment ScoutingFindFragment on ScoutingFindInterface {
                    ...ScoutingFindBaseFragment
                    state
                    }

                    fragment ScoutingFindBaseFragment on ScoutingFindInterface {
                    scoutingFindId
                    createdAt
                    clusterType
                    clusterCount
                    gravityWell
                    includeInSurvey
                    note
                    ... on ShipClusterFind {
                        shipRocks {
                        ...ShipRockFragment
                        }
                    }
                    }

                    fragment ShipRockFragment on ShipRock {
                    mass
                    inst
                    res
                    state
                    rockType
                    ores {
                        ore
                        percent
                    }
                    }  
            """
            )

            variables = {
                "sessionId": session_id,
                "scoutingFind": {
                    "state": "DISCOVERED",
                    "clusterCount": cluster_count,
                    "gravityWell": self.active_session["sessionSettings"]["gravityWell"],
                    "includeInSurvey": True,
                    "note": "{'info': 'This cluster has been discovered by Cora - your AI Compagnion.'"
                    + (f", 'cluster_type': '{cluster_type}'" if cluster_type else "")
                    + "}",
                },
                "shipRocks": [],
            }

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return None
            else:
                return response["addScoutingFind"]
        except Exception as e:
            print(
                f"Error trying creating cluster: {str(e)}:\n{traceback.print_stack()}"
            )
            return None

    def add_ship_cluster_scan_results(
        self, session_id, cluster, ship_rock_scan_result
    ):
        if not isinstance(cluster, dict) or not cluster.get("scoutingFindId"):
            return {
                "success": False,
                "response_instructions": "Tell the player the scouting cluster could not be resolved.",
                "result": "Missing or invalid scouting cluster.",
            }

        mutation = gql(
            """mutation updateScoutingFind($sessionId: ID!, $scoutingFindId: ID!, $scoutingFind: ScoutingFindInput!, $shipRocks: [ShipRockInput!]) {
                updateScoutingFind(
                    sessionId: $sessionId
                    scoutingFindId: $scoutingFindId
                    scoutingFind: $scoutingFind
                    shipRocks: $shipRocks
                ) {
                    ...ScoutingFindFragment
                }
            }

            fragment ScoutingFindFragment on ScoutingFindInterface {
                ...ScoutingFindBaseFragment
                state
            }

            fragment ScoutingFindBaseFragment on ScoutingFindInterface {
                sessionId
                scoutingFindId
                clusterCount
                includeInSurvey
                note
                ... on ShipClusterFind {
                    shipRocks {
                        ...ShipRockFragment
                    }
                }
            }

            fragment ShipRockFragment on ShipRock {
                mass
                inst
                res
                state
                rockType
                ores {
                    ore
                    percent
                }
            }
            """
        )

        if not ship_rock_scan_result or not ship_rock_scan_result.get("ores"):
            print_debug("No valid scan data in 'captureShipRockScan'.")
            return {
                "success": False,
                "response_instructions": "Tell user there's no valid scan data.",
                "result": "The scan result is empty or invalid."
            }
        ores = ship_rock_scan_result["ores"]
        cleaned_ores = [
            {key: value for key, value in ore.items() if key != "__typename"}
            for ore in ores
        ]

        def _normalize_ore_key(value):
            if not isinstance(value, str):
                return ""
            return "".join(ch for ch in value.upper() if ch.isalnum())

        def _normalize_scan_name(value):
            if not isinstance(value, str):
                return ""
            value = value.upper()
            # Remove parenthetical suffixes like "(RAW)" / "(ORE)" and whitespace separators.
            value = re.sub(r"\([^)]*\)", "", value)
            value = value.replace(" ", "").replace("-", "").replace("_", "")
            # Normalize common OCR variants.
            value = value.replace("MATERIALS", "MATERIAL")
            if value == "INERTMATERIAL":
                return "INERTMATERIAL"
            # Drop common suffix tokens, e.g. "BEXALITERAW" -> "BEXALITE".
            for suffix in ("RAW", "ORE"):
                if value.endswith(suffix) and len(value) > len(suffix):
                    value = value[: -len(suffix)]
            return value

        def _to_percent(value):
            if isinstance(value, (int, float)):
                num = float(value)
            elif isinstance(value, str):
                cleaned = value.strip().replace("%", "").replace(",", ".")
                try:
                    num = float(cleaned)
                except ValueError:
                    return None
            else:
                return None

            if num > 1:
                num = num / 100
            if num < 0:
                return None
            return num

        ship_ore_names = self.get_ship_ore_names() or []
        normalized_ship_ores = {
            _normalize_ore_key(ore_name): ore_name for ore_name in ship_ore_names
        }

        normalized_ores = []
        for ore in cleaned_ores:
            raw_name = ore.get("ore")
            if not raw_name:
                continue

            percent_value = _to_percent(ore.get("percent"))
            if percent_value is None:
                continue
            ore["percent"] = percent_value

            if raw_name in ship_ore_names:
                normalized_ores.append(ore)
                continue

            normalized_key = _normalize_ore_key(raw_name)
            mapped_name = normalized_ship_ores.get(normalized_key)
            if mapped_name:
                ore["ore"] = mapped_name
                normalized_ores.append(ore)
                continue

            cleaned_key = _normalize_scan_name(raw_name)
            mapped_name = normalized_ship_ores.get(cleaned_key)
            if mapped_name:
                ore["ore"] = mapped_name
                normalized_ores.append(ore)
                continue

            if cleaned_key in ("INERTMATERIAL", "INERTMATERIALS"):
                ore["ore"] = "INERTMATERIAL"
                normalized_ores.append(ore)
                continue
            print_debug(f"Unknown ship ore name from scan: {raw_name}")

        ore_totals = {}
        for ore in normalized_ores:
            ore_name = ore["ore"]
            ore_totals[ore_name] = ore_totals.get(ore_name, 0) + ore["percent"]
        normalized_ores = [
            {"ore": ore_name, "percent": percent}
            for ore_name, percent in ore_totals.items()
            if percent > 0
        ]

        total_percent = sum(ore["percent"] for ore in normalized_ores)
        if total_percent > 1:
            # Keep ratios but ensure payload sums to 1.
            normalized_ores = [
                {"ore": ore["ore"], "percent": ore["percent"] / total_percent}
                for ore in normalized_ores
                if ore["percent"] > 0
            ]
            total_percent = sum(ore["percent"] for ore in normalized_ores)
        if 1 - total_percent > 0:
            normalized_ores.append({"ore": "INERTMATERIAL", "percent": 1 - total_percent})

        def _normalize_cluster_type(value):
            if not isinstance(value, str):
                return None
            key = _normalize_ore_key(value)
            for suffix in ("DEPOSITS", "DEPOSIT", "CLUSTERS", "CLUSTER", "ROCKS", "ROCK"):
                if key.endswith(suffix) and len(key) > len(suffix):
                    key = key[: -len(suffix)]
            if key in SHIP_CLUSTER_TYPES:
                return key
            return None

        rock_type = _normalize_cluster_type(ship_rock_scan_result.get("rockType"))
        if not rock_type:
            rock_type = _normalize_cluster_type(cluster.get("clusterType"))

        def _to_float(value):
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                cleaned = value.strip().replace(",", ".")
                try:
                    return float(cleaned)
                except ValueError:
                    return None
            return None

        ship_rocks = cluster.get("shipRocks", [])
        inst_value = _to_float(ship_rock_scan_result.get("inst"))
        if inst_value is None:
            inst_value = ship_rock_scan_result.get("inst")
        if isinstance(inst_value, (int, float)) and inst_value == 0:
            inst_value = 1.0

        res_value = _to_percent(ship_rock_scan_result.get("res"))
        if res_value is None:
            res_value = ship_rock_scan_result.get("res")
        if isinstance(res_value, (int, float)) and res_value == 0:
            res_value = 0.01

        ship_rock_payload = {
            "mass": ship_rock_scan_result["mass"],
            "state": "READY",
            "inst": inst_value,
            "res": res_value,
            "ores": normalized_ores,
        }
        if rock_type:
            ship_rock_payload["rockType"] = rock_type

        ship_rocks.append(ship_rock_payload)

        scouting_find_payload = {
            "state": "DISCOVERED",
            "includeInSurvey": True,
        }
        if cluster.get("clusterCount") is not None:
            scouting_find_payload["clusterCount"] = cluster.get("clusterCount")
        if cluster.get("note"):
            scouting_find_payload["note"] = cluster.get("note")
        if cluster.get("gravityWell"):
            scouting_find_payload["gravityWell"] = cluster.get("gravityWell")
        elif self.active_session and self.active_session.get("sessionSettings", {}).get("gravityWell"):
            scouting_find_payload["gravityWell"] = self.active_session["sessionSettings"]["gravityWell"]

        variables = {
            "sessionId": session_id,
            "scoutingFindId": cluster["scoutingFindId"],
            "scoutingFind": scouting_find_payload,
            "shipRocks": ship_rocks,
        }

        try:
            print_debug(f"Adding ship cluster scan results: {json.dumps(variables, indent=2)}")
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return {
                    "success": False,
                    "response_instructions": "Shortly tell why the scan couldn't be saved. ",
                    "result": response["errors"],
                }
            else:
                update_find = response.get("updateScoutingFind", {}) or {}
                response_warnings = []
                response_ship_rocks = update_find.get("shipRocks") or []
                if not response_ship_rocks:
                    response_warnings.append("Regolith response contains no shipRocks.")
                else:
                    latest_response_rock = response_ship_rocks[-1]
                    response_ores = latest_response_rock.get("ores") or []
                    if not response_ores:
                        response_warnings.append("Regolith response contains no ores for the latest rock.")
                    sent_ore_names = {
                        ore.get("ore")
                        for ore in ship_rock_payload.get("ores", [])
                        if isinstance(ore, dict) and ore.get("ore")
                    }
                    response_ore_names = {
                        ore.get("ore")
                        for ore in response_ores
                        if isinstance(ore, dict) and ore.get("ore")
                    }
                    missing_in_response = sorted(sent_ore_names - response_ore_names)
                    if missing_in_response:
                        response_warnings.append(
                            f"Regolith response is missing ores: {', '.join(missing_in_response)}"
                        )

                    sent_rock_type = ship_rock_payload.get("rockType")
                    if sent_rock_type and not latest_response_rock.get("rockType"):
                        response_warnings.append(
                            f"Regolith response did not persist rockType '{sent_rock_type}'."
                        )

                return {
                    "success": True,
                    "response_instructions": (
                        "Shortly confirm that the scan has been saved, like: '9 of 12 rocks scanned. "
                        if not response_warnings
                        else "Confirm the scan save, but warn that Regolith returned incomplete data."
                    ),
                    "total_scans": f"{len(ship_rocks)}/{update_find.get('clusterCount', cluster.get('clusterCount', '?'))}",
                    "warnings": response_warnings,
                }
        except Exception as e:
            print(f"Error during save scan: {str(e)}:\n{traceback.print_stack()}")
            return {
                "success": False,
                "response_instructions": "Tell there was a technical error. ",
                "result": f"Unable to save scan. Check the logs because of {str(e)}. ",
            }

    def process_work_orders(self, data):
        current_time_ms = int(datetime.now().timestamp() * 1000)

        # Zuerst Duplikate entfernen (hier anhand orderId).
        # Wenn du orderId + sessionId für die Eindeutigkeit brauchst,
        # kannst du stattdessen (order['orderId'], order['sessionId']) als Schlüssel benutzen.
        unique_orders_map = {}
        for o in data["profile"]["workOrders"]["items"]:
            if o["orderId"] not in unique_orders_map:
                unique_orders_map[o["orderId"]] = o

        # In eine Liste umwandeln
        unique_orders = list(unique_orders_map.values())

        # Jetzt die eigentliche Logik
        refinery_groups = defaultdict(
            lambda: {
                "order_count": 0,
                "ores": set(),
                "sessions": defaultdict(lambda: {"session_id": None, "orders": []}),
            }
        )

        total_orders_in_processing = 0
        next_order_finish_duration = float(
            "inf"
        )  # Initialize to the largest possible number

        for order in unique_orders:
            # skip if no end‐time
            process_end = order.get("processEndTime")
            if process_end is None:
                continue

            # Prüfen, ob der Auftrag noch läuft
            if process_end > current_time_ms:
                total_orders_in_processing += 1
                if process_end < next_order_finish_duration:
                    next_order_finish_duration = process_end

            # Wenn Auftrag fertig (d. h. Endzeit < jetzt) und noch nicht verkauft
            if not order.get("isSold", False) and process_end < current_time_ms:
                refinery = order["refinery"]
                session_id = order["sessionId"]

                # Update Zählungen und Daten sammeln
                refinery_groups[refinery]["order_count"] += 1
                refinery_groups[refinery]["ores"].update(
                    [ore["ore"] for ore in order["shipOres"]]
                )
                refinery_groups[refinery]["sessions"][session_id][
                    "session_id"
                ] = session_id
                refinery_groups[refinery]["sessions"][session_id]["orders"].append(
                    {"orderId": order["orderId"]}
                )

        total_refined_orders = sum(
            info["order_count"] for info in refinery_groups.values()
        )

        if total_orders_in_processing == 0:
            next_order_finish_str = "No active orders"
        else:
            secs_remaining = (next_order_finish_duration - current_time_ms) / 1000
            next_order_finish_str = time_string_converter.convert_seconds_to_str(
                int(secs_remaining)
            )

        refinery_orders = []
        # Sortiere nach der höchsten 'order_count'
        for refinery, info in sorted(
            refinery_groups.items(), key=lambda x: -x[1]["order_count"]
        ):
            sessions_sorted = sorted(
                info["sessions"].values(), key=lambda x: -len(x["orders"])
            )
            refinery_entry = {
                "refinery": refinery,
                "order_count": info["order_count"],
                "ores": list(info["ores"]),
                "sessions": [
                    {"sessionId": session["session_id"], "orders": session["orders"]}
                    for session in sessions_sorted
                ],
            }
            refinery_orders.append(refinery_entry)
       
        # Rückgabe
        if total_refined_orders > 0 and total_orders_in_processing > 0:
            return {
                "total_finished_refinery_orders": total_refined_orders,
                "total_refinery_orders_in_processing": total_orders_in_processing,
                "next_refinery_job_finished_in": next_order_finish_str,
            }
        elif total_refined_orders > 0 and total_orders_in_processing == 0:
            return {
                "total_finished_refinery_orders": total_refined_orders,
                "finished_refinery_orders": refinery_orders,
            }
        elif total_refined_orders == 0 and total_orders_in_processing > 0:
            return {
                "total_refinery_orders_in_processing": total_orders_in_processing,
                "next_refinery_job_finished_in": next_order_finish_str,
            }
        
        return None
    
        # {
        #     "total_finished_refinery_orders": 3,
        #     "total_refinery_orders_in_processing": 0,
        #     "next_refinery_job_finished_in": "No active orders", # or 21h 33m
        #     "finished_refinery_orders": [
        #         {
        #             "refinery": "MIC-L2",
        #             "order_count": 3,
        #             "ores": [
        #                 "GOLD", "TARANITE"
        #             ],
        #             "sessions": [
        #             {
        #                 "sessionId": "dasdf",
        #                 "orders": [
        #                     {
        #                         "orderId": "hasldfasd",
        #                     }
        #                 ]
        #             }
        #         }

        #     ]
        # }

    def delete_processed_sessions(self):
        print_debug("deleting processed sessions. ")
        query = self.get_active_work_session_query()

        try:
            response = self.client.execute(query)

            if "errors" in response:
                print("Errors during Graph-QL request:")
                for error in response["errors"]:
                    print(error["message"])
                return {
                    "success": False,
                    "message": "There was an error when I tried to retrieve active work orders. I'm very sorry. ",
                }
            else:
                return self.delete_sessions(response)
        except Exception as e:
            print(
                f"Error during work order retrieval {str(e)}: \n{traceback.print_stack()}"
            )
            return {
                "success": False,
                "message": "Sorry, but regolith seems not to be available currently. ",
            }

    def delete_sessions(self, work_order_sessions):
        current_time_ms = int(datetime.now().timestamp() * 1000)

        valid_sessions = {}
        for order in work_order_sessions["profile"]["workOrders"]["items"]:
            session_id = order["sessionId"]
            if order["isSold"] and order["processEndTime"] < current_time_ms:
                if session_id not in valid_sessions:
                    valid_sessions[session_id] = True
            else:
                # Sobald eine Order die Kriterien nicht erfüllt, wird die Session als ungültig markiert
                valid_sessions[session_id] = False

        if len(valid_sessions) == 0:
            return {"success": True, "message": "You don't have any active sessions. "}

        count_deleted = 0
        count_not_deleted = 0
        count_errors = 0
        total_sessions = 0
        for session_id, is_valid in valid_sessions.items():
            total_sessions += 1
            if is_valid:
                success = self.delete_session(session_id)
                if success:
                    count_deleted += 1
                else:
                    count_errors += 1
            else:
                count_not_deleted += 1

        if count_errors == 0 and count_deleted > 0:
            return {
                "success": True,
                "message": "All processed sessions have been deleted. Give a summary. ",
                "data": {
                    "total_sessions_evaluated": total_sessions,
                    "deleted_finished_sessions": count_deleted,
                    "sessions_with_active_jobs": count_not_deleted,
                },
            }
        elif count_errors > 0 and count_deleted > 0:
            return {
                "success": False,
                "message": "Not all processed sessions could be deleted. Give a summary. ",
                "data": {
                    "total_sessions_evaluated": total_sessions,
                    "deleted_finished_sessions": count_deleted,
                    "sessions_with_active_jobs": count_not_deleted,
                    "finished_sessions_that_could_not_be_deleted": count_errors,
                },
            }
        elif count_errors > 0 and count_deleted == 0:
            return {
                "success": False,
                "message": "None of the processed sessions could be deleted. Give a summary. ",
                "data": {
                    "total_sessions_evaluated": total_sessions,
                    "deleted_finished_sessions": count_deleted,
                    "sessions_with_active_jobs": count_not_deleted,
                    "finished_sessions_that_could_not_be_deleted": count_errors,
                },
            }

        return {
            "success": False,
            "message": "You don't have any processed sessions that could be deleted, but you have active sessions. ",
            "data": {
                "total_sessions_evaluated": total_sessions,
                "deleted_finished_sessions": count_deleted,
                "sessions_with_active_jobs": count_not_deleted,
                "finished_sessions_that_could_not_be_deleted": count_errors,
            },
        }

    def delete_session(self, session_id):
        print_debug(f"Deleting session {session_id}")
        mutation = gql(
            """
                mutation DeleteSession($sessionId: ID!) {
            deleteSession(sessionId: $sessionId)
        }
        """
        )

        variables = {"sessionId": session_id}

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Fehler bei der GraphQL-Anfrage:")
                for error in response["errors"]:
                    print(error["message"])
                return False

            print_debug(f'Session deleted: {response["deleteSession"]}')
            return True
        except Exception as e:
            print(
                f"Error during session deletion {str(e)}: \n{traceback.print_stack()}"
            )
            return False

    def _save_debug_data(self, image_type=None, image_data=None, error_message=None):
        """
        Saves image data and error messages to the debug_data directory.
        The filename depends on file_type and a timestamp.
        """
        debug_dir = os.path.join("debug_data", image_type)
        os.makedirs(debug_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        if image_data:
            filename = f"{'cropped_screenshot'}_{timestamp}.jpg"
            image_path = os.path.join(debug_dir, filename)
            with open(image_path, "wb") as img_file:
                img_file.write(base64.b64decode(image_data.split(",")[1]))

        if error_message:
            filename = f"{'regolith_error'}_{timestamp}.txt"
            error_path = os.path.join(debug_dir, filename)
            with open(error_path, "w") as err_file:
                err_file.write(error_message)

    def fetch_lookups(self):
        """
        Fetches lookup data from the GraphQL API.
        Note: refineryBonusLookup was removed from the API.
        """
        query = gql(
            """
            query GetLookups {
                lookups {
                    CIG {
                    oreProcessingLookup
                    methodsBonusLookup
                    }
                }
            }
            """
        )

        try:
            response = self.client.execute(query)

            if "errors" in response:
                print("Fehler bei der GraphQL-Anfrage:")
                for error in response["errors"]:
                    print(error["message"])
                return None
            else:
                return response["lookups"]["CIG"]
        except Exception as e:
            print(
                f"Error during lookups fetch {str(e)}: \n{traceback.format_exc()}"
            )
            return None

    def ore_amt_calc(self, ore_yield, ore, refinery, method):
        """
        Calculates the final ore amount after applying processing and method bonuses.
        Note: Refinery-specific bonuses were removed from the API.

        Args:
            ore_yield (float): Initial ore yield.
            ore (str): Type of ore.
            refinery (str): Name of the refinery (unused, kept for compatibility).
            method (str): Refining method used.

        Returns:
            int: Final ore amount rounded to the nearest integer.
        """
        # Fetch lookup data
        if self.lookups is None:
            self.lookups = self.fetch_lookups()
        
        # If lookups failed to load, return the yield value as-is
        if self.lookups is None:
            print_debug(f"Warning: Lookups not available, using yield value {ore_yield} as amount")
            return round(ore_yield)
        
        ore_processing_lookup = self.lookups["oreProcessingLookup"]
        methods_bonus_lookup = self.lookups["methodsBonusLookup"]

        # Default bonuses
        processing_bonus = 1
        method_bonus = 1

        # Method bonus lookup
        if method not in methods_bonus_lookup:
            print_debug(f"Method {method} not found in lookups.")
        else:
            method_bonus = methods_bonus_lookup[method][0]

        # Ore processing bonus lookup
        if ore not in ore_processing_lookup:
            print_debug(f"Ore {ore} not found in ore processing lookup.")
        else:
            processing_bonus = ore_processing_lookup[ore][0]

        # Final calculation (refinery bonus removed from API)
        final_ore_yield = ore_yield / (processing_bonus * method_bonus)
        return round(final_ore_yield)


# Example usage
if __name__ == "__main__":
    regolith = RegolithAPI(None, "i288P0IjLz9HiYTFWV8nd8CMErZjueu2a2GxthVs")
    current_time = int(time.time())

    # regolith.create_mining_session()

    # variables = {
    #     "sessionId": regolith.active_session_id,
    #     "shipOres": [
    #         {
    #             "amt": 100,  # Die Menge des Erzes
    #             "ore": "QUANTANIUM"  # Der Enum-Wert des Erzes
    #         }
    #     ],
    #     "workOrder": {
    #         "expenses": [
    #             {
    #                 "amount": 6841,
    #                 "name": "Refinery Fee"
    #             }
    #         ],
    #         "includeTransferFee": True,
    #         "isRefined": True,
    #         "isSold": False,
    #         "method": "DINYX_SOLVENTATION",  # Angenommen, dies ist ein gültiger Wert im RefineryMethodEnum
    #         "note": "Work order created by Cora - Your Star Citizen ai-compagnion",
    #         "processDurationS": 3600,  # Angenommen, dies ist die Dauer in Sekunden
    #         "processStartTime": current_time,  # Ein Zeitstempel
    #         "refinery": "MICL2",  # Angenommen, dies ist ein gültiger Wert im RefineryEnum
    #     }
    #     # Fülle die anderen Listenparameter entsprechend
    # }

    # regolith.create_work_order(regolith.active_session_id, None)
    # regolith.delete_mining_session(regolith.activeSessionId)
    # regolith.get_refinery_names()
    # print_debug(f"refineries: {regolith.refineries}")
    # regolith.get_refinery_method_names()
    # print_debug(f"refinery methods: {regolith.refinery_methods}")
    # regolith.get_location_names()
    # print_debug(f"locations: {regolith.locations}")
    # regolith.get_gravity_wells()
    # print_debug(f"gravity wells: {regolith.gravity_wells}")
    # regolith.get_last_active_session()
    # regolith.initialize_all_names()
