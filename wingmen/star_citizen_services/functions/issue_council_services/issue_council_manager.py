import json
import re
import webbrowser
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher

import requests

from services.printr import Printr
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.function_manager import FunctionManager


DEBUG = True
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class IssueCouncilManager(FunctionManager):
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = (
        "Checks Star Citizen Issue Council for known bugs."
    )
    MANAGER_CAPABILITIES = [
        "Search Issue Council by free text and bug symptoms",
        "Pick the closest matching issue and summarize relevance",
        "Analyze reproductions, duplicate links, and possible duplicate variants",
        "Create a new issue when no relevant issue exists",
        "Opens issue links in browser.",
    ]

    DEFAULT_PROJECT_ID = "5bb2df28-5a58-4d02-84b4-c28cce4e1fa0"
    DEFAULT_PROJECT_CODE = "STAR-CITIZEN"
    DEFAULT_STATUSES = ["OPEN", "CONFIRMED", "UNDER_INVESTIGATION"]
    DEFAULT_MAX_BROWSER_OPEN_TABS = 15
    DEFAULT_ISSUE_SEVERITY = "MEDIUM"
    ALLOWED_ISSUE_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    STOP_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "auf",
        "bei",
        "bug",
        "das",
        "dem",
        "den",
        "der",
        "des",
        "die",
        "ein",
        "eine",
        "einem",
        "einen",
        "einer",
        "es",
        "for",
        "hat",
        "have",
        "ich",
        "im",
        "in",
        "is",
        "ist",
        "it",
        "mit",
        "not",
        "oder",
        "of",
        "on",
        "the",
        "und",
        "wenn",
        "wie",
        "zu",
    }
    LLM_SELECTION_SYSTEM_PROMPT = (
        "You map a Star Citizen bug description to Issue Council issues.\n"
        "Return only a valid JSON object with keys:\n"
        "- best_issue_code: string or null (must be one of provided candidate codes)\n"
        "- known_bug: boolean\n"
        "- match_confidence: number between 0 and 1\n"
        "- reasoning_short: short string\n"
        "- review_issue_codes: array of candidate codes for deeper detail fetch\n"
        "- possible_duplicate_codes: array of candidate codes that might be variants\n"
        "- missing_information: array of short clarification questions\n"
        "Rules:\n"
        "- Prioritize symptom/behavior match over popularity.\n"
        "- If no clear match exists, set best_issue_code to null and known_bug to false.\n"
        "- Never invent issue codes."
    )
    LLM_DUPLICATE_REVIEW_SYSTEM_PROMPT = (
        "You evaluate if Issue Council candidates are relevant to a player's bug report and if they are plausible duplicates.\n"
        "Return only a valid JSON object with key 'evaluations' as an array.\n"
        "Each entry must contain:\n"
        "- code: string (must be one of provided codes)\n"
        "- relevance_score: number 0..1 (overall relevance to player's described bug)\n"
        "- duplicate_relevance_score: number 0..1 (how likely this issue is a duplicate/variant of the best match)\n"
        "- is_relevant: boolean\n"
        "- possible_duplicate: boolean\n"
        "- reasoning_short: short string\n"
        "Scoring guidance:\n"
        "- <0.5 means weak match, >=0.5 moderate, >=0.7 strong.\n"
        "- Use issue details (actual behavior, expected behavior, steps, environment), not title words only.\n"
        "- Never invent issue codes.\n"
    )
    LLM_search_phrases_SYSTEM_PROMPT = (
        "You convert a Star Citizen bug description into concise English Issue Council search queries.\n"
        "Return only a valid JSON object with key 'search_phrases' (array of strings).\n"
        "Rules:\n"
        "- English only.\n"
        "- Use short high-signal terms/phrases (1-5 words).\n"
        "- Focus on symptoms and entities.\n"
        "- Do not add explanations."
    )
    LLM_CATEGORY_SELECTION_SYSTEM_PROMPT = (
        "You map a Star Citizen bug report to the best matching Issue Council category.\n"
        "Return only a valid JSON object with keys:\n"
        "- category_id: string or null (must be one of provided category ids)\n"
        "- reasoning_short: short string\n"
        "Rules:\n"
        "- Prefer category semantics over popularity.\n"
        "- Never invent category ids."
    )

    SIMILAR_ISSUES_QUERY = """
query Issues($query: SimilarIssuesQueryInput!) {
  similarIssues(query: $query) {
    totalCount
    edges {
      node {
        id
        code
        status
        search {
          score
          relevanceScore
          highlights {
            field
            matches
          }
        }
        details {
          title
          severity
          category {
            name
          }
          environment {
            id
            code
            name
          }
        }
        openDetails {
          openedOn
          expiresOn
        }
        community {
          contributionCount
          reproductionCount
          voteCount
        }
        archivedDetails {
          archivedOn
          reason
          duplicateOf {
            code
          }
        }
        confirmedDetails {
          confirmedOn
        }
        underInvestigationDetails {
          investigationStartedOn
        }
        fixedDetails {
          fixedOn
          fixedInReleaseCode
        }
      }
    }
  }
}
"""

    FILTERED_ISSUES_FALLBACK_QUERY = """
query Issues($filteredQuery: IssueQueryInput!) {
  filteredIssues: issues(query: $filteredQuery) {
    totalCount
    edges {
      node {
        id
        code
        status
        search {
          score
          relevanceScore
          highlights {
            field
            matches
          }
        }
        details {
          title
          severity
          category {
            name
          }
          environment {
            id
            code
            name
          }
        }
        openDetails {
          openedOn
          expiresOn
        }
        community {
          contributionCount
          reproductionCount
          nonReproductionCount
          voteCount
        }
        archivedDetails {
          archivedOn
          reason
          duplicateOf {
            code
          }
        }
        confirmedDetails {
          confirmedOn
        }
        underInvestigationDetails {
          investigationStartedOn
        }
        fixedDetails {
          fixedOn
          fixedInReleaseCode
        }
      }
    }
  }
}
"""

    ISSUE_DETAILS_QUERY = """
query IssueByCode($code: String!) {
  issueByCode(code: $code) {
    id
    code
    status
    project {
      code
      name
    }
    openDetails {
      confirmationThreshold
      openedOn
      expiresOn
    }
    details {
      title
      severity
      category {
        name
      }
      environment {
        id
        code
        name
      }
      release {
        version {
          code
        }
      }
      reproductionSteps {
        description
      }
      actualBehaviour {
        description
      }
      expectedBehaviour {
        description
      }
      workaround {
        description
      }
    }
    community {
      contributionCount
      reproductionCount
      nonReproductionCount
      voteCount
      possibleDuplicateIssuesCount
      possibleDuplicateIssues {
        entries {
          duplicateCount
          issue {
            code
            title
          }
        }
      }
      lastContribution {
        submittedOn
      }
    }
    confirmedDetails {
      confirmedOn
      additionalInfo
    }
    archivedDetails {
      archivedOn
      reason
      additionalInfo
      duplicateOf {
        code
        title
      }
    }
    underInvestigationDetails {
      investigationStartedOn
      additionalInfo
    }
    fixedDetails {
      fixedOn
      additionalInfo
      fixedInReleaseCode
    }
    externalIssue {
      code
      url
      fixedInReleaseCode
    }
  }
}
"""

    PROJECT_DETAILS_QUERY = """
query Project($code: String!, $environmentQueryInput: EnvironmentQueryInput!, $releaseDeploymentQueryInput: ReleaseDeploymentQueryInput!) {
  projectByCode(code: $code) {
    id
    code
    name
    environments(query: $environmentQueryInput) {
      edges {
        node {
          id
          code
          name
          status
          viewerProperties {
            canOpenIssue
            canPostContribution
          }
          deployments(query: $releaseDeploymentQueryInput) {
            edges {
              node {
                id
                status
                isCurrent
                completedOn
                release {
                  id
                  code
                  version {
                    code
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

    ISSUE_CATEGORIES_QUERY = """
query ProjectIssueCategories($projectId: ID!, $query: IssueCategoryQueryInput!) {
  project(id: $projectId) {
    id
    issueCategories(query: $query) {
      edges {
        node {
          id
          code
          name
          status
          statistics {
            issueCount
          }
        }
      }
    }
  }
}
"""

    SUGGESTED_SYSTEM_CONFIGURATION_QUERY = """
query GetSuggestedSystemConfiguration($query: SuggestedSystemConfigurationQueryInput!) {
  viewer {
    id
    suggestedSystemConfiguration(query: $query) {
      id
      name
    }
  }
}
"""

    OPEN_ISSUE_MUTATION = """
mutation OpenIssue($input: OpenIssueInput!) {
  openIssue(input: $input) {
    code
    success
    message
    issue {
      id
      code
      status
      details {
        title
        severity
        category {
          id
          code
          name
        }
        environment {
          id
          code
          name
        }
        release {
          id
          code
          version {
            code
          }
        }
      }
      project {
        id
        code
        name
      }
    }
    problem {
      type
      title
      status
      help
      data {
        ... on ValidationErrors {
          errors {
            field
            code
            message
            help
          }
        }
      }
    }
  }
}
"""

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config

        manager_cfg = self.config.get("IssueCouncilManager", {})
        if not isinstance(manager_cfg, dict):
            manager_cfg = {}

        self.api_url = manager_cfg.get(
            "api_url",
            "https://api-issue-council.robertsspaceindustries.com/gql",
        )
        self.issue_web_url = manager_cfg.get(
            "issue_web_url",
            "https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues",
        )
        self.project_id = manager_cfg.get("project_id", self.DEFAULT_PROJECT_ID)
        self.project_code = str(
            manager_cfg.get("project_code", self.DEFAULT_PROJECT_CODE)
        ).strip() or self.DEFAULT_PROJECT_CODE
        self.request_timeout_seconds = self._coerce_int(
            manager_cfg.get("request_timeout_seconds", 12), default=12, minimum=4, maximum=60
        )
        self.default_search_limit = self._coerce_int(
            manager_cfg.get("default_search_limit", 20), default=20, minimum=5, maximum=30
        )
        self.max_detail_fetch = self._coerce_int(
            manager_cfg.get("max_detail_fetch", 14), default=14, minimum=5, maximum=40
        )
        self.max_possible_duplicate_fetch = self._coerce_int(
            manager_cfg.get("max_possible_duplicate_fetch", 8), default=8, minimum=3, maximum=25
        )
        self.llm_validation_enabled = bool(manager_cfg.get("llm_validation_enabled", True))
        self.llm_validation_candidates = self._coerce_int(
            manager_cfg.get("llm_validation_candidates", 12), default=12, minimum=4, maximum=25
        )
        self.llm_temperature = self._coerce_float(
            manager_cfg.get("llm_temperature", 0.15), default=0.15, minimum=0.0, maximum=1.2
        )
        self.llm_max_tokens = self._coerce_int(
            manager_cfg.get("llm_max_tokens", 1200), default=1200, minimum=300, maximum=3500
        )
        self.llm_duplicate_review_candidates = self._coerce_int(
            manager_cfg.get("llm_duplicate_review_candidates", 12),
            default=12,
            minimum=4,
            maximum=30,
        )
        self.llm_relevance_min = self._coerce_float(
            manager_cfg.get("llm_relevance_min", 0.5),
            default=0.5,
            minimum=0.0,
            maximum=1.0,
        )
        self.llm_duplicate_relevance_min = self._coerce_float(
            manager_cfg.get("llm_duplicate_relevance_min", 0.55),
            default=0.55,
            minimum=0.0,
            maximum=1.0,
        )
        self.llm_detail_char_limit = self._coerce_int(
            manager_cfg.get("llm_detail_char_limit", 380),
            default=380,
            minimum=120,
            maximum=1200,
        )
        self.enforce_search_phrases = bool(manager_cfg.get("enforce_search_phrases", True))
        self.auto_generate_search_phrases = bool(
            manager_cfg.get("auto_generate_search_phrases", True)
        )
        self.debug_mode = bool(
            manager_cfg.get(
                "debug_mode",
                self.config.get("features", {}).get("debug_mode", False),
            )
        )
        self.debug_log_payloads = bool(manager_cfg.get("debug_log_payloads", False))
        self.bearer_token_env_var = manager_cfg.get(
            "bearer_token_env_var",
            "ISSUE_COUNCIL_BEARER_TOKEN",
        )
        self.bearer_token_file = manager_cfg.get(
            "bearer_token_file",
            "star_citizen_data/issue_council_data/.issue_council_bearer_token",
        )
        self.bearer_token = self._normalize_bearer_token_value(manager_cfg.get("bearer_token", None))
        self.session_cookie = manager_cfg.get("session_cookie", None)
        self.auth_debug_hint = manager_cfg.get(
            "auth_debug_hint",
            "Open DevTools Network on issue-council.robertsspaceindustries.com and copy the Authorization Bearer token from a gql request.",
        )
        self.token_capture_script_path = manager_cfg.get(
            "token_capture_script_path",
            "star_citizen_data/issue_council_data/scripts/capture_issue_council_token.py",
        )
        self.token_capture_timeout_seconds = self._coerce_int(
            manager_cfg.get("token_capture_timeout_seconds", 600),
            default=600,
            minimum=60,
            maximum=1800,
        )
        self.token_capture_retry_cooldown_seconds = self._coerce_int(
            manager_cfg.get("token_capture_retry_cooldown_seconds", 30),
            default=30,
            minimum=5,
            maximum=300,
        )
        self.project_context_refresh_seconds = self._coerce_int(
            manager_cfg.get("project_context_refresh_seconds", 21600),  # 6 hours
            default=21600,
            minimum=1800,
            maximum=86400,
        )
        self.last_token_capture_attempt_ts = 0.0

        bearer_secret = self.secret_keeper.retrieve(
            requester="IssueCouncilManager",
            key="issue_council_bearer_token",
            friendly_key_name="Issue Council Bearer token",
            prompt_if_missing=False,
        )
        if bearer_secret:
            self.bearer_token = self._normalize_bearer_token_value(bearer_secret)

        session_cookie_secret = self.secret_keeper.retrieve(
            requester="IssueCouncilManager",
            key="issue_council_session_cookie",
            friendly_key_name="Issue Council session cookie header value",
            prompt_if_missing=False,
        )
        if session_cookie_secret:
            self.session_cookie = session_cookie_secret

        self._load_bearer_token_from_sources(allow_file=True)

        environment_ids = manager_cfg.get("default_environment_ids", [])
        if isinstance(environment_ids, str):
            environment_ids = [environment_ids]
        if not isinstance(environment_ids, list):
            environment_ids = []
        self.default_environment_ids = [env_id for env_id in environment_ids if isinstance(env_id, str) and env_id]

        self.project_context = {}
        self.project_context_loaded_at = 0.0
        self.issue_categories = []
        self.issue_categories_loaded_at = 0.0
        self.cached_system_configuration_id = None
        self.cached_system_configuration_loaded_at = 0.0
        self.last_analysis = None

    def get_context_mapping(self) -> AIContext:
        return AIContext.CORA

    def register_functions(self, function_register):
        function_register[self.check_issue_council_for_known_bug.__name__] = self.check_issue_council_for_known_bug
        function_register[self.open_issue_council_issues_in_browser.__name__] = self.open_issue_council_issues_in_browser
        function_register[self.create_issue_council_issue.__name__] = self.create_issue_council_issue

    def get_function_prompt(self) -> str:
        return (
            f"When the player ask to search for an issue or bug, call {self.check_issue_council_for_known_bug.__name__}. "
            "Always prepare Issue Council search phrases in English, even if the player speaks another language. "
            "Use the player's wording as bug_description and do not invent missing details. "
            "Always pass search_phrases with concise English symptom phrases. Avoid single word search phrases unless for the key aspect of the bug description. combine the object with symptoms to build search phrases. "
            "Optionally pass environment as environment name, to filter search results by environment. "
            "Example search_phrases for bug_description 'Is there a bug about the fabricator dissapearing in the hangar?': ['fabricator', 'fabricator hangar', 'fabricator disappearing hangar', 'fabricator missing']. "
            "If no relevant issue is found, ask if the player wants to create a new issue and call "
            f"{self.create_issue_council_issue.__name__}. "
            "Creating an issue requires environment, actual behavior, expected behavior, and reproduction steps. All text must be in English. even if the user speaks another language. Do not invent any details, only use the provided information. "
            "When the user asks to open issue links, call "
            f"{self.open_issue_council_issues_in_browser.__name__}. "
            "For browser opening, default to source=last_analysis, unless user asks for a single specific code. "
        )

    def get_function_tools(self) -> list[dict]:
        search_environment_schema = self._build_environment_param_schema(required=False)
        create_environment_schema = self._build_environment_param_schema(required=True)
        severity_schema = self._build_severity_param_schema()
        category_schema = self._build_category_param_schema()
        return [
            {
                "type": "function",
                "function": {
                    "name": self.check_issue_council_for_known_bug.__name__,
                    "description": (
                        "Searches Star Citizen Issue Council for a described bug."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "bug_description": {
                                "type": "string",
                                "description": "Natural language bug description from the player.",
                            },
                            "search_phrases": {
                                "type": "array",
                                "description": "Search phrases for Issue Council lookup.",
                                "items": {"type": "string"},
                            },
                            "environment": search_environment_schema,
                        },
                        "required": ["bug_description", "search_phrases"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": self.create_issue_council_issue.__name__,
                    "description": (
                        "Creates a new Issue Council issue when no relevant known issue exists. All Text must be in english."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "environment": create_environment_schema,
                            "title": {
                                "type": "string",
                                "description": "Optional short issue title.",
                            },
                            "bug_description": {
                                "type": "string",
                                "description": "Optional full bug description context.",
                            },
                            "actual_behaviour": {
                                "type": "string",
                                "description": "Required. What happens currently.",
                            },
                            "expected_behaviour": {
                                "type": "string",
                                "description": "Required. What should happen instead.",
                            },
                            "reproduction_steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Required. Ordered reproduction steps as list of strings.",
                            },
                            "severity": severity_schema,
                            "category": category_schema,
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": self.open_issue_council_issues_in_browser.__name__,
                    "description": (
                        "Opens issue links in browser. Default source is the latest analysis. "
                        "Root issue is opened first, then by ascending issue number."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "description": "Source for issue codes to open.",
                                "enum": ["last_analysis", "issue_codes"],
                            },
                            "issue_codes": {
                                "type": "array",
                                "description": "Required for source=issue_codes. Example: ['STARC-188247'].",
                                "items": {"type": "string"},
                            },
                        },
                    },
                },
            },
        ]

    def check_issue_council_for_known_bug(self, function_args):
        description = (function_args.get("bug_description") or "").strip()
        if len(description) < 4:
            return {
                "success": False,
                "known_bug": False,
                "instructions": "Ask the user for a more specific bug description.",
                "do_not_cache": True,
            }

        threshold = 0.42
        project_context_result = self._refresh_project_context(force=False)
        active_environments = project_context_result.get("active_environments", [])
        environment_input = function_args.get("environment")
        selected_environment = None
        if environment_input:
            if not project_context_result.get("success", False):
                return {
                    "success": False,
                    "known_bug": False,
                    "error": project_context_result.get("error"),
                    "instructions": (
                        "Project environment metadata could not be loaded. "
                        "Please refresh authentication and retry."
                    ),
                    "do_not_cache": True,
                }
            selected_environment = self._resolve_environment_filter(
                environment_input=environment_input,
                active_environments=active_environments,
            )
            if not selected_environment:
                return {
                    "success": False,
                    "known_bug": False,
                    "invalid_environment_filter": str(environment_input),
                    "available_environments": self._build_environment_options_payload(active_environments),
                    "instructions": (
                        "The provided environment filter is unknown. "
                        "Ask the user to choose one of the available active environments and retry."
                    ),
                    "do_not_cache": True,
                }

        statuses = list(self.DEFAULT_STATUSES)
        search_phrases = function_args.get("search_phrases", [])
        
        print_debug(f"IssueCouncil search terms: {search_phrases}")

        candidates_by_code = {}
        variation_runs = []
        for term in search_phrases:
            term = str(term or "").strip()
            if not term:
                continue
            self._debug_log(
                "graphql similar issues query",
                {
                    "title": term,
                    "statuses": statuses,
                    "first": self.default_search_limit,
                    "environment_filter": (selected_environment or {}).get("name"),
                },
                force_payload=True,
            )
            search_result = self._search_issues(
                search_term=term,
                statuses=statuses,
                first=self.default_search_limit,
                environment_filter=selected_environment,
            )
            variation_runs.append(
                {
                    "search_term": term,
                    "success": search_result.get("success", False),
                    "total_count": search_result.get("total_count", 0),
                    "search_backend": search_result.get("search_backend"),
                    "environment_filter": (selected_environment or {}).get("name"),
                    "error": search_result.get("error"),
                }
            )
            if not search_result.get("success", False):
                continue

            for issue_node in search_result.get("issues", []):
                code = issue_node.get("code")
                if not code:
                    continue

                summary = self._extract_issue_summary(issue_node)
                summary.setdefault("matched_terms", [])
                summary.setdefault("search_scores", [])
                summary.setdefault("search_relevance_scores", [])
                summary["matched_terms"].append(term)
                summary["search_scores"].append(summary.get("search_score", 0.0))
                summary["search_relevance_scores"].append(summary.get("search_relevance_score", 0.0))

                existing = candidates_by_code.get(code)
                if existing is None:
                    candidates_by_code[code] = summary
                else:
                    existing["matched_terms"] = self._dedupe_list(existing.get("matched_terms", []) + [term])
                    existing["search_scores"] = [*existing.get("search_scores", []), summary.get("search_score", 0.0)]
                    existing["search_relevance_scores"] = [
                        *existing.get("search_relevance_scores", []),
                        summary.get("search_relevance_score", 0.0),
                    ]
                    if summary.get("search_score", 0.0) > existing.get("search_score", 0.0):
                        existing["search_score"] = summary.get("search_score", 0.0)
                    if summary.get("search_relevance_score", 0.0) > existing.get("search_relevance_score", 0.0):
                        existing["search_relevance_score"] = summary.get("search_relevance_score", 0.0)
                    if not existing.get("title") and summary.get("title"):
                        existing["title"] = summary.get("title")

        ranked_candidates = self._rank_candidates(description, list(candidates_by_code.values()))

        if not ranked_candidates:
            return {
                "success": True,
                "known_bug": False,
                "searched_terms": search_phrases,
                "search_runs": variation_runs,
                "candidate_count": 0,
                "selected_environment_filter": self._build_environment_option(selected_environment),
                "issue_creation_suggested": True,
                "issue_creation_requirements": {
                    "requires_environment": True,
                    "required_fields": [
                        "environment",
                        "actual_behaviour",
                        "expected_behaviour",
                        "reproduction_steps",
                    ],
                    "available_environments": self._build_environment_options_payload(active_environments),
                },
                "instructions": (
                    "No matching issue was found with current filters. "
                    "Ask if the user wants to create a new Issue Council ticket. "
                    "If yes, collect environment, actual behavior, expected behavior, and reproduction steps, then call create_issue_council_issue."
                ),
                "do_not_cache": True,
            }

        llm_selection = {}
        best_candidate = ranked_candidates[0]
        best_code = best_candidate.get("code")
        if self.llm_validation_enabled:
            llm_selection = self._llm_validate_issue_candidates(
                user_description=description,
                threshold=threshold,
                ranked_candidates=ranked_candidates[: self.llm_validation_candidates],
            )
            selected_code = self._normalize_issue_code(llm_selection.get("best_issue_code"))
            if selected_code:
                selected_candidate = self._find_candidate_by_code(ranked_candidates, selected_code)
                if selected_candidate:
                    best_candidate = selected_candidate
                    best_code = selected_code
        llm_selection_active = bool(llm_selection.get("success"))

        details_by_code = {}
        review_codes = self._normalize_issue_codes((llm_selection if llm_selection_active else {}).get("review_issue_codes", []))
        detail_fetch_order = self._dedupe_list(
            [
                best_code,
                *review_codes,
                *[candidate.get("code") for candidate in ranked_candidates[: self.max_detail_fetch]],
            ]
        )
        for code in detail_fetch_order[: self.max_detail_fetch]:
            if not code:
                continue
            detail_result = self._get_issue_details(code)
            if detail_result.get("success", False) and detail_result.get("issue"):
                details_by_code[code] = detail_result["issue"]

        best_issue_detail = self._ensure_issue_detail(best_code, details_by_code)
        root_code = self._resolve_root_code(best_code, details_by_code)
        if not root_code:
            root_code = best_code
        root_issue_detail = self._ensure_issue_detail(root_code, details_by_code)

        possible_duplicates = []
        if best_issue_detail:
            possible_duplicates.extend(self._extract_possible_duplicate_entries(best_issue_detail))
        if root_issue_detail and root_code != best_code:
            possible_duplicates.extend(self._extract_possible_duplicate_entries(root_issue_detail))

        # Also include high-scoring candidates not already in confirmed hierarchy as possible variants.
        ranked_candidate_variants = []
        for candidate in ranked_candidates:
            code = candidate.get("code")
            if not code or code == best_code:
                continue
            ranked_candidate_variants.append(
                {
                    "code": code,
                    "title": candidate.get("title", ""),
                    "status": candidate.get("status"),
                    "confidence": candidate.get("confidence", 0.0),
                    "search_relevance_score": candidate.get("search_relevance_score", 0.0),
                    "source": "similar_issue_search",
                }
            )
            if len(ranked_candidate_variants) >= self.max_possible_duplicate_fetch:
                break

        llm_possible_duplicate_codes = self._normalize_issue_codes(
            (llm_selection if llm_selection_active else {}).get("possible_duplicate_codes", [])
        )
        llm_possible_duplicate_variants = []
        for code in llm_possible_duplicate_codes:
            if not code or code == best_code:
                continue
            candidate_match = self._find_candidate_by_code(ranked_candidates, code) or {}
            llm_possible_duplicate_variants.append(
                {
                    "code": code,
                    "title": candidate_match.get("title", ""),
                    "status": candidate_match.get("status"),
                    "confidence": candidate_match.get("confidence", 0.0),
                    "search_relevance_score": candidate_match.get("search_relevance_score", 0.0),
                    "source": "llm_candidate_validation",
                }
            )

        possible_duplicates = self._merge_possible_duplicates(possible_duplicates, ranked_candidate_variants)
        possible_duplicates = self._merge_possible_duplicates(possible_duplicates, llm_possible_duplicate_variants)

        # Fetch detail for linked issues that appeared as potential duplicates.
        for candidate in possible_duplicates[: self.max_possible_duplicate_fetch]:
            linked_code = candidate.get("code")
            if not linked_code:
                continue
            self._ensure_issue_detail(linked_code, details_by_code)

        duplicate_relevance_by_code = {}
        if self.llm_validation_enabled:
            duplicate_relevance_by_code = self._llm_score_duplicate_relevance(
                user_description=description,
                best_code=best_code,
                ranked_candidates=ranked_candidates,
                details_by_code=details_by_code,
            )
            possible_duplicates = self._filter_possible_duplicates_by_relevance(
                possible_duplicates=possible_duplicates,
                duplicate_relevance_by_code=duplicate_relevance_by_code,
                min_relevance=self.llm_relevance_min,
                min_duplicate_relevance=self.llm_duplicate_relevance_min,
            )

        confirmed_tree_codes = self._collect_confirmed_tree_codes(root_code, details_by_code)
        if best_code and best_code not in confirmed_tree_codes:
            confirmed_tree_codes.append(best_code)
        if root_code and root_code not in confirmed_tree_codes:
            confirmed_tree_codes.insert(0, root_code)
        confirmed_tree_codes = self._dedupe_list([code for code in confirmed_tree_codes if code])

        confirmed_tree_codes_sorted = self._sort_issue_codes(confirmed_tree_codes)
        confirmed_tree_order = [root_code] + [
            code for code in confirmed_tree_codes_sorted if code and code != root_code
        ]

        confirmed_tree_order = self._dedupe_list([code for code in confirmed_tree_order if code])

        possible_only_codes = []
        for possible in possible_duplicates:
            code = possible.get("code")
            if not code or code in confirmed_tree_order:
                continue
            possible_only_codes.append(code)
        possible_only_codes = self._sort_issue_codes(self._dedupe_list(possible_only_codes))

        browser_order = confirmed_tree_order.copy()
        browser_order_with_possible = self._dedupe_list([*confirmed_tree_order, *possible_only_codes])

        direct_duplicates_of_best = self._count_direct_duplicates_of(best_code, details_by_code)
        total_confirmed_duplicates = max(0, len([code for code in confirmed_tree_order if code != root_code]))

        hierarchy_tree = self._render_hierarchy_tree(
            root_code=root_code,
            best_code=best_code,
            details_by_code=details_by_code,
            possible_duplicates=possible_duplicates,
        )
        printr.print(hierarchy_tree, tags="info")

        heuristic_confidence = best_candidate.get("confidence", 0.0)
        llm_confidence = self._coerce_float(
            (llm_selection if llm_selection_active else {}).get("match_confidence", heuristic_confidence),
            default=heuristic_confidence,
            minimum=0.0,
            maximum=1.0,
        )
        best_confidence = llm_confidence if llm_selection_active else heuristic_confidence
        llm_known_bug = (llm_selection if llm_selection_active else {}).get("known_bug")
        known_bug = bool(llm_known_bug) if isinstance(llm_known_bug, bool) else best_confidence >= threshold

        best_details_payload = self._build_issue_payload(best_issue_detail, fallback=best_candidate)
        root_details_payload = self._build_issue_payload(root_issue_detail)
        possible_duplicates_preview = self._format_issue_code_preview(
            possible_duplicates,
            max_items=4,
        )

        best_matching_issue_payload = {
            **best_details_payload,
            "confidence": best_confidence,
            "heuristic_confidence": heuristic_confidence,
            "llm_confidence": llm_confidence if llm_selection_active else None,
            "matched_terms": best_candidate.get("matched_terms", []),
            "search_score": best_candidate.get("search_score", 0.0),
            "search_relevance_score": best_candidate.get("search_relevance_score", 0.0),
        }
        summary_payload = self._build_summary_payload_for_tts(
            player_bug_description=description,
            known_bug=known_bug,
            confidence=best_confidence,
            confidence_threshold=threshold,
            best_matching_issue=best_matching_issue_payload,
            root_issue=root_details_payload,
            direct_duplicates_of_best_issue=direct_duplicates_of_best,
            total_confirmed_duplicates_in_tree=total_confirmed_duplicates,
            possible_unmarked_duplicates=possible_duplicates,
            possible_duplicates_preview=possible_duplicates_preview,
            browser_open_order=browser_order,
        )

        result = {
            "success": True,
            "known_bug": known_bug,
            "search_runs": variation_runs,
            "selected_environment_filter": self._build_environment_option(selected_environment),
            "candidate_count": len(ranked_candidates),
            "best_matching_issue": best_matching_issue_payload,
            "top_candidates": ranked_candidates[:5],
            "duplicate_analysis": {
                "root_issue": root_details_payload,
                "root_issue_code": root_code,
                "direct_duplicates_of_best_issue": direct_duplicates_of_best,
                "total_confirmed_duplicates_in_tree": total_confirmed_duplicates,
                "possible_unmarked_duplicates_count": len(possible_only_codes),
                "possible_unmarked_duplicates": possible_duplicates,
                "llm_duplicate_relevance_by_code": duplicate_relevance_by_code,
                "llm_relevance_threshold": self.llm_relevance_min,
                "llm_duplicate_relevance_threshold": self.llm_duplicate_relevance_min,
            },
            "hierarchy_tree_console": hierarchy_tree,
            "browser_open_order": browser_order,
            "browser_open_order_with_possible_duplicates": browser_order_with_possible,
            "llm_validation": llm_selection,
            "possible_duplicates_preview": possible_duplicates_preview,
            "requires_user_confirmation_for_browser_open": True,
            "instructions": (
                "Summarize yes/no for known bug likelihood first. "
                "Then explain best matching issue and duplicate situation. "
                "If duplicate_analysis.possible_unmarked_duplicates_count > 0, explicitly summarize the content of at least two potential duplicates. "
                "Mention that browser links can be opened only after explicit user confirmation."
            ),
            "summary_payload": summary_payload,
            "do_not_cache": True,
        }

        self.last_analysis = {
            "best_issue_code": best_code,
            "root_issue_code": root_code,
            "selected_environment_filter": self._build_environment_option(selected_environment),
            "browser_open_order": browser_order,
            "browser_open_order_with_possible_duplicates": browser_order_with_possible,
            "possible_duplicates": possible_duplicates,
            "llm_validation": llm_selection,
            "hierarchy_tree_console": hierarchy_tree,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return result

    def create_issue_council_issue(self, function_args):
        project_context_result = self._refresh_project_context(force=True)
        if not project_context_result.get("success", False):
            return {
                "success": False,
                "error": project_context_result.get("error"),
                "instructions": (
                    "Project metadata could not be loaded. "
                    "Please refresh authentication and retry issue creation."
                ),
                "do_not_cache": True,
            }

        active_environments = project_context_result.get("active_environments", [])
        environment_input = function_args.get("environment")
        selected_environment = self._resolve_environment_filter(
            environment_input=environment_input,
            active_environments=active_environments,
        )
        if not selected_environment:
            return {
                "success": False,
                "missing_required_fields": ["environment"],
                "available_environments": self._build_environment_options_payload(active_environments),
                "instructions": (
                    "Issue creation requires an active environment. "
                    "Ask the user which environment should be used and call create_issue_council_issue again."
                ),
                "do_not_cache": True,
            }
        if not bool(selected_environment.get("can_open_issue")):
            return {
                "success": False,
                "selected_environment": self._build_environment_option(selected_environment),
                "available_environments": self._build_environment_options_payload(active_environments),
                "instructions": (
                    "The selected environment does not allow opening issues for the current account. "
                    "Ask the user to choose a different active environment."
                ),
                "do_not_cache": True,
            }

        release_id = selected_environment.get("current_release_id")
        if not release_id:
            return {
                "success": False,
                "selected_environment": self._build_environment_option(selected_environment),
                "instructions": (
                    "No active release deployment was found for the selected environment. "
                    "Ask the user to choose another active environment."
                ),
                "do_not_cache": True,
            }

        actual_behaviour = str(function_args.get("actual_behaviour") or "").strip()
        expected_behaviour = str(function_args.get("expected_behaviour") or "").strip()
        reproduction_steps = self._normalize_reproduction_steps(
            function_args.get("reproduction_steps")
        )

        missing_required_fields = []
        if not actual_behaviour:
            missing_required_fields.append("actual_behaviour")
        if not expected_behaviour:
            missing_required_fields.append("expected_behaviour")
        if not reproduction_steps:
            missing_required_fields.append("reproduction_steps")

        if missing_required_fields:
            return {
                "success": False,
                "missing_required_fields": missing_required_fields,
                "selected_environment": self._build_environment_option(selected_environment),
                "instructions": (
                    "Collect the missing issue details from the user and call create_issue_council_issue again. "
                    "Required details are actual behavior, expected behavior, and clear reproduction steps."
                ),
                "do_not_cache": True,
            }

        bug_description = str(function_args.get("bug_description") or "").strip()
        title = str(function_args.get("title") or "").strip()
        if not title:
            title = self._build_issue_title(
                bug_description=bug_description,
                actual_behaviour=actual_behaviour,
                expected_behaviour=expected_behaviour,
            )

        severity = self._normalize_issue_severity(function_args.get("severity"))
        category_selection = self._select_issue_category(
            category_input=function_args.get("category"),
            bug_description=bug_description,
            title=title,
            actual_behaviour=actual_behaviour,
            expected_behaviour=expected_behaviour,
            reproduction_steps=reproduction_steps,
        )
        if not category_selection:
            return {
                "success": False,
                "instructions": (
                    "Issue category could not be determined. "
                    "Please retry with more bug context or provide a category explicitly."
                ),
                "do_not_cache": True,
            }

        details_payload = {
            "title": title,
            "categoryId": category_selection.get("id"),
            "severity": severity,
            "reproductionSteps": [
                {"description": step, "evidences": []}
                for step in reproduction_steps
            ],
            "releaseId": release_id,
            "environmentId": selected_environment.get("id"),
            "projectId": self.project_id,
            "actualBehaviour": {
                "description": actual_behaviour,
                "evidences": [],
            },
            "expectedBehaviour": {
                "description": expected_behaviour,
                "evidences": [],
            },
            "additionalEvidences": [],
        }
        system_configuration_id = self._get_suggested_system_configuration_id(force=False)
        if system_configuration_id:
            details_payload["systemConfigurationId"] = system_configuration_id

        software_configuration_id = str(
            function_args.get("software_configuration_id") or ""
        ).strip()
        if software_configuration_id:
            details_payload["softwareConfigurationId"] = software_configuration_id

        request_result = self._request_graphql(
            self.OPEN_ISSUE_MUTATION,
            {"input": {"details": details_payload}},
        )
        if not request_result.get("success", False):
            return request_result

        open_issue = self._as_dict(
            self._as_dict(request_result.get("data")).get("openIssue")
        )
        issue_payload = self._as_dict(open_issue.get("issue"))
        created_issue_code = self._normalize_issue_code(issue_payload.get("code"))
        created_success = bool(open_issue.get("success")) and bool(created_issue_code)
        if not created_success:
            return {
                "success": False,
                "error": open_issue.get("message") or "Issue creation failed.",
                "problem": self._extract_problem_payload(open_issue.get("problem")),
                "selected_environment": self._build_environment_option(selected_environment),
                "selected_category": {
                    "id": category_selection.get("id"),
                    "code": category_selection.get("code"),
                    "name": category_selection.get("name"),
                },
                "instructions": (
                    "Issue could not be created. Summarize the validation error and ask the user for the missing or corrected data."
                ),
                "do_not_cache": True,
            }

        issue_url = self._issue_url_for_code(created_issue_code)
        was_opened = webbrowser.open(issue_url, new=2)
        self._debug_log(
            "created issue",
            {
                "code": created_issue_code,
                "url": issue_url,
                "opened_browser": bool(was_opened),
                "environment": selected_environment.get("name"),
                "release_version": selected_environment.get("current_release_version"),
            },
        )

        return {
            "success": True,
            "issue_created": True,
            "created_issue_code": created_issue_code,
            "created_issue_url": issue_url,
            "browser_opened": bool(was_opened),
            "selected_environment": self._build_environment_option(selected_environment),
            "selected_category": {
                "id": category_selection.get("id"),
                "code": category_selection.get("code"),
                "name": category_selection.get("name"),
            },
            "release_version": selected_environment.get("current_release_version"),
            "instructions": (
                "Confirm that the issue was created and opened in the browser so the user can add evidence and manual corrections."
            ),
            "do_not_cache": True,
        }

    def open_issue_council_issues_in_browser(self, function_args):
        source = function_args.get("source", "last_analysis")

        codes_to_open = []
        if source == "last_analysis":
            if not self.last_analysis:
                return {
                    "success": False,
                    "instructions": (
                        "No prior issue analysis available. Run check_issue_council_for_known_bug first."
                    ),
                    "do_not_cache": True,
                }
            codes_to_open = self.last_analysis.get("browser_open_order_with_possible_duplicates", [])
            if not codes_to_open:
                codes_to_open = self.last_analysis.get("browser_open_order", [])
        elif source == "issue_codes":
            issue_codes = self._normalize_issue_codes(function_args.get("issue_codes", []))
            if not issue_codes:
                return {
                    "success": False,
                    "instructions": "Please provide at least one valid issue code like STARC-188247.",
                    "do_not_cache": True,
                }
            codes_to_open = self._build_browser_order_from_explicit_codes(issue_codes)
            if (
                self.last_analysis
                and len(codes_to_open) == 1
                and codes_to_open[0]
                in {
                    self.last_analysis.get("best_issue_code"),
                    self.last_analysis.get("root_issue_code"),
                }
            ):
                # If model only requested the best/root issue implicitly, expand with known variants.
                codes_to_open = self.last_analysis.get("browser_open_order_with_possible_duplicates", codes_to_open)
        else:
            return {
                "success": False,
                "instructions": "Invalid source. Use source=last_analysis or source=issue_codes.",
                "do_not_cache": True,
            }

        if source == "last_analysis" and len(codes_to_open) <= 1 and self.last_analysis:
            possible_variant_codes = self._sort_issue_codes(
                [
                    entry.get("code")
                    for entry in self.last_analysis.get("possible_duplicates", [])
                    if isinstance(entry, dict)
                ]
            )
            if possible_variant_codes:
                codes_to_open = self._dedupe_list([*codes_to_open, *possible_variant_codes])

        codes_to_open = self._dedupe_list(self._normalize_issue_codes(codes_to_open))[
            : self.DEFAULT_MAX_BROWSER_OPEN_TABS
        ]
        if not codes_to_open:
            return {
                "success": False,
                "instructions": "No issue codes available to open.",
                "do_not_cache": True,
            }

        opened = []
        for code in codes_to_open:
            issue_url = self._issue_url_for_code(code)
            was_opened = webbrowser.open(issue_url, new=2)
            opened.append({"code": code, "url": issue_url, "opened": bool(was_opened)})
        self._debug_log(
            "browser open sequence",
            {
                "source": source,
                "requested_codes": codes_to_open,
                "max_open_tabs": self.DEFAULT_MAX_BROWSER_OPEN_TABS,
                "opened_count": len([entry for entry in opened if entry.get("opened")]),
            },
        )

        successful_opens = len([entry for entry in opened if entry.get("opened")])
        return {
            "success": successful_opens > 0,
            "requested_tabs": len(codes_to_open),
            "opened_tabs": successful_opens,
            "open_sequence": codes_to_open,
            "opened": opened,
            "instructions": (
                "Confirm only, that the issue tabs were opened."
            ),
            "do_not_cache": True,
        }

    def _search_issues(
        self,
        search_term: str,
        statuses: list[str],
        first: int,
        environment_filter: dict | None = None,
    ):
        similar_result = self._search_similar_issues(
            search_term=search_term,
            first=first,
            environment_filter=environment_filter,
        )
        if similar_result.get("success", False):
            return similar_result

        filtered_result = self._search_issues_fallback_filtered(
            search_term=search_term,
            statuses=statuses,
            first=first,
            environment_filter=environment_filter,
        )
        if not filtered_result.get("success", False):
            similar_error = str(similar_result.get("error", "")).strip()
            fallback_error = str(filtered_result.get("error", "")).strip()
            if similar_error and fallback_error:
                filtered_result["error"] = (
                    f"similarIssues failed: {similar_error}. "
                    f"filteredIssues fallback failed: {fallback_error}"
                )
        else:
            filtered_result["fallback_from_similar_error"] = similar_result.get("error")
        return filtered_result

    def _search_similar_issues(
        self,
        search_term: str,
        first: int,
        environment_filter: dict | None = None,
    ):
        variables = {
            "query": {
                "projectIds": [self.project_id],
                "paging": {"first": first},
                "similarIssue": {
                    "title": search_term,
                    "severity": None,
                },
            }
        }
        request_result = self._request_graphql(self.SIMILAR_ISSUES_QUERY, variables)
        if not request_result.get("success", False):
            return request_result

        data = request_result.get("data", {})
        similar_issues = data.get("similarIssues", {}) if isinstance(data, dict) else {}
        edges = similar_issues.get("edges", []) if isinstance(similar_issues, dict) else []
        issues = []
        for edge in edges:
            node = edge.get("node", {}) if isinstance(edge, dict) else {}
            if node:
                issues.append(node)

        issues = self._filter_issues_by_environment(issues, environment_filter)
        return {
            "success": True,
            "issues": issues,
            "total_count": len(issues),
            "search_backend": "similarIssues",
            "do_not_cache": True,
        }

    def _search_issues_fallback_filtered(
        self,
        search_term: str,
        statuses: list[str],
        first: int,
        environment_filter: dict | None = None,
    ):
        environment_ids = (
            [environment_filter.get("id")]
            if isinstance(environment_filter, dict) and environment_filter.get("id")
            else []
        )
        variables = {
            "filteredQuery": {
                "projectIds": [self.project_id],
                "text": search_term,
                "statuses": statuses,
                "severities": [],
                "categoryIds": [],
                "releaseIds": [],
                "environmentIds": environment_ids,
                "dateRanges": [],
                "sortBy": {
                    "direction": "DESC",
                    "field": "RELEVANCE",
                },
                "paging": {"first": first},
                "placePromotedIssuesFirst": True,
                "tags": [],
            }
        }
        request_result = self._request_graphql(self.FILTERED_ISSUES_FALLBACK_QUERY, variables)
        if not request_result.get("success", False):
            return request_result

        data = request_result.get("data", {})
        filtered_issues = data.get("filteredIssues", {}) if isinstance(data, dict) else {}
        edges = filtered_issues.get("edges", []) if isinstance(filtered_issues, dict) else []
        issues = []
        for edge in edges:
            node = edge.get("node", {}) if isinstance(edge, dict) else {}
            if node:
                issues.append(node)

        issues = self._filter_issues_by_environment(issues, environment_filter)
        return {
            "success": True,
            "issues": issues,
            "total_count": len(issues),
            "search_backend": "filteredIssues_fallback",
            "do_not_cache": True,
        }

    def _get_issue_details(self, code: str):
        code = self._normalize_issue_code(code)
        if not code:
            return {"success": False, "error": "Invalid issue code.", "do_not_cache": True}

        request_result = self._request_graphql(self.ISSUE_DETAILS_QUERY, {"code": code})
        if not request_result.get("success", False):
            return request_result

        issue = request_result.get("data", {}).get("issueByCode") if isinstance(request_result.get("data"), dict) else None
        if not issue:
            return {"success": False, "error": f"Issue {code} not found.", "do_not_cache": True}
        return {"success": True, "issue": issue, "do_not_cache": True}

    def _request_graphql(self, query: str, variables: dict):
        payload = {"query": query, "variables": variables}
        if not self.bearer_token:
            self._attempt_auto_token_capture(reason="missing_token")

        headers = self._build_request_headers()
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.request_timeout_seconds,
                headers=headers,
            )
            if response.status_code in [401, 403]:
                # Retry once after reloading token from dynamic sources in case token rotated while app was running.
                self._load_bearer_token_from_sources(allow_file=True, force_reload=True)
                if not self._attempt_auto_token_capture(reason=f"http_{response.status_code}"):
                    print_debug("Automatic token capture did not provide a fresh token.")
                headers = self._build_request_headers()
                response = requests.post(
                    self.api_url,
                    json=payload,
                    timeout=self.request_timeout_seconds,
                    headers=headers,
                )

            if response.status_code in [401, 403]:
                return {
                    "success": False,
                    "auth_required": True,
                    "error": self._build_auth_error_message(status_code=response.status_code),
                    "do_not_cache": True
                }

            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            return {"success": False, "error": f"Issue Council request failed: {error}", "do_not_cache": True}
        except ValueError as error:
            return {"success": False, "error": f"Issue Council response parse failed: {error}", "do_not_cache": True}

        errors = payload.get("errors", [])
        if errors:
            message = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
            return {"success": False, "error": f"Issue Council GraphQL error: {message}", "do_not_cache": True}
        return {"success": True, "data": payload.get("data", {}), "do_not_cache": True}

    def _refresh_project_context(self, force: bool = False):
        now = time.time()
        if (
            not force
            and self.project_context
            and (now - self.project_context_loaded_at) < self.project_context_refresh_seconds
        ):
            return {
                "success": True,
                "project": self.project_context.get("project", {}),
                "active_environments": self.project_context.get("active_environments", []),
                "do_not_cache": True,
            }

        variables = {
            "code": self.project_code,
            "environmentQueryInput": {
                "name": "",
                "sortBy": {"field": "SCHEDULE_OPENING_ON", "direction": "DESC"},
                "statuses": ["OPEN"],
                "includeIdsInResult": [],
                "paging": {"first": 50},
            },
            "releaseDeploymentQueryInput": {
                "statuses": ["ACTIVE"],
                "sortBy": {"field": "RELEASE_CREATED_ON", "direction": "DESC"},
                "paging": {"first": 100},
            },
        }
        request_result = self._request_graphql(self.PROJECT_DETAILS_QUERY, variables)
        if not request_result.get("success", False):
            return request_result

        project = self._as_dict(self._as_dict(request_result.get("data")).get("projectByCode"))
        if not project:
            return {
                "success": False,
                "error": f"Project not found for code {self.project_code}.",
                "do_not_cache": True,
            }

        environments = []
        environments_node = self._as_dict(project.get("environments"))
        for edge in environments_node.get("edges", []):
            node = self._as_dict(self._as_dict(edge).get("node"))
            if not node:
                continue
            deployment = self._select_current_deployment(
                self._as_dict(node.get("deployments"))
            )
            release = self._as_dict(self._as_dict(deployment).get("release"))
            version = self._as_dict(release.get("version"))
            viewer_props = self._as_dict(node.get("viewerProperties"))
            environments.append(
                {
                    "id": node.get("id"),
                    "code": node.get("code"),
                    "name": node.get("name"),
                    "status": node.get("status"),
                    "can_open_issue": bool(viewer_props.get("canOpenIssue")),
                    "can_post_contribution": bool(viewer_props.get("canPostContribution")),
                    "current_deployment_id": deployment.get("id"),
                    "current_release_id": release.get("id"),
                    "current_release_code": release.get("code"),
                    "current_release_version": version.get("code"),
                    "current_deployment_status": deployment.get("status"),
                    "current_deployment_completed_on": deployment.get("completedOn"),
                }
            )

        environments.sort(key=lambda env: str(env.get("name") or ""))
        self.project_context = {
            "project": {
                "id": project.get("id"),
                "code": project.get("code"),
                "name": project.get("name"),
            },
            "active_environments": environments,
        }
        self.project_context_loaded_at = now
        return {
            "success": True,
            "project": self.project_context.get("project", {}),
            "active_environments": environments,
            "do_not_cache": True,
        }

    def _select_current_deployment(self, deployments_node: dict):
        deployments_node = self._as_dict(deployments_node)
        deployment_nodes = []
        for edge in deployments_node.get("edges", []):
            node = self._as_dict(self._as_dict(edge).get("node"))
            if node:
                deployment_nodes.append(node)
        if not deployment_nodes:
            return {}

        for deployment in deployment_nodes:
            if bool(deployment.get("isCurrent")):
                return deployment
        for deployment in deployment_nodes:
            if str(deployment.get("status", "")).upper() == "ACTIVE":
                return deployment
        return deployment_nodes[0]

    def _resolve_environment_filter(self, environment_input, active_environments: list[dict]):
        token = self._normalize_match_token(environment_input)
        if not token:
            return None

        exact_matches = []
        partial_matches = []
        for environment in active_environments:
            env = self._as_dict(environment)
            env_id = self._normalize_match_token(env.get("id"))
            env_code = self._normalize_match_token(env.get("code"))
            env_name = self._normalize_match_token(env.get("name"))
            env_release_version = self._normalize_match_token(env.get("current_release_version"))
            haystack = [env_id, env_code, env_name, env_release_version]
            if token in [item for item in haystack if item]:
                exact_matches.append(env)
                continue
            if any(token in item for item in haystack if item):
                partial_matches.append(env)

        if exact_matches:
            return exact_matches[0]
        if partial_matches:
            return partial_matches[0]
        return None

    def _filter_issues_by_environment(
        self,
        issues: list[dict],
        environment_filter: dict | None,
    ):
        if not environment_filter:
            return issues

        target_id = self._normalize_match_token(environment_filter.get("id"))
        target_code = self._normalize_match_token(environment_filter.get("code"))
        target_name = self._normalize_match_token(environment_filter.get("name"))
        if not any([target_id, target_code, target_name]):
            return issues

        filtered_issues = []
        for issue in issues:
            issue_details = self._as_dict(self._as_dict(issue).get("details"))
            issue_env = self._as_dict(issue_details.get("environment"))
            issue_env_id = self._normalize_match_token(issue_env.get("id"))
            issue_env_code = self._normalize_match_token(issue_env.get("code"))
            issue_env_name = self._normalize_match_token(issue_env.get("name"))

            id_match = bool(target_id and issue_env_id and target_id == issue_env_id)
            code_match = bool(target_code and issue_env_code and target_code == issue_env_code)
            name_match = bool(target_name and issue_env_name and target_name in issue_env_name)
            if id_match or code_match or name_match:
                filtered_issues.append(issue)
        return filtered_issues

    def _build_environment_option(self, environment: dict | None):
        environment = self._as_dict(environment)
        if not environment:
            return None
        return {
            "id": environment.get("id"),
            "code": environment.get("code"),
            "name": environment.get("name"),
            "current_release_version": environment.get("current_release_version"),
            "current_release_id": environment.get("current_release_id"),
            "can_open_issue": bool(environment.get("can_open_issue")),
        }

    def _build_environment_options_payload(self, environments: list[dict]):
        options = []
        for environment in environments:
            option = self._build_environment_option(environment)
            if option:
                options.append(option)
        return options

    def _get_available_environment_names_for_tool_schema(self):
        environment_names = []
        project_context_result = self._refresh_project_context(force=False)
        environments = []
        if project_context_result.get("success", False):
            environments = project_context_result.get("active_environments", [])
        elif self.project_context:
            environments = self.project_context.get("active_environments", [])

        for environment in environments:
            name = str(self._as_dict(environment).get("name") or "").strip()
            if name:
                environment_names.append(name)
        environment_names = self._dedupe_list(environment_names)
        environment_names.sort()
        return environment_names

    def _build_environment_param_schema(self, required: bool):
        environment_names = self._get_available_environment_names_for_tool_schema()
        if required:
            description = (
                "Required. Environment name where the issue occurs. "
                "Use one of the enum values."
            )
        else:
            description = (
                "Optional environment name filter. "
                "Default is no environment restriction."
            )
        schema = {
            "type": "string",
            "description": description,
        }
        if environment_names:
            schema["enum"] = environment_names
        return schema

    def _build_severity_param_schema(self):
        allowed_values = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        return {
            "type": "string",
            "description": "Optional issue severity. Use one of the enum values. Default is MEDIUM.",
            "enum": allowed_values,
        }

    def _get_available_category_names_for_tool_schema(self):
        category_names = []
        categories_result = self._get_issue_categories(force=False)
        categories = []
        if categories_result.get("success", False):
            categories = categories_result.get("categories", [])
        elif self.issue_categories:
            categories = self.issue_categories

        for category in categories:
            name = str(self._as_dict(category).get("name") or "").strip()
            if name:
                category_names.append(name)
        category_names = self._dedupe_list(category_names)
        category_names.sort()
        return category_names

    def _build_category_param_schema(self):
        category_names = self._get_available_category_names_for_tool_schema()
        schema = {
            "type": "string",
            "description": (
                "Optional issue category name. Use one of the enum values. "
                "If omitted, the manager auto-selects the best category."
            ),
        }
        if category_names:
            schema["enum"] = category_names
        return schema

    def _build_issue_title(
        self,
        bug_description: str,
        actual_behaviour: str,
        expected_behaviour: str,
    ):
        candidate = str(bug_description or "").strip()
        if not candidate:
            candidate = str(actual_behaviour or "").strip()
        if not candidate:
            candidate = str(expected_behaviour or "").strip()
        candidate = " ".join(candidate.split()).strip()
        if not candidate:
            return "Issue report created by Wingman"
        if len(candidate) > 110:
            candidate = f"{candidate[:110].rstrip()}..."
        return candidate

    def _normalize_reproduction_steps(self, raw_steps):
        steps = []
        if isinstance(raw_steps, str):
            for line in raw_steps.replace("\r", "\n").split("\n"):
                line = line.strip(" -\t")
                if line:
                    steps.append(line)
        elif isinstance(raw_steps, list):
            for entry in raw_steps:
                text = str(entry or "").strip(" -\t")
                if text:
                    steps.append(text)
        return self._dedupe_list(steps)

    def _normalize_issue_severity(self, severity_value):
        normalized = str(severity_value or self.DEFAULT_ISSUE_SEVERITY).strip().upper()
        if normalized in self.ALLOWED_ISSUE_SEVERITIES:
            return normalized
        return self.DEFAULT_ISSUE_SEVERITY

    def _get_issue_categories(self, force: bool = False):
        now = time.time()
        if (
            not force
            and self.issue_categories
            and (now - self.issue_categories_loaded_at) < self.project_context_refresh_seconds
        ):
            return {"success": True, "categories": self.issue_categories, "do_not_cache": True}

        variables = {
            "projectId": self.project_id,
            "query": {
                "name": "",
                "statuses": ["ACTIVE"],
                "includeIdsInResult": [],
                "sortBy": {"field": "NAME", "direction": "ASC"},
                "paging": {"first": 100},
            },
        }
        request_result = self._request_graphql(self.ISSUE_CATEGORIES_QUERY, variables)
        if not request_result.get("success", False):
            return request_result

        categories = []
        project_node = self._as_dict(self._as_dict(request_result.get("data")).get("project"))
        issue_categories = self._as_dict(project_node.get("issueCategories"))
        for edge in issue_categories.get("edges", []):
            node = self._as_dict(self._as_dict(edge).get("node"))
            stats = self._as_dict(node.get("statistics"))
            if not node:
                continue
            categories.append(
                {
                    "id": node.get("id"),
                    "code": node.get("code"),
                    "name": node.get("name"),
                    "status": node.get("status"),
                    "issue_count": self._coerce_int(
                        stats.get("issueCount", 0),
                        default=0,
                        minimum=0,
                        maximum=99999999,
                    ),
                }
            )

        self.issue_categories = categories
        self.issue_categories_loaded_at = now
        return {"success": True, "categories": categories, "do_not_cache": True}

    def _select_issue_category(
        self,
        category_input,
        bug_description: str,
        title: str,
        actual_behaviour: str,
        expected_behaviour: str,
        reproduction_steps: list[str],
    ):
        categories_result = self._get_issue_categories(force=False)
        if not categories_result.get("success", False):
            return None
        categories = categories_result.get("categories", [])
        if not categories:
            return None

        explicit_match = self._resolve_issue_category(category_input, categories)
        if explicit_match:
            return explicit_match

        llm_selection = self._llm_select_issue_category(
            categories=categories,
            bug_description=bug_description,
            title=title,
            actual_behaviour=actual_behaviour,
            expected_behaviour=expected_behaviour,
            reproduction_steps=reproduction_steps,
        )
        if llm_selection:
            return llm_selection

        for category in categories:
            if self._normalize_match_token(category.get("code")) == "general-ui":
                return category
        return max(categories, key=lambda item: item.get("issue_count", 0))

    def _resolve_issue_category(self, category_input, categories: list[dict]):
        token = self._normalize_match_token(category_input)
        if not token:
            return None
        exact_matches = []
        partial_matches = []
        for category in categories:
            category_id = self._normalize_match_token(category.get("id"))
            category_code = self._normalize_match_token(category.get("code"))
            category_name = self._normalize_match_token(category.get("name"))
            haystack = [category_id, category_code, category_name]
            if token in [item for item in haystack if item]:
                exact_matches.append(category)
                continue
            if any(token in item for item in haystack if item):
                partial_matches.append(category)
        if exact_matches:
            return exact_matches[0]
        if partial_matches:
            return partial_matches[0]
        return None

    def _llm_select_issue_category(
        self,
        categories: list[dict],
        bug_description: str,
        title: str,
        actual_behaviour: str,
        expected_behaviour: str,
        reproduction_steps: list[str],
    ):
        category_payload = [
            {
                "id": category.get("id"),
                "code": category.get("code"),
                "name": category.get("name"),
                "issue_count": category.get("issue_count", 0),
            }
            for category in categories
            if category.get("id")
        ]
        if not category_payload:
            return None

        payload = {
            "bug_report": {
                "title": title,
                "bug_description": bug_description,
                "actual_behaviour": actual_behaviour,
                "expected_behaviour": expected_behaviour,
                "reproduction_steps": reproduction_steps[:8],
            },
            "categories": category_payload,
        }
        completion = self.ask_ai(
            self.LLM_CATEGORY_SELECTION_SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=min(800, self.llm_max_tokens),
            temperature=min(0.2, self.llm_temperature),
            response_format={"type": "json_object"},
            llm_call="issue_category_selection",
        )
        parsed = self._extract_json_object_from_completion(completion)
        if not isinstance(parsed, dict):
            return None
        category_id = str(parsed.get("category_id") or "").strip()
        if not category_id:
            return None
        return self._resolve_issue_category(category_id, categories)

    def _get_suggested_system_configuration_id(self, force: bool = False):
        now = time.time()
        if (
            not force
            and self.cached_system_configuration_loaded_at
            and (now - self.cached_system_configuration_loaded_at)
            < self.project_context_refresh_seconds
        ):
            return self.cached_system_configuration_id

        variables = {"query": {"supportedByProjectId": self.project_id}}
        request_result = self._request_graphql(
            self.SUGGESTED_SYSTEM_CONFIGURATION_QUERY,
            variables,
        )
        self.cached_system_configuration_loaded_at = now
        if not request_result.get("success", False):
            return None
        viewer = self._as_dict(self._as_dict(request_result.get("data")).get("viewer"))
        config = self._as_dict(viewer.get("suggestedSystemConfiguration"))
        self.cached_system_configuration_id = config.get("id")
        return self.cached_system_configuration_id

    def _extract_problem_payload(self, problem):
        problem = self._as_dict(problem)
        payload = {
            "type": problem.get("type"),
            "title": problem.get("title"),
            "status": problem.get("status"),
            "help": problem.get("help"),
            "validation_errors": [],
        }
        data = self._as_dict(problem.get("data"))
        validation_errors = self._as_dict(data).get("errors", [])
        for entry in validation_errors:
            entry = self._as_dict(entry)
            payload["validation_errors"].append(
                {
                    "field": entry.get("field"),
                    "code": entry.get("code"),
                    "message": entry.get("message"),
                    "help": entry.get("help"),
                }
            )
        return payload

    @staticmethod
    def _normalize_match_token(value):
        normalized = str(value or "").strip().lower()
        normalized = normalized.replace("_", "-")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _extract_issue_summary(self, issue_node: dict):
        issue_node = self._as_dict(issue_node)
        details = self._as_dict(issue_node.get("details"))
        community = self._as_dict(issue_node.get("community"))
        search_info = self._as_dict(issue_node.get("search"))
        open_details = self._as_dict(issue_node.get("openDetails"))
        archived_details = self._as_dict(issue_node.get("archivedDetails"))
        details_environment = self._as_dict(details.get("environment"))
        duplicate_of = self._as_dict(archived_details.get("duplicateOf"))
        highlights = search_info.get("highlights", []) if isinstance(search_info, dict) else []

        flattened_matches = []
        for highlight in highlights:
            for match in highlight.get("matches", []):
                cleaned = re.sub(r"</?[^>]+>", "", str(match)).strip()
                if cleaned:
                    flattened_matches.append(cleaned)

        return {
            "code": issue_node.get("code"),
            "status": issue_node.get("status"),
            "title": details.get("title", ""),
            "severity": details.get("severity"),
            "environment_id": details_environment.get("id"),
            "environment_code": details_environment.get("code"),
            "environment_name": details_environment.get("name"),
            "opened_on": open_details.get("openedOn"),
            "reproduction_count": community.get("reproductionCount", 0),
            "contribution_count": community.get("contributionCount", 0),
            "vote_count": community.get("voteCount", 0),
            "search_score": self._coerce_float(search_info.get("score", 0.0), default=0.0, minimum=0.0, maximum=100000.0),
            "search_relevance_score": self._coerce_float(search_info.get("relevanceScore", 0.0), default=0.0, minimum=0.0, maximum=1.0),
            "highlight_matches": flattened_matches,
            "duplicate_of_code": duplicate_of.get("code"),
        }

    def _rank_candidates(self, user_description: str, candidates: list[dict]):
        if not candidates:
            return []

        max_search_score = max((candidate.get("search_score", 0.0) for candidate in candidates), default=1.0)
        if max_search_score <= 0:
            max_search_score = 1.0

        ranked = []
        normalized_description = (user_description or "").lower()

        for candidate in candidates:
            title = candidate.get("title", "") or ""
            highlights = " ".join(candidate.get("highlight_matches", []))
            composite_text = f"{title} {highlights}".strip().lower()
            textual_similarity = SequenceMatcher(None, normalized_description, composite_text).ratio()
            normalized_search_score = candidate.get("search_score", 0.0) / max_search_score
            relevance_score = self._coerce_float(
                candidate.get("search_relevance_score", 0.0),
                default=0.0,
                minimum=0.0,
                maximum=1.0,
            )
            reproduction_count = self._coerce_float(candidate.get("reproduction_count", 0), default=0.0, minimum=0.0, maximum=2000.0)
            reproduction_bonus = min(1.0, reproduction_count / 100.0)
            confidence = round(
                (textual_similarity * 0.47)
                + (normalized_search_score * 0.28)
                + (relevance_score * 0.15)
                + (reproduction_bonus * 0.10),
                4,
            )

            ranked.append(
                {
                    **candidate,
                    "text_similarity": round(textual_similarity, 4),
                    "confidence": confidence,
                    "matched_terms": self._dedupe_list(candidate.get("matched_terms", [])),
                }
            )

        ranked.sort(
            key=lambda issue: (
                issue.get("confidence", 0.0),
                issue.get("search_score", 0.0),
                issue.get("reproduction_count", 0),
            ),
            reverse=True,
        )
        return ranked

    def _llm_validate_issue_candidates(self, user_description: str, threshold: float, ranked_candidates: list[dict]):
        if not ranked_candidates:
            return {}

        candidate_payload = []
        allowed_codes = set()
        for candidate in ranked_candidates:
            code = self._normalize_issue_code(candidate.get("code"))
            if not code:
                continue
            allowed_codes.add(code)
            candidate_payload.append(
                {
                    "code": code,
                    "title": candidate.get("title"),
                    "status": candidate.get("status"),
                    "severity": candidate.get("severity"),
                    "environment_name": candidate.get("environment_name"),
                    "search_score": candidate.get("search_score", 0.0),
                    "search_relevance_score": candidate.get("search_relevance_score", 0.0),
                    "heuristic_confidence": candidate.get("confidence", 0.0),
                    "reproduction_count": candidate.get("reproduction_count", 0),
                    "matched_terms": candidate.get("matched_terms", []),
                    "highlight_matches": candidate.get("highlight_matches", [])[:6],
                }
            )

        if not candidate_payload:
            return {}

        user_payload = {
            "player_bug_description": user_description,
            "known_bug_confidence_threshold": threshold,
            "candidate_issues": candidate_payload,
        }
        self._debug_log("llm validates issue candidates request", user_payload)
        completion = self.ask_ai(
            self.LLM_SELECTION_SYSTEM_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            max_tokens=self.llm_max_tokens,
            temperature=self.llm_temperature,
            response_format={"type": "json_object"},
            llm_call="issue_candidate_selection",
        )
        parsed = self._extract_json_object_from_completion(completion)
        self._debug_log("llm validates issue candidates response", parsed)
        if not isinstance(parsed, dict):
            return {"success": False, "error": "Could not parse LLM candidate selection response.", "do_not_cache": True}

        best_issue_code = self._normalize_issue_code(parsed.get("best_issue_code"))
        if best_issue_code and best_issue_code not in allowed_codes:
            best_issue_code = None

        review_codes = [
            code
            for code in self._normalize_issue_codes(parsed.get("review_issue_codes", []))
            if code in allowed_codes
        ]
        possible_duplicate_codes = [
            code
            for code in self._normalize_issue_codes(parsed.get("possible_duplicate_codes", []))
            if code in allowed_codes
        ]

        return {
            "success": True,
            "best_issue_code": best_issue_code,
            "known_bug": parsed.get("known_bug"),
            "match_confidence": self._coerce_float(
                parsed.get("match_confidence", 0.0),
                default=0.0,
                minimum=0.0,
                maximum=1.0,
            ),
            "reasoning_short": str(parsed.get("reasoning_short", "")).strip(),
            "review_issue_codes": review_codes,
            "possible_duplicate_codes": possible_duplicate_codes,
            "missing_information": parsed.get("missing_information", []),
            "do_not_cache": True,
        }

    def _llm_score_duplicate_relevance(
        self,
        user_description: str,
        best_code: str,
        ranked_candidates: list[dict],
        details_by_code: dict,
    ):
        candidate_payload = []
        allowed_codes = set()
        for candidate in ranked_candidates[: self.llm_duplicate_review_candidates]:
            code = self._normalize_issue_code(candidate.get("code"))
            if not code or code == best_code:
                continue
            issue_detail = details_by_code.get(code)
            candidate_payload.append(
                self._build_issue_context_for_llm(
                    code=code,
                    candidate=candidate,
                    issue_detail=issue_detail,
                )
            )
            allowed_codes.add(code)

        if not candidate_payload:
            return {}

        user_payload = {
            "player_bug_description": user_description,
            "best_issue_code": best_code,
            "candidates": candidate_payload,
        }
        self._debug_log("llm duplicate relevance request", user_payload)
        completion = self.ask_ai(
            self.LLM_DUPLICATE_REVIEW_SYSTEM_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            max_tokens=self.llm_max_tokens,
            temperature=self.llm_temperature,
            response_format={"type": "json_object"},
            llm_call="duplicate_relevance_scoring",
        )
        parsed = self._extract_json_object_from_completion(completion)
        self._debug_log("llm duplicate relevance response", parsed)
        if not isinstance(parsed, dict):
            return {}

        evaluations = parsed.get("evaluations", [])
        if not isinstance(evaluations, list):
            return {}

        scores_by_code = {}
        for entry in evaluations:
            entry = self._as_dict(entry)
            code = self._normalize_issue_code(entry.get("code"))
            if not code or code not in allowed_codes:
                continue
            scores_by_code[code] = {
                "relevance_score": self._coerce_float(
                    entry.get("relevance_score", 0.0),
                    default=0.0,
                    minimum=0.0,
                    maximum=1.0,
                ),
                "duplicate_relevance_score": self._coerce_float(
                    entry.get("duplicate_relevance_score", 0.0),
                    default=0.0,
                    minimum=0.0,
                    maximum=1.0,
                ),
                "is_relevant": bool(entry.get("is_relevant", False)),
                "possible_duplicate": bool(entry.get("possible_duplicate", False)),
                "reasoning_short": str(entry.get("reasoning_short", "")).strip(),
            }
        return scores_by_code

    def _build_issue_context_for_llm(self, code: str, candidate: dict, issue_detail: dict):
        candidate = self._as_dict(candidate)
        issue_detail = self._as_dict(issue_detail)
        details = self._as_dict(issue_detail.get("details"))
        steps = self._as_dict(details.get("reproductionSteps"))
        actual = self._as_dict(details.get("actualBehaviour"))
        expected = self._as_dict(details.get("expectedBehaviour"))
        workaround = self._as_dict(details.get("workaround"))
        category = self._as_dict(details.get("category"))
        environment = self._as_dict(details.get("environment"))

        title = details.get("title") or candidate.get("title") or ""
        status = issue_detail.get("status") or candidate.get("status")
        severity = details.get("severity") or candidate.get("severity")
        environment_name = environment.get("name") or candidate.get("environment_name")
        summary = {
            "code": code,
            "title": title,
            "status": status,
            "severity": severity,
            "environment_name": environment_name,
            "category_name": category.get("name"),
            "heuristic_confidence": candidate.get("confidence", 0.0),
            "search_score": candidate.get("search_score", 0.0),
            "search_relevance_score": candidate.get("search_relevance_score", 0.0),
            "reproduction_count": candidate.get("reproduction_count", 0),
            "actual_behaviour": self._truncate_text(actual.get("description"), self.llm_detail_char_limit),
            "expected_behaviour": self._truncate_text(expected.get("description"), self.llm_detail_char_limit),
            "reproduction_steps": self._truncate_text(steps.get("description"), self.llm_detail_char_limit),
            "workaround": self._truncate_text(workaround.get("description"), self.llm_detail_char_limit),
        }
        return summary

    def _filter_possible_duplicates_by_relevance(
        self,
        possible_duplicates: list[dict],
        duplicate_relevance_by_code: dict,
        min_relevance: float,
        min_duplicate_relevance: float,
    ):
        filtered = []
        for entry in possible_duplicates:
            entry = self._as_dict(entry).copy()
            code = self._normalize_issue_code(entry.get("code"))
            if not code:
                continue
            score = self._as_dict(duplicate_relevance_by_code.get(code))
            if score:
                entry["relevance_score"] = score.get("relevance_score", 0.0)
                entry["duplicate_relevance_score"] = score.get("duplicate_relevance_score", 0.0)
                entry["llm_reasoning"] = score.get("reasoning_short", "")
                include = (
                    entry["relevance_score"] >= min_relevance
                    and entry["duplicate_relevance_score"] >= min_duplicate_relevance
                ) or bool(score.get("possible_duplicate", False))
                if not include:
                    continue
            else:
                # Keep only entries with a real duplicate signal if we have no LLM score.
                duplicate_signal = self._coerce_int(
                    entry.get("duplicate_count_signal", 0),
                    default=0,
                    minimum=0,
                    maximum=99999,
                )
                if duplicate_signal <= 0:
                    continue
            filtered.append(entry)

        filtered.sort(
            key=lambda item: (
                item.get("duplicate_relevance_score", 0.0),
                item.get("relevance_score", 0.0),
                item.get("duplicate_count_signal", 0),
                item.get("confidence", 0.0),
            ),
            reverse=True,
        )
        return filtered

    @staticmethod
    def _find_candidate_by_code(candidates: list[dict], code: str):
        for candidate in candidates:
            if candidate.get("code") == code:
                return candidate
        return None

    @staticmethod
    def _extract_json_object_from_completion(completion):
        if completion is None:
            return None
        try:
            content = completion.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError):
            return None
        text = str(content).strip()
        if not text:
            return None
        if text.startswith("```json"):
            text = text.split("```json", 1)[-1]
        if text.startswith("```"):
            text = text.split("```", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _format_issue_code_preview(entries: list[dict], max_items: int = 4):
        codes = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            code = entry.get("code")
            if not code:
                continue
            codes.append(str(code))
            if len(codes) >= max_items:
                break
        return ", ".join(codes)

    def _build_summary_payload_for_tts(
        self,
        player_bug_description: str,
        known_bug: bool,
        confidence: float,
        confidence_threshold: float,
        best_matching_issue: dict,
        root_issue: dict,
        direct_duplicates_of_best_issue: int,
        total_confirmed_duplicates_in_tree: int,
        possible_unmarked_duplicates: list[dict],
        possible_duplicates_preview: str,
        browser_open_order: list[str],
    ):
        best_issue = self._as_dict(best_matching_issue)
        root = self._as_dict(root_issue)

        compact_possible_duplicates = []
        for candidate in possible_unmarked_duplicates[:3]:
            candidate = self._as_dict(candidate)
            if not candidate.get("code"):
                continue
            compact_possible_duplicates.append(
                {
                    "title": candidate.get("title"),
                    "status": candidate.get("status"),
                    "confidence": candidate.get("confidence"),
                    "reasoning_short": candidate.get("reasoning_short"),
                }
            )

        return {
            "success": True,
            "player_bug_description": str(player_bug_description or "").strip(),
            "known_bug": bool(known_bug),
            "confidence": self._coerce_float(
                confidence,
                default=0.0,
                minimum=0.0,
                maximum=1.0,
            ),
            "confidence_threshold": self._coerce_float(
                confidence_threshold,
                default=0.0,
                minimum=0.0,
                maximum=1.0,
            ),
            "best_matching_issue": {
                "title": best_issue.get("title"),
                "status": best_issue.get("status"),
                "severity": best_issue.get("severity"),
                "environment_name": best_issue.get("environment_name"),
                "confidence": best_issue.get("confidence"),
                "actual_behaviour": best_issue.get("actual_behaviour"),
                "opened_on": best_issue.get("opened_on"),
                "confirmed_on": best_issue.get("confirmed_on"),
                "fixed_on": best_issue.get("fixed_on"),
            },
            "duplicate_analysis": {
                "root_issue": {
                    "code": root.get("code"),
                    "title": root.get("title"),
                    "status": root.get("status"),
                },
                "direct_duplicates_of_best_issue": direct_duplicates_of_best_issue,
                "total_confirmed_duplicates_in_tree": total_confirmed_duplicates_in_tree,
                "possible_unmarked_duplicates_count": len(possible_unmarked_duplicates),
                "possible_unmarked_duplicates": compact_possible_duplicates,
            },
            "possible_duplicates_preview": str(possible_duplicates_preview or "").strip(),
            "instructions": (
                "Generate one short spoken response in the player's language. "
                "Start with yes/no for known bug likelihood and mention uncertainty when confidence is near threshold. "
                "Do not mention issue codes when mentioning specific issues, focus on the description of the issue. "
                "Explain the best matching issue and information about known duplicates. "
                "If other potential issues exists that might be relevant, explicitly mention the title and status of at least two of them. "
                "Finally, ask the if he wants you to open the issues in the browser. "
                "Do not read JSON keys or field names aloud."
            ),
        }

    def _debug_log(self, label: str, payload=None, force_payload: bool = False):
        if not (self.debug_mode or DEBUG):
            return
        include_payload = payload is not None and (force_payload or self.debug_log_payloads)
        if not include_payload:
            message = f"[IssueCouncil][debug] {label}"
        else:
            try:
                payload_text = json.dumps(payload, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                payload_text = str(payload)
            if len(payload_text) > 6000:
                payload_text = f"{payload_text[:6000]}... [truncated]"
            message = f"[IssueCouncil][debug] {label}: {payload_text}"
        printr.print(message, tags="grey", wait_for_gui=False, console_only=True)

    def _build_issue_payload(self, detail=None, fallback=None):
        fallback = fallback or {}
        detail = self._as_dict(detail)
        details = self._as_dict(detail.get("details"))
        community = self._as_dict(detail.get("community"))
        open_details = self._as_dict(detail.get("openDetails"))
        archived_details = self._as_dict(detail.get("archivedDetails"))
        details_environment = self._as_dict(details.get("environment"))
        duplicate_of = self._as_dict(archived_details.get("duplicateOf"))
        fixed_details = self._as_dict(detail.get("fixedDetails"))
        confirmed_details = self._as_dict(detail.get("confirmedDetails"))
        under_investigation_details = self._as_dict(detail.get("underInvestigationDetails"))
        last_contribution = self._as_dict(community.get("lastContribution"))
        actual_behaviour = self._as_dict(details.get("actualBehaviour"))

        opened_on = open_details.get("openedOn") or fallback.get("opened_on")
        issue_age_days = self._age_days(opened_on)

        payload = {
            "code": detail.get("code") or fallback.get("code"),
            "title": details.get("title") or fallback.get("title"),
            "status": detail.get("status") or fallback.get("status"),
            "severity": details.get("severity") or fallback.get("severity"),
            "environment_name": (details_environment.get("name") or fallback.get("environment_name")),
            "opened_on": opened_on,
            "issue_age_days": issue_age_days,
            "is_new_issue": issue_age_days is not None and issue_age_days <= 14,
            "reproduction_count": community.get("reproductionCount", fallback.get("reproduction_count", 0)),
            "contribution_count": community.get("contributionCount", fallback.get("contribution_count", 0)),
            "vote_count": community.get("voteCount", fallback.get("vote_count", 0)),
            "possible_duplicate_issues_count": community.get("possibleDuplicateIssuesCount", 0),
            "duplicate_of_code": (duplicate_of.get("code") or fallback.get("duplicate_of_code")),
            "fixed_on": fixed_details.get("fixedOn"),
            "confirmed_on": confirmed_details.get("confirmedOn"),
            "under_investigation_since": under_investigation_details.get("investigationStartedOn"),
            "last_contribution_on": last_contribution.get("submittedOn"),
            "actual_behaviour": actual_behaviour.get("description"),
        }
        return payload

    def _extract_possible_duplicate_entries(self, issue_detail: dict):
        issue_detail = self._as_dict(issue_detail)
        community = self._as_dict(issue_detail.get("community"))
        possible = self._as_dict(community.get("possibleDuplicateIssues"))
        entries = possible.get("entries", []) if isinstance(possible, dict) else []
        response = []
        for entry in entries:
            entry = self._as_dict(entry)
            issue = self._as_dict(entry.get("issue"))
            code = self._normalize_issue_code(issue.get("code"))
            if not code:
                continue
            response.append(
                {
                    "code": code,
                    "title": issue.get("title", ""),
                    "duplicate_count_signal": entry.get("duplicateCount", 0),
                    "source": "issue_council_possible_duplicates",
                }
            )
        return response

    def _merge_possible_duplicates(self, first_list: list[dict], second_list: list[dict]):
        merged = {}
        for entry in [*first_list, *second_list]:
            code = self._normalize_issue_code(entry.get("code"))
            if not code:
                continue
            existing = merged.get(code, {})
            merged[code] = {
                "code": code,
                "title": entry.get("title") or existing.get("title", ""),
                "status": entry.get("status") or existing.get("status"),
                "confidence": max(entry.get("confidence", 0.0), existing.get("confidence", 0.0)),
                "duplicate_count_signal": max(
                    self._coerce_int(entry.get("duplicate_count_signal", 0), default=0, minimum=0, maximum=99999),
                    self._coerce_int(existing.get("duplicate_count_signal", 0), default=0, minimum=0, maximum=99999),
                ),
                "source": self._dedupe_list(
                    [
                        *(existing.get("source", []) if isinstance(existing.get("source"), list) else [existing.get("source")] if existing.get("source") else []),
                        *(entry.get("source", []) if isinstance(entry.get("source"), list) else [entry.get("source")] if entry.get("source") else []),
                    ]
                ),
            }

        merged_list = list(merged.values())
        merged_list.sort(
            key=lambda item: (
                item.get("duplicate_count_signal", 0),
                item.get("confidence", 0.0),
                -self._issue_code_number(item.get("code")),
            ),
            reverse=True,
        )
        return merged_list

    def _collect_confirmed_tree_codes(self, root_code: str, details_by_code: dict):
        if not root_code:
            return []

        confirmed_codes = set()
        for code in details_by_code.keys():
            if code == root_code:
                confirmed_codes.add(code)
                continue
            if self._is_descendant_of(code, root_code, details_by_code):
                confirmed_codes.add(code)
        confirmed_codes.add(root_code)
        return self._sort_issue_codes(list(confirmed_codes))

    def _is_descendant_of(self, issue_code: str, root_code: str, details_by_code: dict):
        current_code = issue_code
        visited = set()
        while current_code and current_code not in visited:
            visited.add(current_code)
            if current_code == root_code:
                return True
            current_detail = details_by_code.get(current_code)
            if not current_detail:
                return False
            duplicate_of_code = self._duplicate_of_code(current_detail)
            if not duplicate_of_code:
                return False
            current_code = duplicate_of_code
        return False

    def _resolve_root_code(self, start_code: str, details_by_code: dict):
        if not start_code:
            return None

        current_code = start_code
        visited = set()
        while current_code and current_code not in visited:
            visited.add(current_code)
            issue_detail = self._ensure_issue_detail(current_code, details_by_code)
            if not issue_detail:
                break
            duplicate_of_code = self._duplicate_of_code(issue_detail)
            if not duplicate_of_code:
                return current_code
            current_code = duplicate_of_code
        return current_code or start_code

    def _duplicate_of_code(self, issue_detail: dict):
        issue_detail = self._as_dict(issue_detail)
        archived_details = self._as_dict(issue_detail.get("archivedDetails"))
        duplicate_of = self._as_dict(archived_details.get("duplicateOf"))
        return self._normalize_issue_code(duplicate_of.get("code"))

    def _ensure_issue_detail(self, issue_code: str, details_by_code: dict):
        issue_code = self._normalize_issue_code(issue_code)
        if not issue_code:
            return None

        if issue_code in details_by_code:
            return details_by_code.get(issue_code)

        detail_result = self._get_issue_details(issue_code)
        if detail_result.get("success", False):
            details_by_code[issue_code] = detail_result.get("issue")
            return details_by_code[issue_code]
        return None

    def _count_direct_duplicates_of(self, parent_code: str, details_by_code: dict):
        if not parent_code:
            return 0
        count = 0
        for issue_detail in details_by_code.values():
            if self._duplicate_of_code(issue_detail) == parent_code:
                count += 1
        return count

    def _render_hierarchy_tree(self, root_code: str, best_code: str, details_by_code: dict, possible_duplicates: list[dict]):
        if not root_code:
            root_code = best_code

        children = {}
        for code, issue_detail in details_by_code.items():
            parent = self._duplicate_of_code(issue_detail)
            if not parent:
                continue
            children.setdefault(parent, []).append(code)

        for parent_code in list(children.keys()):
            children[parent_code] = self._sort_issue_codes(children[parent_code])

        lines = ["Issue Council hierarchy (confirmed duplicates):"]
        if not root_code:
            lines.append("No hierarchy data available.")
        else:
            root_detail = details_by_code.get(root_code, {})
            lines.append(self._tree_line_for_issue(root_code, root_detail, is_root=True, is_best=(root_code == best_code)))
            self._append_child_tree_lines(
                parent_code=root_code,
                children=children,
                details_by_code=details_by_code,
                lines=lines,
                prefix="",
                best_code=best_code,
            )

        if possible_duplicates:
            lines.append("")
            lines.append("Potential unmarked duplicates / variants:")
            for entry in possible_duplicates[: self.max_possible_duplicate_fetch]:
                code = entry.get("code")
                title = entry.get("title", "")
                confidence = entry.get("confidence", 0.0)
                signal = entry.get("duplicate_count_signal", 0)
                relevance_score = self._coerce_float(
                    entry.get("relevance_score", 0.0),
                    default=0.0,
                    minimum=0.0,
                    maximum=1.0,
                )
                duplicate_relevance_score = self._coerce_float(
                    entry.get("duplicate_relevance_score", 0.0),
                    default=0.0,
                    minimum=0.0,
                    maximum=1.0,
                )
                lines.append(
                    f"  ? {code}: {title} (dup_signal={signal}, dup_rel={duplicate_relevance_score}, rel={relevance_score}, confidence={confidence})"
                )

        return "\n".join(lines)

    def _append_child_tree_lines(
        self,
        parent_code: str,
        children: dict,
        details_by_code: dict,
        lines: list[str],
        prefix: str,
        best_code: str,
    ):
        child_codes = children.get(parent_code, [])
        for index, child_code in enumerate(child_codes):
            is_last = index == len(child_codes) - 1
            branch = "\\- " if is_last else "|- "
            child_detail = details_by_code.get(child_code, {})
            label = self._tree_line_for_issue(
                child_code,
                child_detail,
                is_root=False,
                is_best=(child_code == best_code),
            )
            lines.append(f"{prefix}{branch}{label}")
            child_prefix = f"{prefix}{'   ' if is_last else '|  '}"
            self._append_child_tree_lines(
                parent_code=child_code,
                children=children,
                details_by_code=details_by_code,
                lines=lines,
                prefix=child_prefix,
                best_code=best_code,
            )

    def _tree_line_for_issue(self, code: str, issue_detail: dict, is_root: bool, is_best: bool):
        issue_detail = self._as_dict(issue_detail)
        details = self._as_dict(issue_detail.get("details"))
        title = details.get("title", "")
        status = issue_detail.get("status", "UNKNOWN")
        marker = []
        if is_root:
            marker.append("ROOT")
        if is_best:
            marker.append("BEST_MATCH")
        marker_text = f" [{'|'.join(marker)}]" if marker else ""
        if title:
            return f"{code} ({status}){marker_text} - {title}"
        return f"{code} ({status}){marker_text}"

    def _build_browser_order_from_explicit_codes(self, issue_codes: list[str]):
        details_by_code = {}
        for code in issue_codes:
            self._ensure_issue_detail(code, details_by_code)

        grouped_by_root = {}
        for code in issue_codes:
            root_code = self._resolve_root_code(code, details_by_code) or code
            grouped_by_root.setdefault(root_code, set()).add(code)
            grouped_by_root[root_code].add(root_code)

        ordered_codes = []
        ordered_roots = self._sort_issue_codes(list(grouped_by_root.keys()))
        for root_code in ordered_roots:
            ordered_codes.append(root_code)
            rest = self._sort_issue_codes(
                [code for code in grouped_by_root[root_code] if code != root_code]
            )
            ordered_codes.extend(rest)
        return self._dedupe_list(ordered_codes)

    def _issue_url_for_code(self, issue_code: str):
        if "{code}" in self.issue_web_url:
            return self.issue_web_url.format(code=issue_code)
        return f"{self.issue_web_url.rstrip('/')}/{issue_code}"

    @staticmethod
    def _normalize_issue_code(issue_code: str):
        if not issue_code:
            return None
        normalized = str(issue_code).strip().upper()
        match = re.match(r"^([A-Z]+-\d+)$", normalized)
        return match.group(1) if match else None

    def _normalize_issue_codes(self, codes):
        if isinstance(codes, str):
            codes = [codes]
        if not isinstance(codes, list):
            return []
        normalized = []
        for code in codes:
            normalized_code = self._normalize_issue_code(code)
            if normalized_code:
                normalized.append(normalized_code)
        return self._dedupe_list(normalized)

    def _sort_issue_codes(self, issue_codes: list[str]):
        return sorted(
            self._normalize_issue_codes(issue_codes),
            key=lambda code: self._issue_code_number(code),
        )

    @staticmethod
    def _issue_code_number(issue_code: str):
        match = re.search(r"(\d+)$", str(issue_code))
        if not match:
            return 10**12
        return int(match.group(1))

    @staticmethod
    def _dedupe_list(values: list):
        deduped = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    @staticmethod
    def _as_dict(value):
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _truncate_text(text: str, max_chars: int):
        if not text:
            return ""
        normalized = " ".join(str(text).split()).strip()
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[:max_chars].rstrip()}..."

    @staticmethod
    def _coerce_int(value, default: int, minimum: int, maximum: int):
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            coerced = default
        return max(minimum, min(maximum, coerced))

    @staticmethod
    def _coerce_float(value, default: float, minimum: float, maximum: float):
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            coerced = default
        return max(minimum, min(maximum, coerced))

    @staticmethod
    def _age_days(iso_date: str):
        if not iso_date:
            return None
        try:
            date_value = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
            if date_value.tzinfo is None:
                date_value = date_value.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - date_value
            return max(0, delta.days)
        except ValueError:
            return None

    def _build_request_headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie
        return headers

    def _load_bearer_token_from_sources(self, allow_file: bool, force_reload: bool = False):
        env_token = os.environ.get(self.bearer_token_env_var)
        if env_token:
            stripped_env_token = self._normalize_bearer_token_value(env_token)
            if stripped_env_token:
                self.bearer_token = stripped_env_token

        if allow_file:
            file_token = self._read_bearer_token_from_file(self.bearer_token_file)
            if file_token and (force_reload or not env_token):
                self.bearer_token = file_token

    @staticmethod
    def _read_bearer_token_from_file(file_path: str):
        if not file_path:
            return None
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                token = IssueCouncilManager._normalize_bearer_token_value(file.read())
                return token or None
        except OSError:
            return None

    @staticmethod
    def _normalize_bearer_token_value(raw_value):
        if not raw_value:
            return None
        token = str(raw_value).strip()
        if not token:
            return None
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token or None

    def _build_auth_error_message(self, status_code: int):
        return (
            f"Issue Council authentication failed with HTTP {status_code}. "
            "Provide a fresh Bearer token via one of these sources: "
            "secrets.yaml key 'issue_council_bearer_token', "
            f"env var '{self.bearer_token_env_var}', "
            f"or file '{self.bearer_token_file}'. "
            "Token retrieval is semi-automatic: keep browser session logged in and periodically copy the current token. "
            f"Hint: {self.auth_debug_hint}"
        )

    def _attempt_auto_token_capture(self, reason: str):
        self._load_bearer_token_from_sources(allow_file=True, force_reload=False)
        if self.bearer_token and reason == "missing_token":
            return True

        now = time.time()
        if now - self.last_token_capture_attempt_ts < self.token_capture_retry_cooldown_seconds:
            return bool(self.bearer_token)
        self.last_token_capture_attempt_ts = now

        script_path = self.token_capture_script_path
        if not script_path:
            return False

        resolved_script_path = (
            script_path
            if os.path.isabs(script_path)
            else os.path.abspath(os.path.join(os.getcwd(), script_path))
        )
        if not os.path.exists(resolved_script_path):
            printr.print_warn(
                f"IssueCouncil token helper not found: {resolved_script_path}.",
                wait_for_gui=False,
            )
            return False

        printr.print(
            (
                f"IssueCouncil auth: launching token helper ({reason}). "
                "Please complete RSI login in the opened browser window."
            ),
            tags="info",
            wait_for_gui=False,
        )

        command = [
            sys.executable,
            resolved_script_path,
            "--token-file",
            self.bearer_token_file,
            "--issue-url",
            self._build_issue_capture_url(),
            "--api-url-prefix",
            self.api_url,
            "--timeout-seconds",
            str(self.token_capture_timeout_seconds),
        ]
        try:
            process = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.token_capture_timeout_seconds + 45,
            )
        except (OSError, subprocess.SubprocessError) as error:
            printr.print_warn(
                f"Could not run IssueCouncil token helper: {error}",
                wait_for_gui=False,
            )
            return False

        if process.returncode != 0:
            stdout_text = (process.stdout or "").strip()
            stderr_text = (process.stderr or "").strip()
            info_text = stderr_text or stdout_text or f"exit code {process.returncode}"
            printr.print_warn(
                f"IssueCouncil token helper failed: {info_text}",
                wait_for_gui=False,
            )
            return False

        self._load_bearer_token_from_sources(allow_file=True, force_reload=True)
        return bool(self.bearer_token)

    def _build_issue_capture_url(self):
        issue_url = str(self.issue_web_url or "").strip()
        if not issue_url:
            return "https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues"
        if "{code}" in issue_url:
            issue_url = issue_url.replace("{code}", "").rstrip("/")
        return issue_url


if __name__ == "__main__":
    print("IssueCouncilManager module loaded.")
