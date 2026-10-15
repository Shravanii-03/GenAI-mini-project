"""
diagram_generator.py — Professional PlantUML Diagram Generator
Generates research-paper quality activity diagrams like TUM paper Fig.3
"""

import json
import os
import subprocess
from pathlib import Path


class DiagramGenerator:
    """Generates PlantUML activity diagrams for SDV safety scenarios"""
    
    def __init__(self, output_dir="outputs/diagrams"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # Check if PlantUML is available
        self.plantuml_jar = self._find_plantuml()
    
    def _find_plantuml(self):
        """Find PlantUML JAR file"""
        possible_paths = [
            "plantuml.jar",
            "plantuml-1.2026.2.jar",
            "/usr/local/bin/plantuml.jar",
            str(Path.home() / "plantuml.jar")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                print(f" Found PlantUML: {path}")
                return path
        
        print("  PlantUML not found - will use matplotlib fallback")
        return None
    
    def generate_plantuml_code(self, data):
        """
        Generate PlantUML code for activity diagram
        Matches the style of TUM paper Figure 3
        """
        
        frame = data.get("frame", {})
        evaluation = data.get("evaluation", {})
        threat = data.get("threat", {})
        
        scenario_type = evaluation.get("scenario_type", "unknown").upper()
        delay = evaluation.get("actual_delay_ms", 0)
        max_delay = evaluation.get("expected_delay_ms", 100)
        violation = evaluation.get("violation", False)
        risk = evaluation.get("risk_score", 0)
        road = evaluation.get("road_condition", "dry")
        attack = frame.get("attack", {}).get("type", "none")
        
        # Color coding
        brake_color = "#FFCCCC" if violation else "#CCFFCC"
        
        plantuml = f"""@startuml
title Scenario: {scenario_type}
note right
  Delay: {delay}ms / {max_delay}ms
  Risk: {risk:.2f}
  Road: {road}
  Attack: {attack}
end note

start

:Capture Camera Data;
:Detect Pedestrian (Camera);

if (Camera detects pedestrian?) then (yes)
  :CamPed = true;
else (no)
  :CamPed = false;
endif

:Capture LiDAR Data;
:Detect Pedestrian (LiDAR);

if (LiDAR detects pedestrian?) then (yes)
  :LidarPed = true;
else (no)
  :LidarPed = false;
endif

:Listen CamPed;
:Listen LidarPed;

if (CamPed == true OR LidarPed == true) then (yes)
  :{brake_color}**Brake**;
  note right
    {' VIOLATION' if violation else ' OK'}
    Delay: {delay}ms
    {'Exceeds limit!' if violation else 'Within limit'}
  end note
else (no)
  :Accelerate;
endif

stop

@enduml
"""
        return plantuml
    
    def save_plantuml(self, code, filename):
        """Save PlantUML code to .puml file"""
        filepath = os.path.join(self.output_dir, filename + ".puml")
        with open(filepath, "w", encoding="utf-8") as f:
             f.write(code)
        print(f" Saved PlantUML: {filepath}")
        return filepath
    
    def render_plantuml_to_png(self, puml_file):
        """Render .puml file to PNG using PlantUML JAR"""
        
        if not self.plantuml_jar:
            print("  Cannot render - PlantUML JAR not found")
            return None
        
        try:
            # Run: java -jar plantuml.jar diagram.puml
            result = subprocess.run(
                ["java", "-jar", self.plantuml_jar, puml_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                png_file = puml_file.replace(".puml", ".png")
                print(f" Rendered PNG: {png_file}")
                return png_file
            else:
                print(f"❌ PlantUML error: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"❌ Failed to render PlantUML: {e}")
            return None
    
    def generate_all_scenarios(self, violation_files):
        """Generate diagrams for all violation files"""
        
        diagrams = []
        
        for i, filepath in enumerate(violation_files[:6]):  # Max 6 diagrams
            try:
                with open(filepath) as f:
                    data = json.load(f)
                
                # Generate PlantUML code
                code = self.generate_plantuml_code(data)
                
                # Save .puml file
                scenario_type = data.get("evaluation", {}).get("scenario_type", f"scenario_{i}")
                puml_file = self.save_plantuml(code, f"diagram_{scenario_type}_{i}")
                
                # Render to PNG
                png_file = self.render_plantuml_to_png(puml_file)
                
                if png_file:
                    diagrams.append({
                        "scenario": scenario_type,
                        "puml": puml_file,
                        "png": png_file,
                        "data": data
                    })
            
            except Exception as e:
                print(f"❌ Failed to process {filepath}: {e}")
        
        return diagrams


# Test
if __name__ == "__main__":
    import glob
    
    gen = DiagramGenerator()
    
    # Find all violation files
    files = sorted(glob.glob("outputs/live_violation_*.json"), reverse=True)
    
    if files:
        print(f"\n📊 Generating diagrams for {len(files[:6])} scenarios...\n")
        diagrams = gen.generate_all_scenarios(files[:6])
        print(f"\n✅ Generated {len(diagrams)} diagrams")
    else:
        print("❌ No violation files found in outputs/")