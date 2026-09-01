import json
import os
import copy
import subprocess
import xml.etree.ElementTree as ET
import shutil
import sys
import re

# ── Intermediate-event helpers ───────────────────────────────────────────────

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"


def _resolve_prosimos_bin() -> str | None:
    """Locate Prosimos without requiring virtual-environment activation.

    Launching ``.venv/Scripts/python.exe`` directly does not prepend that
    Scripts directory to PATH on Windows, even though console entry points
    installed for the interpreter live there.
    """
    configured = os.getenv("PROSIMOS_BIN")
    if configured:
        return configured

    on_path = shutil.which("prosimos")
    if on_path:
        return on_path

    executable_name = "prosimos.exe" if os.name == "nt" else "prosimos"
    beside_python = os.path.join(os.path.dirname(sys.executable), executable_name)
    if os.path.isfile(beside_python):
        return beside_python

    return None

def _intermediate_event_ids_from_bpmn(bpmn_path: str) -> list:
    """Return IDs of all intermediate catch / boundary events in the BPMN."""
    ids = []
    try:
        tree = ET.parse(bpmn_path)
        root = tree.getroot()
        for tag in ("intermediateCatchEvent", "boundaryEvent", "intermediateThrowEvent"):
            for el in root.iter(f"{{{_BPMN_NS}}}{tag}"):
                eid = el.get("id")
                if eid:
                    ids.append(eid)
    except Exception:
        pass
    return ids

def _ensure_event_distributions(config: dict, bpmn_path: str) -> None:
    """Inject a fix(0) distribution for every BPMN intermediate event that is
    not already listed in config['event_distribution'], so Prosimos never
    raises a KeyError in event_duration()."""
    if "event_distribution" not in config:
        config["event_distribution"] = []
    existing = {e["event_id"] for e in config["event_distribution"]}
    for eid in _intermediate_event_ids_from_bpmn(bpmn_path):
        if eid not in existing:
            config["event_distribution"].append({
                "event_id": eid,
                "distribution_name": "fix",
                "distribution_params": [{"value": 0}]
            })
            print(f"  [Executor] Added missing event distribution for: {eid}")

def extract_hourly_rates(base_config):
    """Dynamically reads hourly rates from a Prosimos JSON config dict."""
    rates = {}
    for profile in base_config.get('resource_profiles', []):
        for res in profile.get('resource_list', []):
            rates[res['id']] = res.get('cost_per_hour', 0)
            rates[res['name']] = res.get('cost_per_hour', 0)
    return rates


def _validate_scenario_resource_allocations(scenario_def: dict, base_config: dict) -> dict:
    """Reject scenario staffing that cannot be represented faithfully.

    Every resource profile assigned to a task must retain at least one resource.
    Silently coercing zero to one makes the simulation run, but changes the
    business meaning of the scenario and invalidates its interpretation.
    """
    allocations = scenario_def.get("resource_allocations") or {}
    known_profiles = [
        profile.get("id")
        for profile in base_config.get("resource_profiles", [])
        if profile.get("id")
    ]
    normalized_profiles = {}
    for profile_id in known_profiles:
        normalized = re.sub(r"[^a-z0-9]", "", profile_id.lower())
        normalized_profiles.setdefault(normalized, []).append(profile_id)
    scenario_name = scenario_def.get("name", "<unnamed>")
    validated = {}

    for profile_id, count in allocations.items():
        resolved_profile_id = profile_id
        if profile_id not in known_profiles:
            normalized = re.sub(r"[^a-z0-9]", "", profile_id.lower())
            matches = normalized_profiles.get(normalized, [])
            if len(matches) == 1:
                resolved_profile_id = matches[0]
            else:
                raise ValueError(
                    f"Scenario '{scenario_name}' allocates unknown resource profile "
                    f"'{profile_id}'. Known profiles: {sorted(known_profiles)}."
                )
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError(
                f"Scenario '{scenario_name}' resource allocation for "
                f"'{profile_id}' must be an integer, got {count!r}."
            )
        if count < 1:
            raise ValueError(
                f"Scenario '{scenario_name}' allocates {count} resources to "
                f"'{profile_id}'. Prosimos requires at least one resource for "
                "tasks mapped to that profile. Model temporary absence with an "
                "availability calendar, or reduce a baseline pool that contains "
                "more than one resource."
            )
        validated[resolved_profile_id] = count

    return validated

def execute_scenario(scenario_def, base_config, bpmn_path, output_log_path, total_cases=500, progress_callback=None):
    """
    Patches the base Prosimos config dynamically based on scenario definitions,
    saves the temp config, runs Prosimos, and cleans up.
    Returns the effective resource costs for that scenario.
    """
    print(f"[Executor] Running scenario: {scenario_def['name']}...")
    
    patched_config = copy.deepcopy(base_config)
    validated_allocations = _validate_scenario_resource_allocations(scenario_def, patched_config)
    
    if 'arrival_rate' in scenario_def:
        try:
            patched_config['arrival_time_distribution']['distribution_params'][1]['value'] = scenario_def['arrival_rate']
        except (KeyError, IndexError):
            print(f"  [!] Warning: Could not patch arrival rate for {scenario_def['name']}")
            
    if 'resource_allocations' in scenario_def:
        allocs = validated_allocations
        for profile in patched_config.get('resource_profiles', []):
            prof_id = profile['id']
            if prof_id in allocs:
                target_amount = allocs[prof_id]
                base_cost = profile['resource_list'][0].get('cost_per_hour', 0) if profile['resource_list'] else 0
                
                # Check for cost overrides dynamically
                cost_overrides = scenario_def.get('cost_overrides', {})
                if prof_id in cost_overrides:
                    base_cost = cost_overrides[prof_id]
                
                # Inherit the calendar (working hours) from the existing resource
                original_res = profile['resource_list'][0] if profile['resource_list'] else None
                cal = original_res.get('calendar', 'Standard_Working_Hours') if original_res else 'Standard_Working_Hours'

                # Rebuild resource list using identical IDs and Names
                new_resources = [
                    {
                        "id": f"{prof_id}_{i}", 
                        "name": f"{prof_id}_{i}", 
                        "cost_per_hour": base_cost, 
                        "amount": 1, 
                        "calendar": cal
                    } for i in range(1, target_amount + 1)
                ]
                profile['resource_list'] = new_resources
                
                # CRITICAL: Spread the workload!
                # Prosimos requires that if multiple resources can do a task, they are all listed in task_resource_distribution.
                new_resource_ids = [r['id'] for r in new_resources]
                for task_dist in patched_config.get('task_resource_distribution', []):
                    # Check if this task was originally assigned to ANY instance of this profile
                    # (The AI may have generated _1, _2, etc. in the base distribution)
                    found_assignment = False
                    old_entries_to_remove = []
                    template_entry = None
                    for r_entry in task_dist.get('resources', []):
                        r_id = r_entry.get('resource_id', '')
                        if r_id.startswith(f"{prof_id}_") or r_id == prof_id:
                            old_entries_to_remove.append(r_entry)
                            if not template_entry:
                                template_entry = copy.deepcopy(r_entry)
                                
                    if old_entries_to_remove and template_entry:
                        found_assignment = True
                        
                        # Remove ALL old entries belonging to this profile
                        task_dist['resources'] = [r for r in task_dist.get('resources', []) if r not in old_entries_to_remove]
                        
                        # Add a new identical entry for each resource in the new scaled pool
                        for r_id in new_resource_ids:
                            new_entry = copy.deepcopy(template_entry)
                            new_entry['resource_id'] = r_id
                            task_dist['resources'].append(new_entry)
                    if found_assignment:
                        continue
                
    # Safeguard for missing keys in user base JSONs
    if "task_resource_distribution" not in patched_config:
        patched_config["task_resource_distribution"] = []

    # Inject zero-duration distributions for any intermediate/boundary events
    # that the AI-generated JSON omitted — prevents Prosimos KeyError in event_duration()
    _ensure_event_distributions(patched_config, bpmn_path)

    # Save temp config for Prosimos to consume alongside the output log
    temp_dir = os.path.dirname(output_log_path) or "."
    temp_json = os.path.join(temp_dir, f'temp_{scenario_def["name"]}.json')
    with open(temp_json, 'w', encoding='utf-8') as f:
        json.dump(patched_config, f, indent=4)
        
    # Resolve prosimos binary path before entering the subprocess block,
    # so the exception handler can always report the resolved value.
    prosimos_bin = _resolve_prosimos_bin()

    if not prosimos_bin:
        msg = (
            "Could not find the Prosimos CLI. "
            "Install prosimos==1.2.4 in the active Python environment, "
            "ensure `prosimos` is available on PATH, or set "
            "PROSIMOS_BIN=/absolute/path/to/prosimos."
        )
        if progress_callback:
            progress_callback(f"  [!] Error: {msg}")
        else:
            print(f"  [!] Error: {msg}")
        raise FileNotFoundError(msg)

    try:
        subprocess.run([
            prosimos_bin, "start-simulation", 
            "--bpmn_path", bpmn_path, 
            "--json_path", temp_json, 
            "--total_cases", str(total_cases), 
            "--log_out_path", output_log_path
        ], check=True, stdout=subprocess.DEVNULL)
        # Only remove if successful to allow debugging on failure
        os.remove(temp_json)
    except FileNotFoundError:
        msg = (
            f"  [!] Error: Could not execute Prosimos binary. "
            f"Resolved value: '{prosimos_bin}'. "
            "Install prosimos==1.2.4 or set PROSIMOS_BIN."
        )
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg)
        raise
    except subprocess.CalledProcessError as e:
        print(f"  [!] Simulation failed. Preserving {temp_json} for debugging.")
        raise e
    
    # Add utf-8-sig BOM to output log so Excel on Windows reads Polish chars correctly
    try:
        with open(output_log_path, 'r', encoding='utf-8') as f_in:
            content = f_in.read()
        with open(output_log_path, 'w', encoding='utf-8-sig') as f_out:
            f_out.write(content)
    except Exception as e:
        print(f"  [!] Warning: Could not inject BOM into log file: {e}")
    
    return extract_hourly_rates(patched_config)
