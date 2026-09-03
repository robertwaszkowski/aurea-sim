import pytest
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile
from aureasim.role_resolver import infer_duration_policy, infer_task_class, resolve_task_roles
from aureasim.ai_generator import apply_deterministic_resources

def create_temp_bpmn(xml_content: str) -> Path:
    temp_dir = Path(tempfile.mkdtemp())
    bpmn_path = temp_dir / "test.bpmn"
    bpmn_path.write_text(xml_content, encoding='utf-8')
    return bpmn_path

def test_trailing_parentheses():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
        <bpmn:process id="Process_1">
            <bpmn:task id="Task_1" name="Sign the agreement (Auditor)" />
        </bpmn:process>
    </bpmn:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Task_1"]
    assert task["role_name"] == "Auditor"
    assert task["clean_task_name"] == "Sign the agreement"
    assert task["role_source"] == "task_label_suffix"

def test_trailing_brackets():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
        <bpmn:process id="Process_1">
            <bpmn:task id="Task_1" name="Acceptance [Manager]" />
        </bpmn:process>
    </bpmn:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Task_1"]
    assert task["role_name"] == "Manager"
    assert task["clean_task_name"] == "Acceptance"
    assert task["role_source"] == "task_label_suffix"


def test_script_task_is_resolved_and_retains_its_bpmn_type():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
        <bpmn:process id="Process_1">
            <bpmn:scriptTask id="Task_1" name="Synchronize [System]" />
        </bpmn:process>
    </bpmn:definitions>
    """
    task = resolve_task_roles(create_temp_bpmn(xml))["Task_1"]

    assert task["role_name"] == "System"
    assert task["role_source"] == "task_label_suffix"
    assert task["bpmn_task_type"] == "scriptTask"


def test_semantic_task_classification_identifies_rapid_approval_in_english_and_polish():
    assert infer_task_class("Approve payment", "userTask") == ("short_transaction", "semantic_rule")
    assert infer_task_class("Zatwierdzenie decyzji", "userTask") == ("short_transaction", "semantic_rule")


def test_semantic_task_classification_keeps_substantive_work_out_of_short_transaction():
    assert infer_task_class("Verify application", "userTask") == ("active_human", "semantic_rule")
    assert infer_task_class("Weryfikacja wniosku", "userTask") == ("active_human", "semantic_rule")
    assert infer_task_class("Add records and approve invoice", "userTask") == ("active_human", "semantic_rule")


def test_semantic_task_classification_recognizes_polish_imperative_approval():
    assert infer_task_class("Zatwierdź decyzję", "userTask") == ("short_transaction", "semantic_rule")
    assert infer_task_class("Zatwierdź pozostawienie wniosku bez rozpatrzenia", "userTask") == (
        "short_transaction", "semantic_rule"
    )


def test_explicit_task_class_overrides_semantic_inference():
    assert infer_task_class("Verify application", "userTask", "short_transaction") == (
        "short_transaction", "bpmn_annotation"
    )


def test_system_role_overrides_action_word_semantics():
    assert infer_task_class("Approve application", "userTask", role_name="System") == (
        "automated", "role_semantics"
    )


def test_finance_approval_uses_wider_automatic_seconds_policy():
    policy = infer_duration_policy(
        "Approve document in Finance and Accounting Department", "short_transaction"
    )
    assert policy == {
        "id": "financial_approval", "minimum_seconds": 30.0,
        "fallback_seconds": 90.0, "maximum_seconds": 180.0, "std_seconds": 30.0,
    }

def test_no_role_fallback():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
        <bpmn:process id="Process_1">
            <bpmn:task id="Activity_abc123" />
        </bpmn:process>
    </bpmn:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Activity_abc123"]
    assert task["role_id"] == "Activity_abc123_Role"
    assert task["role_source"] == "task_id_fallback"

def test_aurea_responsible_ref():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:aurea="http://www.tecna.com/bpmn/aurea">
        <aurea:Role id="role_lawyer" code="Lawyer">
            <aurea:DisplayName>{"en": "Lawyer"}</aurea:DisplayName>
        </aurea:Role>
        <bpmn:process id="Process_1">
            <bpmn:task id="Task_1" name="Do legal work" aurea:responsibleRef="role_lawyer" />
        </bpmn:process>
    </bpmn:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Task_1"]
    assert task["role_name"] == "Lawyer"
    assert task["role_source"] == "aurea_responsibleRef"


def test_converted_lowercase_aurea_role_resolves_code_and_display_name():
    """New-Aurea converter output must not degrade a System role to Role_3."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:aurea="http://aurea.software/schema/2024/bpmn">
        <bpmn:process id="Process_1">
            <bpmn:extensionElements>
                <aurea:role id="Role_3" code="system" assignmentMode="STATIC">
                    <aurea:displayName>{"und": "System"}</aurea:displayName>
                </aurea:role>
            </bpmn:extensionElements>
            <bpmn:task id="Task_1" name="Synchronize data" aurea:responsibleRef="Role_3" />
        </bpmn:process>
    </bpmn:definitions>
    """

    task = resolve_task_roles(create_temp_bpmn(xml))["Task_1"]

    assert task["role_name"] == "System"
    assert task["role_id"] == "System"
    assert task["role_source"] == "aurea_responsibleRef"

def test_lane_membership():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
        <bpmn:process id="Process_1">
            <bpmn:laneSet>
                <bpmn:lane id="Lane_1" name="Finance Department">
                    <bpmn:flowNodeRef>Task_1</bpmn:flowNodeRef>
                </bpmn:lane>
            </bpmn:laneSet>
            <bpmn:task id="Task_1" name="Pay Invoice" />
        </bpmn:process>
    </bpmn:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Task_1"]
    assert task["role_name"] == "Finance Department"
    assert task["role_source"] == "bpmn_lane"

def test_priority_lane_over_suffix():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
        <bpmn:process id="Process_1">
            <bpmn:laneSet>
                <bpmn:lane id="Lane_1" name="Department">
                    <bpmn:flowNodeRef>Task_1</bpmn:flowNodeRef>
                </bpmn:lane>
            </bpmn:laneSet>
            <bpmn:task id="Task_1" name="Audit [Auditor]" />
        </bpmn:process>
    </bpmn:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Task_1"]
    assert task["role_name"] == "Department"
    assert task["role_source"] == "bpmn_lane"

def test_priority_aurea_over_lane_and_suffix():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:aurea="http://www.tecna.com/bpmn/aurea">
        <aurea:Role id="role_lawyer" code="Lawyer">
            <aurea:DisplayName>{"en": "Lawyer"}</aurea:DisplayName>
        </aurea:Role>
        <bpmn:process id="Process_1">
            <bpmn:laneSet>
                <bpmn:lane id="Lane_1" name="Finance Department">
                    <bpmn:flowNodeRef>Task_1</bpmn:flowNodeRef>
                </bpmn:lane>
            </bpmn:laneSet>
            <bpmn:task id="Task_1" name="Audit (Employee)" aurea:responsibleRef="role_lawyer" />
        </bpmn:process>
    </bpmn:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Task_1"]
    assert task["role_name"] == "Lawyer"
    assert task["role_source"] == "aurea_responsibleRef"

def test_apply_deterministic_resources_integration():
    # Input AI data hallucinating a bad resource but including provenance
    ai_data = {
        "resource_profiles": [
            {
                "id": "Auditor",
                "name": "Auditor",
                "resource_list": [
                    {
                        "id": "Auditor_1",
                        "name": "Auditor_1",
                        "cost_per_hour": 150.0,
                        "amount": 1,
                        "calendar": "Standard_Working_Hours",
                        "evidence_status": "grounded_confirmed",
                        "source_urls": ["http://example.com/salary"],
                        "evidence_rationale": "Found in salary DB"
                    }
                ]
            }
        ],
        "task_resource_distribution": [
            {
                "task_id": "Task_SignAgreement",
                "resources": [
                    {
                        "resource_id": "Auditor_1",
                        "distribution_params": [{"value": 500}, {"value": 50}, {"value": 0}, {"value": 9999}],
                        "evidence_status": "grounded_extrapolated",
                        "source_urls": ["http://example.com/duration"],
                        "evidence_rationale": "Extrapolated from similar task"
                    }
                ]
            }
        ]
    }
    
    # Authoritative semantics generated from our parser
    semantics = {
        "tasks": [
            {
                "task_id": "Task_SignAgreement",
                "task_name": "Sign the agreement (Auditor)",
                "clean_task_name": "Sign the agreement",
                "resolved_role": "Auditor",
                "role_id": "Auditor",
                "resource_instance_id": "Auditor_1",
                "role_source": "task_label_suffix"
            }
        ]
    }
    
    result = apply_deterministic_resources(ai_data, semantics)
    
    # 1. Verify resource ID was rewritten but duration and provenance kept
    dist = result["task_resource_distribution"][0]
    assert dist["task_id"] == "Task_SignAgreement"
    assert dist["resources"][0]["resource_id"] == "Auditor_1"
    assert dist["resources"][0]["distribution_params"][0]["value"] == 500  # Kept AI duration
    assert dist["resources"][0]["evidence_status"] == "grounded_extrapolated"
    assert dist["resources"][0]["source_urls"] == ["http://example.com/duration"]
    assert dist["resources"][0]["evidence_rationale"] == "Extrapolated from similar task"
    
    # 2. Verify resource profiles contains Auditor with correct cost and provenance
    assert "resource_profiles" in result
    profiles = result["resource_profiles"]
    assert len(profiles) == 1
    assert profiles[0]["id"] == "Auditor"
    
    res = profiles[0]["resource_list"][0]
    assert res["id"] == "Auditor_1"
    assert res["cost_per_hour"] == 150.0
    assert res["evidence_status"] == "grounded_confirmed"
    assert res["source_urls"] == ["http://example.com/salary"]
    assert res["evidence_rationale"] == "Found in salary DB"
    
def test_apply_deterministic_resources_structural():
    ai_data = {}
    semantics = {
        "tasks": [
            {
                "task_id": "Task_Auto",
                "task_name": "System Task",
                "clean_task_name": "System Task",
                "resolved_role": "System",
                "role_id": "System",
                "resource_instance_id": "System_1",
                "role_source": "task_id_fallback"
            }
        ]
    }
    result = apply_deterministic_resources(ai_data, semantics)
    profiles = result["resource_profiles"]
    assert len(profiles) == 1
    res = profiles[0]["resource_list"][0]
    assert res["id"] == "System_1"
    assert res["cost_per_hour"] == 0.0
    assert res["evidence_status"] == "structural_value"
    assert res["evidence_rationale"] == "Structural non-labor resource; zero hourly labor cost."
    assert res["calendar"] == "24_7_Calendar"


def test_apply_deterministic_resources_clears_web_evidence_for_system_subrole():
    """System_SAP has the same structural provenance rules as System."""
    ai_data = {
        "resource_profiles": [{
            "id": "System_SAP",
            "resource_list": [{
                "id": "System_SAP_1",
                "cost_per_hour": 50.0,
                "evidence_status": "grounded_proxy",
                "source_urls": ["https://example.com/system-cost"],
                "evidence_rationale": "Generated web estimate.",
            }],
        }],
    }
    semantics = {
        "tasks": [{
            "task_id": "Task_Auto",
            "task_name": "Automated update",
            "clean_task_name": "Automated update",
            "resolved_role": "System SAP",
            "role_id": "System_SAP",
            "resource_instance_id": "System_SAP_1",
            "role_source": "aurea_responsibleRef",
        }],
    }

    resource = apply_deterministic_resources(ai_data, semantics)["resource_profiles"][0]["resource_list"][0]

    assert resource["cost_per_hour"] == 0.0
    assert resource["calendar"] == "24_7_Calendar"
    assert resource["evidence_status"] == "structural_value"
    assert resource["source_urls"] == []


def test_semantic_namespace():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <semantic:definitions xmlns:semantic="http://www.omg.org/spec/BPMN/20100524/MODEL">
        <semantic:process id="Process_1">
            <semantic:laneSet>
                <semantic:lane id="Lane_1" name="HR">
                    <semantic:flowNodeRef>Task_1</semantic:flowNodeRef>
                </semantic:lane>
            </semantic:laneSet>
            <semantic:task id="Task_1" name="Hire" />
        </semantic:process>
    </semantic:definitions>
    """
    bpmn_path = create_temp_bpmn(xml)
    roles = resolve_task_roles(bpmn_path)
    
    task = roles["Task_1"]
    assert task["role_name"] == "HR"
    assert task["role_source"] == "bpmn_lane"

def test_real_bpmn_smoke_test():
    bpmn_dir = Path(__file__).parent.parent / "examples"
    
    counts = {
        "aurea_responsibleRef": 0,
        "bpmn_lane": 0,
        "task_label_suffix": 0,
        "task_id_fallback": 0
    }
    
    for process in ["Incident Management", "Leave Request", "RES_Sales_Process"]:
        bpmn_path = bpmn_dir / f"{process}.bpmn"
        if bpmn_path.exists():
            roles = resolve_task_roles(bpmn_path)
            for info in roles.values():
                counts[info["role_source"]] += 1
                
    print("\nRole source counts for real BPMNs:", counts)
    assert sum(counts.values()) > 0

