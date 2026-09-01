"""Prepare the small, public BPMN example library.

The selected models originate from the local evaluation workspace.  This helper
retains their BPMN control flow, identifiers and English task labels while
removing organisation-specific automation, descriptions and legacy metadata.
It must never be used on the private process-mining repository.
"""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS = ROOT / "diagrams"
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

ET.register_namespace("bpmn", BPMN_NS)
ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
ET.register_namespace("aurea", "http://aurea.software/schema/2024/bpmn")

PUBLIC_MINED_MODELS = (
    "Business_Travel_Delegation_Request.bpmn",
    "Cost_Invoice_Workflow.bpmn",
    "Milk_Support_Application.bpmn",
)

PUBLIC_ROLE_NAMES = {
    "Business_Travel_Delegation_Request.bpmn": {
        "Role_0": "Employee",
        "Role_1": "Supervisor",
        "Role_2": "Authorised employee",
        "Role_3": "Finance and accounting employee",
        "Role_5": "Human-resources employee",
        "Role_6": "Management",
        "Role_7": "Management Board",
        "Role_8": "SAP system",
    },
    "Cost_Invoice_Workflow.bpmn": {
        "Role_0": "Reception",
        "Role_1": "Cost allocation officer",
        "Role_2": "Authoriser",
        "Role_3": "Accounting department",
        "Role_4": "System",
        "Role_5": "Informed",
        "Role_6": "Manager",
        "Role_7": "Assigned person",
    },
    "Milk_Support_Application.bpmn": {
        "Role_0": "Operator",
        "Role_1": "Verifier",
        "Role_2": "Approver",
        "Role_3": "System",
        "Role_4": "Manager",
    },
}


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def sanitize(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    for parent in root.iter():
        for child in list(parent):
            # These fields refer to legacy packages, forms, scripts and
            # organisation-specific instructions.  None is required by
            # AureaSim's BPMN analysis or the Prosimos simulation pipeline.
            if child.tag == f"{{{BPMN_NS}}}documentation" or local_name(child) in {
                "defaultProceduresPackage",
                "description",
                "groovyScript",
                "formRef",
            }:
                parent.remove(child)
    role_names = PUBLIC_ROLE_NAMES[path.name]
    for role in root.iter():
        if local_name(role) != "role" or role.get("id") not in role_names:
            continue
        name = role_names[role.get("id")]
        role.set("code", name.replace(" ", "_"))
        for child in role:
            if local_name(child) == "displayName":
                child.text = json.dumps({"en": name})
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    for filename in PUBLIC_MINED_MODELS:
        sanitize(DIAGRAMS / filename)
        print(f"Sanitized {filename}")
