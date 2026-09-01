import pandas as pd

def analyze_scenario_log(scenario_name, log_path, hourly_rates, kpi_config=None, base_config=None):
    """
    Parses a single Prosimos event log and calculates KPI metrics using pandas.
    Applies the scenario's specific hourly rates to calculate Activity-Based Costing.
    """
    print(f"[Analyzer] Processing data for: {scenario_name}...")
    
    try:
        df = pd.read_csv(log_path)
    except FileNotFoundError:
        print(f"  [!] Log file not found: {log_path}")
        return None, None
        
    df['enable_time'] = pd.to_datetime(df['enable_time'])
    df['start_time'] = pd.to_datetime(df['start_time'])
    df['end_time'] = pd.to_datetime(df['end_time'])
    
    df['wait_time_hr'] = (df['start_time'] - df['enable_time']).dt.total_seconds() / 3600
    df['work_time_hr'] = (df['end_time'] - df['start_time']).dt.total_seconds() / 3600
    
    # Assign costs
    def assign_dynamic_rate(res_name):
        if res_name in hourly_rates:
            return hourly_rates[res_name]
        for key, rate in hourly_rates.items():
            if isinstance(res_name, str) and key in res_name:
                return rate
        return 0
        
    df['Hourly_Rate'] = df['resource'].apply(assign_dynamic_rate)
    df['Task_Cost_PLN'] = df['work_time_hr'] * df['Hourly_Rate']
    
    # Calculate cycle times per case
    cases = df.groupby('case_id').agg(start=('enable_time', 'min'), end=('end_time', 'max'))
    cases['cycle_days'] = (cases['end'] - cases['start']).dt.total_seconds() / 86400
    
    total_cases = len(cases)
    avg_cost_per_case = df['Task_Cost_PLN'].sum() / total_cases if total_cases > 0 else 0
    
    kpi = {
        "Scenario": scenario_name,
        "Total_Cases": total_cases,
        "Avg_Cycle_Time_Days": round(cases['cycle_days'].mean(), 2),
        "Avg_Cost_Per_Case_PLN": round(avg_cost_per_case, 2)
    }
    
    if kpi_config and "wait_times" in kpi_config:
        profile_names = {}
        if base_config and 'resource_profiles' in base_config:
            for profile in base_config['resource_profiles']:
                p_id = profile.get('id')
                names = set()
                for r in profile.get('resource_list', []):
                    if r.get('name'):
                        names.add(r.get('name'))
                    if r.get('id'):
                        names.add(r.get('id'))
                        names.add(r.get('id').replace('_', ' '))
                        
                if p_id and names:
                    profile_names[p_id] = list(names)
                    
        for resource_filter in kpi_config["wait_times"]:
            if resource_filter in profile_names:
                mapped_names = profile_names[resource_filter]
                mask = df['resource'].isin(mapped_names) | df['resource'].str.contains(str(resource_filter), na=False) | df['resource'].str.contains(str(resource_filter).replace('_', ' '), na=False)
            else:
                mask = df['resource'].str.contains(str(resource_filter), na=False) | df['resource'].str.contains(str(resource_filter).replace('_', ' '), na=False)
                
            val = df[mask]['wait_time_hr'].mean() if mask.any() else 0
            kpi[f"Wait_Time_Hrs_{resource_filter}"] = round(val, 2)
            
    return kpi, df

def generate_detailed_excel(df, output_path):
    """Aggregates detailed resource stats into an Excel file."""
    resource_stats = df[df['Hourly_Rate'] > 0].groupby('resource').agg(
        Task_Count=('case_id', 'count'), 
        Total_Work_Hrs=('work_time_hr', 'sum'),
        Total_Cost=('Task_Cost_PLN', 'sum')
    ).round(2).reset_index()
    
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        resource_stats.to_excel(writer, sheet_name='Resource_Stats', index=False)
