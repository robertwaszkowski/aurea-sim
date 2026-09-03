import os
import xml.etree.ElementTree as ET
import re
import json
import math
from copy import deepcopy
import random
import secrets
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import urllib.request

from pydantic import BaseModel, Field, model_validator

# Ensure user installed dependencies before proceeding
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

# -----------------
# Branding Model
# -----------------
class ProjectBranding(BaseModel):
    display_name: str = Field(description="A human-readable name for the project.")
    icon: str = Field(description="A Material Design Icon name (e.g., mdi-account-group, mdi-cart, mdi-wrench, mdi-bank) that represents the business process.")
    color: str = Field(description="A standard Vuetify/Material color name (e.g., blue, green, orange, purple, teal, deep-purple, amber, cyan, indigo).")

# -----------------
# Name Humanizer
# -----------------
def humanize_name(name: str) -> str:
    """
    Converts technical identifiers to human-readable text.
    e.g. 'RES_Sales_Process' -> 'RES Sales Process'
         'Task_ReviewOffer'  -> 'Review Offer'
         'addProspect'       -> 'Add Prospect'
    """
    # Remove common prefixes: Task_, Gateway_, Flow_, Event_
    name = re.sub(r'^(Task|Gateway|Event|Flow|Sub|SubProcess)[_\s]?', '', name, flags=re.IGNORECASE)
    # Replace underscores and hyphens with spaces
    name = name.replace('_', ' ').replace('-', ' ')
    # Split camelCase: insert space before each uppercase letter preceded by lowercase
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # Collapse multiple spaces and strip
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Capitalize first letter of each word but PRESERVE existing uppercase
    # e.g. 'RES Sales' stays 'RES Sales', 'addProspect' stays 'Add Prospect'
    words = name.split()
    return " ".join(w[0].upper() + w[1:] if len(w) > 0 else w for w in words)

def prompt_task_name(task: dict) -> str:
    """Helper to return a prompt-safe task name, preferring the cleaned version."""
    return (
        task.get("clean_task_name")
        or task.get("task_name")
        or task.get("task_id")
        or "Unnamed task"
    )

# -----------------
# URL Redirect Resolver
# -----------------
def resolve_redirect(url: str, timeout: int = 6) -> str:
    """
    Follow a redirect URL (e.g. Vertex AI grounding redirect) to get the real page URL.
    Falls back to the original URL on any error.
    """
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.url
    except Exception:
        return url

def url_to_readable_title(url: str) -> str:
    """
    Convert a resolved URL to a human-readable title using its path components.
    Example: https://www.salaryexpert.com/salary/job/environmental-consultant/poland
          -> "Environmental Consultant › Poland - salaryexpert.com"
    """
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')

    if 'vertexaisearch.cloud.google.com' in domain:
        return domain  # unresolved redirect, can't do better

    raw_path = unquote(parsed.path)
    skip = {'index', 'index.html', 'index.php', 'home', 'default', 'sites',
            'files', 'documents', 'wp-content', 'uploads', 'blog', 'en', 'pl',
            'resources', 'resource-library', 'resource-listing', 'salary', 'job'}
    parts = [p for p in raw_path.split('/') if p and p.lower() not in skip]

    def humanize_part(s: str) -> str:
        s = re.sub(r'\.[a-z]{2,4}$', '', s)          # strip .pdf, .html etc.
        s = s.replace('-', ' ').replace('_', ' ')
        return ' '.join(w.capitalize() for w in s.split())

    readable = [humanize_part(p) for p in parts[-3:] if len(p) > 2]

    if readable:
        return ' › '.join(readable) + f' - {domain}'
    return domain

# -----------------
# API Fallback Matrix
def generate_with_fallback(client, prompt, config, return_model=False):
    models_to_try = [
        'gemini-2.5-flash',
        'gemini-1.5-flash',
        'gemini-1.5-pro'
    ]
    
    last_error = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return (response, model_name) if return_model else response
        except Exception as e:
            last_error = e
            error_str = str(e)
            if any(err in error_str for err in ["429", "RESOURCE_EXHAUSTED"]):
                print(f"\n  [!] Model {model_name} exhausted quota. Falling back...")
                continue
            elif any(err in error_str for err in ["404", "NOT_FOUND"]):
                print(f"\n  [!] Model {model_name} not yet available on this API tier. Falling back...")
                continue
            elif any(err in error_str for err in ["503", "UNAVAILABLE", "500"]):
                print(f"\n  [!] Model {model_name} is currently experiencing high demand. Falling back...")
                continue
            else:
                raise e
                
    raise last_error

def compress_citations(text):
    """
    Finds sequences of citations like [1, 2, 3, 5] and converts them to [1-3, 5].
    """
    import re
    
    def replace_func(match):
        # Extract numbers from the bracketed string
        raw_nums = match.group(1)
        try:
            nums = sorted(list(set(int(n.strip()) for n in raw_nums.split(','))))
        except ValueError:
            return match.group(0) # Not a clean list of numbers
            
        if not nums:
            return match.group(0)
            
        ranges = []
        if nums:
            start = nums[0]
            end = nums[0]
            
            for i in range(1, len(nums)):
                if nums[i] == end + 1:
                    end = nums[i]
                else:
                    if start == end:
                        ranges.append(str(start))
                    else:
                        ranges.append(f"{start}-{end}")
                    start = nums[i]
                    end = nums[i]
            
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{end}")
        
        return f"[{', '.join(ranges)}]"

    # Pattern: [ followed by digits, commas, and spaces, ending in ]
    ptrn = r'\[([\d\s,]+)\]'
    return re.sub(ptrn, replace_func, text)

# -----------------
# Pydantic Schema
# -----------------
ID_REGEX = r"^[a-zA-Z0-9_]+$"

EVIDENCE_STATUSES = {
    "grounded_confirmed",
    "grounded_proxy",
    "grounded_extrapolated",
    "heuristic_fallback",
    "structural_value",
}

# Prosimos task durations represent active resource service time. A value above
# one working day is much more likely to be an end-to-end cycle/queue benchmark
# accidentally copied from web research than continuous hands-on work.
MAX_ACTIVE_TASK_SECONDS = 8 * 60 * 60
DEFAULT_HUMAN_TASK_SECONDS = 10 * 60
SHORT_TRANSACTION_MIN_SECONDS = 1
SHORT_TRANSACTION_DEFAULT_SECONDS = 15
SHORT_TRANSACTION_MAX_SECONDS = 60
SHORT_TRANSACTION_STD_SECONDS = 7.5
DEFAULT_SYSTEM_TASK_SECONDS = 0.02
SYSTEM_TASK_STD_SECONDS = 0.01
SYSTEM_TASK_MIN_SECONDS = 0.001
SYSTEM_TASK_MAX_SECONDS = 1.0

class DistributionParam(BaseModel):
    value: float

class TaskResourceDetail(BaseModel):
    resource_id: str = Field(
        pattern=ID_REGEX,
        description="Resource instance ID. No spaces. Use underscores."
    )
    distribution_name: str = Field(
        description="Must be 'norm' for Normal Distribution"
    )
    distribution_params: list[DistributionParam] = Field(
        description="4 floats: [mean (sec), standard deviation (sec), min (0), max (999999)]"
    )

    evidence_status: str = Field(
        description=(
            "One of: grounded_confirmed, grounded_proxy, grounded_extrapolated, "
            "heuristic_fallback, structural_value."
        )
    )
    source_urls: list[str] = Field(
        default=[],
        description="URLs supporting this specific task-duration value, if any."
    )
    evidence_rationale: str = Field(
        default="",
        description="Short explanation of how this specific task-duration value was determined."
    )

    @model_validator(mode="after")
    def validate_evidence_status(self) -> "TaskResourceDetail":
        if self.evidence_status not in EVIDENCE_STATUSES:
            raise ValueError(f"Invalid evidence_status: {self.evidence_status}")
        return self

class TaskResourceEntry(BaseModel):
    task_id: str
    resources: list[TaskResourceDetail]

class ResourceInstance(BaseModel):
    id: str = Field(
        pattern=ID_REGEX,
        description="Unique ID for this specific employee/resource instance. No spaces."
    )
    name: str
    cost_per_hour: float
    amount: int = Field(description="Always 1")
    calendar: str = Field(description="Use 'Standard_Working_Hours' or '24_7_Calendar'")

    evidence_status: str = Field(
        description=(
            "One of: grounded_confirmed, grounded_proxy, grounded_extrapolated, "
            "heuristic_fallback, structural_value."
        )
    )
    source_urls: list[str] = Field(
        default=[],
        description="URLs supporting this specific resource-cost value, if any."
    )
    evidence_rationale: str = Field(
        default="",
        description="Short explanation of how this specific resource-cost value was determined."
    )

    @model_validator(mode="after")
    def validate_evidence_status(self) -> "ResourceInstance":
        if self.evidence_status not in EVIDENCE_STATUSES:
            raise ValueError(f"Invalid evidence_status: {self.evidence_status}")
        return self

class ResourceProfile(BaseModel):
    id: str = Field(pattern=ID_REGEX, description="Role ID, e.g. RKR, Manager_Role. No spaces.")
    name: str
    resource_list: list[ResourceInstance]

class ProbabilityEntry(BaseModel):
    path_id: str = Field(description="The SequenceFlow ID")
    value: float

class GatewayBranch(BaseModel):
    gateway_id: str
    probabilities: list[ProbabilityEntry]

class ArrivalFrequency(BaseModel):
    events: float = Field(description="Number of cases arriving per period, e.g. 2.0 for '2 cases per week'")
    per_count: float = Field(description="The period count, e.g. 1.0 for 'per 1 week'")
    per_unit: str = Field(description="Time unit. Must be exactly one of: 'second', 'minute', 'hour', 'day', 'week', 'month'")
    rationale: str = Field(description="Business reason for this estimate, e.g. 'Based on typical RES B2B pipeline velocity: approximately 2 qualified leads per week per territory'")

class ArrivalTimeConfig(BaseModel):
    frequency: ArrivalFrequency

class GenerationMetadata(BaseModel):
    methodology: str = Field(description="Detailed description of the methodology used")
    sources: List[str] = Field(description="Human-readable list of sources used for data estimation")
    source_urls: List[str] = Field(default=[], description="Actual URLs retrieved by Google Search during research phase")
    rationale: str = Field(description="Scientific or business-logic rationale for the predicted values")
    grounding_mode: str = Field(default="web_grounded", description="Generation mode: 'web_grounded' or 'heuristic'.")
    grounding_status: str = Field(default="unknown", description="Grounding status, e.g. 'success', 'failed_fallback', or 'disabled_by_experiment'.")

class ProsimosPredictedBase(BaseModel):
    metadata: GenerationMetadata
    arrival_time: ArrivalTimeConfig
    resource_profiles: list[ResourceProfile]
    task_resource_distribution: list[TaskResourceEntry]
    gateway_branching_probabilities: list[GatewayBranch]

    @model_validator(mode='after')
    def validate_referential_integrity(self) -> 'ProsimosPredictedBase':
        # Create a set of ALL individual resource IDs
        all_res_ids = set()
        for p in self.resource_profiles:
            for r in p.resource_list:
                all_res_ids.add(r.id)
        
        # Ensure every task assignment points to an existing resource ID
        for t in self.task_resource_distribution:
            for r_detail in t.resources:
                if r_detail.resource_id not in all_res_ids:
                    # In Prosimos, we must point to the specific resource ID
                    # If AI pointed to the Role ID, we fix it to the first instance
                    for p in self.resource_profiles:
                        if p.id == r_detail.resource_id:
                            r_detail.resource_id = p.resource_list[0].id
                            break
                    
                    if r_detail.resource_id not in all_res_ids:
                        raise ValueError(f"Task {t.task_id} assigned to non-existent resource {r_detail.resource_id}")
        return self

class MissingTasksFix(BaseModel):
    task_resource_distribution: list[TaskResourceEntry]

# -----------------
# Deterministic Resource Enforcement
# -----------------
def apply_deterministic_resources(ai_data: dict, semantics: dict) -> dict:
    """
    Forces ai_data to use exactly the deterministic roles specified in semantics.
    """
    # 2.3 Build deterministic resource profiles
    from aureasim.role_resolver import normalize_role_id

    existing_costs = {}

    def remember_cost(key: str | None, payload: dict) -> None:
        if not key:
            return
        existing_costs[key] = payload
        existing_costs[normalize_role_id(key)] = payload

        if key.endswith("_1"):
            existing_costs[normalize_role_id(key.removesuffix("_1"))] = payload

    for profile in ai_data.get("resource_profiles", []):
        profile_id = profile.get("id")

        for resource in profile.get("resource_list", []):
            resource_id = resource.get("id")

            payload = {
                "cost_per_hour": resource.get("cost_per_hour", 30.0),
                "evidence_status": resource.get("evidence_status", "heuristic_fallback"),
                "source_urls": resource.get("source_urls", []),
                "evidence_rationale": resource.get(
                    "evidence_rationale",
                    "No parameter-level rationale provided by generator."
                ),
            }

            remember_cost(resource_id, payload)
            remember_cost(profile_id, payload)
                
    new_resource_profiles = []
    unique_roles = {t["role_id"]: t for t in semantics.get("tasks", [])}
    for role_id, role_info in unique_roles.items():
        payload = (
            existing_costs.get(role_id)
            or existing_costs.get(role_info["resource_instance_id"])
        )

        if payload is None:
            payload = {
                "cost_per_hour": 30.0,
                "evidence_status": "heuristic_fallback",
                "source_urls": [],
                "evidence_rationale": (
                    "Fallback cost assigned because generator did not provide "
                    "a matching cost estimate."
                ),
            }

        cost = payload["cost_per_hour"]
        evidence_status = payload["evidence_status"]
        source_urls = payload["source_urls"]
        evidence_rationale = payload["evidence_rationale"]

        if is_structural_system_role(role_id):
            cost = 0.0
            evidence_status = "structural_value"
            source_urls = []
            evidence_rationale = "Structural non-labor resource; zero hourly labor cost."

        calendar = "24_7_Calendar" if cost == 0.0 else "Standard_Working_Hours"

        new_resource_profiles.append({
            "id": role_id,
            "name": role_id,
            "resource_list": [{
                "id": role_info["resource_instance_id"],
                "name": role_info["resource_instance_id"],
                "cost_per_hour": cost,
                "amount": 1,
                "calendar": calendar,
                "evidence_status": evidence_status,
                "source_urls": source_urls,
                "evidence_rationale": evidence_rationale,
            }]
        })
        
    ai_data["resource_profiles"] = new_resource_profiles

    # 2.4 Build deterministic task-resource distribution
    duration_by_task = {}

    for entry in ai_data.get("task_resource_distribution", []):
        task_id = entry.get("task_id")
        if not task_id or not entry.get("resources"):
            continue

        resource_entry = entry["resources"][0]
        params = resource_entry.get("distribution_params")

        if not params:
            continue

        duration_by_task[task_id] = {
            "distribution_name": resource_entry.get("distribution_name", "norm"),
            "distribution_params": params,
            "evidence_status": resource_entry.get("evidence_status", "heuristic_fallback"),
            "source_urls": resource_entry.get("source_urls", []),
            "evidence_rationale": resource_entry.get(
                "evidence_rationale",
                "No parameter-level rationale provided by generator."
            ),
        }

    new_task_resource_distribution = []
    for task in semantics.get("tasks", []):
        payload = duration_by_task.get(task["task_id"])

        if payload is None:
            payload = {
                "distribution_name": "norm",
                "distribution_params": [
                    {"value": 600},
                    {"value": 120},
                    {"value": 0},
                    {"value": 9999999},
                ],
                "evidence_status": "heuristic_fallback",
                "source_urls": [],
                "evidence_rationale": (
                    "Fallback duration assigned because generator did not provide "
                    "this task duration."
                ),
            }

        new_task_resource_distribution.append({
            "task_id": task["task_id"],
            "resources": [{
                "resource_id": task["resource_instance_id"],
                "distribution_name": payload["distribution_name"],
                "distribution_params": payload["distribution_params"],
                "evidence_status": payload["evidence_status"],
                "source_urls": payload["source_urls"],
                "evidence_rationale": payload["evidence_rationale"],
            }]
        })
        
    ai_data["task_resource_distribution"] = new_task_resource_distribution
    return ai_data


def is_structural_system_role(role_id: str) -> bool:
    """Return whether an authoritative role label denotes automation."""
    normalized = role_id.casefold().replace("-", "_").replace(" ", "_")
    return (
        normalized in {"system", "system_role", "automation", "automated", "robot", "bot", "api"}
        or normalized.startswith("system_")
        or normalized.endswith("_system")
    )


def is_structural_system_task(task: dict) -> bool:
    """Identify automated execution from BPMN structure, never web evidence.

    BPMN service/script tasks are automated by definition. Plain BPMN tasks
    may also have an authoritative Aurea role such as ``System`` or
    ``System SAP``. This deliberately does not infer automation from ordinary
    task-label words such as "OCR".
    """
    task_type = str(task.get("bpmn_task_type", "")).casefold()
    if task_type in {"servicetask", "scripttask"}:
        return True
    if str(task.get("task_class", "")).casefold() == "external_wait":
        return True
    return is_structural_system_role(str(task.get("role_id", "")))


def _sample_duration_policy_fallback(policy: dict, rng: random.Random) -> float:
    """Sample a bounded semantic prior instead of injecting a fixed value."""
    return round(rng.triangular(
        float(policy["minimum_seconds"]),
        float(policy["maximum_seconds"]),
        float(policy["fallback_seconds"]),
    ), 3)


def stabilize_task_durations(ai_data: dict, semantics: dict, fallback_seed=None) -> dict:
    """Reject implausible cycle-time-as-service-time estimates deterministically.

    Web benchmarks commonly report elapsed approval or resolution time, while
    Prosimos requires active task execution time. Values that are non-positive,
    non-finite, or longer than one working day are replaced with a conservative
    deterministic service-time prior. Every replacement is retained in metadata
    so the correction is visible and auditable.
    """
    task_semantics = {
        task.get("task_id"): task for task in semantics.get("tasks", [])
    }
    sampled_fallback_seed = secrets.randbits(64) if fallback_seed is None else fallback_seed
    fallback_rng = random.Random(sampled_fallback_seed)
    corrections = []

    for task_entry in ai_data.get("task_resource_distribution", []):
        task_id = task_entry.get("task_id")
        semantic = task_semantics.get(task_id, {})
        task_class = str(semantic.get("task_class", "")).casefold()
        is_system_task = is_structural_system_task(semantic)
        is_short_transaction = task_class == "short_transaction"
        duration_policy = semantic.get("duration_policy") or {
            "id": "rapid_transaction",
            "minimum_seconds": SHORT_TRANSACTION_MIN_SECONDS,
            "fallback_seconds": SHORT_TRANSACTION_DEFAULT_SECONDS,
            "maximum_seconds": SHORT_TRANSACTION_MAX_SECONDS,
            "std_seconds": SHORT_TRANSACTION_STD_SECONDS,
        }
        fallback_mean = (
            DEFAULT_SYSTEM_TASK_SECONDS if is_system_task
            else DEFAULT_HUMAN_TASK_SECONDS
        )

        for resource_entry in task_entry.get("resources", []):
            params = resource_entry.get("distribution_params", [])
            if not params:
                continue

            try:
                original_mean = float(params[0].get("value"))
            except (AttributeError, TypeError, ValueError):
                original_mean = math.nan

            reason = None
            if task_class == "external_wait":
                reason = (
                    "BPMN annotation identifies an external-wait lifecycle state; "
                    "it has no active resource service time"
                )
            elif is_system_task:
                reason = (
                    "BPMN structure identifies an automated performer; active machine "
                    "service time uses the deterministic near-zero structural prior"
                )
            elif not math.isfinite(original_mean) or original_mean <= 0:
                reason = "non-positive or non-finite service-time mean"
            elif is_short_transaction and not (
                float(duration_policy["minimum_seconds"])
                <= original_mean
                <= float(duration_policy["maximum_seconds"])
            ):
                reason = (
                    "BPMN annotation identifies a short human transaction; active service "
                    "time must remain within its semantic seconds-scale duration policy"
                )
            elif original_mean > MAX_ACTIVE_TASK_SECONDS:
                reason = (
                    "mean exceeds the one-working-day active-service limit; "
                    "the source likely describes queue, wait, or end-to-end cycle time"
                )

            if reason is None:
                continue

            original_rationale = resource_entry.get("evidence_rationale", "")
            resource_entry["distribution_name"] = "norm"
            replacement_mean = (
                DEFAULT_SYSTEM_TASK_SECONDS if is_system_task
                else _sample_duration_policy_fallback(duration_policy, fallback_rng) if is_short_transaction
                else fallback_mean
            )
            resource_entry["distribution_params"] = (
                [
                    {"value": DEFAULT_SYSTEM_TASK_SECONDS},
                    {"value": SYSTEM_TASK_STD_SECONDS},
                    {"value": SYSTEM_TASK_MIN_SECONDS},
                    {"value": SYSTEM_TASK_MAX_SECONDS},
                ]
                if is_system_task else [
                    {"value": replacement_mean},
                    {"value": float(duration_policy["std_seconds"])},
                    {"value": float(duration_policy["minimum_seconds"])},
                    {"value": float(duration_policy["maximum_seconds"])},
                ] if is_short_transaction else [
                    {"value": fallback_mean},
                    {"value": fallback_mean * 0.2},
                    {"value": 0},
                    {"value": 9999999},
                ]
            )
            resource_entry["evidence_status"] = (
                "structural_value" if is_system_task else "heuristic_fallback"
            )
            resource_entry["source_urls"] = []
            resource_entry["evidence_rationale"] = (
                f"Deterministic service-time guardrail applied: {reason}. "
                f"Replaced the generated mean with {replacement_mean} seconds. "
                f"Original generator rationale: {original_rationale or 'not provided'}"
            )
            corrections.append({
                "task_id": task_id,
                "task_name": prompt_task_name(semantic),
                "original_mean_seconds": (
                    original_mean if math.isfinite(original_mean) else None
                ),
                "replacement_mean_seconds": replacement_mean,
                "reason": reason,
            })

    metadata = ai_data.setdefault("metadata", {})
    metadata["task_duration_stabilization_policy"] = {
        "enabled": True,
        "target_measure": "active_resource_service_time_seconds",
        "excluded_measures": [
            "queue_time",
            "waiting_time",
            "handoff_delay",
            "end_to_end_cycle_time",
        ],
        "maximum_active_task_seconds": MAX_ACTIVE_TASK_SECONDS,
        "human_fallback_seconds": DEFAULT_HUMAN_TASK_SECONDS,
        "short_transaction_policy": {
            "task_class": "short_transaction",
            "meaning": "brief human interaction, such as confirming, routing, recording, or approving without substantive review",
            "task_specific": True,
            "fallback_sampling_policy": {
                "id": "rapid_transaction",
                "minimum_seconds": SHORT_TRANSACTION_MIN_SECONDS,
                "fallback_seconds": SHORT_TRANSACTION_DEFAULT_SECONDS,
                "maximum_seconds": SHORT_TRANSACTION_MAX_SECONDS,
                "std_seconds": SHORT_TRANSACTION_STD_SECONDS,
                "sampling": "bounded triangular draw with fallback_seconds as the mode",
            },
        },
        "system_fallback_seconds": DEFAULT_SYSTEM_TASK_SECONDS,
        "fallback_sampling_seed": str(sampled_fallback_seed),
        "system_task_policy": {
            "detection": "BPMN service/script task or authoritative System role",
            "mean_seconds": DEFAULT_SYSTEM_TASK_SECONDS,
            "std_seconds": SYSTEM_TASK_STD_SECONDS,
            "min_seconds": SYSTEM_TASK_MIN_SECONDS,
            "max_seconds": SYSTEM_TASK_MAX_SECONDS,
        },
        "corrections": corrections,
    }
    return ai_data


def normalize_parameter_provenance(ai_data: dict) -> dict:
    """Downgrade unsupported grounding claims while preserving generated values.

    Search research can inform a parameter even when the model cannot attach a
    parameter-level URL. Such a value must remain a heuristic fallback under
    AureaSim's provenance policy rather than failing an otherwise usable run.
    """
    corrections = []
    grounded_statuses = {
        "grounded_confirmed", "grounded_proxy", "grounded_extrapolated",
    }

    def normalize(entry: dict, label: str) -> None:
        status = entry.get("evidence_status")
        source_urls = entry.get("source_urls") or []
        if status not in grounded_statuses or source_urls:
            return
        prior_rationale = entry.get("evidence_rationale", "")
        entry["evidence_status"] = "heuristic_fallback"
        entry["source_urls"] = []
        entry["evidence_rationale"] = (
            "Parameter-level grounding claim downgraded because the generator "
            "did not supply a supporting URL. "
            f"Original generator rationale: {prior_rationale or 'not provided'}"
        )
        corrections.append({"parameter": label, "original_status": status})

    for profile in ai_data.get("resource_profiles", []):
        for resource in profile.get("resource_list", []):
            normalize(resource, f"resource_cost::{resource.get('id', 'unknown')}")
    for task in ai_data.get("task_resource_distribution", []):
        for resource in task.get("resources", []):
            normalize(resource, f"task_duration::{task.get('task_id', 'unknown')}")

    ai_data.setdefault("metadata", {})["parameter_provenance_normalization"] = {
        "enabled": True,
        "corrections": corrections,
    }
    return ai_data

# -----------------
# Pydantic Schemas (Experiment Scenarios)
# -----------------

class KpiTarget(BaseModel):
    wait_times: List[str] = Field(description="List of role IDs to track for wait times (e.g., ['RKR', 'DPE'])")

class ReportSettings(BaseModel):
    title: str = Field(description="Title of the simulation experiment report")
    description: str = Field(description="A short descriptive sentence about what scenarios we are running.")
    kpis: KpiTarget

class RoleAllocation(BaseModel):
    role_id: str
    count: int = Field(
        ge=1,
        description=(
            "Positive resource headcount. Never use zero: a role assigned to a "
            "task must retain at least one resource for the process to complete."
        ),
    )

class RoleCost(BaseModel):
    role_id: str
    cost_per_hour: float

class CustomScenarioConfig(BaseModel):
    name: str = Field(description="Unique, short name without spaces")
    description: str = Field(description="One sentence describing the business assumption of this scenario, e.g. 'Tests the system under double the normal incoming demand.'")
    arrival_rate: int = Field(description="Arrival rate duration in seconds")
    resource_allocations_list: Optional[List[RoleAllocation]] = Field(default=None)
    cost_overrides_list: Optional[List[RoleCost]] = Field(default=None)

class ExperimentScenarioSchema(BaseModel):
    metadata: GenerationMetadata
    base_parameters: str = Field(description="Leave blank.")
    report_settings: ReportSettings
    scenarios: List[CustomScenarioConfig]

    @model_validator(mode='after')
    def validate_experiment_integrity(self):
        # We can't easily validate against the base JSON file here without extra context
        # but we can ensure internal consistency (e.g. role_id is uppercase/short as per instructions)
        for sc in self.scenarios:
            if sc.resource_allocations_list:
                for ra in sc.resource_allocations_list:
                    if not ra.role_id or not ra.role_id.strip():
                        raise ValueError(f"Scenario '{sc.name}' has an empty role_id in allocations.")
        return self

# -----------------
# BPMN Parser
# -----------------
def extract_semantic_context(bpmn_path):
    tree = ET.parse(bpmn_path)
    root = tree.getroot()
    
    namespaces = {
        'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
        'aurea': 'http://www.tecna.com/bpmn/aurea'  # Typical custom namespace setup
    }
    
    # 0. Extract global Aurea Role mappings
    from aureasim.role_resolver import resolve_task_roles
    resolved_tasks = resolve_task_roles(bpmn_path)
    
    # 1. Extract Tasks and use deterministic role metadata
    tasks = []
    for info in resolved_tasks.values():
        tasks.append({
            "task_id": info["task_id"],
            "task_name": info["original_task_name"],
            "clean_task_name": info["clean_task_name"],
            "resolved_role": info["role_name"],
            "role_id": info["role_id"],
            "resource_instance_id": info["resource_instance_id"],
            "role_source": info["role_source"],
            "bpmn_task_type": info["bpmn_task_type"],
            "task_class": info["task_class"],
            "task_class_source": info["task_class_source"],
            "duration_policy": info["duration_policy"],
        })

    # 2. Extract Gateways and outgoing paths
    gateways = []
    
    # Pre-parse all sequence flows to map source -> outgoing paths
    from aureasim.role_resolver import get_elements_by_local_name
    seq_out_map = {}
    for seq in get_elements_by_local_name(root, 'sequenceFlow'):
        src = seq.get('sourceRef')
        seq_id = seq.get('id')
        seq_name = seq.get('name', '')
        if src:
            if src not in seq_out_map:
                seq_out_map[src] = []
            seq_out_map[src].append({"path_id": seq_id, "path_name": seq_name})
            
    for gw in get_elements_by_local_name(root, {'exclusiveGateway', 'inclusiveGateway'}):
        gw_id = gw.get('id')
        gw_name = gw.get('name', 'Unnamed Gateway')
        
        outgoing = seq_out_map.get(gw_id, [])
        
        # Only add gateways that actually branch
        if len(outgoing) > 1:
            gateways.append({
                "gateway_id": gw_id,
                "gateway_name": gw_name,
                "outgoing_paths": outgoing
            })

        
    return {"tasks": tasks, "gateways": gateways}

# -----------------
# Phase 1: Research via Google Search Grounding
# -----------------
def _research_with_search(client, roles: list, tasks: list, context: str = "") -> dict:
    """
    Phase 1 of two-phase generation.
    Uses Google Search grounding to retrieve real salary and benchmark data.
    Returns a dict with 'brief' (plain text research summary) and 'urls' (list of source URLs).
    Falls back gracefully if search is unavailable.
    """
    role_names = ", ".join(set(t.get("resolved_role") or "Unknown" for t in tasks))
    task_role_pairs = "\n    ".join(
        f"- Task: {prompt_task_name(t)} | Role: {t.get('resolved_role') or t.get('role_id') or 'Unknown'}"
        for t in tasks[:8]
    )
    context_hint = f" The process operates in the following context: {context}." if context else ""

    search_prompt = f"""
    You are a research assistant for a business process simulation project.{context_hint}
    I need REAL, empirically grounded data for the following roles and tasks in a BPMN process.

    ROLES: {role_names}
    TASKS AND RESPONSIBLE ROLES (sample):
    {task_role_pairs}

    Please search the web and provide:
    1. Median or average hourly salary/cost for each role (in PLN or EUR, converted if needed).
    2. Standard ACTIVE PROCESSING (TOUCH/SERVICE) TIME benchmarks for the listed tasks.
    3. Any relevant industry frameworks (APQC, ISO standards, Lean Six Sigma benchmarks) that apply.

    TIME-MEASURE RULES:
    - Task execution duration means continuous hands-on resource service time for one task instance.
    - Keep queue time, waiting for approval, handoff delay, SLA/resolution time, and end-to-end
      cycle/lead/turnaround time separate from active processing time.
    - Never present a multi-step or entry-to-approval cycle-time benchmark as a task execution time.
    - If only elapsed/cycle time is available, label it diagnostic-only and state that it must not
      be used as the task duration. Do not infer touch time from it without explicit evidence.

    Be specific. Cite your sources with exact URLs. If you cannot find data for a specific role or task,
    state that clearly rather than guessing.
    """

    try:
        search_response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=search_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1
            )
        )
        brief = search_response.text

        # Extract grounding URL+title pairs from the response metadata
        urls = []
        sources = []
        if hasattr(search_response, 'candidates') and search_response.candidates:
            candidate = search_response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                gm = candidate.grounding_metadata
                if hasattr(gm, 'grounding_chunks') and gm.grounding_chunks:
                    for chunk in gm.grounding_chunks:
                        if hasattr(chunk, 'web') and chunk.web and hasattr(chunk.web, 'uri'):
                            uri = chunk.web.uri
                            real_url = resolve_redirect(uri)
                            urls.append(real_url)
                # Always derive titles from the resolved URLs so sources[i] always matches urls[i]
                sources = [url_to_readable_title(u) for u in urls]

        return {
            "brief": brief,
            "urls": urls,
            "sources": sources,
            "success": True,
            "research_model": "gemini-2.5-flash",
        }

    except Exception as e:
        print(f"\n  [!] Web search phase unavailable ({type(e).__name__}). Falling back to heuristic estimation.")
        return {
            "brief": "",
            "urls": [],
            "sources": [],
            "success": False,
            "research_model": "gemini-2.5-flash",
            "fallback_note": "Web search unavailable. Values are heuristic estimates based on BPMN semantic analysis only."
        }

def _heuristic_research_disabled() -> dict:
    """
    Experiment/reproducibility mode: deliberately skip external grounding.
    Values generated downstream are heuristic estimates based on BPMN semantics
    and process context only.
    """
    return {
        "brief": "",
        "urls": [],
        "sources": [],
        "success": False,
        "mode": "heuristic",
        "grounding_mode": "heuristic",
        "grounding_status": "disabled_by_experiment",
        "research_model": None,
        "fallback_note": (
            "Grounding intentionally disabled. Values are heuristic estimates "
            "based on BPMN semantic analysis, role labels, task labels, and process context only."
        ),
    }


def _frozen_evidence_research(evidence: dict) -> dict:
    """Normalize a locally frozen, reviewed evidence packet for generation.

    This deliberately does not call an external service. It supports controlled
    comparisons where every repetition receives identical evidence.
    """
    brief = str(evidence.get("brief", "")).strip()
    urls = evidence.get("urls", [])
    sources = evidence.get("sources", [])
    if not brief or not isinstance(urls, list) or not isinstance(sources, list):
        raise ValueError("Frozen evidence requires a non-empty brief plus URL and source lists.")
    return {
        "brief": brief,
        "urls": urls,
        "sources": sources,
        "success": True,
        "mode": "frozen_evidence",
        "grounding_mode": "frozen_evidence",
        "grounding_status": "reviewed_packet",
        "research_model": None,
    }

def _research_scenarios_with_search(client, context: str = "") -> dict:
    """
    Phase 1 for Experiment Scenarios.
    Uses Google Search grounding to retrieve stress-testing benchmarks.
    """
    context_hint = f" The process operates in the following context: {context}." if context else ""
    
    search_prompt = f"""
    You are a research assistant for a business process simulation project.{context_hint}
    I need REAL, empirically grounded capacity planning data and stress-testing methodologies.
    
    Please search the web and provide:
    1. Industry standard stress-testing methodologies and 'What-If' scenarios (e.g. Erlang-C, queueing theory).
    2. Typical capacity bottlenecks for this industry.
    3. Reasonable percentage ranges for stress testing (e.g., peak demand spikes, resource absenteeism rates).
    
    Be specific. Cite your sources with exact URLs.
    """
    
    try:
        search_response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=search_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1
            )
        )
        brief = search_response.text

        # Extract grounding URL+title pairs from the response metadata
        urls = []
        sources = []
        if hasattr(search_response, 'candidates') and search_response.candidates:
            candidate = search_response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                gm = candidate.grounding_metadata
                if hasattr(gm, 'grounding_chunks') and gm.grounding_chunks:
                    for chunk in gm.grounding_chunks:
                        if hasattr(chunk, 'web') and chunk.web and hasattr(chunk.web, 'uri'):
                            uri = chunk.web.uri
                            real_url = resolve_redirect(uri)
                            urls.append(real_url)
                sources = [url_to_readable_title(u) for u in urls]

        return {"brief": brief, "urls": urls, "sources": sources, "success": True}

    except Exception as e:
        print(f"\n  [!] Web search phase unavailable ({type(e).__name__}). Falling back to heuristic estimation.")
        return {
            "brief": "",
            "urls": [],
            "sources": [],
            "success": False,
            "fallback_note": "Web search unavailable. Scenarios will be ideated purely via internal LLM heuristics."
        }

# -----------------
# Generate Request
# -----------------
SOURCE_REQUIRED_STATUSES = {
    "grounded_confirmed",
    "grounded_proxy",
    "grounded_extrapolated",
}

SOURCE_FORBIDDEN_STATUSES = {
    "heuristic_fallback",
    "structural_value",
}

def _validate_evidence_source_consistency(
    *,
    label: str,
    status: str,
    source_urls: list,
) -> None:
    if status in SOURCE_REQUIRED_STATUSES and not source_urls:
        raise ValueError(
            f"{label} has evidence_status={status} but no source_urls"
        )

    if status in SOURCE_FORBIDDEN_STATUSES and source_urls:
        raise ValueError(
            f"{label} has evidence_status={status} but source_urls is not empty"
        )

def validate_parameter_provenance(ai_data: dict) -> None:
    allowed = EVIDENCE_STATUSES

    for profile in ai_data.get("resource_profiles", []):
        for resource in profile.get("resource_list", []):
            rid = resource.get("id")
            status = resource.get("evidence_status")

            if status not in allowed:
                raise ValueError(
                    f"Resource {rid} missing/invalid evidence_status: {status}"
                )
            if "source_urls" not in resource:
                raise ValueError(f"Resource {rid} missing source_urls")
            if "evidence_rationale" not in resource:
                raise ValueError(f"Resource {rid} missing evidence_rationale")

            _validate_evidence_source_consistency(
                label=f"Resource {rid}",
                status=status,
                source_urls=resource.get("source_urls", []),
            )

    for task_entry in ai_data.get("task_resource_distribution", []):
        task_id = task_entry.get("task_id")

        for resource_entry in task_entry.get("resources", []):
            status = resource_entry.get("evidence_status")

            if status not in allowed:
                raise ValueError(
                    f"Task {task_id} missing/invalid evidence_status: {status}"
                )
            if "source_urls" not in resource_entry:
                raise ValueError(f"Task {task_id} missing source_urls")
            if "evidence_rationale" not in resource_entry:
                raise ValueError(f"Task {task_id} missing evidence_rationale")

            _validate_evidence_source_consistency(
                label=f"Task {task_id}",
                status=status,
                source_urls=resource_entry.get("source_urls", []),
            )

def semantic_context_for_prompt(semantics):
    """Keep recovery fallbacks internal rather than encouraging their repetition."""
    prompt_semantics = deepcopy(semantics)
    for task in prompt_semantics.get("tasks", []):
        policy = task.get("duration_policy")
        if policy:
            policy.pop("fallback_seconds", None)
            policy.pop("std_seconds", None)
            policy["selection_instruction"] = (
                "Infer a task-specific active-service mean inside these bounds; "
                "do not use a universal default."
            )
    return prompt_semantics


def generate_base_prosimos_json(
    bpmn_path,
    api_key,
    industry_context: str = "",
    progress_callback=None,
    generation_mode: str = "grounded",
    frozen_evidence: dict | None = None,
):
    if not genai:
        raise ImportError("google-genai library is missing! Cannot launch AI predictor.")
    
    allowed_modes = {"grounded", "heuristic", "frozen_evidence"}
    if generation_mode not in allowed_modes:
        raise ValueError(
            f"Unsupported generation_mode={generation_mode!r}. "
            f"Expected one of: {sorted(allowed_modes)}"
        )

    client = genai.Client(api_key=api_key)
    
    semantics = extract_semantic_context(bpmn_path)

    # --- Phase 1: Optional Web Research ---
    if generation_mode == "heuristic":
        msg = "AI Phase 1/2: Skipping web grounding; using heuristic mode..."
        if progress_callback:
            progress_callback(msg)
        print(f"  [AI] {msg}")
        research = _heuristic_research_disabled()
    elif generation_mode == "frozen_evidence":
        msg = "AI Phase 1/2: Using locally frozen reviewed evidence..."
        if progress_callback:
            progress_callback(msg)
        print(f"  [AI] {msg}")
        if frozen_evidence is None:
            raise ValueError("frozen_evidence mode requires a frozen evidence packet")
        research = _frozen_evidence_research(frozen_evidence)
    else:
        msg = "AI Phase 1/2: Searching the web for empirical benchmarks..."
        if progress_callback:
            progress_callback(msg)
        print(f"  [AI] {msg}")
        research = _research_with_search(
            client=client,
            roles=semantics.get("tasks", []),
            tasks=semantics.get("tasks", []),
            context=industry_context,
        )
        research["mode"] = "grounded"
        research["grounding_mode"] = "web_grounded"
        research["grounding_status"] = "success" if research.get("success") else "failed_fallback"

    research_section = ""
    if research["success"] and research["brief"]:
        evidence_origin = (
            "Locally frozen, reviewed evidence packet"
            if generation_mode == "frozen_evidence"
            else "Retrieved via Google Search"
        )
        research_section = f"""
    EMPIRICAL RESEARCH DATA ({evidence_origin} - treat as candidate evidence):
    {research['brief']}

    CRITICAL: Base cost_per_hour and duration estimates on relevant evidence above, but first
    verify that every duration is ACTIVE TOUCH/SERVICE TIME for one task instance. Never use
    queue time, approval waiting, SLA/resolution time, or end-to-end cycle/lead/turnaround time
    as a Prosimos task duration. Where active service time is unavailable, use a conservative
    semantic fallback and state so in the rationale.
    """
    else:
        if generation_mode == "heuristic":
            research_section = """
    HEURISTIC GENERATION MODE:
    External grounding has been intentionally disabled for this run.
    Estimate costs, durations, arrival rates, and gateway probabilities from BPMN task labels,
    role labels, process context, and general domain knowledge only.

    CRITICAL:
    - Do not claim that values are externally sourced.
    - State clearly in metadata that values are heuristic estimates.
    - Use conservative, plausible ranges for exploratory simulation.
    """
        else:
            research_section = """
    NOTE: Web search was unavailable. Use semantic analysis of task names and roles
    to make reasonable estimates. Be honest in the metadata that these are heuristic values.
    """

    # --- Phase 2: Structured JSON Generation ---
    msg = "AI Phase 2/2: Generating structured simulation parameters..."
    if progress_callback: progress_callback(msg)
    print(f"  [AI] {msg}")
    task_mappings = []
    role_mappings = {}
    for t in semantics.get("tasks", []):
        task_mappings.append(
            f"Task '{prompt_task_name(t)}' ({t['task_id']}; class={t.get('task_class', 'active_human')}; "
            f"class_source={t.get('task_class_source', 'default')}) "
            f"-> '{t['resource_instance_id']}'"
        )
        role_mappings[t['role_id']] = t['resource_instance_id']
        
    role_mapping_str = "\n    ".join([f"Role '{r_id}' -> '{r_inst}'" for r_id, r_inst in role_mappings.items()])
    task_mapping_str = "\n    ".join(task_mappings)

    if generation_mode == "heuristic":
        parameter_instruction = (
            "Resource assignment is fixed and deterministic. You MUST NOT choose or change the resource assigned to each task.\n"
            "    Estimate only:\n"
            "    - cost_per_hour for each role (heuristic, source-free estimates),\n"
            "    - duration distribution for each task,\n"
            "    - arrival rate,\n"
            "    - gateway probabilities."
        )
    else:
        parameter_instruction = (
            "Resource assignment is fixed and deterministic. You MUST NOT choose or change the resource assigned to each task.\n"
            "    Estimate only:\n"
            "    - cost_per_hour for each role (base this on the research data above),\n"
            "    - duration distribution for each task,\n"
            "    - arrival rate,\n"
            "    - gateway probabilities."
        )

    prompt = f"""
    You are an expert BPM simulation specialist using the Prosimos stochastic simulation engine.
    I have a BPMN process mapped below.
    {research_section}
    BPMN SEMANTICS:
    {json.dumps(semantic_context_for_prompt(semantics), indent=2)}

    INSTRUCTIONS:
    1. {parameter_instruction}
    
    For resource_profiles, create exactly these roles:
    {role_mapping_str}

    For each task, use exactly this resource_id in task_resource_distribution:
    {task_mapping_str}

    PARAMETER-LEVEL EVIDENCE RULES:
    For every resource cost and every task duration, you MUST provide:
    - evidence_status
    - source_urls
    - evidence_rationale

    Use evidence_status exactly as follows:
    - grounded_confirmed: use only when the value is directly supported by retrieved source data for the same role/task or a very close equivalent.
    - grounded_proxy: use when the value is based on a related sourced role/task, but not the exact one.
    - grounded_extrapolated: use when the value is derived from retrieved source context but is not directly stated.
    - heuristic_fallback: use when no relevant source was found and the value is estimated from process semantics or general knowledge.
    - structural_value: use for deterministic non-labor/system values, such as System or Customer cost = 0.

    Never use grounded_confirmed, grounded_proxy, or grounded_extrapolated unless at least one relevant source URL is included in source_urls. If you cannot attach a source URL to that specific parameter, classify it as heuristic_fallback.

    For grounded_confirmed, grounded_proxy, or grounded_extrapolated, include relevant source_urls.
    For heuristic_fallback, source_urls must be empty.
    For structural_value, source_urls must be empty unless a source is genuinely needed.
    evidence_rationale must explain the value at parameter level, not only at process level.

    2. Create `task_resource_distribution` for EVERY task. Use normal distribution mean/stddev (SECONDS).
       Format: [mean, stddev, 0, 9999999]
       The mean is ACTIVE RESOURCE SERVICE (TOUCH) TIME for one task instance only.
       Exclude all queueing, waiting for another person, handoff, batching, SLA/resolution,
       and end-to-end cycle/lead/turnaround time. A benchmark stated in days is normally elapsed
       time and MUST NOT be used unless it explicitly says a resource works continuously for that duration.
       A task with `task_class` equal to `external_wait` is not human service work; assign it a
       near-zero structural duration. The deterministic guardrail will enforce that classification.
       A task with `task_class` equal to `short_transaction` is a brief human interaction (for
       example, confirming, routing, recording, or approving without substantive review). Its
       active service-time mean must obey its task-level `duration_policy` bounds, which are in
       seconds. Infer a task-specific value inside those bounds; no universal default is supplied.
       Do not assign it a generic multi-minute office-work duration. A task called
       "review" or "verify" is not a short transaction unless its BPMN class explicitly says so.
    3. Create `gateway_branching_probabilities` summing to 1.0 per gateway.
    4. arrival_time: Estimate the realistic case arrival rate for this process.
       - Express as a frequency: how many cases arrive per unit of time (e.g. 3 per week, 10 per day).
       - Base your estimate on the industry context, process name, and any research data above.
       - Provide a clear business rationale explaining your reasoning.
    5. metadata:
       ...
    NAMING RULES:
    - Role profile IDs must exactly match the listed role IDs.
    - Resource instance IDs must exactly match the listed resource instance IDs.
    - Do not invent additional roles or resources.
    """

    generation_result = generate_with_fallback(
        client=client,
        prompt=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ProsimosPredictedBase,
            temperature=0.4
        ),
        return_model=True,
    )
    # Keep compatibility with injected test doubles and third-party wrappers
    # that still return only the response object.
    if isinstance(generation_result, tuple):
        response, generation_model = generation_result
    else:
        response = generation_result
        reported_model = getattr(response, "model_version", None)
        generation_model = reported_model if isinstance(reported_model, str) else "unrecorded_legacy_response"
    
    ai_data = json.loads(response.text)
    
    # --- Phase 2b: Strict Missing Task Validation ---
    expected_task_ids = {t["task_id"] for t in semantics.get("tasks", [])}
    generated_task_ids = {t.get("task_id") for t in ai_data.get("task_resource_distribution", [])}
    missing_tasks = expected_task_ids - generated_task_ids
    
    if missing_tasks:
        missing_tasks_list = list(missing_tasks)
        msg_fix = f"AI missed tasks: {missing_tasks_list}. Requesting corrections..."
        if progress_callback: progress_callback(f"[AI] {msg_fix}")
        print(f"  [!] {msg_fix}")
        
        missing_semantics = [t for t in semantics.get("tasks", []) if t["task_id"] in missing_tasks]
        
        fix_prompt = f"""
        You missed some tasks in your previous generation.
        Generate the `task_resource_distribution` entries for the following missing tasks:
        {json.dumps(missing_semantics, indent=2)}
        
        You MUST assign them to one of the following existing resource profiles:
        {json.dumps(ai_data.get("resource_profiles", []), indent=2)}
        
        Remember: The 'resource_id' MUST exactly match an 'id' from the resource_profiles list provided above.
        """
        
        fix_response = generate_with_fallback(
            client=client,
            prompt=fix_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MissingTasksFix,
                temperature=0.2
            )
        )
        
        fix_data = json.loads(fix_response.text)
        if "task_resource_distribution" not in ai_data:
            ai_data["task_resource_distribution"] = []
        ai_data["task_resource_distribution"].extend(fix_data.get("task_resource_distribution", []))
    
    # Inject guaranteed generic calendars (AI doesn't generate these reliably)
    ai_data["resource_calendars"] = [
        {
            "id": "Standard_Working_Hours",
            "name": "Standard Working Hours",
            "time_periods": [{"beginTime": "08:00:00", "endTime": "16:00:00", "from": "MONDAY", "to": "FRIDAY"}]
        },
        {
            "id": "24_7_Calendar",
            "name": "24/7 System Calendar",
            "time_periods": [{"beginTime": "00:00:00", "endTime": "23:59:59", "from": "MONDAY", "to": "SUNDAY"}]
        }
    ]
    ai_data["arrival_time_calendar"] = [
        {"beginTime": "08:00:00", "endTime": "16:00:00", "from": "MONDAY", "to": "FRIDAY"}
    ]
    
    # --- Strict Deterministic Resource Post-Processing ---
    ai_data = apply_deterministic_resources(ai_data, semantics)

    if generation_mode == "heuristic":
        for profile in ai_data.get("resource_profiles", []):
            for resource in profile.get("resource_list", []):
                if resource.get("cost_per_hour", 0) == 0:
                    resource["evidence_status"] = "structural_value"
                    resource["evidence_rationale"] = (
                        "Structural non-labor resource; zero hourly labor cost."
                    )
                else:
                    resource["evidence_status"] = "heuristic_fallback"
                    resource["evidence_rationale"] = (
                        "Heuristic-mode generation; external grounding intentionally disabled."
                    )
                resource["source_urls"] = []

        for task_entry in ai_data.get("task_resource_distribution", []):
            for resource_entry in task_entry.get("resources", []):
                resource_entry["evidence_status"] = "heuristic_fallback"
                resource_entry["source_urls"] = []
                resource_entry["evidence_rationale"] = (
                    "Heuristic-mode generation; external grounding intentionally disabled."
                )

    ai_data = normalize_parameter_provenance(ai_data)
    ai_data = stabilize_task_durations(ai_data, semantics)

    # Convert AI-chosen frequency to mean_seconds for Prosimos
    _UNIT_SECS = {
        'second': 1, 'minute': 60, 'hour': 3600,
        'day': 86400, 'week': 604800, 'month': 2592000
    }
    freq = ai_data.get("arrival_time", {}).get("frequency", {})
    events = freq.get("events", 1.0) or 1.0
    per_count = freq.get("per_count", 1.0) or 1.0
    per_unit = freq.get("per_unit", "week")
    mean_secs = (_UNIT_SECS.get(per_unit, 604800) * per_count) / events

    ai_data["arrival_time_distribution"] = {
        "distribution_name": "expon",
        "distribution_params": [{"value": 0}, {"value": round(mean_secs, 2)}, {"value": 0}, {"value": 9999999}],
        "frequency": freq  # kept for UI display
    }
    ai_data["process_model"] = os.path.basename(bpmn_path)
    ai_data["metadata"]["generated_at"] = datetime.now().isoformat()
    ai_data["metadata"]["grounding_mode"] = research.get("grounding_mode", "web_grounded")
    ai_data["metadata"]["grounding_status"] = research.get("grounding_status", "unknown")
    ai_data["metadata"]["generation_model"] = generation_model
    ai_data["metadata"]["research_model"] = research.get("research_model")
    ai_data["metadata"]["generation_temperature"] = 0.4
    ai_data["metadata"]["resource_assignment_policy"] = {
        "mode": "deterministic_bpmn_role_binding",
        "priority_order": [
            "aurea_responsibleRef",
            "bpmn_lane",
            "task_label_suffix",
            "task_id_fallback"
        ],
        "enforced": True
    }

    ai_data["metadata"]["parameter_provenance_policy"] = {
        "enabled": True,
        "evidence_statuses": [
            "grounded_confirmed",
            "grounded_proxy",
            "grounded_extrapolated",
            "heuristic_fallback",
            "structural_value",
        ],
        "scope": "resource_costs_and_task_duration_means",
    }

    # Inject real URLs from web search grounding, or explicitly clear them for heuristic/fallback mode.
    if research.get("success") and research.get("urls"):
        ai_data["metadata"]["source_urls"] = research["urls"]
        ai_data["metadata"]["sources"] = [url_to_readable_title(u) for u in research["urls"]]
    else:
        note = research.get("fallback_note", "")
        ai_data["metadata"]["source_urls"] = []
        ai_data["metadata"]["sources"] = [note] if note else []
        
    # Inject a task name mapping to help analytical scripts match task_ids to human-readable clean names
    task_name_map = {}
    for t in semantics.get("tasks", []):
        task_name_map[t["task_id"]] = {
            "task_name": t.get("task_name", ""),
            "clean_task_name": t.get("clean_task_name", ""),
            "resolved_role": t.get("resolved_role", "")
        }
    ai_data["metadata"]["task_name_map"] = task_name_map

    # Dump research context log to file for provenance testing
    research_log_path = os.path.join(os.path.dirname(bpmn_path), "research_log.json")
    with open(research_log_path, 'w', encoding='utf-8') as f:
        json.dump(research, f, indent=4)

    # Dump generated Base_params to file
    out_path = os.path.join(os.path.dirname(bpmn_path), f"AutoGenerated_Base_params.json")
    validate_parameter_provenance(ai_data)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(ai_data, f, indent=4)
        
    return out_path

def generate_project_branding(process_name: str, api_key: str = None) -> ProjectBranding:
    """
    Uses the LLM to determine a representative icon and color for a project.
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key or not genai:
        # Static fallback if no API
        return ProjectBranding(icon="mdi-chart-timeline-variant", color="indigo")

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are a UI designer for AureaSim, a business process simulation toolkit.
    Based on the business process name below, suggest a Material Design Icon (MDI) and a harmonic Material color.
    
    Process Name: {process_name}
    
    Rules:
    1. Icon must be a valid MDI name (e.g., 'mdi-account-group', 'mdi-cart', 'mdi-wrench').
    2. Color must be a standard Material color (e.g., 'blue', 'green', 'orange', 'purple', 'teal', 'deep-purple', 'amber').
    3. Choose icons that reflect the domain (e.g., 'mdi-currency-usd' for Sales, 'mdi-account-cog' for HR, 'mdi-bag-suitcase' for Vacations/Leave).
    """
    
    try:
        config = types.GenerateContentConfig(
            response_mime_type='application/json',
            response_schema=ProjectBranding,
            temperature=0.2
        )
        
        response = generate_with_fallback(client, prompt, config)
        return ProjectBranding.model_validate_json(response.text)
    except Exception as e:
        print(f"  [!] Branding generation failed: {e}")
        return ProjectBranding(icon="mdi-chart-timeline-variant", color="indigo")

def generate_experiment_json(bpmn_path, base_json_path, api_key, num_scenarios=3, industry_context: str = "", progress_callback=None, generation_mode: str = "grounded"):
    """
    Reads the base_params.json to understand current roles/costs,
    then queries Gemini to ideate and construct an experiment.json.
    Uses two-phase generation: Phase 1 searches the web for stress-testing benchmarks,
    Phase 2 produces the structured JSON grounded in that research.
    """
    if not genai:
        raise ImportError("google-genai library is missing! Cannot launch AI predictor.")
    client = genai.Client(api_key=api_key)
    process_name = humanize_name(Path(bpmn_path).stem)
    
    with open(base_json_path, 'r', encoding='utf-8') as f:
        base_data = json.load(f)
        
    active_roles = {}
    for rp in base_data.get("resource_profiles", []):
        resource_list = rp.get("resource_list", [])
        active_roles[rp["id"]] = {
            "name": rp["name"],
            "cost_per_hour": resource_list[0].get("cost_per_hour", 30) if resource_list else 30,
            "starting_amount": sum(int(resource.get("amount", 1)) for resource in resource_list) if resource_list else 1,
        }
        
    # --- Phase 1: Research stress-testing methodologies ---
    if generation_mode == "heuristic":
        msg = "AI Phase 1/2: Skipping web grounding; using heuristic mode..."
        if progress_callback: progress_callback(msg)
        print(f"  [AI] {msg}")
        research = _heuristic_research_disabled()
    else:
        msg = "AI Phase 1/2: Searching for capacity planning benchmarks..."
        if progress_callback: progress_callback(msg)
        print(f"  [AI] {msg}")
        research = _research_scenarios_with_search(
            client=client,
            context=industry_context
        )

    research_section = ""
    if research["success"] and research["brief"]:
        research_section = f"""
    CAPACITY PLANNING RESEARCH (via Google Search - use as scientific grounding):
    {research['brief']}
    """

    # --- Phase 2: Structured scenario generation ---
    msg = "AI Phase 2/2: Designing experiment scenarios..."
    if progress_callback: progress_callback(msg)
    print(f"  [AI] {msg}")
    prompt = f"""
    You are an expert BPM simulation analyst designing experiments for the '{process_name}' process.
    {research_section}
    Starting runtime configuration:
    {json.dumps(active_roles, indent=2)}

    INSTRUCTIONS:
    1. Design EXACTLY {num_scenarios} diverse, realistic "What-If" scenarios. You MUST output exactly {num_scenarios} scenarios in total.
    2. Start with 'A_Baseline' using exact starting amounts and arrival_rate around 144000 seconds.
    3. For the remaining scenarios, create stress scenarios (e.g. 'B_Peak_Load') or recovery scenarios.
    4. For each scenario, write a concise 'description' (1 sentence) summarizing the business assumption, e.g. "Tests maximum capacity under a 14x increase in demand."
    5. Ensure kpis.wait_times contains exactly: {list(active_roles.keys())}
    6. Every resource allocation count MUST be a positive integer (at least 1). Never use 0.
       A zero-resource role would make its mapped tasks impossible to complete. If a role's
       baseline headcount is 1, do not create a staff-reduction/total-absence scenario for
       that role. Choose a demand stress, capacity reinforcement, or another feasible scenario.
    7. Use only these exact role IDs in resource allocations: {list(active_roles.keys())}
    8. metadata:
       - methodology: Name the specific stress-testing methodology used (e.g., "Erlang-C queueing model").
       - sources: Reference the research data retrieved above and any capacity planning theories applied.
       - source_urls: Leave as empty list [] - URLs will be injected automatically.
       - rationale: Explain the What-If goal of each scenario in business terms.
    """
    
    response = generate_with_fallback(
        client=client,
        prompt=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExperimentScenarioSchema,
            temperature=0.4
        )
    )
    
    ai_data = json.loads(response.text)
    
    # Inject timestamp and real source titles+URLs
    ai_data["metadata"]["generated_at"] = datetime.now().isoformat()
    if research["success"] and research["urls"]:
        ai_data["metadata"]["source_urls"] = research["urls"]
        if research.get("sources"):
            ai_data["metadata"]["sources"] = research["sources"]
    else:
        note = research.get("fallback_note", "")
        ai_data["metadata"]["source_urls"] = []
        if note and not ai_data["metadata"].get("sources"):
            ai_data["metadata"]["sources"] = [note]
    
    # Force the generated path to be dynamically correct
    ai_data["base_parameters"] = os.path.basename(base_json_path)
    
    # Map generated strictly-modelled lists back to standard python Dictionaries for Prosimos
    for sc in ai_data.get("scenarios", []):
        allocs = sc.pop("resource_allocations_list", None)
        if allocs:
            sc["resource_allocations"] = {x["role_id"]: x["count"] for x in allocs}
            
        costs = sc.pop("cost_overrides_list", None)
        if costs:
            sc["cost_overrides"] = {x["role_id"]: x["cost_per_hour"] for x in costs}
    target_path = os.path.join(str(Path(bpmn_path).parent), f"AutoGenerated_Experiment_Scenarios.json")
    with open(target_path, "w", encoding='utf-8') as f:
        json.dump(ai_data, f, indent=4)
        
    return target_path

def generate_executive_summary(results_df, scenarios, report_settings, api_key, base_config=None, exp_config=None, references=None):
    """
    Sends the aggregated tabular data and scenario configurations to Gemini to
    narrate a comprehensive Business Process Executive Summary with inline citations.
    """
    if not genai:
        raise ImportError("google-genai library is missing! Cannot launch AI predictor.")
    client = genai.Client(api_key=api_key)

    # Format the inputs for the LLM
    tabular_results = results_df.to_csv(index=False)
    scenario_configs = json.dumps(scenarios, indent=2)
    base_params = json.dumps(base_config, indent=2) if base_config else "{}"
    experiment_metadata = json.dumps(exp_config.get("metadata", {}), indent=2) if exp_config else "{}"
    title = humanize_name(report_settings.get("title", "Simulation Experiment"))

    # Build numbered reference list for inline citations
    references = references or []
    if references:
        ref_lines = [f"[{i+1}] {r['title']}" for i, r in enumerate(references)]
        references_block = "AVAILABLE REFERENCES (for inline citations):\n" + "\n".join(ref_lines)
        citation_instruction = (
            "CITATION RULE: Whenever you state a fact that is supported by any of the AVAILABLE REFERENCES above, "
            "add the corresponding inline citation number immediately after the claim, e.g. \"Key Account Managers "
            "typically earn 80–100 PLN/hr [2].\" Only cite sources that are genuinely relevant to the claim. "
            "Do NOT add a References section - it is rendered separately."
        )
    else:
        references_block = ""
        citation_instruction = "No external references were retrieved. State assumptions clearly."
    
    prompt = f"""
    You are an expert Business Process Consultant & Data Analyst. 
    You have just finished running a Prosimos discrete-event simulation for: '{title}'.
    
    BASE MODEL PARAMETERS (From AutoGenerated_Base_params.json):
    {base_params}
    
    WHAT-IF EXPERIMENT SCENARIOS (From AutoGenerated_Experiment_Scenarios.json):
    {scenario_configs}
    
    EXPERIMENT METADATA & HYPOTHESES:
    {experiment_metadata}
    
    SIMULATION RESULTS (Quantitative outputs):
    {tabular_results}

    {references_block}

    INSTRUCTIONS:
    Write a Comprehensive Executive Summary Report detailing the experiment.
    Format your response purely in Markdown, using standard Headers (e.g. '# Header 1', '## Header 2').
    Do not use complex HTML.
    IMPORTANT: DO NOT output any Markdown tables (e.g., using '|'). Use bulleted lists and narrative paragraphs for metrics.
    INTEGRATION RULES:
    - Refer to "Table 4. Baseline Resource Setup" and "Table 5. Scenario Parameter Overrides Matrix" in your narrative description of the parameters and scenario overrides.
    - Do NOT list the raw resource profiles, amounts, hourly rates, or arrival rate numbers in raw bullet lists; describe their significance, assumptions, and business rationale instead.
    NAMING RULES (strictly enforced):
    - NEVER use raw technical identifiers: no 'Task_ReviewOffer', no 'RES_Sales_Process', no 'Gateway_XYZ'.
    - Always use the human-readable task name (e.g. 'Review Offer', not 'Task_ReviewOffer').
    - Always use the human-readable process title (e.g. 'Sales Process', not 'RES_Sales_Process').
    - Resolve any underscores and CamelCase from all names before writing them.
    {citation_instruction}

    Your report MUST include these sections:
    1. Executive Overview
    2. Model Parameterization (Base): Discuss base configuration parameters, work calendars, and cost assumptions using references to Table 4. Cite relevant sources inline.
    3. Scenario Matrix & Hypothesis (Experiments): Detail every scenario hypothesis and parameter tweaks, referencing Table 5.
    4. Detailed Breakdown: Outcome of EVERY scenario based on the numeric results.
    5. Deep Dive Discussion: Bottleneck resolutions, cycle time tradeoffs, cost implications across scenarios.
    6. Strategic Recommendations for the business based on the data.
    DO NOT include a References section - it is appended automatically.
    """
    
    response = generate_with_fallback(
        client=client,
        prompt=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3
        )
    )
    
    return response.text


