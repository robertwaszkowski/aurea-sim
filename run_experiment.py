import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(errors='replace')

import argparse
import json
import os
import subprocess
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("[AureaSim] Installing missing package: openpyxl...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])

import pandas as pd
from aureasim.sanitizer import auto_sanitize_bpmn
from aureasim.executor import execute_scenario
from aureasim.analyzer import analyze_scenario_log, generate_detailed_excel
from aureasim.reporter import (
    generate_charts,
    generate_docx_report,
    generate_latex_report,
    generate_offline_executive_summary,
    generate_pdf_report,
)
from aureasim.reference_data import apply_eligible_historical_analogues, repository_status

def main():
    parser = argparse.ArgumentParser(description="AureaSim Generic Simulation Runner")
    parser.add_argument("--bpmn", required=True, help="Path to raw BPMN 2.0 XML")
    parser.add_argument("--config", required=True, help="Path to JSON Experiment config file")
    parser.add_argument("--outdir", default="./results", help="Output directory for logs and reports")
    parser.add_argument("--params", required=False, help="Path to base parameters JSON file (overrides config)")
    parser.add_argument("--reference-repository", help="Portable historical-task repository used for evidence validation")
    
    args = parser.parse_args()

    if args.reference_repository:
        os.environ["AUREASIM_HISTORICAL_REPOSITORY"] = args.reference_repository
    reference_status = repository_status(Path(__file__).resolve().parent)
    if reference_status["configured"] and not reference_status["valid"]:
        raise ValueError(f"Reference repository is invalid: {reference_status.get('error', 'unknown error')}")

    os.makedirs(args.outdir, exist_ok=True)
    
    print("==================================================")
    print("AUREASIM BPMN SIMULATION PIPELINE INITIALIZING")
    print("Reference data:", "active" if reference_status["valid"] else "not configured")
    print("==================================================")
    
    with open(args.config, 'r', encoding='utf-8') as f:
        experiment_conf = json.load(f)
        
    config_dir = os.path.dirname(os.path.abspath(args.config))
    raw_base_path = experiment_conf.get("base_parameters", "")
    
    if args.params:
        base_json_path = args.params
    else:
        if os.path.isabs(raw_base_path):
            base_json_path = raw_base_path
        else:
            base_json_path = os.path.join(config_dir, raw_base_path)
            
    with open(base_json_path, 'r', encoding='utf-8') as f:
        prosimos_base = json.load(f)

    if reference_status["valid"]:
        metadata = prosimos_base.get("metadata", {})
        prosimos_base, applied = apply_eligible_historical_analogues(
            prosimos_base,
            repository_path=Path(str(reference_status["path"])),
            project_path=Path(args.bpmn).resolve(),
            process_alias=str(metadata.get("process_alias") or Path(args.bpmn).stem),
            process_id=str(metadata.get("process_id") or Path(args.bpmn).stem),
            process_version=str(metadata.get("process_version") or "unknown"),
        )
        print(f"Reference-data analogue durations applied: {len(applied)}")

    # 1. Sanitize BPMN
    s_bpmn_path = auto_sanitize_bpmn(args.bpmn, args.outdir, params=prosimos_base)

    # 2 & 3. Iterate Scenarios and Analyze
    scenarios = experiment_conf.get("scenarios", [])
    results = []
    baseline_df = None
    dfs_dict = {}
    
    for s_def in scenarios:
        s_name = s_def['name']
        log_out = os.path.join(args.outdir, f"log_{s_name}.csv")
        
        # Execute dynamically
        active_rates = execute_scenario(s_def, prosimos_base, s_bpmn_path, log_out, total_cases=500)
        
        # Analyze log
        kpis_config = experiment_conf.get("report_settings", {}).get("kpis", {})
        kpi, df = analyze_scenario_log(s_name, log_out, active_rates, kpis_config, prosimos_base)
        
        if kpi:
            results.append(kpi)
            if df is not None:
                dfs_dict[s_name] = df
            if s_name == "Base" or baseline_df is None:
                baseline_df = df
                
    # 4. Generate Reports
    if results:
        results_df = pd.DataFrame(results)
        
        # Save CSV
        results_df.to_csv(os.path.join(args.outdir, "Simulation_KPIs.csv"), index=False, encoding='utf-8-sig')
        
        # Generate Detailed Excel for first/baseline scenario
        if baseline_df is not None:
            generate_detailed_excel(baseline_df, os.path.join(args.outdir, "Baseline_Resource_Costs.xlsx"))
        
        # Charts
        charts_img = os.path.join(args.outdir, "Scenario_Comparison.png")
        generate_charts(results_df, charts_img)
        
        # DOCX Document
        report_docx = os.path.join(args.outdir, "Experiment_Report.docx")
        generate_docx_report(
            experiment_conf.get("report_settings", {}),
            results_df,
            charts_img,
            report_docx,
            dfs_dict=dfs_dict,
            base_config=prosimos_base,
            scenarios_config=scenarios
        )

        # Keep CLI/replay artifacts aligned with projects produced by the GUI.
        offline_summary = generate_offline_executive_summary(results_df)
        Path(args.outdir, "AI_Executive_Summary.md").write_text(
            offline_summary,
            encoding="utf-8",
        )
        canonical_docx = os.path.join(args.outdir, "AureaSim_Report.docx")
        generate_docx_report(
            experiment_conf.get("report_settings", {}),
            results_df,
            charts_img,
            canonical_docx,
            ai_summary_text=offline_summary,
            dfs_dict=dfs_dict,
            base_config=prosimos_base,
            scenarios_config=scenarios,
        )
        generate_pdf_report(
            experiment_conf.get("report_settings", {}),
            results_df,
            charts_img,
            os.path.join(args.outdir, "AureaSim_Report.pdf"),
            ai_summary_text=offline_summary,
            dfs_dict=dfs_dict,
            base_config=prosimos_base,
            scenarios_config=scenarios,
        )
        generate_latex_report(
            experiment_conf.get("report_settings", {}),
            results_df,
            charts_img,
            os.path.join(args.outdir, "AureaSim_Report_Source.tex"),
            ai_summary_text=offline_summary,
            dfs_dict=dfs_dict,
            base_config=prosimos_base,
            scenarios_config=scenarios,
        )
        
        print("==================================================")
        print("🎉 PIPELINE EXECUTED SUCCESSFULLY")
        print(f"Results available in: {args.outdir}")
        print("==================================================")
    else:
        print("[!] No results generated. Check if simulation executed correctly.")

if __name__ == "__main__":
    main()
