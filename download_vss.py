import requests

url = "https://raw.githubusercontent.com/COVESA/vehicle_signal_specification/main/spec/VehicleSignalSpecification.json"
r = requests.get(url)
with open("knowledge_base/vss_full.json", "w") as f:
    f.write(r.text)
print("Downloaded real VSS catalog!")