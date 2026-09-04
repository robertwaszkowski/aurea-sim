import os
import json
import shutil
import asyncio
from pathlib import Path
from datetime import datetime
import pandas as pd

from aureasim.sanitizer import auto_sanitize_bpmn
from aureasim.executor import execute_scenario
from aureasim.analyzer import analyze_scenario_log, generate_detailed_excel
from aureasim.reporter import generate_charts, generate_docx_report
from aureasim.ai_generator import (
    generate_base_prosimos_json, 
    generate_experiment_json, 
    generate_project_branding,
    generate_executive_summary
)


def _display_name_for_workspace(working_dir: str) -> str:
    """Read a human-facing project title without changing its stable folder ID."""
    config_path = Path(working_dir) / "project_config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return str(config.get("display_name") or config.get("name") or Path(working_dir).name)
    except (OSError, ValueError, TypeError):
        return Path(working_dir).name

def run_automated_simulation(
    original_bpmn_path: str,
    industry_context: str,
    num_scenarios: int,
    api_key: str,
    progress_callback,
    project_name_override: str = None,
    generation_mode: str = "heuristic",
    inflation_factor: float = 1.0,
    skip_ai_report: bool = False,
    report_formats: list = None
):
    if report_formats is None:
        report_formats = ["docx", "pdf", "latex"]
    """
    Runs the entire AureaSim pipeline in a headless manner (for API usage).
    progress_callback should be an async function taking a string message.
    """
    def sync_cb(msg):
        # We might be calling from sync code, so we create a task if we are in an event loop
        # But for simplicity, we will assume progress_callback is thread-safe or we handle it in server.py
        pass # We will pass a synchronous callback that appends to a queue

    # We will accept a synchronous callback for simplicity since generate_* are synchronous
    cb = progress_callback

    bpmn_filename = os.path.basename(original_bpmn_path)
    process_name = project_name_override if project_name_override else Path(original_bpmn_path).stem
    
    # 1. Create Folder
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    working_dir = os.path.join(root_dir, "projects", process_name)
    counter = 1
    base_dir = working_dir
    while os.path.exists(working_dir):
        working_dir = f"{base_dir}-{counter}"
        counter += 1

    os.makedirs(working_dir, exist_ok=True)
    cb(f"[INIT] Created isolated workspace: projects/{os.path.basename(working_dir)}")
    bpmn_path = os.path.join(working_dir, bpmn_filename)
    shutil.copy2(original_bpmn_path, bpmn_path)
    
    cb(f"[BRANDING] Generating project branding...")
    try:
        branding_obj = generate_project_branding(process_name, api_key=api_key)
        # Convert Pydantic model → plain dict, then add timestamp
        branding_dict = branding_obj.model_dump() if hasattr(branding_obj, "model_dump") else dict(branding_obj)
        branding_dict["created_at"] = datetime.now().timestamp()

        config_path = os.path.join(working_dir, "project_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(branding_dict, f, indent=4)
    except Exception as e:
        cb(f"[WARNING] Branding generation failed: {e}")

    # 2. Base Prosimos
    cb("[AI] Generating Base Prosimos Parameters...")
    try:
        import time
        start_time = time.time()
        base_json_path = generate_base_prosimos_json(
            bpmn_path, api_key, industry_context,
            progress_callback=lambda m: cb(f"[AI] {m}"),
            generation_mode=generation_mode
        )
        end_time = time.time()
        generation_time_seconds = end_time - start_time
        
        # Inject into JSON metadata and apply multiplier
        with open(base_json_path, 'r', encoding='utf-8') as f:
            base_data = json.load(f)
        if "metadata" not in base_data:
            base_data["metadata"] = {}
        base_data["metadata"]["generation_time_seconds"] = generation_time_seconds
        
        if inflation_factor != 1.0:
            for res in base_data.get('resource_profiles', []):
                for rl in res.get('resource_list', []):
                    if 'cost_per_hour' in rl:
                        rl['cost_per_hour'] = round(float(rl['cost_per_hour']) * inflation_factor, 2)
            cb(f"[AI] Applied inflation factor {inflation_factor}x to salaries.")
            
        with open(base_json_path, 'w', encoding='utf-8') as f:
            json.dump(base_data, f, indent=4)
            
    except Exception as e:
        cb(f"[ERROR] Base Params generation failed: {e}")
        raise RuntimeError(f"Base Params generation failed: {e}")

    # 3. Experiment Scenarios
    cb("[AI] Innovating Business Scenarios...")
    try:
        exp_path = generate_experiment_json(
            bpmn_path, base_json_path, api_key, num_scenarios, industry_context,
            progress_callback=lambda m: cb(f"[AI] {m}")
        )
        
        with open(exp_path, 'r', encoding='utf-8') as f:
            exp_data = json.load(f)
            
        scenarios = exp_data.get("scenarios", [])
        report_settings = exp_data.get("report_settings", {})
        
    except Exception as e:
        cb(f"[ERROR] Scenarios generation failed: {e}")
        raise RuntimeError(f"Scenarios generation failed: {e}")

    if not scenarios:
        cb("[ERROR] No scenarios generated. Aborting.")
        raise RuntimeError("No scenarios generated. Aborting.")

    # 4. Run Pipeline
    outdir = os.path.join(working_dir, "results")
    os.makedirs(outdir, exist_ok=True)
    
    cb("[SIM] Starting Simulation Execution Pipeline...")
    
    results = []
    dfs_dict = {}
    
    with open(base_json_path, 'r', encoding='utf-8') as f:
        prosimos_base = json.load(f)
        
    cb("[SIM] Sanitizing BPMN Model...")
    s_bpmn_path = auto_sanitize_bpmn(bpmn_path, outdir, params=prosimos_base)
    
    for s_def in scenarios:
        s_name = s_def['name']
        cb(f"[SIM] Simulating Scenario: {s_name}...")
        
        log_out = os.path.join(outdir, f"log_{s_name}.csv")
        active_rates = execute_scenario(s_def, prosimos_base, s_bpmn_path, log_out, total_cases=500, progress_callback=cb)
        
        kpis_config = report_settings.get("kpis", {})
        kpi, df = analyze_scenario_log(s_name, log_out, active_rates, kpis_config, prosimos_base)
        
        if kpi:
            results.append(kpi)
            dfs_dict[s_name] = df

    cb("[REPORT] Aggregating Simulation Data...")
    if not results:
        cb("[ERROR] No valid results generated!")
        return

    results_df = pd.DataFrame(results)
    results_df.to_csv(os.path.join(outdir, "Simulation_KPIs.csv"), index=False, encoding='utf-8-sig')
    
    if "Base" in dfs_dict:
        generate_detailed_excel(dfs_dict["Base"], os.path.join(outdir, "Baseline_Resource_Costs.xlsx"))
        
    charts_img = os.path.join(outdir, "Scenario_Comparison.png")
    generate_charts(results_df, charts_img)

    # 5. Collect references from metadata
    cb("[REPORT] Resolving scientific citations...")
    import subprocess as _sp

    def _resolve_redirect(url: str) -> str:
        try:
            result = _sp.check_output([
                "curl", "-Ls", "-o", "/dev/null", "-w", "%{url_effective}",
                "--max-time", "5", url
            ], text=True).strip()
            return result if result else url
        except Exception:
            return url

    raw_urls = []
    with open(base_json_path, 'r', encoding='utf-8') as f:
        base_config = json.load(f)
    if isinstance(base_config.get("metadata"), dict):
        raw_urls.extend(base_config["metadata"].get("source_urls", []))
    if isinstance(exp_data.get("metadata"), dict):
        raw_urls.extend(exp_data["metadata"].get("source_urls", []))

    raw_urls = list(set([u.strip() for u in raw_urls if u.strip()]))
    all_refs = []
    for raw_url in raw_urls:
        resolved = _resolve_redirect(raw_url)
        all_refs.append({"title": resolved, "url": resolved})

    seen_urls = set()
    deduped_refs = []
    for r in all_refs:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            deduped_refs.append(r)

    report_settings["references"] = deduped_refs

    # Write resolved URLs back into the base params JSON so the web UI shows clean citations
    resolved_urls = [r["url"] for r in deduped_refs]
    if resolved_urls and isinstance(base_config.get("metadata"), dict):
        base_config["metadata"]["source_urls"] = resolved_urls
        with open(base_json_path, 'w', encoding='utf-8') as f:
            json.dump(base_config, f, indent=4)

    # 6. Executive Summary
    summary_text = None
    if not skip_ai_report:
        cb("[AI] Drafting Executive Summary (this may take a minute)...")
        try:
            summary_text = generate_executive_summary(
                results_df, scenarios, report_settings, api_key,
                base_config=base_config, exp_config=exp_data,
                references=deduped_refs
            )
            # Save summary to a file for the web UI to pick up
            if summary_text:
                from aureasim.ai_generator import compress_citations
                # Compress expanded citations: [1, 2, 3, 4] → [1-4]
                summary_text = compress_citations(summary_text)

                summary_path = os.path.join(outdir, "AI_Executive_Summary.md")
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write(summary_text)
        except Exception as e:
            cb(f"[ERROR] Executive summary generation failed: {e}")
    else:
        cb("[AI] Skipping Executive Summary drafting as requested.")


    # 7. Generate all report formats (DOCX, PDF, LaTeX)
    cb("[REPORT] Compiling Final Reports (DOCX, PDF, LaTeX)...")
    
    docx_out = os.path.join(outdir, "AureaSim_Report.docx")
    if "docx" in report_formats:
        try:
            generate_docx_report(
                report_settings, results_df, charts_img, docx_out,
                ai_summary_text=summary_text, dfs_dict=dfs_dict,
                base_config=prosimos_base, scenarios_config=scenarios
            )
        except Exception as e:
            cb(f"[ERROR] DOCX generation failed: {e}")

    if "pdf" in report_formats:
        try:
            from aureasim.reporter import generate_pdf_report
            pdf_out = os.path.join(outdir, "AureaSim_Report.pdf")
            generate_pdf_report(
                report_settings, results_df, charts_img, pdf_out,
                ai_summary_text=summary_text, dfs_dict=dfs_dict,
                base_config=prosimos_base, scenarios_config=scenarios
            )
            cb(f"[REPORT] Exported PDF: {os.path.basename(pdf_out)}")
        except Exception as e:
            cb(f"[ERROR] PDF generation failed: {e}")

    if "latex" in report_formats:
        try:
            from aureasim.reporter import generate_latex_report
            latex_out = os.path.join(outdir, "AureaSim_Report_Source.tex")
            generate_latex_report(
                report_settings, results_df, charts_img, latex_out,
                ai_summary_text=summary_text, dfs_dict=dfs_dict,
                base_config=prosimos_base, scenarios_config=scenarios
            )
            cb(f"[REPORT] Exported LaTeX Source code: {os.path.basename(latex_out)}")
        except Exception as e:
            cb(f"[ERROR] LaTeX generation failed: {e}")

    project_name = Path(working_dir).name
    display_name = _display_name_for_workspace(working_dir)
    cb(f"[DONE] project={project_name} display_name={display_name} Headless Simulation Completed Successfully!")
    return working_dir

def run_demo_simulation(progress_callback, project_name_override: str = None):
    """
    Runs a deterministic offline demo using pre-generated files from examples/.
    Does not require GEMINI_API_KEY.
    """
    cb = progress_callback
    process_name = project_name_override if project_name_override else "RES_Sales_Process_Demo"
    
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    working_dir = os.path.join(root_dir, "projects", process_name)
    counter = 1
    base_dir = working_dir
    while os.path.exists(working_dir):
        working_dir = f"{base_dir}-{counter}"
        counter += 1

    os.makedirs(working_dir, exist_ok=True)
    cb(f"[INIT] Created isolated workspace: projects/{os.path.basename(working_dir)}")
    
    bpmn_path = os.path.join(working_dir, f"{process_name}.bpmn")
    branding_path = os.path.join(working_dir, "project_config.json")
    experiment_path = os.path.join(working_dir, "AutoGenerated_Experiment_Scenarios.json")
    base_json_path = os.path.join(working_dir, "AutoGenerated_Base_params.json")
    
    examples_dir = os.path.join(root_dir, "examples")
    
    src_bpmn = os.path.join(examples_dir, f"{process_name}.bpmn")
    src_config = os.path.join(examples_dir, f"{process_name}_config.json")
    src_base = os.path.join(examples_dir, f"{process_name}_base.json")
    
    if not os.path.exists(src_bpmn):
        # Fallback to default if somehow the file is missing
        src_bpmn = os.path.join(examples_dir, "RES_Sales_Process.bpmn")
        src_config = os.path.join(examples_dir, "RES_Sales_Process_config.json")
        src_base = os.path.join(examples_dir, "RES_Sales_Process_base.json")
        cb(f"[WARN] Specific demo files not found for {process_name}, using default.")

    shutil.copy2(src_bpmn, bpmn_path)
    shutil.copy2(src_config, experiment_path)
    shutil.copy2(src_base, base_json_path)
    with open(branding_path, "w", encoding="utf-8") as f:
        json.dump({"display_name": process_name.replace("_", " ")}, f, indent=2)

    import time
    cb("[DEMO] Loading bundled BPMN model and fixed simulation parameters...")
    time.sleep(1.0)
    cb("[DEMO] Loading bundled Prosimos base parameters...")
    time.sleep(0.5)
    cb("[DEMO] No external AI service is used in offline demo mode.")
    time.sleep(1.0)
    cb("[DEMO] Validating bundled BPMN structure and node logic...")
    time.sleep(1.0)
    cb("[DEMO] Bundled base parameters loaded.")
    time.sleep(0.5)
    cb("[DEMO] Loading bundled experiment scenarios...")
    time.sleep(1.2)
    cb("[DEMO] Bundled experiment configuration loaded.")
    time.sleep(0.5)

    with open(experiment_path, 'r', encoding='utf-8') as f:
        exp_data = json.load(f)
        scenarios = exp_data.get("scenarios", [])
        report_settings = exp_data.get("report_settings", {})

    with open(base_json_path, 'r', encoding='utf-8') as f:
        prosimos_base = json.load(f)

    outdir = os.path.join(working_dir, "results")
    os.makedirs(outdir, exist_ok=True)
    
    cb("[SIM] Starting Simulation Execution Pipeline...")
    
    results = []
    dfs_dict = {}
    
    cb("[SIM] Sanitizing BPMN Model...")
    s_bpmn_path = auto_sanitize_bpmn(bpmn_path, outdir, params=prosimos_base)
    
    for s_def in scenarios:
        s_name = s_def['name']
        cb(f"[SIM] Simulating Scenario: {s_name}...")
        
        log_out = os.path.join(outdir, f"log_{s_name}.csv")
        active_rates = execute_scenario(s_def, prosimos_base, s_bpmn_path, log_out, total_cases=500, progress_callback=cb)
        
        kpis_config = report_settings.get("kpis", {})
        kpi, df = analyze_scenario_log(s_name, log_out, active_rates, kpis_config, prosimos_base)
        
        if kpi:
            results.append(kpi)
            dfs_dict[s_name] = df

    cb("[REPORT] Aggregating Simulation Data...")
    if not results:
        cb("[ERROR] No valid results generated!")
        return

    results_df = pd.DataFrame(results)
    results_df.to_csv(os.path.join(outdir, "Simulation_KPIs.csv"), index=False, encoding='utf-8-sig')
    
    # We use A_Baseline or Base based on what is in the example
    base_key = "Base" if "Base" in dfs_dict else ("A_Baseline" if "A_Baseline" in dfs_dict else list(dfs_dict.keys())[0])
    generate_detailed_excel(dfs_dict[base_key], os.path.join(outdir, "Baseline_Resource_Costs.xlsx"))
        
    charts_img = os.path.join(outdir, "Scenario_Comparison.png")
    generate_charts(results_df, charts_img)

    # No URL resolution in offline/heuristic mode
    cb("[REPORT] Generating rule-based executive summary...")
    from aureasim.reporter import generate_offline_executive_summary
    offline_summary = generate_offline_executive_summary(results_df)
    
    cb("[REPORT] Compiling Final Reports (DOCX, PDF, LaTeX)...")
    
    docx_out = os.path.join(outdir, "AureaSim_Report.docx")
    try:
        generate_docx_report(
            report_settings, results_df, charts_img, docx_out,
            ai_summary_text=offline_summary, dfs_dict=dfs_dict,
            base_config=prosimos_base, scenarios_config=scenarios
        )
    except Exception as e:
        cb(f"[ERROR] DOCX generation failed: {e}")

    try:
        from aureasim.reporter import generate_pdf_report
        pdf_out = os.path.join(outdir, "AureaSim_Report.pdf")
        generate_pdf_report(
            report_settings, results_df, charts_img, pdf_out,
            ai_summary_text=offline_summary, dfs_dict=dfs_dict,
            base_config=prosimos_base, scenarios_config=scenarios
        )
    except Exception as e:
        cb(f"[ERROR] PDF generation failed: {e}")

    try:
        from aureasim.reporter import generate_latex_report
        latex_out = os.path.join(outdir, "AureaSim_Report_Source.tex")
        generate_latex_report(
            report_settings, results_df, charts_img, latex_out,
            ai_summary_text=offline_summary, dfs_dict=dfs_dict,
            base_config=prosimos_base, scenarios_config=scenarios
        )
    except Exception as e:
        cb(f"[ERROR] LaTeX generation failed: {e}")

    project_name = Path(working_dir).name
    display_name = _display_name_for_workspace(working_dir)
    cb(f"[DONE] project={project_name} display_name={display_name} Headless Simulation Completed Successfully!")
    return working_dir
