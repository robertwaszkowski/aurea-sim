from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from xml.etree import ElementTree as ET

from .package import build_project_zip, project_metadata, validate_project_zip


OLD_NS = "http://xmlns.tecna.pl/xml/ns/diagram"
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
AUREA_NS = "http://aurea.software/schema/2024/bpmn"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

NS = {"old": OLD_NS, "bpmn": BPMN_NS, "bpmndi": BPMNDI_NS, "dc": DC_NS, "di": DI_NS, "aurea": AUREA_NS}

for prefix, uri in (
    ("bpmn", BPMN_NS),
    ("bpmndi", BPMNDI_NS),
    ("dc", DC_NS),
    ("di", DI_NS),
    ("aurea", AUREA_NS),
    ("xsi", XSI_NS),
):
    ET.register_namespace(prefix, uri)


class ConversionError(RuntimeError):
    """Raised when the input or generated artifacts are structurally invalid."""


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    source_path: Optional[str] = None
    old_id: Optional[str] = None


@dataclass(frozen=True)
class Metadata:
    process_id: Optional[str] = None
    process_version: Optional[str] = None
    process_name: Optional[str] = None
    process_definition_id: Optional[str] = None


@dataclass
class NodeRecord:
    old_id: str
    new_id: str
    subtype: str
    element: ET.Element
    x: float
    y: float
    width: float
    height: float
    label: Optional["TransitionLabel"] = None


@dataclass(frozen=True)
class TransitionLabel:
    text: str
    x: float
    y: float
    width: float = 100.0
    height: float = 35.0


@dataclass(frozen=True)
class LegacyLabelAssociations:
    gateway_labels: Mapping[str, TransitionLabel]
    flow_labels: Mapping[int, TransitionLabel]
    consumed_label_ids: Tuple[str, ...]
    inferred_count: int


SUBTYPE_TO_BPMN: Dict[str, Tuple[str, str, float, float]] = {
    # These are the effective legacy connector bounds, including the old
    # connection-point frame. The serialized flow endpoints are expressed
    # against these bounds rather than generic BPMN element dimensions.
    "301": ("startEvent", "StartEvent", 32.0, 32.0),
    "302": ("endEvent", "EndEvent", 32.0, 32.0),
    "401": ("exclusiveGateway", "Gateway", 44.0, 44.0),
    "600": ("task", "Task", 133.0, 64.0),
    "604": ("task", "Task", 133.0, 80.0),
    "101": ("textAnnotation", "Annotation", 100.0, 50.0),
    "102": ("textAnnotation", "Label", 100.0, 35.0),
}

FIELD_TYPES: Dict[str, Tuple[str, Optional[str], Optional[str]]] = {
    "attachment": ("string", "binary", "file-input"),
    "button": ("string", None, "button"),
    "checkbox": ("boolean", None, "checkbox"),
    "combobox": ("string", None, "select"),
    "component": ("object", None, None),
    "date": ("string", "date", "date-picker"),
    "html": ("string", None, "static-content"),
    "number": ("number", None, "text-field"),
    "radiogroup": ("string", None, "radio-button"),
    "text": ("string", None, "text-field"),
    "textarea": ("string", None, "textarea"),
    "viewer": ("string", None, "static-content"),
}

CONFIRMED_PROCEDURE_EVENTS = {"INIT", "POST_TL", "PRE", "PRE_TL", "SAVE", "START"}
KNOWN_OUTPUT_FILES = {
    "process.bpmn",
    "process.form",
    "process.schema.json",
    "process.ui-options.json",
    "legacy-visibility.json",
    "id-map.json",
    "conversion-report.json",
    "source.augraph.xml",
    ".project.json",
    "project.zip",
}


def _q(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def _normalize_legacy_namespace(root: ET.Element) -> bool:
    """Normalize the unnamespaced AuGraph variant emitted by older Oracle exports."""
    if root.tag != "AuGraph":
        return False
    for element in root.iter():
        if isinstance(element.tag, str) and not element.tag.startswith("{"):
            element.tag = _q(OLD_NS, element.tag)
    return True


def _child_text(element: ET.Element, name: str, default: str = "") -> str:
    child = element.find(f"old:{name}", NS)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _first_text(element: ET.Element, names: Iterable[str]) -> str:
    for name in names:
        value = _child_text(element, name)
        if value:
            return value
    return ""


def _number(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_identifier(value: str, fallback: str = "item") -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    value = value.strip("_.-") or fallback
    if not re.match(r"[A-Za-z_]", value):
        value = f"_{value}"
    return value


def _json_key(value: str, fallback: str) -> str:
    value = value.strip()
    return value or fallback


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_xml(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True, short_empty_elements=True)


def _diagnostic(
    diagnostics: List[Diagnostic],
    severity: str,
    code: str,
    message: str,
    source_path: Optional[str] = None,
    old_id: Optional[str] = None,
) -> None:
    diagnostics.append(Diagnostic(severity, code, message, source_path, old_id))


def _prepare_output(output_dir: Path) -> None:
    if output_dir.exists():
        entries = list(output_dir.iterdir())
        if entries:
            names = {entry.name for entry in entries}
            unknown = names - KNOWN_OUTPUT_FILES
            if unknown:
                raise ConversionError(
                    f"Output directory is not empty and contains unrelated files: {output_dir}"
                )
            raise ConversionError(
                f"Output directory already contains a previous conversion: {output_dir}. "
                "Choose a new destination or remove it explicitly."
            )
    output_dir.mkdir(parents=True, exist_ok=True)


def _source_identity(root: ET.Element, supplied: Metadata) -> Metadata:
    model = root.find(".//old:Model", NS)
    return Metadata(
        process_id=supplied.process_id or (model.get("shortName") if model is not None else None),
        process_version=supplied.process_version or (model.get("version") if model is not None else None),
        process_name=supplied.process_name or (model.get("name") if model is not None else None),
        process_definition_id=supplied.process_definition_id,
    )


def _add_extensions(parent: ET.Element) -> ET.Element:
    extension = parent.find("bpmn:extensionElements", NS)
    if extension is None:
        extension = ET.SubElement(parent, _q(BPMN_NS, "extensionElements"))
    return extension


def _add_process_metadata(
    old_root: ET.Element,
    process: ET.Element,
    identity: Metadata,
) -> None:
    documentation = ET.SubElement(process, _q(BPMN_NS, "documentation"))
    documentation.text = json.dumps(
        {
            "legacyDefinitionId": identity.process_definition_id,
            "legacyProcessId": identity.process_id,
            "legacyProcessVersion": identity.process_version,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    model = old_root.find(".//old:Model", NS)
    procedures_package = model.get("package") if model is not None else None
    if procedures_package:
        extension = _add_extensions(process)
        package = ET.SubElement(extension, _q(AUREA_NS, "defaultProceduresPackage"))
        package.text = procedures_package


def _convert_roles(
    old_root: ET.Element,
    process: ET.Element,
    diagnostics: List[Diagnostic],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    by_index: Dict[str, str] = {}
    id_map: Dict[str, str] = {}
    roles = old_root.findall("./old:Roles/old:Role", NS)
    if not roles:
        return by_index, id_map
    extension = _add_extensions(process)
    for ordinal, role in enumerate(roles, 1):
        old_index = _child_text(role, "index") or str(ordinal)
        code = _child_text(role, "name") or f"role_{old_index}"
        new_id = _safe_identifier(f"Role_{old_index}")
        if old_index in by_index:
            _diagnostic(diagnostics, "error", "DUPLICATE_ROLE_INDEX", "Duplicate old role index.", "/AuGraph/Roles/Role", old_index)
            continue
        by_index[old_index] = new_id
        id_map[old_index] = new_id
        attrs = {"id": new_id, "code": code, "assignmentMode": "STATIC"}
        role_element = ET.SubElement(extension, _q(AUREA_NS, "role"), attrs)
        label = _child_text(role, "label")
        description = _child_text(role, "desc")
        if label:
            display = ET.SubElement(role_element, _q(AUREA_NS, "displayName"))
            display.text = json.dumps({"und": label}, ensure_ascii=False, sort_keys=True)
        if description:
            desc = ET.SubElement(role_element, _q(AUREA_NS, "description"))
            desc.text = json.dumps({"und": description}, ensure_ascii=False, sort_keys=True)
        if _child_text(role, "exactlyOne"):
            _diagnostic(
                diagnostics,
                "warning",
                "ROLE_EXACTLY_ONE_UNVERIFIED",
                "Legacy exactlyOne role semantics have no confirmed new-Aurea mapping.",
                "/AuGraph/Roles/Role/exactlyOne",
                old_index,
            )
    return by_index, id_map


def _add_procedures(
    old_connector: ET.Element,
    new_element: ET.Element,
    diagnostics: List[Diagnostic],
    old_id: str,
) -> None:
    procedures = old_connector.findall("./old:Procedures/old:Proc", NS)
    if not procedures:
        return
    extension = _add_extensions(new_element)
    for ordinal, procedure in enumerate(procedures, 1):
        event = (procedure.get("type") or "").upper()
        attrs = {
            "name": procedure.get("name") or f"legacy_procedure_{ordinal}",
            "event": event,
        }
        arguments = procedure.get("param")
        if arguments:
            attrs["arguments"] = arguments
        ET.SubElement(extension, _q(AUREA_NS, "groovyScript"), attrs)
        source_kind = (procedure.get("source") or "database").lower()
        if source_kind != "script":
            _diagnostic(
                diagnostics,
                "warning",
                "PROCEDURE_IMPLEMENTATION_KIND_UNSUPPORTED",
                f"Legacy {source_kind} procedure was retained as a named reference, but only Groovy script references are confirmed in new Aurea.",
                "/AuGraph/AuConnectors/Connector/Procedures/Proc",
                old_id,
            )
        _diagnostic(
            diagnostics,
            "warning",
            "PROCEDURE_BODY_MISSING",
            f"AuGraph identifies a {source_kind} procedure but does not contain its implementation body; no executable project file was generated.",
            "/AuGraph/AuConnectors/Connector/Procedures/Proc",
            old_id,
        )
        if event not in CONFIRMED_PROCEDURE_EVENTS:
            _diagnostic(
                diagnostics,
                "warning",
                "PROCEDURE_EVENT_UNVERIFIED",
                f"Legacy procedure event {event or '<empty>'} was retained but is not observed in the new-Aurea sample.",
                "/AuGraph/AuConnectors/Connector/Procedures/Proc",
                old_id,
            )


def _convert_nodes(
    old_root: ET.Element,
    process: ET.Element,
    role_by_index: Mapping[str, str],
    transition_label_ids: Iterable[str],
    gateway_labels: Mapping[str, TransitionLabel],
    diagnostics: List[Diagnostic],
) -> Tuple[Dict[str, NodeRecord], Dict[str, str]]:
    nodes: Dict[str, NodeRecord] = {}
    id_map: Dict[str, str] = {}
    linked_labels = set(transition_label_ids)
    for ordinal, connector in enumerate(old_root.findall("./old:AuConnectors/old:Connector", NS), 1):
        old_id = _child_text(connector, "hashCode") or f"missing_{ordinal}"
        subtype = _child_text(connector, "elementSubType")
        if subtype == "102" and old_id in linked_labels:
            continue
        if old_id in nodes:
            _diagnostic(diagnostics, "error", "DUPLICATE_CONNECTOR_ID", "Duplicate connector hashCode.", "/AuGraph/AuConnectors/Connector", old_id)
            continue
        mapping = SUBTYPE_TO_BPMN.get(subtype)
        if mapping is None:
            _diagnostic(
                diagnostics,
                "warning",
                "UNSUPPORTED_CONNECTOR_SUBTYPE",
                f"Connector subtype {subtype or '<empty>'} is not mapped in milestone 1.",
                "/AuGraph/AuConnectors/Connector",
                old_id,
            )
            continue
        tag, prefix, width, height = mapping
        new_id = _safe_identifier(f"{prefix}_{old_id}")
        inferred_gateway_label = gateway_labels.get(old_id)
        if tag == "exclusiveGateway":
            name = (
                inferred_gateway_label.text
                if inferred_gateway_label is not None
                else _first_text(
                    connector,
                    ("descriptionText", "name", "title", "elementLabel", "shortName"),
                )
            )
        else:
            name = _first_text(connector, ("name", "title", "elementLabel", "shortName"))
        attrs = {"id": new_id}
        if name and tag != "textAnnotation":
            attrs["name"] = name
        element = ET.SubElement(process, _q(BPMN_NS, tag), attrs)
        if tag == "textAnnotation":
            text = ET.SubElement(element, _q(BPMN_NS, "text"))
            text.text = name or _child_text(connector, "descriptionText")
            if subtype == "102":
                _diagnostic(
                    diagnostics,
                    "warning",
                    "LABEL_AS_TEXT_ANNOTATION",
                    "Legacy free label was preserved as a BPMN text annotation.",
                    "/AuGraph/AuConnectors/Connector",
                    old_id,
                )
        description = _child_text(connector, "descriptionText")
        if description and tag != "textAnnotation":
            extension = _add_extensions(element)
            desc = ET.SubElement(extension, _q(AUREA_NS, "description"))
            desc.text = json.dumps({"und": description}, ensure_ascii=False, sort_keys=True)
        owner = _child_text(connector, "owner")
        if owner and tag == "task":
            role_id = role_by_index.get(owner)
            if role_id:
                element.set(_q(AUREA_NS, "responsibleRef"), role_id)
            else:
                _diagnostic(diagnostics, "warning", "UNRESOLVED_TASK_OWNER", "Task owner does not resolve to a converted role.", "/AuGraph/AuConnectors/Connector/owner", old_id)
        _add_procedures(connector, element, diagnostics, old_id)
        if connector.find("./old:Actions", NS) is not None:
            _diagnostic(diagnostics, "warning", "LEGACY_ACTIONS_RETAINED_IN_SOURCE", "Legacy UI actions have no confirmed automatic mapping.", "/AuGraph/AuConnectors/Connector/Actions", old_id)
        nodes[old_id] = NodeRecord(
            old_id=old_id,
            new_id=new_id,
            subtype=subtype,
            element=element,
            x=_number(_child_text(connector, "left")),
            y=_number(_child_text(connector, "top")),
            width=width,
            height=height,
            label=inferred_gateway_label,
        )
        id_map[old_id] = new_id
    return nodes, id_map


def _extract_visibility(
    old_root: ET.Element,
    connector_id_map: Mapping[str, str],
    diagnostics: List[Diagnostic],
) -> Dict[str, Any]:
    """Preserve AuGraph task visibility rules until a runtime target is confirmed."""
    tasks = []
    parameter_count = 0
    for ordinal, connector in enumerate(old_root.findall("./old:AuConnectors/old:Connector", NS), 1):
        params = connector.find("./old:params", NS)
        if params is None:
            continue
        parameters = []
        for parameter in params.findall("./old:param", NS):
            parameters.append({key: value for key, value in sorted(parameter.attrib.items())})
        if not parameters and not params.attrib:
            continue
        parameter_count += len(parameters)
        old_id = _child_text(connector, "hashCode") or f"missing_{ordinal}"
        entry: Dict[str, Any] = {
            "sourceConnectorId": old_id,
            "targetBpmnId": connector_id_map.get(old_id),
            "parameters": parameters,
        }
        if params.attrib:
            entry["containerAttributes"] = {
                key: value for key, value in sorted(params.attrib.items())
            }
        tasks.append(entry)
    if tasks:
        _diagnostic(
            diagnostics,
            "warning",
            "LEGACY_VISIBILITY_RETAINED",
            f"Preserved {parameter_count} parameter-visibility rules for {len(tasks)} connectors in legacy-visibility.json; no confirmed new-Aurea runtime mapping was applied.",
            "/AuGraph/AuConnectors/Connector/params",
        )
    return {
        "formatVersion": 1,
        "mappingStatus": "PRESERVED_TARGET_MAPPING_UNCONFIRMED",
        "tasks": tasks,
    }


def _condition_kind(connection: ET.Element) -> Tuple[Optional[ET.Element], str]:
    condition = connection.find("./old:conditions", NS)
    return condition, (condition.get("type") if condition is not None else "")


def _transition_label_ids(old_root: ET.Element) -> List[str]:
    result: List[str] = []
    for linked in old_root.findall("./old:AuConnections/old:Connection/old:linkedWidgets", NS):
        for attribute in ("startWidgetId", "endWidgetId"):
            widget_id = linked.get(attribute)
            if widget_id and widget_id not in result:
                result.append(widget_id)
    return result


def _transition_labels(old_root: ET.Element) -> Dict[str, TransitionLabel]:
    labels: Dict[str, TransitionLabel] = {}
    for connector in old_root.findall("./old:AuConnectors/old:Connector", NS):
        if _child_text(connector, "elementSubType") != "102":
            continue
        old_id = _child_text(connector, "hashCode")
        if not old_id:
            continue
        text = _first_text(
            connector,
            ("descriptionText", "name", "title", "elementLabel", "shortName"),
        )
        if text:
            labels[old_id] = TransitionLabel(
                text=text,
                x=_number(_child_text(connector, "left")),
                y=_number(_child_text(connector, "top")),
            )
    return labels


def _point_segment_distance(
    point: Tuple[float, float],
    start: Tuple[float, float],
    end: Tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    projection = (
        (point[0] - start[0]) * delta_x
        + (point[1] - start[1]) * delta_y
    ) / length_squared
    projection = max(0.0, min(1.0, projection))
    nearest = (
        start[0] + projection * delta_x,
        start[1] + projection * delta_y,
    )
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def _label_flow_distance(
    label: TransitionLabel,
    points: List[Tuple[float, float]],
) -> float:
    center = (label.x + label.width / 2.0, label.y + label.height / 2.0)
    return min(
        _point_segment_distance(center, start, end)
        for start, end in zip(points, points[1:])
    )


def _legacy_label_associations(old_root: ET.Element) -> LegacyLabelAssociations:
    """Recover labels from old diagrams that predate linkedWidgets metadata.

    The old editor serialized a gateway followed by its loose subtype-102
    captions. When links are absent, geometry is the only remaining relation.
    """
    connectors = old_root.findall("./old:AuConnectors/old:Connector", NS)
    connections = old_root.findall("./old:AuConnections/old:Connection", NS)
    labels = _transition_labels(old_root)
    explicit_ids = set(_transition_label_ids(old_root))
    gateway_labels: Dict[str, TransitionLabel] = {}
    flow_labels: Dict[int, TransitionLabel] = {}
    consumed = set(explicit_ids)
    inferred_count = 0

    for index, gateway in enumerate(connectors):
        if _child_text(gateway, "elementSubType") != "401":
            continue
        gateway_id = _child_text(gateway, "hashCode")
        candidates: List[Tuple[str, TransitionLabel]] = []
        following = index + 1
        while following < len(connectors):
            connector = connectors[following]
            if _child_text(connector, "elementSubType") != "102":
                break
            label_id = _child_text(connector, "hashCode")
            if label_id and label_id not in explicit_ids and label_id in labels:
                candidates.append((label_id, labels[label_id]))
            following += 1

        description = _child_text(gateway, "descriptionText")
        generic_name = _child_text(gateway, "name").strip().lower() in {
            "", "bramka", "gateway"
        }
        if not description and generic_name and candidates:
            label_id, label = candidates.pop(0)
            gateway_labels[gateway_id] = label
            consumed.add(label_id)
            inferred_count += 1

        outgoing: List[Tuple[int, List[Tuple[float, float]]]] = []
        for ordinal, connection in enumerate(connections, 1):
            if _child_text(connection, "start") != gateway_id:
                continue
            if connection.find("./old:linkedWidgets", NS) is not None:
                continue
            points = _deduplicate_waypoints(
                (
                    _number(point.get("left") or "0"),
                    _number(point.get("top") or "0"),
                )
                for point in connection.findall("./old:Point", NS)
            )
            if len(points) >= 2:
                outgoing.append((ordinal, points))

        possible = sorted(
            (
                _label_flow_distance(label, points),
                label_id,
                label,
                ordinal,
            )
            for label_id, label in candidates
            for ordinal, points in outgoing
        )
        assigned_labels = set()
        assigned_flows = set()
        for distance, label_id, label, ordinal in possible:
            if distance > 120.0:
                break
            if label_id in assigned_labels or ordinal in assigned_flows:
                continue
            flow_labels[ordinal] = label
            consumed.add(label_id)
            assigned_labels.add(label_id)
            assigned_flows.add(ordinal)
            inferred_count += 1

    return LegacyLabelAssociations(
        gateway_labels=gateway_labels,
        flow_labels=flow_labels,
        consumed_label_ids=tuple(sorted(consumed)),
        inferred_count=inferred_count,
    )


def _deduplicate_waypoints(
    points: Iterable[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    result: List[Tuple[float, float]] = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    return result


def _boundary_waypoint(
    node: NodeRecord,
    toward: Tuple[float, float],
) -> Tuple[float, float]:
    """Project a legacy endpoint onto its converted BPMN shape boundary."""
    center_x = node.x + node.width / 2.0
    center_y = node.y + node.height / 2.0
    delta_x = toward[0] - center_x
    delta_y = toward[1] - center_y
    if abs(delta_x) < 1e-9 and abs(delta_y) < 1e-9:
        return center_x, center_y

    half_width = node.width / 2.0
    half_height = node.height / 2.0
    if node.subtype in {"301", "302"}:
        scale = 1.0 / math.sqrt(
            (delta_x / half_width) ** 2 + (delta_y / half_height) ** 2
        )
    elif node.subtype == "401":
        scale = 1.0 / (
            abs(delta_x) / half_width + abs(delta_y) / half_height
        )
    else:
        x_scale = half_width / abs(delta_x) if abs(delta_x) >= 1e-9 else math.inf
        y_scale = half_height / abs(delta_y) if abs(delta_y) >= 1e-9 else math.inf
        scale = min(x_scale, y_scale)
    return center_x + delta_x * scale, center_y + delta_y * scale


def _normalize_flow_waypoints(
    source: NodeRecord,
    target: NodeRecord,
    points: Iterable[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    normalized = _deduplicate_waypoints(points)
    if len(normalized) < 2:
        normalized = [
            (source.x + source.width / 2.0, source.y + source.height / 2.0),
            (target.x + target.width / 2.0, target.y + target.height / 2.0),
        ]

    source_direction = normalized[0]
    if source_direction == (
        source.x + source.width / 2.0,
        source.y + source.height / 2.0,
    ):
        source_direction = normalized[1]
    target_direction = normalized[-1]
    if target_direction == (
        target.x + target.width / 2.0,
        target.y + target.height / 2.0,
    ):
        target_direction = normalized[-2]

    normalized[0] = _boundary_waypoint(source, source_direction)
    normalized[-1] = _boundary_waypoint(target, target_direction)
    return _deduplicate_waypoints(normalized)


def _convert_flows(
    old_root: ET.Element,
    process: ET.Element,
    nodes: Mapping[str, NodeRecord],
    inferred_labels: Mapping[int, TransitionLabel],
    diagnostics: List[Diagnostic],
) -> Tuple[List[Tuple[str, ET.Element, List[Tuple[float, float]], Optional[TransitionLabel]]], Dict[str, str]]:
    flows: List[Tuple[str, ET.Element, List[Tuple[float, float]], Optional[TransitionLabel]]] = []
    id_map: Dict[str, str] = {}
    labels = _transition_labels(old_root)
    for ordinal, connection in enumerate(old_root.findall("./old:AuConnections/old:Connection", NS), 1):
        old_key = f"connection:{ordinal}"
        old_type = connection.get("type") or ""
        source_old = _child_text(connection, "start")
        target_old = _child_text(connection, "end")
        if old_type and old_type != "SEQ_FLOW":
            _diagnostic(diagnostics, "warning", "UNSUPPORTED_CONNECTION_TYPE", f"Connection type {old_type} is not mapped.", "/AuGraph/AuConnections/Connection", old_key)
            continue
        source = nodes.get(source_old)
        target = nodes.get(target_old)
        if source is None or target is None:
            _diagnostic(diagnostics, "warning", "FLOW_ENDPOINT_NOT_CONVERTED", "Sequence flow was omitted because one or both endpoints were not converted.", "/AuGraph/AuConnections/Connection", old_key)
            continue
        if source.subtype in {"101", "102"} or target.subtype in {"101", "102"}:
            _diagnostic(diagnostics, "warning", "ANNOTATION_CONNECTION_UNSUPPORTED", "A connector touching a legacy annotation was not treated as sequence flow.", "/AuGraph/AuConnections/Connection", old_key)
            continue
        new_id = _safe_identifier(f"Flow_{ordinal}_{source_old}_{target_old}")
        attrs = {"id": new_id, "sourceRef": source.new_id, "targetRef": target.new_id}
        linked = connection.find("./old:linkedWidgets", NS)
        label: Optional[TransitionLabel] = inferred_labels.get(ordinal)
        if linked is not None:
            label_id = linked.get("startWidgetId") or linked.get("endWidgetId")
            if label_id:
                explicit_label = labels.get(label_id)
                if explicit_label is not None:
                    label = explicit_label
                else:
                    _diagnostic(
                        diagnostics,
                        "warning",
                        "TRANSITION_LABEL_UNRESOLVED",
                        f"Linked transition label {label_id} could not be resolved.",
                        "/AuGraph/AuConnections/Connection/linkedWidgets",
                        old_key,
                    )
        if label is not None:
            attrs["name"] = label.text
        flow = ET.SubElement(process, _q(BPMN_NS, "sequenceFlow"), attrs)
        ET.SubElement(source.element, _q(BPMN_NS, "outgoing")).text = new_id
        ET.SubElement(target.element, _q(BPMN_NS, "incoming")).text = new_id
        condition, kind = _condition_kind(connection)
        if condition is not None:
            if kind == "default" and source.subtype == "401":
                source.element.set("default", new_id)
            elif kind:
                _diagnostic(
                    diagnostics,
                    "warning",
                    "FLOW_CONDITION_NOT_EXECUTABLE",
                    "Legacy flow condition is preserved in the source but was not emitted as an executable expression.",
                    "/AuGraph/AuConnections/Connection/conditions",
                    old_key,
                )
        legacy_points = [
            (_number(point.get("left") or "0"), _number(point.get("top") or "0"))
            for point in connection.findall("./old:Point", NS)
        ]
        if len(_deduplicate_waypoints(legacy_points)) < 2:
            _diagnostic(diagnostics, "warning", "FLOW_WAYPOINTS_SYNTHESIZED", "Fewer than two old waypoints were available, so center points were synthesized.", "/AuGraph/AuConnections/Connection/Point", old_key)
        points = _normalize_flow_waypoints(source, target, legacy_points)
        flows.append((new_id, flow, points, label))
        id_map[old_key] = new_id
    return flows, id_map


def _add_diagram(
    definitions: ET.Element,
    process_id: str,
    nodes: Mapping[str, NodeRecord],
    flows: Iterable[Tuple[str, ET.Element, List[Tuple[float, float]], Optional[TransitionLabel]]],
    diagnostics: List[Diagnostic],
) -> Tuple[float, float]:
    flow_list = list(flows)
    x_values = [node.x for node in nodes.values()]
    y_values = [node.y for node in nodes.values()]
    for node in nodes.values():
        if node.label is not None:
            x_values.append(node.label.x)
            y_values.append(node.label.y)
    for _flow_id, _flow, points, label in flow_list:
        x_values.extend(x for x, _y in points)
        y_values.extend(y for _x, y in points)
        if label is not None:
            x_values.append(label.x)
            y_values.append(label.y)
    offset_x = 100.0 - min(x_values) if x_values else 0.0
    offset_y = 100.0 - min(y_values) if y_values else 0.0
    if offset_x or offset_y:
        _diagnostic(
            diagnostics,
            "warning",
            "DIAGRAM_COORDINATES_NORMALIZED",
            f"Shifted legacy diagram coordinates by ({offset_x:g}, {offset_y:g}) so the model opens in the visible canvas area.",
            "/AuGraph",
        )
    diagram = ET.SubElement(definitions, _q(BPMNDI_NS, "BPMNDiagram"), {"id": f"Diagram_{process_id}"})
    plane = ET.SubElement(diagram, _q(BPMNDI_NS, "BPMNPlane"), {"id": f"Plane_{process_id}", "bpmnElement": process_id})
    for node in nodes.values():
        shape = ET.SubElement(plane, _q(BPMNDI_NS, "BPMNShape"), {"id": f"{node.new_id}_di", "bpmnElement": node.new_id})
        ET.SubElement(
            shape,
            _q(DC_NS, "Bounds"),
            {"x": f"{node.x + offset_x:g}", "y": f"{node.y + offset_y:g}", "width": f"{node.width:g}", "height": f"{node.height:g}"},
        )
        if node.label is not None:
            bpmn_label = ET.SubElement(shape, _q(BPMNDI_NS, "BPMNLabel"))
            ET.SubElement(
                bpmn_label,
                _q(DC_NS, "Bounds"),
                {
                    "x": f"{node.label.x + offset_x:g}",
                    "y": f"{node.label.y + offset_y:g}",
                    "width": f"{node.label.width:g}",
                    "height": f"{node.label.height:g}",
                },
            )
    for flow_id, _, points, label in flow_list:
        edge = ET.SubElement(plane, _q(BPMNDI_NS, "BPMNEdge"), {"id": f"{flow_id}_di", "bpmnElement": flow_id})
        for x, y in points:
            ET.SubElement(edge, _q(DI_NS, "waypoint"), {"x": f"{x + offset_x:g}", "y": f"{y + offset_y:g}"})
        if label is not None:
            bpmn_label = ET.SubElement(edge, _q(BPMNDI_NS, "BPMNLabel"))
            ET.SubElement(
                bpmn_label,
                _q(DC_NS, "Bounds"),
                {
                    "x": f"{label.x + offset_x:g}",
                    "y": f"{label.y + offset_y:g}",
                    "width": f"{label.width:g}",
                    "height": f"{label.height:g}",
                },
            )
    return offset_x, offset_y


def _legacy_field_metadata(field: ET.Element) -> Dict[str, Any]:
    ignored = {"name", "label", "type"}
    attributes = {key: value for key, value in sorted(field.attrib.items()) if key not in ignored and value not in (None, "")}
    child_tags = sorted({child.tag.rsplit("}", 1)[-1] for child in field if child.tag.rsplit("}", 1)[-1] not in {"Option", "Value", "DefaultValue"}})
    result: Dict[str, Any] = {}
    if attributes:
        result["attributes"] = attributes
    if child_tags:
        result["retainedInSourceChildren"] = child_tags
    return result


def _field_schema(
    field: ET.Element,
    diagnostics: List[Diagnostic],
    source_path: str,
) -> Dict[str, Any]:
    old_type = (field.get("type") or "text").lower()
    mapped = FIELD_TYPES.get(old_type)
    if mapped is None:
        json_type, json_format, component = "string", None, None
        _diagnostic(diagnostics, "warning", "UNSUPPORTED_FIELD_TYPE", f"Legacy field type {old_type or '<empty>'} fell back to string.", source_path)
    else:
        json_type, json_format, component = mapped
    schema: Dict[str, Any] = {"type": json_type}
    label = field.get("label")
    if label:
        schema["label"] = label
    if json_format:
        schema["format"] = json_format
    if component:
        schema["layout"] = {"component": component}
    options = field.findall("./old:Option", NS)
    option_values: List[str] = []
    option_labels: Dict[str, str] = {}
    for option in options:
        value = (option.text or "").strip() or option.get("label") or ""
        if value and value not in option_values:
            option_values.append(value)
            if option.get("label"):
                option_labels[value] = option.get("label") or value
    if option_values:
        schema["enum"] = option_values
        if option_labels:
            schema["x-aurea-option-labels"] = option_labels
    default = field.find("./old:DefaultValue", NS)
    if default is not None and (default.text or "").strip():
        schema["default"] = (default.text or "").strip()
    legacy = _legacy_field_metadata(field)
    if legacy:
        schema["x-aurea-legacy"] = legacy
        _diagnostic(diagnostics, "warning", "LEGACY_FIELD_METADATA_RETAINED", "Legacy field metadata is annotated and retained in the source; runtime equivalence is not guaranteed.", source_path)
    if old_type in {"button", "component", "html", "viewer", "attachment"}:
        _diagnostic(diagnostics, "warning", "FIELD_WIDGET_MAPPING_UNVERIFIED", f"Widget mapping for legacy {old_type} fields is not confirmed against a canonical project package.", source_path)
    return schema


def _collect_form_properties(
    parent: ET.Element,
    diagnostics: List[Diagnostic],
    path: str,
    ui_layouts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    generated = 0
    for child in list(parent):
        local = child.tag.rsplit("}", 1)[-1]
        child_path = f"{path}/{local}"
        if local == "Field":
            generated += 1
            key = _json_key(child.get("name") or "", f"field_{generated}")
            original_key = key
            suffix = 2
            while key in properties:
                key = f"{original_key}_{suffix}"
                suffix += 1
            if key != original_key:
                _diagnostic(diagnostics, "warning", "DUPLICATE_FIELD_NAME_RENAMED", f"Duplicate field name was emitted as {key}.", child_path)
            properties[key] = _field_schema(child, diagnostics, child_path)
        elif local in {"Layout", "Tab", "Row", "Column"}:
            nested = _collect_form_properties(child, diagnostics, child_path, ui_layouts)
            layout_name = child.get("name") or ""
            ui_layouts.append(
                {
                    "kind": local.lower(),
                    "name": layout_name or None,
                    "legacyType": child.get("type"),
                    "fields": list(nested),
                }
            )
            if layout_name:
                key = _json_key(layout_name, f"group_{len(ui_layouts)}")
                if key in properties:
                    key = f"{key}_{len(ui_layouts)}"
                properties[key] = {
                    "type": "object",
                    "properties": nested,
                    "label": child.get("label") or layout_name,
                    "layout": {"component": "fields-group"},
                    "x-aurea-legacy-layout": {key: value for key, value in sorted(child.attrib.items()) if value},
                }
            else:
                for key, value in nested.items():
                    candidate = key
                    suffix = 2
                    while candidate in properties:
                        candidate = f"{key}_{suffix}"
                        suffix += 1
                    properties[candidate] = value
            _diagnostic(diagnostics, "warning", "LEGACY_LAYOUT_APPROXIMATED", "Legacy row/column layout was approximated; exact rendering equivalence is unverified.", child_path)
    return properties


def _convert_process_data(
    old_root: ET.Element,
    identity: Metadata,
    diagnostics: List[Diagnostic],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    process_data = old_root.find("./old:ProcessData", NS)
    ui_layouts: List[Dict[str, Any]] = []
    properties = (
        _collect_form_properties(process_data, diagnostics, "/AuGraph/ProcessData", ui_layouts)
        if process_data is not None
        else {}
    )
    if process_data is None:
        _diagnostic(diagnostics, "warning", "PROCESS_DATA_MISSING", "No ProcessData element was found; an empty schema was generated.", "/AuGraph")
    title = identity.process_name or identity.process_id or "Converted Aurea process data"
    schema: Dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
        "x-aurea-source-format": "AuGraph",
    }
    ui_options: Dict[str, Any] = {
        "fieldOrder": list(properties),
        "legacyLayouts": ui_layouts,
        "conversionStatus": "approximate",
    }
    form = dict(schema)
    form["i18n"] = {}
    form["options"] = ui_options
    return schema, ui_options, form


def _validate_bpmn(root: ET.Element) -> Dict[str, Any]:
    errors: List[str] = []
    if root.tag != _q(BPMN_NS, "definitions"):
        errors.append("Root is not bpmn:definitions.")
    process = root.find("bpmn:process", NS)
    if process is None:
        errors.append("No bpmn:process exists.")
        return {"valid": False, "errors": errors}
    ids: Dict[str, ET.Element] = {}
    duplicates: List[str] = []
    for element in root.iter():
        element_id = element.get("id")
        if element_id:
            if element_id in ids:
                duplicates.append(element_id)
            ids[element_id] = element
    if duplicates:
        errors.append(f"Duplicate BPMN IDs: {', '.join(sorted(set(duplicates)))}")
    flow_ids = set()
    node_ids = {element.get("id") for element in list(process) if element.tag in {
        _q(BPMN_NS, "startEvent"), _q(BPMN_NS, "endEvent"), _q(BPMN_NS, "exclusiveGateway"),
        _q(BPMN_NS, "task"), _q(BPMN_NS, "textAnnotation")
    }}
    for flow in process.findall("bpmn:sequenceFlow", NS):
        flow_id = flow.get("id") or "<missing>"
        flow_ids.add(flow_id)
        if flow.get("sourceRef") not in node_ids:
            errors.append(f"Flow {flow_id} has unknown sourceRef.")
        if flow.get("targetRef") not in node_ids:
            errors.append(f"Flow {flow_id} has unknown targetRef.")
    for node in list(process):
        for direction in ("incoming", "outgoing"):
            for ref in node.findall(f"bpmn:{direction}", NS):
                if (ref.text or "") not in flow_ids:
                    errors.append(f"Node {node.get('id')} has unknown {direction} reference.")
    for edge in root.findall(".//bpmndi:BPMNEdge", NS):
        if edge.get("bpmnElement") not in flow_ids:
            errors.append(f"BPMNEdge {edge.get('id')} has unknown flow reference.")
        if len(edge.findall("di:waypoint", NS)) < 2:
            errors.append(f"BPMNEdge {edge.get('id')} has fewer than two waypoints.")
    return {"valid": not errors, "errors": errors, "xsdValidation": "not-run"}


def _validate_json_schema(schema: Mapping[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    if schema.get("type") != "object":
        errors.append("Schema root type must be object.")
    if not isinstance(schema.get("properties"), dict):
        errors.append("Schema properties must be an object.")
    try:
        json.loads(json.dumps(schema, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        errors.append(f"Schema is not JSON serializable: {exc}")
    return {"valid": not errors, "errors": errors, "metaSchemaValidation": "structural-only"}


def convert_definition(
    xml_text: str,
    output_dir: Path,
    metadata: Optional[Metadata] = None,
    source_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert one combined old-Aurea AuGraph document and write its artifacts."""
    metadata = metadata or Metadata()
    try:
        old_root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ConversionError(f"Invalid source XML: {exc}") from exc
    namespace_normalized = _normalize_legacy_namespace(old_root)
    if old_root.tag != _q(OLD_NS, "AuGraph"):
        raise ConversionError(f"Expected AuGraph in {OLD_NS}, found {old_root.tag!r}.")
    _prepare_output(output_dir)
    diagnostics: List[Diagnostic] = []
    if namespace_normalized:
        _diagnostic(
            diagnostics,
            "warning",
            "LEGACY_NAMESPACE_NORMALIZED",
            "The unnamespaced legacy AuGraph variant was normalized to the canonical diagram namespace.",
            "/AuGraph",
        )
    identity = _source_identity(old_root, metadata)
    source_process_id = identity.process_id or identity.process_definition_id or "converted_process"
    bpmn_process_id = _safe_identifier(f"Process_{source_process_id}")
    definitions_id = _safe_identifier(f"Definitions_{source_process_id}")
    definitions = ET.Element(
        _q(BPMN_NS, "definitions"),
        {
            "id": definitions_id,
            "targetNamespace": "http://aurea.software/converted",
            _q(XSI_NS, "schemaLocation"): f"{BPMN_NS} BPMN20.xsd",
        },
    )
    process_attrs = {"id": bpmn_process_id, "isExecutable": "true"}
    if identity.process_name:
        process_attrs["name"] = identity.process_name
    process = ET.SubElement(definitions, _q(BPMN_NS, "process"), process_attrs)
    _add_process_metadata(old_root, process, identity)
    role_by_index, role_id_map = _convert_roles(old_root, process, diagnostics)
    label_associations = _legacy_label_associations(old_root)
    transition_label_ids = label_associations.consumed_label_ids
    if label_associations.inferred_count:
        _diagnostic(
            diagnostics,
            "warning",
            "LEGACY_LABEL_ASSOCIATIONS_INFERRED",
            f"Inferred {label_associations.inferred_count} gateway/transition label associations from legacy connector order and diagram geometry because linkedWidgets metadata was absent.",
            "/AuGraph/AuConnectors",
        )
    nodes, connector_id_map = _convert_nodes(
        old_root,
        process,
        role_by_index,
        transition_label_ids,
        label_associations.gateway_labels,
        diagnostics,
    )
    visibility = _extract_visibility(old_root, connector_id_map, diagnostics)
    flows, flow_id_map = _convert_flows(
        old_root,
        process,
        nodes,
        label_associations.flow_labels,
        diagnostics,
    )
    diagram_offset = _add_diagram(definitions, bpmn_process_id, nodes, flows, diagnostics)
    for procedure in old_root.findall("./old:Procedures/old:Proc", NS):
        _diagnostic(
            diagnostics,
            "warning",
            "GLOBAL_PROCEDURE_NOT_MAPPED",
            f"Global legacy procedure event {(procedure.get('type') or '<empty>').upper()} has no confirmed process-level target.",
            "/AuGraph/Procedures/Proc",
        )
    schema, ui_options, form = _convert_process_data(old_root, identity, diagnostics)
    bpmn_validation = _validate_bpmn(definitions)
    schema_validation = _validate_json_schema(schema)
    if not bpmn_validation["valid"]:
        for message in bpmn_validation["errors"]:
            _diagnostic(diagnostics, "error", "BPMN_VALIDATION_ERROR", message)
    if not schema_validation["valid"]:
        for message in schema_validation["errors"]:
            _diagnostic(diagnostics, "error", "JSON_SCHEMA_VALIDATION_ERROR", message)

    bpmn_path = output_dir / "process.bpmn"
    schema_path = output_dir / "process.schema.json"
    options_path = output_dir / "process.ui-options.json"
    visibility_path = output_dir / "legacy-visibility.json"
    form_path = output_dir / "process.form"
    id_map_path = output_dir / "id-map.json"
    source_path = output_dir / "source.augraph.xml"
    metadata_path = output_dir / ".project.json"
    package_path = output_dir / "project.zip"
    _write_xml(bpmn_path, definitions)
    _write_json(schema_path, schema)
    _write_json(options_path, ui_options)
    _write_json(visibility_path, visibility)
    _write_json(form_path, form)
    project_name = identity.process_name or identity.process_id or "Converted Aurea project"
    project_version = identity.process_version or "1.0.0"
    _write_json(metadata_path, project_metadata(project_name, project_version))
    id_map = {
        "process": {source_process_id: bpmn_process_id},
        "roles": role_id_map,
        "connectors": connector_id_map,
        "connections": flow_id_map,
    }
    _write_json(id_map_path, id_map)
    with source_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(xml_text)
    build_project_zip(
        package_path,
        metadata_path,
        {"process.bpmn": bpmn_path, "process.form": form_path},
    )
    package_validation = validate_project_zip(package_path)
    if not package_validation["valid"]:
        for message in package_validation["errors"]:
            _diagnostic(diagnostics, "error", "PROJECT_PACKAGE_VALIDATION_ERROR", message)
    artifacts = {}
    for path in (bpmn_path, form_path, schema_path, options_path, visibility_path, id_map_path, source_path, metadata_path, package_path):
        artifacts[path.name] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    report = {
        "converterVersion": "0.2.0",
        "source": {
            "label": source_label,
            "format": "AuGraph",
            "namespace": OLD_NS,
            "identity": asdict(identity),
        },
        "output": {
            "bpmnProcessId": bpmn_process_id,
            "packageGenerated": True,
            "packageFilename": package_path.name,
            "diagramCoordinateOffset": {"x": diagram_offset[0], "y": diagram_offset[1]},
            "artifacts": artifacts,
        },
        "summary": {
            "convertedConnectors": len(connector_id_map),
            "convertedConnections": len(flow_id_map),
            "convertedRoles": len(role_id_map),
            "formProperties": len(schema["properties"]),
            "visibilityTasksPreserved": len(visibility["tasks"]),
            "visibilityRulesPreserved": sum(len(task["parameters"]) for task in visibility["tasks"]),
            "warnings": sum(item.severity == "warning" for item in diagnostics),
            "errors": sum(item.severity == "error" for item in diagnostics),
        },
        "validation": {"bpmn": bpmn_validation, "jsonSchema": schema_validation, "projectPackage": package_validation},
        "diagnostics": [asdict(item) for item in diagnostics],
        "deferred": [
            "Executable mapping of legacy flow conditions",
            "Exact runtime mapping of legacy form actions and layouts",
            "Runtime application of the preserved legacy visibility matrix",
            "External procedure implementations and separately stored legacy RACI data",
            "BPMN XSD validation against a locally supplied schema set",
        ],
    }
    report_path = output_dir / "conversion-report.json"
    _write_json(report_path, report)
    if report["summary"]["errors"]:
        raise ConversionError(
            f"Conversion artifacts were written, but {report['summary']['errors']} validation/conversion errors were reported in {report_path}."
        )
    return report
