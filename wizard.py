import os
import glob
import json
import time
from pathlib import Path
import warnings
import sys

# Force UTF-8 on Windows so Rich borders don't render as gibberish (â”Œ...)
if sys.platform == "win32":
    os.system("chcp 65001 > nul")

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(errors='replace')

# Suppress seaborn/pandas warnings for clean CLI output
warnings.filterwarnings("ignore")


import questionary
from questionary import Style

CUSTOM_STYLE = Style([
    ('qmark', 'fg:ansicyan bold'),
    ('question', 'bold'),
    ('answer', 'fg:ansiyellow bold'),
    ('pointer', 'fg:ansicyan bold'),
    ('highlighted', 'fg:ansicyan bold noreverse'),
    ('selected', 'fg:ansicyan bold noreverse'),
    ('separator', 'fg:ansigray'),
    ('instruction', 'fg:ansigray italic'),
    ('text', ''),
    ('disabled', 'fg:ansigray italic')
])

_orig_select = questionary.select
def custom_select(*args, **kwargs):
    kwargs.setdefault('style', CUSTOM_STYLE)
    return _orig_select(*args, **kwargs)
questionary.select = custom_select

_orig_text = questionary.text
def custom_text(*args, **kwargs):
    kwargs.setdefault('style', CUSTOM_STYLE)
    return _orig_text(*args, **kwargs)
questionary.text = custom_text

_orig_confirm = questionary.confirm
def custom_confirm(*args, **kwargs):
    kwargs.setdefault('style', CUSTOM_STYLE)
    return _orig_confirm(*args, **kwargs)
questionary.confirm = custom_confirm

_orig_checkbox = questionary.checkbox
def custom_checkbox(*args, **kwargs):
    kwargs.setdefault('style', CUSTOM_STYLE)
    return _orig_checkbox(*args, **kwargs)
questionary.checkbox = custom_checkbox

_orig_password = questionary.password
def custom_password(*args, **kwargs):
    kwargs.setdefault('style', CUSTOM_STYLE)
    return _orig_password(*args, **kwargs)
questionary.password = custom_password

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, MofNCompleteColumn
from rich.table import Table
from rich import box

import pandas as pd
from dotenv import load_dotenv, set_key

class ExecutionTracker:
    def __init__(self):
        self.steps = []
        self.start_times = {}

    def start(self, step_name):
        self.start_times[step_name] = time.time()

    def stop(self, step_name, status="[green]Completed[/green]"):
        if step_name in self.start_times:
            elapsed = time.time() - self.start_times.pop(step_name)
            self.steps.append((step_name, elapsed, status))

    def omit(self, step_name, reason="[yellow]Omitted[/yellow]"):
        self.steps.append((step_name, 0.0, reason))

    def print_summary(self):
        from rich.table import Table
        from rich import box
        
        table = Table(title="⏱️  Execution Time Summary", show_header=True, header_style="bold magenta", box=box.ROUNDED)
        table.add_column("Step", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Time", justify="right")
        
        total_time = 0.0
        for step_name, elapsed, status in self.steps:
            total_time += elapsed
            if elapsed > 0:
                if elapsed < 1.0:
                    time_str = f"{elapsed*1000:.0f}ms"
                else:
                    time_str = f"{elapsed:.2f}s"
            else:
                time_str = "-"
            table.add_row(step_name, status, time_str)
            
        table.add_row("Total Execution Time", "", f"[bold]{total_time:.2f}s[/bold]", style="bold")
        console.print(table)

tracker = ExecutionTracker()


from aureasim.sanitizer import auto_sanitize_bpmn
from aureasim.executor import execute_scenario
from aureasim.analyzer import analyze_scenario_log, generate_detailed_excel
from aureasim.reporter import generate_charts, generate_docx_report
from aureasim.ai_generator import generate_base_prosimos_json, generate_experiment_json, generate_project_branding

console = Console()

def print_banner():
    banner = Text("AureaSim Interactive Wizard", style="bold cyan", justify="center")
    console.print(Panel(banner, border_style="cyan"))
    console.print()

def find_files(extension):
    """Finds files in current directory & subdirectories avoiding dot-folders."""
    files = []
    for root, dirs, filenames in os.walk("."):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for name in filenames:
            if name.endswith(extension):
                files.append(os.path.join(root, name))
    return files

def configure_manual_scenarios():
    console.print("\n[bold yellow]Interactive Scenario Configuration[/bold yellow]")
    scenarios = []
    num_str = questionary.text("How many scenarios do you want to configure?", default="1").ask()
    
    if not num_str or not num_str.isdigit():
        return []
        
    num_scenarios = int(num_str)
    
    for i in range(num_scenarios):
        console.print(f"\n[cyan]--- Scenario {i+1} ---[/cyan]")
        name = questionary.text(f"Scenario Name (e.g., S{i+1}):", default=f"Scenario_{i+1}").ask()
        arrival_str = questionary.text("Arrival rate (e.g., 28800 for 8hr, 144000 for week):", default="144000").ask()
        
        allocations = {}
        while questionary.confirm("Add dynamic human resource override?", default=False).ask():
            res_id = questionary.text("Resource ID (e.g., DPE, RKR):").ask()
            count_str = questionary.text(f"Amount of staff for '{res_id}':").ask()
            if count_str and count_str.isdigit():
                allocations[res_id] = int(count_str)
            
        cost_overrides = {}
        while questionary.confirm("Add custom cost/hour override for a resource?", default=False).ask():
            res_id = questionary.text("Resource ID:").ask()
            cost_str = questionary.text(f"New Hourly Rate for '{res_id}':").ask()
            if cost_str and cost_str.isdigit():
                cost_overrides[res_id] = int(cost_str)
            
        scene = {
            "name": name,
            "arrival_rate": int(arrival_str) if arrival_str.isdigit() else 144000
        }
        if allocations: scene["resource_allocations"] = allocations
        if cost_overrides: scene["cost_overrides"] = cost_overrides
        scenarios.append(scene)
        
    return scenarios

def run_pipeline(bpmn_path, base_json_path, scenarios, report_settings, outdir, exp_config=None, should_resolve_refs=False, offline_demo_mode=False):
    os.makedirs(outdir, exist_ok=True)
    
    results = []
    dfs_dict = {}
    
    with open(base_json_path, 'r', encoding='utf-8') as f:
        prosimos_base = json.load(f)
        
    console.print()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(complete_style="cyan", finished_style="green"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=False,
        console=console
    ) as progress:
        
        # Task 1: Sanitization
        task1 = progress.add_task("[cyan]Sanitizing BPMN Model...", total=1)
        # Suppress stdout from modules so it doesn't break the progress bar
        import builtins
        original_print = builtins.print
        builtins.print = lambda *args, **kwargs: None
        
        tracker.start('BPMN Sanitization')
        s_bpmn_path = auto_sanitize_bpmn(bpmn_path, outdir)
        tracker.stop('BPMN Sanitization')
        progress.update(task1, advance=1, description="[green]BPMN Sanitized!")
        
        # Task 2: Executions
        tracker.start('Simulation Engine')
        for s_def in scenarios:
            s_name = s_def['name']
            s_task = progress.add_task(f"[cyan]Simulating Domain Scenario: {s_name}...", total=1)
            
            log_out = os.path.join(outdir, f"log_{s_name}.csv")
            active_rates = execute_scenario(s_def, prosimos_base, s_bpmn_path, log_out, total_cases=500)
            
            kpis_config = report_settings.get("kpis", {})
            kpi, df = analyze_scenario_log(s_name, log_out, active_rates, kpis_config, prosimos_base)
            
            if kpi:
                results.append(kpi)
                dfs_dict[s_name] = df
                    
            progress.update(s_task, advance=1, description=f"  [green]✔[/green]  Simulated: {s_name}")
        tracker.stop('Simulation Engine')
        
        # Task 3: Reporting
        task3 = progress.add_task("[cyan]Aggregating Simulation Data...", total=1)
        if results:
            tracker.start('Data Aggregation')
            results_df = pd.DataFrame(results)
            results_df.to_csv(os.path.join(outdir, "Simulation_KPIs.csv"), index=False, encoding='utf-8-sig')
            if "Base" in dfs_dict:
                generate_detailed_excel(dfs_dict["Base"], os.path.join(outdir, "Baseline_Resource_Costs.xlsx"))
                
            charts_img = os.path.join(outdir, "Scenario_Comparison.png")
            generate_charts(results_df, charts_img)
            tracker.stop('Data Aggregation')
            
            progress.update(task3, advance=1, description="[green]Data Aggregated!")
            builtins.print = original_print # Restore printing
            
        else:
            builtins.print = original_print # Restore printing
            console.print("[red]No valid results generated![/red]")
            return
            
    # Outside the Progress block (Terminal is now free)
    if results:
        console.print()
        table = Table(title="Simulation Final KPIs", show_header=True, header_style="bold cyan", box=box.SQUARE)
        
        terminal_df = results_df.copy()
        terminal_df.columns = [c.replace("Wait_Time_Hrs_", "Wait: ")
                                .replace("Avg_Cycle_Time_Days", "Cycle (days)")
                                .replace("Avg_Cost_Per_Case_PLN", "Cost (PLN)")
                                .replace("Total_Cases", "Cases") 
                               for c in terminal_df.columns]
                               
        if "Scenario" in terminal_df.columns:
            terminal_df.set_index("Scenario", inplace=True)
            terminal_df = terminal_df.T
            terminal_df.reset_index(inplace=True)
            terminal_df.rename(columns={"index": "Metric"}, inplace=True)
            
            table.add_column("Metric", style="bold cyan", justify="left")
            for col in terminal_df.columns[1:]:
                table.add_column(str(col), justify="center", style="green")
        else:
            for col in terminal_df.columns:
                table.add_column(col, justify="center")
                
        for _, row in terminal_df.iterrows():
            table.add_row(*[str(x) for x in row])
            
        console.print(table)
        console.print()
        # Build the deduplicated reference list FIRST so it can be passed
        # to the AI for inline citation numbering ([1], [2], etc.)
        import urllib.request

        import subprocess

        def _resolve_redirect(url: str) -> str:
            """Follow a redirect URL to its final destination using curl."""
            try:
                # -L: follow redirects, -s: silent, -o /dev/null: don't save body, 
                # -w %{url_effective}: return final URL, --max-time: timeout
                result = subprocess.check_output([
                    "curl", "-Ls", "-o", "/dev/null", "-w", "%{url_effective}", 
                    "--max-time", "5", url
                ], text=True).strip()
                return result if result else url
            except Exception:
                return url  # Fallback: original URL

        def _collect_refs(meta: dict) -> list:
            raw_urls = meta.get("source_urls", [])
            refs = []
            for raw_url in raw_urls:
                raw_url = raw_url.strip()
                resolved = _resolve_redirect(raw_url)
                refs.append({"title": resolved, "url": resolved})
            return refs

        # ---------------------------------------------------------
        # PROGRESS BAR FOR REFERENCE RESOLUTION
        # ---------------------------------------------------------
        raw_urls_to_resolve = []
        if prosimos_base and isinstance(prosimos_base.get("metadata"), dict):
            raw_urls_to_resolve.extend(prosimos_base["metadata"].get("source_urls", []))
        if exp_config and isinstance(exp_config.get("metadata"), dict):
            raw_urls_to_resolve.extend(exp_config["metadata"].get("source_urls", []))
            
        # Deduplicate raw URLs first so we don't resolve the same link twice
        raw_urls_to_resolve = list(set([u.strip() for u in raw_urls_to_resolve if u.strip()]))
        
        all_refs = []
        tracker.start('Reference Resolution')
        if raw_urls_to_resolve:
            if should_resolve_refs:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[cyan]{task.description}"),
                    BarColumn(pulse_style="cyan"),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                    transient=True
                ) as ref_prog:
                    task = ref_prog.add_task("Resolving scientific citations...", total=len(raw_urls_to_resolve))
                    for raw_url in raw_urls_to_resolve:
                        resolved = _resolve_redirect(raw_url)
                        all_refs.append({"title": resolved, "url": resolved})
                        ref_prog.update(task, advance=1)
            else:
                for raw_url in raw_urls_to_resolve:
                    all_refs.append({"title": raw_url, "url": raw_url})
        tracker.stop('Reference Resolution')

        # Final deduplication (just in case they resolved to the same endpoint)
        seen_urls = set()
        deduped_refs = []
        for r in all_refs:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                deduped_refs.append(r)
                
        report_settings["references"] = deduped_refs

        # 1. First, decide on content (AI Analysis vs Offline analysis)
        ai_summary_text = None

        if offline_demo_mode:
            tracker.start('Offline Executive Summary')
            from aureasim.reporter import generate_offline_executive_summary
            ai_summary_text = generate_offline_executive_summary(results_df)
            tracker.stop('Offline Executive Summary')
            console.print("  [bold green]✔  Offline Executive Summary generated successfully![/bold green]")
        else:
            summary_method = questionary.select(
                "How would you like to write the Executive Summary for the report package?",
                choices=[
                    "🪄  Auto-Generate via Gemini AI (Requires API Key)",
                    "⚙️  Generate offline (Rule-Based analysis)",
                    "❌  Skip Executive Summary"
                ]
            ).ask()

            if summary_method == "🪄  Auto-Generate via Gemini AI (Requires API Key)":
                tracker.start('AI Executive Summary')
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    api_key = questionary.password("Please enter your Google Gemini API Key:").ask()

                if api_key:
                    try:
                        from aureasim.ai_generator import generate_executive_summary
                        with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn(pulse_style="cyan"), TimeElapsedColumn(), transient=True) as ai_prog:
                            ai_prog.add_task("AI Consultant analyzing results and writing Executive Summary...", total=None)
                            ai_summary_text = generate_executive_summary(
                                results_df, scenarios, report_settings, api_key,
                                prosimos_base, exp_config,
                                references=deduped_refs
                            )
                        tracker.stop('AI Executive Summary')
                        console.print("  [bold green]✔  AI Executive Summary generated successfully![/bold green]")
                    except Exception as e:
                        print_ai_error(e)
                        tracker.stop('AI Executive Summary', "[red]Failed[/red]")
                else:
                    console.print("[yellow]No API key provided. Falling back to offline rule-based report summary...[/yellow]")
                    from aureasim.reporter import generate_offline_executive_summary
                    ai_summary_text = generate_offline_executive_summary(results_df)
                    tracker.stop('AI Executive Summary', "[yellow]Offline Fallback[/yellow]")
            elif "offline" in summary_method:
                tracker.start('Offline Executive Summary')
                from aureasim.reporter import generate_offline_executive_summary
                ai_summary_text = generate_offline_executive_summary(results_df)
                tracker.stop('Offline Executive Summary')
                console.print("  [bold green]✔  Offline Executive Summary generated successfully![/bold green]")
            else:
                tracker.omit('Executive Summary', "[yellow]Skipped[/yellow]")

        # 2. Then, decide on packaging (Formats)
        report_formats = questionary.checkbox(
            "Select output formats for your report package:",
            choices=[
                questionary.Choice("DOCX (Microsoft Word)", value="docx", checked=True),
                questionary.Choice("PDF", value="pdf", checked=True),
                questionary.Choice("LaTeX (Raw source code)", value="latex", checked=True)
            ],
            instruction="\n   (Use arrow keys to move, <space> to select, <a> to toggle, <i> to invert)"
        ).ask()

        if not report_formats:
            console.print("[yellow]No report format selected. Finalizing export.[/yellow]")
            tracker.omit('Report Generation', "[yellow]No Formats[/yellow]")
        else:
            tracker.start('Report Generation')
            for fmt in report_formats:
                if fmt == "docx":
                    report_docx = os.path.join(outdir, "AureaSim_Report.docx")
                    generate_docx_report(
                        report_settings, results_df, charts_img, report_docx,
                        ai_summary_text, dfs_dict,
                        base_config=prosimos_base, scenarios_config=scenarios
                    )
                elif fmt == "pdf":
                    from aureasim.reporter import generate_pdf_report
                    report_pdf = os.path.join(outdir, "AureaSim_Report.pdf")
                    generate_pdf_report(
                        report_settings, results_df, charts_img, report_pdf,
                        ai_summary_text, dfs_dict,
                        base_config=prosimos_base, scenarios_config=scenarios
                    )
                elif fmt == "latex":
                    from aureasim.reporter import generate_latex_report
                    import subprocess
                    report_latex = os.path.join(outdir, "AureaSim_Report_LaTeX.tex")
                    generate_latex_report(
                        report_settings, results_df, charts_img, report_latex,
                        ai_summary_text, dfs_dict,
                        base_config=prosimos_base, scenarios_config=scenarios
                    )
                    console.print("  [cyan]Compiling LaTeX to PDF...[/cyan]")
                    try:
                        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory", outdir, report_latex], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        # Cleanup aux, log, out
                        for ext in [".aux", ".log", ".out"]:
                            temp_file = os.path.join(outdir, f"AureaSim_Report_LaTeX{ext}")
                            if os.path.exists(temp_file):
                                os.remove(temp_file)
                        console.print(f"  [green]✔  LaTeX PDF generated:[/green] AureaSim_Report_LaTeX.pdf")
                    except FileNotFoundError:
                        console.print("  [yellow]pdflatex not found. LaTeX source saved but PDF not compiled.[/yellow]")
                    except subprocess.CalledProcessError:
                        console.print("  [red]❌ pdflatex compilation failed. See output directory for logs.[/red]")
            tracker.stop('Report Generation')
    
    console.print()
    console.print(Panel(
        f"[bold green]✔  Pipeline completed successfully![/bold green]\nAll generated artifacts and reports have been saved to:\n[bold]{outdir}[/bold]",
        border_style="green",
        expand=False,
        padding=(1, 3)
    ))
    console.print()
    tracker.print_summary()

def print_ai_error(e):
    error_str = str(e)
    if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
        console.print("\n[bold red]Error: Gemini API Quota Exceeded (429 RESOURCE_EXHAUSTED)[/bold red]")
        console.print("[red]Your API key is associated with a Free-Tier Google Cloud project and has hit a strict rate limit.[/red]")
        console.print("[red]Even if you subscribe to Gemini Advanced (Ultra) on the web, Developer API keys use a completely separate billing system.[/red]")
        console.print("[yellow]To remove the 15 request/minute limit, you must attach a credit card in Google AI Studio to unlock the 'Pay-as-you-go' API tier.[/yellow]\n")
    else:
        console.print(f"\n[red]Fatal AI Generation Error: {e}[/red]\n")

def interactive_file_browser(extension, prompt_msg, start_dir=".", restrict_to_dir=None):
    """Provides a visual terminal navigator for browsing directories."""
    if restrict_to_dir:
        current_dir = os.path.abspath(restrict_to_dir)
    else:
        current_dir = os.path.abspath(start_dir)
    base_dir = os.getcwd()
    
    while True:
        try:
            items = os.listdir(current_dir)
        except Exception:
            current_dir = os.path.dirname(current_dir)
            continue
            
        def has_ext(folder, ext):
            for root, dirs, files_in_dir in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for f in files_in_dir:
                    if f.endswith(ext) and not f.startswith("SANITIZED") and not f.startswith("temp_"):
                        return True
            return False

        folders = [d for d in items if os.path.isdir(os.path.join(current_dir, d)) and not d.startswith('.')]
        folders = [d for d in folders if has_ext(os.path.join(current_dir, d), extension)]
        
        # Omit garbage files from the list visually
        files = [f for f in items if os.path.isfile(os.path.join(current_dir, f)) and f.endswith(extension) 
                 and not f.startswith("SANITIZED") and not f.startswith("temp_")]
        
        folders.sort()
        files.sort()
        
        choices = []
        if not restrict_to_dir or current_dir != os.path.abspath(restrict_to_dir):
            choices.append("⬅️  [Go Up Directory]")
        choices.extend([f"📁 {d}/" for d in folders])
        choices.extend([f"📄 {f}" for f in files])
        
        display_dir = os.path.relpath(current_dir, base_dir)
        if display_dir == ".": 
            display_dir = "./"
        else:
            display_dir = f"./{display_dir}"
            
        selection = questionary.select(
            f"📂 {prompt_msg}\n   Current Location: {display_dir}",
            choices=choices
        ).ask()
        
        if not selection:
            return None
            
        if "Go Up" in selection:
            current_dir = os.path.dirname(current_dir)
            print("\033[F\033[K\033[F\033[K", end="", flush=True)
        elif selection.startswith("📁 "):
            folder_name = selection.replace("📁 ", "").rstrip("/")
            current_dir = os.path.join(current_dir, folder_name)
            print("\033[F\033[K\033[F\033[K", end="", flush=True)
        elif selection.startswith("📄 "):
            file_name = selection.replace("📄 ", "")
            # Clear it one final time so we just see the single final chosen file
            print("\033[F\033[K\033[F\033[K", end="", flush=True)
            console.print(f"[bold cyan]? 📂 {prompt_msg}[/bold cyan]\n  [green]✔  Selected:[/green] {os.path.join(display_dir, file_name)}", highlight=False)
            return os.path.join(current_dir, file_name)

def interactive_base_param_editor(json_path, bpmn_path=None):
    """Provides a fully interactive loop to modify base Prosimos parameters without an external editor."""
    import xml.etree.ElementTree as ET
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    task_mapping = {}
    if bpmn_path and os.path.exists(bpmn_path):
        try:
            tree = ET.parse(bpmn_path)
            root = tree.getroot()
            namespaces = {'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL'}
            for tag in ['task', 'userTask', 'serviceTask', 'receiveTask', 'sendTask', 'manualTask']:
                for elem in root.findall(f'.//bpmn:{tag}', namespaces):
                    t_id = elem.get('id')
                    t_name = elem.get('name', 'Unnamed Task')
                    task_mapping[t_id] = t_name.replace('\n', ' ').strip()
        except:
            pass

    while True:
        console.print()
        main_choice = questionary.select(
            "⚙️  Review and Edit Base Parameters:",
            choices=[
                "💾 Save and Continue",
                "👤 Review Resource Profiles (Costs & Headcount)",
                "⏱️  Review Task Durations (Processing Time)"
            ]
        ).ask()
        print("\033[F\033[K\033[F\033[K", end="", flush=True)
        
        if not main_choice or "Save" in main_choice:
            break
            
        elif "Resource Profiles" in main_choice:
            while True:
                res_choices = []
                for rp in data.get("resource_profiles", []):
                    if not rp.get("resource_list"): continue
                    res = rp["resource_list"][0] # Prosimos grouped profile
                    res_choices.append(
                        questionary.Choice(
                            title=f"{rp.get('name', rp.get('id'))} (Cost: {res.get('cost_per_hour', 0)}/hr, Default Count: {res.get('amount', 1)})",
                            value=rp
                        )
                    )
                res_choices.append(questionary.Choice(title="⬅️  Back to Main Menu", value="back"))
                
                console.print()
                rp_choice = questionary.select("Select a Resource Profile to edit:", choices=res_choices).ask()
                print("\033[F\033[K\033[F\033[K", end="", flush=True)
                
                if not rp_choice or rp_choice == "back":
                    break
                    
                res = rp_choice["resource_list"][0]
                
                new_cost = questionary.text(
                    f"Enter new cost/hour for '{rp_choice.get('name')}':", 
                    default=str(res.get('cost_per_hour', 0))
                ).ask()
                if new_cost and new_cost.replace('.','',1).isdigit():
                    res['cost_per_hour'] = float(new_cost)
                    
                new_count = questionary.text(
                    f"Enter new default worker count for '{rp_choice.get('name')}':", 
                    default=str(res.get('amount', 1))
                ).ask()
                if new_count and new_count.isdigit():
                    res['amount'] = int(new_count)
                    
        elif "Task Durations" in main_choice:
            while True:
                task_choices = []
                for t_entry in data.get("task_resource_distribution", []):
                    t_id = t_entry.get("task_id")
                    dists = t_entry.get("resources", [])
                    if not dists: continue
                    d_params = dists[0].get("distribution_params", [])
                    if d_params and len(d_params) > 0:
                        mean_sec = d_params[0].get("value", 0)
                        
                        t_label = task_mapping.get(t_id, t_id)
                        # Truncate long task names to keep layout clean
                        if len(t_label) > 40: t_label = t_label[:37] + "..."
                        
                        task_choices.append(
                            questionary.Choice(
                                title=f"{t_label} (Mean: {mean_sec}s)",
                                value=t_entry
                            )
                        )
                task_choices.append(questionary.Choice(title="⬅️  Back to Main Menu", value="back"))
                
                console.print()
                t_choice = questionary.select("Select a Task to edit duration:", choices=task_choices).ask()
                print("\033[F\033[K\033[F\033[K", end="", flush=True)
                
                if not t_choice or t_choice == "back":
                    break
                    
                t_id = t_choice.get("task_id")
                t_label = task_mapping.get(t_id, t_id)
                dists = t_choice.get("resources", [])
                
                if dists:
                    for dist in dists:
                        d_params = dist.get("distribution_params", [])
                        if d_params and len(d_params) > 0:
                            current_mean = str(d_params[0].get("value", 0))
                            new_mean = questionary.text(
                                f"Enter new mean duration (seconds) for '{t_label}':", 
                                default=current_mean
                            ).ask()
                            
                            if new_mean and new_mean.replace('.','',1).isdigit():
                                d_params[0]["value"] = float(new_mean)
                            break
                            
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    console.print(f"  [green]✔  Base Parameters saved and locked in![/green]")

def interactive_wizard():
    print_banner()
    
    # Ask for API Key at the very beginning
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    offline_demo_mode = False
    should_resolve_refs = False
    
    if not api_key:
        api_key = questionary.password(
            "Enter Gemini API Key (or leave blank to run in offline demo mode using examples/):"
        ).ask()
        if not api_key or not api_key.strip():
            offline_demo_mode = True
            api_key = ""
        else:
            set_key(".env", "GEMINI_API_KEY", api_key)
            load_dotenv()
            
    # 1. BPMN select via Visual Browser
    if offline_demo_mode:
        original_bpmn_path = interactive_file_browser(
            ".bpmn", 
            "Select an example BPMN model (Offline Demo Mode):", 
            start_dir="examples",
            restrict_to_dir="examples"
        )
    else:
        original_bpmn_path = interactive_file_browser(
            ".bpmn", 
            "Navigate to your target BPMN model:"
        )
        
    if not original_bpmn_path: return
    
    # ---------------------------------------------------------
    # Create Isolated Workspace Folder based on BPMN name
    # ---------------------------------------------------------
    console.print()
    import shutil
    bpmn_filename = os.path.basename(original_bpmn_path)
    process_name = Path(original_bpmn_path).stem
    
    # Create the dedicated folder
    working_dir = os.path.join(".", "projects", process_name)
    
    if os.path.exists(working_dir):
        choice = questionary.select(
            f"Folder '{process_name}' exists. Choose action:",
            choices=[
                "Create with suffix (-1, -2...)",
                "Overwrite (Destructive)" 
            ]
        ).ask()
        
        if not choice: return
        
        if "Overwrite" in choice:
            confirm = questionary.confirm(f"Are you sure you want to permanently delete everything inside '{working_dir}'?").ask()
            if not confirm: return
            shutil.rmtree(working_dir)
        else:
            counter = 1
            while os.path.exists(f"{working_dir}-{counter}"):
                counter += 1
            working_dir = f"{working_dir}-{counter}"

    os.makedirs(working_dir, exist_ok=True)
    
    # Copy BPMN into it and set it as the new operational target
    bpmn_path = os.path.join(working_dir, bpmn_filename)
    shutil.copy2(original_bpmn_path, bpmn_path)
    
    console.print(f"  [green]✔  Created dedicated operating folder:[/green] [bold]{working_dir}[/bold]\n", highlight=False)
    
    # Generate Project Branding (Icon, Color, Display Name)
    try:
        load_dotenv()
        branding_obj = generate_project_branding(process_name)
        config_path = os.path.join(working_dir, "project_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(branding_obj.model_dump(), f, indent=4)
    except Exception:
        pass
    
    # 2. Base Prosimos JSON select
    base_json_method = questionary.select(
        "How to provide Base Prosimos Parameters?",
        choices=[
            "🪄  Auto-Generate via Gemini AI",
            "📁  Select existing JSON config"
        ]
    ).ask()
    if not base_json_method: return

    base_json_path = None
    
    if "Auto-Generate" in base_json_method:
        try:
            console.print()
            console.print("[yellow]Connecting to Google Gemini... Analyzing BPMN logic...[/yellow]\n")

            industry_context = questionary.text(
                "What industry and country is this process for? (improves web-search accuracy)",
                default="General business process, Poland"
            ).ask() or "General business process"
            console.print()

            grounding_choice = questionary.select(
                "How should AureaSim estimate base parameters?",
                choices=[
                    questionary.Choice(
                        "Heuristic (Fast): Estimate from BPMN only",
                        value="heuristic",
                    ),
                    questionary.Choice(
                        "Web-grounded (Slow): Search for external benchmarks",
                        value="grounded",
                    ),
                ],
                default="heuristic",
            ).ask() or "grounded"

            if offline_demo_mode:
                fallback_base = os.path.join("examples", f"{process_name}_base.json")
                if not os.path.exists(fallback_base):
                    fallback_base = os.path.join(os.path.dirname(original_bpmn_path), f"{process_name}_base.json")
                if not os.path.exists(fallback_base):
                    fallback_base = os.path.join("examples", "RES_Sales_Process_base.json")

                if os.path.exists(fallback_base):
                    tracker.start('AI Base Parameter Generation')
                    with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn(pulse_style="cyan"), TimeElapsedColumn(), transient=True) as ai_prog:
                        tid = ai_prog.add_task("AI defining parameters...", total=None)
                        time.sleep(1.0)
                        ai_prog.update(tid, description="Analyzing BPMN process structure...")
                        time.sleep(1.0)
                        ai_prog.update(tid, description="Synthesizing activity durations and resource profiles...")
                        time.sleep(1.0)
                        
                        base_json_path = os.path.join(working_dir, "AutoGenerated_Base_params.json")
                        shutil.copy2(fallback_base, base_json_path)
                        
                        # Copy example project config if available, otherwise write standard project config
                        src_config = os.path.join("examples", f"{process_name}_config.json")
                        if not os.path.exists(src_config):
                            src_config = os.path.join(os.path.dirname(original_bpmn_path), f"{process_name}_config.json")
                        if not os.path.exists(src_config):
                            src_config = os.path.join("examples", "RES_Sales_Process_config.json")
                        
                        if os.path.exists(src_config):
                            shutil.copy2(src_config, os.path.join(working_dir, "project_config.json"))
                    tracker.stop('AI Base Parameter Generation')
                    console.print(f"  [bold green]✔  Base Parameters Auto-Generated:[/bold green] {os.path.basename(base_json_path)}\n")
                else:
                    console.print("\n[red]Error: Offline fallback parameters could not be found.[/red]")
                    return
            else:
                tracker.start('AI Base Parameter Generation')
                with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn(pulse_style="cyan"), TimeElapsedColumn(), transient=True) as ai_prog:
                    tid = ai_prog.add_task("AI defining parameters...", total=None)
                    base_json_path = generate_base_prosimos_json(
                        bpmn_path,
                        api_key,
                        industry_context,
                        progress_callback=lambda m: ai_prog.update(tid, description=m),
                        generation_mode=grounding_choice,
                    )
                tracker.stop('AI Base Parameter Generation')
                console.print(f"  [bold green]✔  Base Parameters Auto-Generated:[/bold green] {os.path.basename(base_json_path)}\n")
                if grounding_choice == "grounded":
                    should_resolve_refs = True
                
            if base_json_path:
                mult_str = questionary.text(
                    "Optional: Enter inflation multiplier to adjust historical AI salaries to current rates\n(e.g., 1.46), or leave blank:",
                    default=""
                ).ask()
                
                if mult_str and mult_str.strip():
                    try:
                        mult = float(mult_str)
                        with open(base_json_path, 'r') as f:
                            b_data = json.load(f)
                        
                        for res in b_data.get('resource_profiles', []):
                            for rl in res.get('resource_list', []):
                                if 'cost_per_hour' in rl:
                                    rl['cost_per_hour'] = round(float(rl['cost_per_hour']) * mult, 2)
                                    
                        with open(base_json_path, 'w') as f:
                            json.dump(b_data, f, indent=4)
                        console.print(f"  [bold cyan]ℹ  Applied {mult}x multiplier to all hourly resource costs.[/bold cyan]")
                    except ValueError:
                        console.print("  [bold red]✖  Invalid multiplier. Skipping adjustment.[/bold red]")
                        
        except Exception as e:
            print_ai_error(e)
            return
    else:
        base_json_path = interactive_file_browser(".json", "Navigate to your existing Base Prosimos JSON config:")
        if not base_json_path: return
        
    interactive_base_param_editor(base_json_path, bpmn_path)
                
    # 3. Experiment Settings
    console.print()
    exp_config = {}
    
    config_choice = questionary.select(
        "How to configure experiment scenarios?",
        choices=[
            "🪄  Auto-Generate realistic scenarios via Gemini AI",
            "🛠️  Configure manually (Interactive)",
            "📁  Load existing pattern (experiment.json)"
        ]
    ).ask()
    if not config_choice: return
    
    if "Auto-Generate" in config_choice:
        console.print()
        num_scenarios = questionary.text("How many dynamic scenarios to generate?", default="3").ask()
        if not num_scenarios or not num_scenarios.isdigit(): return
        
        console.print()
        console.print("[yellow]Connecting to Google Gemini... Innovating business scenarios...[/yellow]\n")
        
        if offline_demo_mode:
            try:
                tracker.start('AI Experiment Generation')
                with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn(pulse_style="cyan"), TimeElapsedColumn(), transient=True) as ai_prog:
                    tid = ai_prog.add_task("AI Phase 1/2: Designing scenarios...", total=None)
                    time.sleep(1.2)
                    ai_prog.update(tid, description="AI Phase 2/2: Mapping resources...")
                    time.sleep(1.2)
                    
                    fallback_config = os.path.join("examples", f"{process_name}_config.json")
                    if not os.path.exists(fallback_config):
                        fallback_config = os.path.join(os.path.dirname(original_bpmn_path), f"{process_name}_config.json")
                    if not os.path.exists(fallback_config):
                        fallback_config = os.path.join("examples", "RES_Sales_Process_config.json")

                    exp_path = os.path.join(working_dir, "AutoGenerated_Experiment_Scenarios.json")
                    shutil.copy2(fallback_config, exp_path)
                tracker.stop('AI Experiment Generation')
                console.print(f"  [bold green]✔  Scenarios Auto-Generated:[/bold green] {os.path.basename(exp_path)}\n")
            except Exception as e:
                print_ai_error(e)
                return
        else:
            try:
                tracker.start('AI Experiment Generation')
                with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn(pulse_style="cyan"), TimeElapsedColumn(), transient=True) as ai_prog:
                    tid = ai_prog.add_task("AI Phase 1/2: Designing scenarios...", total=None)
                    exp_path = generate_experiment_json(
                        bpmn_path, base_json_path, api_key, int(num_scenarios), industry_context,
                        progress_callback=lambda m: ai_prog.update(tid, description=m),
                        generation_mode=grounding_choice
                    )
                tracker.stop('AI Experiment Generation')
                console.print(f"  [bold green]✔  Scenarios Auto-Generated:[/bold green] {os.path.basename(exp_path)}\n")
            except Exception as e:
                print_ai_error(e)
                return
                
        with open(exp_path, 'r', encoding='utf-8') as f:
            exp_data = json.load(f)
            
        exp_config = exp_data
        all_scenarios = exp_data.get("scenarios", [])
        scenarios = all_scenarios
        report_settings = exp_data.get("report_settings", {})
        
        if all_scenarios:
            from questionary import Choice
            choices = [
                Choice(title=f"{s['name']} (Arrival: {s.get('arrival_rate', 'N/A')}s)", value=s, checked=True) 
                for s in all_scenarios
            ]
            console.print()
            scenarios = questionary.checkbox(
                "Review AI-Generated Scenarios. Uncheck any you do not want to execute:",
                choices=choices,
                instruction="\n   (Use arrow keys to move, <space> to select, <a> to toggle, <i> to invert)"
            ).ask()
            
            if not scenarios: return
        else:
            scenarios = []
    elif "Load" in config_choice:
        exp_files = [f for f in find_files(".json") if "experiment" in f.lower() or "scenarios" in f.lower()]
        if exp_files:
            exp_path = questionary.select("Select your experiment JSON:", choices=exp_files).ask()
            if not exp_path: return
            with open(exp_path, 'r', encoding='utf-8') as f:
                exp_data = json.load(f)
            exp_config = exp_data
            scenarios = exp_data.get("scenarios", [])
            report_settings = exp_data.get("report_settings", {})
        else:
            console.print("[yellow]No experiment configs found! Falling back to manual setup.[/yellow]")
            scenarios = configure_manual_scenarios()
            report_settings = {"title": "Wizard Diagnostic Output", "description": "Interactively generated report."}
    else:
        scenarios = configure_manual_scenarios()
        report_settings = {"title": "Wizard Diagnostic Output", "description": "Interactively generated report."}
        
        if scenarios:
            manual_out_path = os.path.join(working_dir, "Manual_Experiment_Scenarios.json")
            with open(manual_out_path, 'w', encoding='utf-8') as f:
                json.dump({"report_settings": report_settings, "scenarios": scenarios}, f, indent=4)
            console.print(f"  [green]✔  Manual Scenarios configured and saved to:[/green] {os.path.basename(manual_out_path)}")
        
    if not scenarios:
        console.print("[red]No scenarios configured. Exiting.[/red]")
        return
        
    outdir = os.path.join(working_dir, "results")
    
    # Confirm
    console.print(f"\n[bold]Ready to simulate {len(scenarios)} scenarios into ->[/bold] [cyan]{outdir}[/cyan]", highlight=False)
    if not questionary.confirm("Start execution?").ask():
        console.print("[yellow]Aborted.[/yellow]")
        return
        
    run_pipeline(bpmn_path, base_json_path, scenarios, report_settings, outdir, exp_config, should_resolve_refs=should_resolve_refs, offline_demo_mode=offline_demo_mode)

if __name__ == "__main__":
    interactive_wizard()
