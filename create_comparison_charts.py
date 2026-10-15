"""
create_comparison_charts.py — Multi-Scenario Comparison Charts
FIXED VERSION (dynamic + correct threshold + latest data only)
"""

import json
import glob
import matplotlib.pyplot as plt
import numpy as np
import os


#  FIXED: Load ONLY latest files (not all history)
def load_all_violations():
    """Load latest violation JSON files (dynamic)"""
    
    files = sorted(
        glob.glob("outputs/live_violation_*.json"),
        key=os.path.getmtime
    )[-8:]  # last 8 scenarios only
    
    data = []
    
    for f in files:
        try:
            with open(f) as file:
                data.append(json.load(file))
        except:
            pass
    
    return data


def create_delay_comparison_chart(data_list):
    """
    Bar chart: Actual delay vs threshold
    FIXED: dynamic + correct threshold + better visuals
    """
    
    fig, ax = plt.subplots(figsize=(14, 6))
    
    scenarios = []
    actual_delays = []
    violations = []
    risks = []
    
    for i, data in enumerate(data_list):
        eval_data = data.get("evaluation", {})
        
        scenario_type = eval_data.get("scenario_type", "unknown").upper()
        road = eval_data.get("road_condition", "")
        actual = eval_data.get("actual_delay_ms", 0)
        violation = eval_data.get("violation", False)
        risk = eval_data.get("risk_score", 0)
        
        scenarios.append(f"{scenario_type} #{i+1}\nroad={road}")
        actual_delays.append(actual)
        violations.append(violation)
        risks.append(risk)
    
    x = np.arange(len(scenarios))
    
    #  Color logic (green = safe, red = fail)
    colors = ['#2ecc71' if not v else '#e74c3c' for v in violations]
    
    bars = ax.bar(x, actual_delays, width=0.6,
                  color=colors,
                  edgecolor='black',
                  linewidth=1.5)
    
    #  Labels inside bars
    for bar, actual, violation, risk in zip(bars, actual_delays, violations, risks):
        height = bar.get_height()
        status = "SAFE" if not violation else "FAIL"
        
        ax.text(
            bar.get_x() + bar.get_width()/2,
            height/2,
            f'{int(actual)}ms\nrisk={risk:.1f}\n{status}',
            ha='center',
            va='center',
            fontsize=9,
            fontweight='bold',
            color='white'
        )
    
    #  FIXED: consistent threshold
    iso_limit = 100
    
    ax.axhline(
        y=iso_limit,
        color='orange',
        linestyle='--',
        linewidth=2,
        label=f'ISO Limit: {iso_limit}ms'
    )
    
    #  Improved labels
    ax.set_xlabel('Scenario', fontsize=12, fontweight='bold')
    ax.set_ylabel('Actual Delay (ms)', fontsize=12, fontweight='bold')
    
    # Better title (research-level)
    ax.set_title(
        'Temporal Safety Validation Across SDV Scenarios\n'
        'Brake must occur within 100ms after detection',
        fontsize=14,
        fontweight='bold'
    )
    
    ax.set_xticks(x)
    ax.set_xticklabels(scenarios, fontsize=9)
    
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('outputs/diagrams/scenario_summary_chart.png', dpi=200)
    plt.close()
    
    print("Saved: outputs/diagrams/scenario_summary_chart.png")


def create_risk_distribution(data_list):
    """Pie chart: Risk severity distribution"""
    
    fig, ax = plt.subplots(figsize=(8, 8))
    
    severities = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    
    for data in data_list:
        sev = data.get("evaluation", {}).get("severity", "MEDIUM")
        severities[sev] = severities.get(sev, 0) + 1
    
    labels = [f"{k}\n({v})" for k, v in severities.items() if v > 0]
    sizes = [v for v in severities.values() if v > 0]
    
    colors = ['#2ecc71', '#f39c12', '#e67e22', '#e74c3c'][:len(sizes)]
    
    ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        autopct='%1.1f%%',
        shadow=True,
        startangle=90,
        textprops={'fontsize': 12, 'fontweight': 'bold'}
    )
    
    ax.set_title('Risk Severity Distribution', fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig('outputs/diagrams/risk_distribution.png', dpi=200)
    plt.close()
    
    print("Saved: outputs/diagrams/risk_distribution.png")


def create_attack_summary(data_list):
    """Bar chart: Attack types detected"""
    
    attack_counts = {}
    
    for data in data_list:
        attack_type = data.get("frame", {}).get("attack", {}).get("type", "none")
        if attack_type != "none":
            attack_counts[attack_type] = attack_counts.get(attack_type, 0) + 1
    
    if not attack_counts:
        print("No attacks to chart")
        return
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    attacks = list(attack_counts.keys())
    counts = list(attack_counts.values())
    
    bars = ax.barh(attacks, counts,
                   color='#e74c3c',
                   edgecolor='black',
                   linewidth=1.5)
    
    for bar, count in zip(bars, counts):
        ax.text(count + 0.2,
                bar.get_y() + bar.get_height()/2,
                str(count),
                va='center',
                fontsize=12,
                fontweight='bold')
    
    ax.set_xlabel('Count', fontsize=12, fontweight='bold')
    ax.set_title('Cyber Attack Types Detected', fontsize=14, fontweight='bold')
    
    ax.grid(axis='x', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('outputs/diagrams/attack_summary.png', dpi=200)
    plt.close()
    
    print("Saved: outputs/diagrams/attack_summary.png")


#  RUN ALL
if __name__ == "__main__":
    print("Generating comparison charts...\n")
    
    data = load_all_violations()
    
    if not data:
        print("No violation data found")
    else:
        print(f"Loaded {len(data)} scenarios\n")
        
        create_delay_comparison_chart(data)
        create_risk_distribution(data)
        create_attack_summary(data)
        
        print("\nAll charts generated in outputs/diagrams/")