import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from aurea_converter.cli import process_main, source_main
from aurea_converter.converter import (
    AUREA_NS,
    BPMN_NS,
    BPMNDI_NS,
    DC_NS,
    DI_NS,
    ConversionError,
    Metadata,
    convert_definition,
)
from aurea_converter.package import validate_project_zip


FIXTURE = Path(__file__).parent / "fixtures" / "minimal.augraph.xml"
NS = {"bpmn": BPMN_NS, "bpmndi": BPMNDI_NS, "dc": DC_NS, "di": DI_NS, "aurea": AUREA_NS}


class ConverterTests(unittest.TestCase):
    def test_converts_sanitized_graph_to_valid_core_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "converted"
            report = convert_definition(
                FIXTURE.read_text(encoding="utf-8"),
                output,
                Metadata(process_definition_id="fixture-1"),
                "sanitized fixture",
            )

            self.assertTrue(report["validation"]["bpmn"]["valid"])
            self.assertTrue(report["validation"]["jsonSchema"]["valid"])
            self.assertEqual(report["summary"]["convertedConnectors"], 4)
            self.assertEqual(report["summary"]["convertedConnections"], 3)
            self.assertEqual(report["summary"]["convertedRoles"], 1)
            self.assertEqual(set(path.name for path in output.iterdir()), {
                "process.bpmn", "process.form", "process.schema.json",
                "process.ui-options.json", "id-map.json",
                "legacy-visibility.json",
                "conversion-report.json", "source.augraph.xml",
                ".project.json", "project.zip",
            })
            self.assertTrue(report["validation"]["projectPackage"]["valid"])
            self.assertTrue(report["output"]["packageGenerated"])
            self.assertEqual(report["summary"]["visibilityTasksPreserved"], 1)
            self.assertEqual(report["summary"]["visibilityRulesPreserved"], 1)

            visibility = json.loads((output / "legacy-visibility.json").read_text(encoding="utf-8"))
            self.assertEqual(visibility["tasks"][0]["sourceConnectorId"], "task-1")
            self.assertEqual(visibility["tasks"][0]["targetBpmnId"], "Task_task-1")
            self.assertEqual(visibility["tasks"][0]["parameters"][0]["path"], "request.subject")

            metadata = json.loads((output / ".project.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata, {
                "name": "Sanitized process",
                "displayName": {},
                "description": {},
                "version": "1.0",
            })
            with zipfile.ZipFile(output / "project.zip") as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    [".project.json", "process.bpmn", "process.form"],
                )
                self.assertEqual(
                    json.loads(archive.read(".project.json")),
                    metadata,
                )
                self.assertEqual(
                    archive.read("process.bpmn"),
                    (output / "process.bpmn").read_bytes(),
                )
                self.assertEqual(
                    archive.read("process.form"),
                    (output / "process.form").read_bytes(),
                )

            bpmn = ET.parse(output / "process.bpmn").getroot()
            process = bpmn.find("bpmn:process", NS)
            self.assertIsNotNone(process)
            self.assertEqual(len(process.findall("bpmn:sequenceFlow", NS)), 3)
            self.assertEqual(len(bpmn.findall(".//bpmndi:BPMNEdge", NS)), 3)
            first_flow = process.find("bpmn:sequenceFlow", NS)
            self.assertEqual(first_flow.get("name"), "Submit")
            first_edge = bpmn.find(
                f".//bpmndi:BPMNEdge[@bpmnElement='{first_flow.get('id')}']",
                NS,
            )
            self.assertIsNotNone(first_edge.find("bpmndi:BPMNLabel/dc:Bounds", NS))
            self.assertIsNone(process.find("bpmn:textAnnotation[@id='Label_flow-label-1']", NS))
            self.assertTrue(all(len(edge.findall("di:waypoint", NS)) >= 2 for edge in bpmn.findall(".//bpmndi:BPMNEdge", NS)))
            self.assertEqual(len(process.findall(".//aurea:role", NS)), 1)
            self.assertEqual(len(process.findall(".//aurea:groovyScript", NS)), 1)
            task = process.find("bpmn:task", NS)
            self.assertNotIn("responsibleRef", task.attrib)
            self.assertEqual(task.get(f"{{{AUREA_NS}}}responsibleRef"), "Role_1")
            bounds = bpmn.findall(".//bpmndi:BPMNShape/dc:Bounds", NS)
            self.assertGreaterEqual(min(float(item.get("x")) for item in bounds), 100.0)
            self.assertGreaterEqual(min(float(item.get("y")) for item in bounds), 100.0)
            shape_bounds = {
                shape.get("bpmnElement"): shape.find("dc:Bounds", NS)
                for shape in bpmn.findall(".//bpmndi:BPMNShape", NS)
            }
            self.assertEqual(shape_bounds["StartEvent_start-1"].get("width"), "32")
            self.assertEqual(shape_bounds["Gateway_gateway-1"].get("width"), "44")
            self.assertEqual(shape_bounds["Task_task-1"].get("width"), "133")
            self.assertEqual(shape_bounds["Task_task-1"].get("height"), "64")
            for edge in bpmn.findall(".//bpmndi:BPMNEdge", NS):
                points = [
                    (waypoint.get("x"), waypoint.get("y"))
                    for waypoint in edge.findall("di:waypoint", NS)
                ]
                self.assertTrue(all(first != second for first, second in zip(points, points[1:])))
            self.assertEqual(
                process.find("bpmn:documentation", NS).text,
                '{"legacyDefinitionId": "fixture-1", "legacyProcessId": "SANITIZED", "legacyProcessVersion": "1.0"}',
            )
            self.assertEqual(
                process.find(".//aurea:defaultProceduresPackage", NS).text,
                "SANITIZED",
            )

            form = json.loads((output / "process.form").read_text(encoding="utf-8"))
            self.assertEqual(form["type"], "object")
            self.assertIn("request", form["properties"])
            request = form["properties"]["request"]["properties"]
            self.assertEqual(request["approved"]["type"], "boolean")
            self.assertEqual(request["priority"]["enum"], ["NORMAL", "URGENT"])
            self.assertEqual(request["details"]["properties"]["comment"]["type"], "string")
            self.assertIn("options", form)

            id_map = json.loads((output / "id-map.json").read_text(encoding="utf-8"))
            self.assertEqual(id_map["connectors"]["task-1"], "Task_task-1")

    def test_refuses_to_overwrite_a_previous_conversion(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "converted"
            xml_text = FIXTURE.read_text(encoding="utf-8")
            convert_definition(xml_text, output)
            with self.assertRaises(ConversionError):
                convert_definition(xml_text, output)

    def test_infers_unlinked_gateway_and_transition_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "converted"
            xml_text = FIXTURE.read_text(encoding="utf-8").replace(
                "<name>Accepted?</name><left>280</left>",
                "<name>Bramka</name><descriptionText></descriptionText><left>280</left>",
            ).replace(
                "    <Connector><hashCode>end-1</hashCode>",
                "    <Connector><hashCode>gateway-caption</hashCode><elementType>100</elementType><elementSubType>102</elementSubType><descriptionText>Accepted?</descriptionText><left>270</left><top>0</top></Connector>\n"
                "    <Connector><hashCode>yes-caption</hashCode><elementType>100</elementType><elementSubType>102</elementSubType><descriptionText>Yes</descriptionText><left>340</left><top>45</top></Connector>\n"
                "    <Connector><hashCode>end-1</hashCode>",
            )

            report = convert_definition(xml_text, output)

            self.assertTrue(report["validation"]["bpmn"]["valid"])
            bpmn = ET.parse(output / "process.bpmn").getroot()
            process = bpmn.find("bpmn:process", NS)
            gateway = process.find("bpmn:exclusiveGateway", NS)
            self.assertEqual(gateway.get("name"), "Accepted?")
            gateway_shape = bpmn.find(
                f".//bpmndi:BPMNShape[@bpmnElement='{gateway.get('id')}']",
                NS,
            )
            self.assertIsNotNone(gateway_shape.find("bpmndi:BPMNLabel/dc:Bounds", NS))
            gateway_flow = process.find(
                f"bpmn:sequenceFlow[@sourceRef='{gateway.get('id')}']",
                NS,
            )
            self.assertEqual(gateway_flow.get("name"), "Yes")
            annotation_texts = {
                annotation.find("bpmn:text", NS).text
                for annotation in process.findall("bpmn:textAnnotation", NS)
            }
            self.assertNotIn("Accepted?", annotation_texts)
            self.assertNotIn("Yes", annotation_texts)

    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            xml_text = FIXTURE.read_text(encoding="utf-8")
            first = root / "first"
            second = root / "second"
            metadata = Metadata(process_definition_id="fixture-1")
            convert_definition(xml_text, first, metadata, "same source")
            convert_definition(xml_text, second, metadata, "same source")
            self.assertEqual(
                {path.name: path.read_bytes() for path in first.iterdir()},
                {path.name: path.read_bytes() for path in second.iterdir()},
            )

    def test_csv_cli_selects_one_definition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path = root / "definitions.csv"
            columns = [
                "process_definition_id", "process_id", "process_version",
                "process_name", "combined_definition_xml",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerow({
                    "process_definition_id": "1",
                    "process_id": "SANITIZED",
                    "process_version": "1.0",
                    "process_name": "Sanitized process",
                    "combined_definition_xml": FIXTURE.read_text(encoding="utf-8"),
                })
                writer.writerow({
                    "process_definition_id": "2",
                    "process_id": "LARGE_SANITIZED",
                    "process_version": "1.0",
                    "process_name": "Large sanitized process",
                    "combined_definition_xml": FIXTURE.read_text(encoding="utf-8").replace(
                        "<Swimlanes/>", f"<Swimlanes/><!-- {'x' * 140000} -->"
                    ),
                })
            output = root / "converted"
            exit_code = process_main([
                "--source", str(csv_path), "--definition-id", "1", "--output", str(output)
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue((output / "conversion-report.json").is_file())

    def test_source_cli_converts_extracted_process_model_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "dataset"
            models = dataset / "process_models"
            models.mkdir(parents=True)
            xml_text = FIXTURE.read_text(encoding="utf-8").replace(
                ' xmlns="http://xmlns.tecna.pl/xml/ns/diagram"', "", 1
            ).replace("\n", "\r\n")
            model = models / "sanitized.augraph.xml"
            model.write_bytes(xml_text.encode("utf-8"))
            manifest = {
                "format_version": 1,
                "model_count": 1,
                "models": [{
                    "process_definition_id": "fixture-1",
                    "process_id": "SANITIZED",
                    "process_version": "1.0",
                    "process_name": "Sanitized process",
                    "file": model.name,
                    "sha256": __import__("hashlib").sha256(xml_text.encode("utf-8")).hexdigest(),
                    "definition_format": "AuGraph",
                }],
            }
            (models / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "converted"

            exit_code = source_main([str(dataset), "--output", str(output), "--quiet"])

            self.assertEqual(exit_code, 0)
            converted = next(output.iterdir())
            report = json.loads((converted / "conversion-report.json").read_text(encoding="utf-8"))
            self.assertGreater(report["summary"]["formProperties"], 0)
            self.assertFalse(any(item["code"] == "PROCESS_DATA_MISSING" for item in report["diagnostics"]))
            self.assertTrue(any(item["code"] == "LEGACY_NAMESPACE_NORMALIZED" for item in report["diagnostics"]))
            self.assertTrue((converted / "project.zip").is_file())

    def test_package_validator_rejects_backend_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "invalid.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(".project.json", json.dumps({
                    "name": "Sanitized", "displayName": {},
                    "description": {}, "version": "1.0.0",
                }))
                archive.writestr("process.bpmn", "<definitions/>")
                archive.writestr("process.form", "{}")
                archive.writestr("unsupported.exe", b"not executable")
            result = validate_project_zip(archive_path)
            self.assertFalse(result["valid"])
            self.assertTrue(any("extension" in error for error in result["errors"]))

    def test_package_validator_rejects_zip_slip_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "invalid.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(".project.json", json.dumps({
                    "name": "Sanitized", "displayName": {},
                    "description": {}, "version": "1.0.0",
                }))
                archive.writestr("process.bpmn", "<definitions/>")
                archive.writestr("process.form", "{}")
                archive.writestr("../outside.txt", "unsafe")
            result = validate_project_zip(archive_path)
            self.assertFalse(result["valid"])
            self.assertTrue(any("Suspicious" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
