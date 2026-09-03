import re
import json
import unicodedata
from pathlib import Path
import xml.etree.ElementTree as ET

LEGACY_AUREA_NAMESPACE = "http://www.tecna.com/bpmn/aurea"
CONVERTED_AUREA_NAMESPACE = "http://aurea.software/schema/2024/bpmn"
AUREA_NAMESPACES = {LEGACY_AUREA_NAMESPACE, CONVERTED_AUREA_NAMESPACE}

# These are intentionally conservative action stems, not a broad attempt to
# infer effort from every task label.  A matching substantive-work stem always
# wins: "verify and approve" remains active_human, while "approve decision"
# becomes a rapid short transaction.
SHORT_TRANSACTION_STEMS = (
    "approve", "approval", "authorize", "authorise", "authorization", "authorisation",
    "confirm", "confirmation", "acknowledge", "assign", "assignment", "route", "routing",
    "forward", "record", "register", "log", "dispatch", "send", "reject", "rejection",
    "decline", "akcept", "zatwierdz", "potwierdz", "przypis", "przekaz", "odesl",
    "odeśl", "zarejestr", "zapisz", "wyslij", "wyślij", "odrzuc", "odmow",
)
SUBSTANTIVE_WORK_STEMS = (
    "review", "verify", "validation", "validate", "check", "analyse", "analyze", "assess",
    "calculate", "prepare", "generate", "create", "complete", "correct", "enter", "describe",
    "investigate", "add", "upload", "attach", "weryfik", "sprawdz", "sprawdź", "uzupeln", "uzupełn", "popraw",
    "wprowadz", "wprowadź", "wylicz", "gener", "przygot", "utworz", "utwórz", "opis", "dod", "załad", "zalad",
)
EXTERNAL_WAIT_STEMS = (
    "wait", "await", "pending", "oczekiw", "czekaj",
)
FINANCIAL_APPROVAL_STEMS = (
    "finance", "accounting", "financial", "księg", "ksieg", "finans",
)


def _semantic_label_key(value: str) -> str:
    """Return a case- and diacritic-insensitive label key for semantic rules.

    BPMN labels may use either Polish noun forms (``Zatwierdzenie``) or an
    imperative form introduced by semantic enrichment (``Zatwierdź``).  Both
    denote the same approval action.  Unicode decomposition prevents the
    classifier from treating the latter as an unrelated label solely because
    of the final accented character.
    """
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))

def get_elements_by_local_name(root, local_names):
    if isinstance(local_names, str):
        local_names = {local_names}
    else:
        local_names = set(local_names)
        
    for elem in root.iter():
        tag = elem.tag
        local_name = tag.split('}', 1)[1] if '}' in tag else tag
        if local_name in local_names:
            yield elem

def normalize_role_id(role_name: str) -> str:
    """Convert a role name into a stable Prosimos-safe ID."""
    # replace whitespace and hyphens with _
    name = re.sub(r'[\s\-]+', '_', role_name)
    # remove non-alphanumeric/underscore characters
    name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    # collapse duplicate underscores
    name = re.sub(r'_+', '_', name)
    # strip leading/trailing underscores
    name = name.strip('_')
    
    # ensure the ID starts with a letter if Prosimos/Pydantic requires it
    if name and name[0].isdigit():
        name = "Role_" + name
        
    if not name:
        name = "System_Role"
        
    return name

def normalize_resource_instance_id(role_id: str) -> str:
    """Return role_id + '_1'."""
    return f"{role_id}_1"

def extract_suffix_role(task_name: str) -> tuple[str, str | None]:
    """
    Return clean_task_name, role_name.
    Supports:
    - Task name (Role)
    - Task name [Role]
    Only trailing suffixes count.
    """
    task_name = task_name.strip()
    m = re.search(r'^(.*?)\s*[\(\[]([^()\[\]]+)[\)\]]$', task_name)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return task_name, None


def infer_task_class(
    task_name: str,
    task_type: str,
    explicit_task_class: str | None = None,
    role_name: str | None = None,
) -> tuple[str, str]:
    """Classify a BPMN task for duration generation from explicit semantics.

    A BPMN ``aurea:taskClass`` annotation is authoritative.  Otherwise, only
    unambiguous lifecycle states and short transactional action labels receive
    a special class.  All other tasks remain ``active_human`` rather than
    receiving an unsupported low-duration assumption.
    """
    if explicit_task_class and explicit_task_class.strip():
        return explicit_task_class.strip(), "bpmn_annotation"

    normalized_type = task_type.casefold()
    if normalized_type in {"servicetask", "scripttask"}:
        return "automated", "bpmn_structure"

    normalized_role = re.sub(r"[\s-]+", "_", str(role_name or "").casefold()).strip("_")
    if normalized_role in {"system", "system_role", "automation", "automated", "robot", "bot", "api"}:
        return "automated", "role_semantics"

    label = _semantic_label_key(task_name)
    if any(stem in label for stem in EXTERNAL_WAIT_STEMS):
        return "external_wait", "semantic_rule"
    if any(stem in label for stem in SUBSTANTIVE_WORK_STEMS):
        return "active_human", "semantic_rule"
    if any(stem in label for stem in SHORT_TRANSACTION_STEMS):
        return "short_transaction", "semantic_rule"
    return "active_human", "default"


def infer_duration_policy(task_name: str, task_class: str) -> dict[str, float | str] | None:
    """Return automatic, auditable duration bounds for rapid human work."""
    if task_class != "short_transaction":
        return None
    label = _semantic_label_key(task_name)
    if any(stem in label for stem in FINANCIAL_APPROVAL_STEMS):
        return {
            "id": "financial_approval",
            "minimum_seconds": 30.0,
            "fallback_seconds": 90.0,
            "maximum_seconds": 180.0,
            "std_seconds": 30.0,
        }
    return {
        "id": "rapid_transaction",
        "minimum_seconds": 1.0,
        "fallback_seconds": 15.0,
        "maximum_seconds": 60.0,
        "std_seconds": 7.5,
    }

def extract_aurea_roles(root) -> dict[str, str]:
    """
    Extract legacy ``aurea:Role`` and converted ``aurea:role`` definitions:
    role_id -> display name / code.

    The old-Aurea converter intentionally writes the new-Aurea lower-case
    elements.  Reading both forms keeps ``aurea:responsibleRef`` meaningful
    instead of falling back to generated identifiers such as ``Role_3``.
    """
    role_map = {}
    for role_elem in root.iter():
        tag = role_elem.tag
        if not isinstance(tag, str) or not any(tag.startswith(f"{{{namespace}}}") for namespace in AUREA_NAMESPACES):
            continue
        if tag.rsplit("}", 1)[-1] not in {"Role", "role"}:
            continue
        role_id = role_elem.get('id')
        if not role_id:
            continue

        display_name = role_elem.get('code', '')
        disp_elem = next(
            (
                child for child in role_elem
                if isinstance(child.tag, str)
                and any(child.tag.startswith(f"{{{namespace}}}") for namespace in AUREA_NAMESPACES)
                and child.tag.rsplit("}", 1)[-1] in {"DisplayName", "displayName"}
            ),
            None,
        )

        if disp_elem is not None and disp_elem.text:
            try:
                disp_json = json.loads(disp_elem.text)
                if "en" in disp_json:
                    display_name = disp_json["en"]
                elif "pl" in disp_json:
                    display_name = disp_json["pl"]
                elif disp_json:
                    display_name = list(disp_json.values())[0]
            except Exception:
                display_name = disp_elem.text

        role_map[role_id] = display_name
    return role_map

def extract_lane_task_roles(root) -> dict[str, str]:
    """
    Extract BPMN lane membership:
    task_id -> lane_name.
    """
    lane_task_roles = {}
    for lane_elem in get_elements_by_local_name(root, 'lane'):
        lane_name = lane_elem.get('name')
        if not lane_name:
            continue
            
        for flow_node in get_elements_by_local_name(lane_elem, 'flowNodeRef'):
            if flow_node.text:
                task_id = flow_node.text.strip()
                lane_task_roles[task_id] = lane_name
                
    return lane_task_roles

def resolve_task_roles(bpmn_path: str | Path) -> dict[str, dict]:
    """
    Return deterministic role metadata for every task.
    """
    tree = ET.parse(bpmn_path)
    root = tree.getroot()
    
    aurea_roles = extract_aurea_roles(root)
    lane_task_roles = extract_lane_task_roles(root)
    
    task_local_names = {
        'task', 'userTask', 'serviceTask', 'scriptTask', 'receiveTask',
        'sendTask', 'manualTask',
    }
    
    resolved_tasks = {}
    
    for task_elem in get_elements_by_local_name(root, task_local_names):
        task_id = task_elem.get('id')
        if not task_id:
            continue
            
        original_task_name = task_elem.get('name', '')
        
        # Priority 1: aurea:responsibleRef
        role_source = None
        role_name = None
        
        for key, val in task_elem.attrib.items():
            if 'responsibleRef' in key:
                role_source = "aurea_responsibleRef"
                role_name = aurea_roles.get(val, val)
                break
                
        # Priority 2: bpmn_lane
        if role_source is None and task_id in lane_task_roles:
            role_source = "bpmn_lane"
            role_name = lane_task_roles[task_id]
            
        # Priority 3: task_label_suffix
        clean_task_name = original_task_name
        if role_source is None:
            clean_name_temp, suffix_role = extract_suffix_role(original_task_name)
            clean_task_name = clean_name_temp
            if suffix_role:
                role_source = "task_label_suffix"
                role_name = suffix_role
        else:
            # We still want the clean task name without a suffix, if one exists
            clean_task_name, _ = extract_suffix_role(original_task_name)
                
        # Priority 4: task_id_fallback
        if role_source is None:
            role_source = "task_id_fallback"
            role_name = f"{task_id} Role"
            clean_task_name = original_task_name if original_task_name else task_id
            
        if not clean_task_name:
            clean_task_name = task_id
            
        role_id = normalize_role_id(role_name)
        resource_instance_id = normalize_resource_instance_id(role_id)
        
        task_type = task_elem.tag.split('}', 1)[-1]
        explicit_task_class = next(
            (
                value.strip()
                for key, value in task_elem.attrib.items()
                if key.rsplit('}', 1)[-1] == 'taskClass' and value.strip()
            ),
            None,
        )
        task_class, task_class_source = infer_task_class(
            clean_task_name, task_type, explicit_task_class, role_name
        )
        duration_policy = infer_duration_policy(clean_task_name, task_class)
        resolved_tasks[task_id] = {
            "task_id": task_id,
            "original_task_name": original_task_name or task_id,
            "clean_task_name": clean_task_name,
            "role_name": role_name,
            "role_id": role_id,
            "resource_instance_id": resource_instance_id,
            "role_source": role_source,
            "bpmn_task_type": task_type,
            "task_class": task_class,
            "task_class_source": task_class_source,
            "duration_policy": duration_policy,
        }
        
    return resolved_tasks
