import os
import json
import xml.etree.ElementTree as ET

BPMN_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
namespaces = {'bpmn': BPMN_NS}
ET.register_namespace('bpmn', BPMN_NS)
ET.register_namespace('bpmndi', 'http://www.omg.org/spec/BPMN/20100524/DI')
ET.register_namespace('dc', 'http://www.omg.org/spec/DD/20100524/DC')
ET.register_namespace('di', 'http://www.omg.org/spec/DD/20100524/DI')

def auto_sanitize_bpmn(bpmn_path, output_dir, params=None):
    """
    Parses a raw BPMN 2.0 file and prepares it for the Prosimos engine.
    Applies flattening rules to Sub-Processes and merges multiple End Events.
    Validates against expected params if provided.
    """
    print(f"[Sanitizer] Analyzing and sanitizing BPMN: {bpmn_path}...")
    
    tree = ET.parse(bpmn_path)
    root = tree.getroot()

    report = {
        "normalized_tasks": [],
        "removed_message_flows": [],
        "flattened_subprocesses": [],
        "warnings": [],
        "errors": []
    }

    # 1. Task Normalization
    task_types = ['userTask', 'manualTask', 'serviceTask', 'scriptTask', 'receiveTask', 'sendTask']
    for process in root.findall('.//bpmn:process', namespaces):
        for t_type in task_types:
            for elem in process.findall(f'bpmn:{t_type}', namespaces):
                t_id = elem.get('id', 'unknown')
                t_name = elem.get('name', '')
                report["normalized_tasks"].append({"id": t_id, "name": t_name, "from_type": t_type})
                elem.tag = f"{{{BPMN_NS}}}task"

    # 2. Message Flow Removal (Only collaboration level)
    for collab in root.findall('.//bpmn:collaboration', namespaces):
        flows = collab.findall('bpmn:messageFlow', namespaces)
        for flow in flows:
            f_id = flow.get('id', 'unknown')
            f_name = flow.get('name', '')
            report["removed_message_flows"].append({"id": f_id, "name": f_name})
            collab.remove(flow)

    # 3. SubProcess Flattening
    for process in root.findall('.//bpmn:process', namespaces):
        subprocesses = process.findall('bpmn:subProcess', namespaces)
        for sub in subprocesses:
            sub_id = sub.get('id')
            sub_name = sub.get('name', '')
            print(f"  -> Flattening SubProcess: {sub_id}")
            
            # Find internal start/end events
            starts = sub.findall('bpmn:startEvent', namespaces)
            ends = sub.findall('bpmn:endEvent', namespaces)
            
            if len(starts) != 1 or len(ends) != 1:
                raise ValueError(f"SubProcess {sub_id} is not well-structured (must have exactly one start and one end event). Found {len(starts)} starts, {len(ends)} ends.")
            
            start_id = starts[0].get('id')
            end_id = ends[0].get('id')

            # Find boundary events attached to this subprocess and remove them (unsupported by Prosimos in this context)
            boundaries = process.findall(f'bpmn:boundaryEvent[@attachedToRef="{sub_id}"]', namespaces)
            for b in boundaries:
                process.remove(b)

            # Find the internal flows that connect from start and to end
            internal_start_flow = sub.find(f'bpmn:sequenceFlow[@sourceRef="{start_id}"]', namespaces)
            internal_end_flow = sub.find(f'bpmn:sequenceFlow[@targetRef="{end_id}"]', namespaces)

            if internal_start_flow is None or internal_end_flow is None:
                raise ValueError(f"SubProcess {sub_id} is not well-structured (missing internal flows from start or to end event).")
                
            first_task_id = internal_start_flow.get('targetRef')
            last_task_id = internal_end_flow.get('sourceRef')

            # Reroute external flows that were pointing to/from the SubProcess
            for flow in process.findall('bpmn:sequenceFlow', namespaces):
                if flow.get('targetRef') == sub_id:
                    flow.set('targetRef', first_task_id)
                if flow.get('sourceRef') == sub_id:
                    flow.set('sourceRef', last_task_id)

            # Extract internal elements (tasks, gateways, other flows) excluding start/end and their direct flows
            for child in list(sub):
                if child.tag in [f"{{{BPMN_NS}}}startEvent", f"{{{BPMN_NS}}}endEvent"]:
                    continue
                if child.tag == f"{{{BPMN_NS}}}sequenceFlow" and child.get('id') in [internal_start_flow.get('id'), internal_end_flow.get('id')]:
                    continue
                # Move to process level
                process.append(child)

            # Remove SubProcess shell
            process.remove(sub)
            report["flattened_subprocesses"].append({"id": sub_id, "name": sub_name})

    # 4. End Event Normalization
    for process in root.findall('.//bpmn:process', namespaces):
        end_events = process.findall('bpmn:endEvent', namespaces)
        if len(end_events) > 1:
            master_end = end_events[0]
            master_id = master_end.get('id')
            print(f"  -> Found {len(end_events)} End Events. Merging them into master ID: {master_id}")
            report["warnings"].append(f"Merged {len(end_events)-1} obsolete end events into master ID: {master_id}")
            
            for obsolete in end_events[1:]:
                obsolete_id = obsolete.get('id')
                # Reroute flows
                for flow in process.findall('bpmn:sequenceFlow', namespaces):
                    if flow.get('targetRef') == obsolete_id:
                        flow.set('targetRef', master_id)
                process.remove(obsolete)

    # 5. Validation
    all_flow_refs = set()
    all_element_ids = set()
    has_start = False
    has_end = False
    
    for process in root.findall('.//bpmn:process', namespaces):
        for elem in process:
            e_id = elem.get('id')
            if e_id:
                all_element_ids.add(e_id)
            if elem.tag == f"{{{BPMN_NS}}}sequenceFlow":
                all_flow_refs.add(elem.get('sourceRef'))
                all_flow_refs.add(elem.get('targetRef'))
            elif elem.tag == f"{{{BPMN_NS}}}startEvent":
                has_start = True
            elif elem.tag == f"{{{BPMN_NS}}}endEvent":
                has_end = True
                
        # Prosimos does not support complex gateways easily if not strictly balanced, but we just check if they are supported types
        for gw in process.findall('bpmn:complexGateway', namespaces) + process.findall('bpmn:eventBasedGateway', namespaces):
            report["warnings"].append(f"Unsupported gateway type found: {gw.tag}")

    dangling = all_flow_refs - all_element_ids
    if dangling:
        raise ValueError(f"Sanitization resulted in dangling sequence flow references: {dangling}")
        
    if not has_start or not has_end:
        raise ValueError("Process must contain at least one startEvent and one endEvent.")

    if params:
        # Check all tasks in task_resource_distribution
        expected_tasks = {t['task_id'] for t in params.get('task_resource_distribution', [])}
        missing = expected_tasks - all_element_ids
        if missing:
            raise ValueError(f"Validation failed: AI generated parameters for task IDs that do not exist in the sanitized BPMN: {missing}")

    base_name = os.path.basename(bpmn_path)
    os.makedirs(output_dir, exist_ok=True)
    sanitized_path = os.path.join(output_dir, f"SANITIZED_{base_name}")
    report_path = os.path.join(output_dir, "sanitizer_report.json")
    
    tree.write(sanitized_path, encoding='utf-8', xml_declaration=True)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=4)
        
    print(f"[Sanitizer] ✅ Success! Created: {sanitized_path}\n")
    return sanitized_path
