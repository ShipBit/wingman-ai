"""Bounded, revision-dated ship recipes from the public EDCD reference projects."""

from datetime import datetime, timezone
import json
import re
import time


API = "https://api.github.com/repos/EDCD/"
RAW = "https://raw.githubusercontent.com/EDCD/"
LIMIT = 9000


def stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


class EngineeringData:
    def __init__(self, provider):
        self.provider = provider

    def lookup(self, query, grade=5, applications=1, galaxy="live"):
        if galaxy != "live":
            return {"error": "Engineering reference is configured for Live; Legacy/unknown galaxy is unsupported."}
        if (not isinstance(query, str) or not 1 <= len(query.strip()) <= 100 or
                type(grade) is not int or not 1 <= grade <= 5 or
                type(applications) is not int or not 1 <= applications <= 100):
            return {"error": "Supply a recipe ID/name/module query, grade 1-5 and 1-100 explicit applications."}
        now = datetime.now(timezone.utc)
        result = {"retrieved_at": now.isoformat(), "galaxy": "live", "sources": [], "recipes": [],
                  "scope": "Listed ship blueprint material costs for explicitly requested applications, not a full grade climb. No experimental/suit recipes, unlock prerequisites, other currencies or fitted-module compatibility guarantee.",
                  "inventory_check": "Use journal symbols below with fresh elite_status materials observations. Missing or requires_refresh quantities are unknown, not zero.",
                  "reference_currentness": "Upstream revision dates are not proof that every recipe matches the current game patch.",
                  "stale_reference": False}
        deadline = time.monotonic() + 30

        def fetch(url, cache_seconds):
            payload, fetched, cached, error = self.provider._fetch(url, deadline=deadline, cache_seconds=cache_seconds)
            if error:
                result["stale_reference"] = True
            result["sources"].append({"url": url, "retrieved_at": datetime.fromtimestamp(fetched, timezone.utc).isoformat() if fetched else None,
                                      "cached": cached, "error": error})
            if payload is None:
                raise ValueError("Reference provider unavailable; no recipe estimate is available")
            return payload

        def revision(repo):
            head = fetch(API + repo + "/commits/master", 3600)
            if not isinstance(head, dict):
                raise ValueError("Invalid reference revision")
            sha = head.get("sha", "")
            when = head.get("commit", {}).get("committer", {}).get("date")
            observed = stamp(when)
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha) or not observed or observed > now:
                raise ValueError("Invalid or future reference revision")
            result["sources"][-1].update(revision=sha, revision_time=when)
            return RAW + repo + "/" + sha + "/"

        try:
            recipes_base = revision("coriolis-data")
            blueprints = fetch(recipes_base + "modifications/blueprints.json", 86400)
            if not isinstance(blueprints, dict):
                raise ValueError("Invalid blueprint catalogue")
            query = query.strip().casefold()
            exact = [key for key in blueprints if key.casefold() == query]
            matches = exact or [key for key, row in blueprints.items() if isinstance(row, dict) and
                all(word in (key + " " + str(row.get("name", "")) + " " + " ".join(row.get("modulename", []))).casefold()
                    for word in query.split())]
            result["matching_recipes"] = len(matches)
            result["omitted_recipes"] = max(0, len(matches) - 5)
            if not matches:
                result["note"] = "No matching reference entry; this does not establish that the upgrade is unavailable in-game."
                return result
            modules = fetch(recipes_base + "modifications/modules.json", 86400)
            material_base = revision("FDevIDs")
            materials = fetch(material_base + "material.csv", 86400)
            if not isinstance(modules, dict) or not isinstance(materials, list):
                raise ValueError("Invalid module/material catalogue")
            names = {}
            for row in materials:
                if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                    continue
                names.setdefault(row["name"].casefold(), []).append(row)
            for key in sorted(matches)[:5]:
                blueprint = blueprints[key]
                entry = {"id": key[:100], "name": str(blueprint.get("name", ""))[:120], "grade": grade,
                         "applications": applications, "module_names": blueprint.get("modulename", [])[:5]}
                recipe = blueprint.get("grades", {}).get(str(grade))
                components = recipe.get("components") if isinstance(recipe, dict) else None
                if (not isinstance(components, dict) or not 1 <= len(components) <= 16 or
                        any(not isinstance(n, str) or len(n) > 120 or type(c) is not int or not 1 <= c <= 1000
                            for n, c in components.items())):
                    entry["cost_status"] = "unknown: requested grade has no complete supported material recipe"
                    result["recipes"].append(entry)
                    continue
                entry["materials"] = []
                for name, count in components.items():
                    row = {"name": name, "per_application": count, "required_for_requested_applications": count * applications}
                    identities = names.get(name.casefold(), [])
                    if len(identities) == 1:
                        identity = identities[0]
                        symbol, category = identity.get("symbol"), identity.get("type")
                        if isinstance(symbol, str) and re.fullmatch(r"[A-Za-z0-9_]{1,100}", symbol) and category in ("Raw", "Manufactured", "Encoded"):
                            row.update(journal_symbol=symbol.casefold(), category=category)
                    if "journal_symbol" not in row:
                        row["inventory_match"] = "unknown material identifier; do not guess from the display name"
                    entry["materials"].append(row)
                engineers = set()
                for module in modules.values():
                    if not isinstance(module, dict):
                        continue
                    availability = module.get("blueprints", {}).get(key, {}).get("grades", {}).get(str(grade), {})
                    for engineer in availability.get("engineers", []):
                        if isinstance(engineer, str) and len(engineer) <= 100:
                            engineers.add(engineer)
                entry["engineers_in_reference"] = sorted(engineers)[:5]
                entry["omitted_engineers"] = max(0, len(engineers) - 5)
                entry["engineer_access"] = "Unverified for this pilot; compare journal engineer progress and current prerequisites"
                entry["cost_status"] = "dated_reference_materials_only"
                result["recipes"].append(entry)
        except (ValueError, TypeError, AttributeError, KeyError):
            result["error"] = "Reference unavailable or malformed; no complete recipe assessment can be made."
            result["recipes"] = []
        while len(json.dumps(result)) > LIMIT and result["recipes"]:
            result["recipes"].pop()
            result["omitted_recipes"] = result.get("omitted_recipes", 0) + 1
        return result
