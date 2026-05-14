import csv, json

CSV_FILE = "tamilnadu_tourism_master.csv"
JSON_FILE = "tamilnadu_tourism_master.json"

items = []
with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    for r in reader:
        # convert numeric fields
        for k in ["latitude", "longitude"]:
            if r.get(k):
                try:
                    r[k] = float(r[k])
                except:
                    r[k] = None
            else:
                r[k] = None
        items.append(r)

with open(JSON_FILE, "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

print("✅ Created", JSON_FILE, "with", len(items), "places")