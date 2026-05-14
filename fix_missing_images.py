import json
import time
import requests

FILE = "tamilnadu_tourism_master_final.json"
WIKI_API = "https://en.wikipedia.org/w/api.php"

session = requests.Session()
session.headers.update({"User-Agent":"tour-ai-project"})

def get_image(place):
    params = {
        "action":"query",
        "prop":"pageimages",
        "format":"json",
        "titles":place,
        "pithumbsize":1000
    }

    r = session.get(WIKI_API, params=params)
    data = r.json()

    pages = data["query"]["pages"]

    for p in pages:
        page = pages[p]
        if "thumbnail" in page:
            return page["thumbnail"]["source"]

    return ""

with open(FILE,"r",encoding="utf8") as f:
    data = json.load(f)

for item in data:
    if item.get("image_url","") == "":
        print("Fetching image for:", item["place_name"])
        img = get_image(item["place_name"])
        item["image_url"] = img
        time.sleep(1.5)

with open(FILE,"w",encoding="utf8") as f:
    json.dump(data,f,indent=2)

print("Done fixing images")