"""
generate_all_visuals.py — Master Visual Generation Script
Runs everything: PlantUML diagrams + comparison charts
"""

import subprocess
import sys

print("="*60)
print("  SDV Safety Visual Generator")
print("  Generating diagrams + charts")
print("="*60)

# Step 1: Generate PlantUML diagrams
print("\n Step 1: Generating activity diagrams...\n")
try:
    subprocess.run([sys.executable, "diagram_generator.py"], check=True)
except Exception as e:
    print(f"  Diagram generation had issues: {e}")

# Step 2: Generate comparison charts
print("\n Step 2: Generating comparison charts...\n")
try:
    subprocess.run([sys.executable, "create_comparison_charts.py"], check=True)
except Exception as e:
    print(f"  Chart generation had issues: {e}")

print("\n" + "="*60)
print(" DONE! Check outputs/diagrams/ for all visuals")
print("="*60)