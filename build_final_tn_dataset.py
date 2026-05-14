import json
import time
import requests
from pathlib import Path

BASE_FILE = "tamilnadu_tourism_master.json"
EXTRA_FILE = "extra_tamilnadu_places.json"
OUTPUT_FILE = "tamilnadu_tourism_master_final.json"

WIKI_API = "https://en.wikipedia.org/w/api.php"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "TN-AI-Tour-Planner/1.0 (educational project)"
})

# Fix weak/generic rows in your current JSON
NAME_FIXES = {
    "Kanchipuram Temples": "Kamakshi Amman Temple",
    "Dharmapuri Forest View": "Adhiyamankottai Fort",
    "Coonoor Tea Gardens": "Sim's Park",
    "Tuticorin Beach": "Harbour Beach",
    "Karur Local Markets": "Pasupathieswarer Temple",
    "Kallakurichi Local Temples": "Sri Lakshmi Narasimha Swamy Temple"
}

# Optional page-title overrides for better Wikipedia matching
PAGE_TITLE_OVERRIDES = {
    "Marina Beach": "Marina Beach",
    "Kapaleeshwarar Temple": "Kapaleeshwarar Temple",
    "Meenakshi Amman Temple": "Meenakshi Temple",
    "Brihadeeswarar Temple": "Brihadisvara Temple, Thanjavur",
    "Ramanathaswamy Temple": "Ramanathaswamy Temple",
    "Vivekananda Rock Memorial": "Vivekananda Rock Memorial",
    "Shore Temple": "Shore Temple",
    "Arignar Anna Zoo": "Arignar Anna Zoological Park",
    "Velankanni Basilica": "Basilica of Our Lady of Good Health",
    "Point Calimere": "Point Calimere Wildlife and Bird Sanctuary",
    "Tharangambadi Fort": "Fort Dansborg",
    "Golden Temple": "Sripuram Golden Temple",
    "Nellaiappar Temple": "Nellaiappar Temple",
    "Thiruchendur Murugan Temple": "Thiruchendur Murugan Temple",
    "Kalyana Pasupatheeswarar Temple": "Pasupatheeswarar Temple, Karur",
    "Government Botanical Garden": "Government Botanical Gardens, Ooty",
    "Rose Garden Ooty": "Government Rose Garden",
    "DakshinaChitra": "DakshinaChitra",
    "Gandhi Memorial Museum": "Gandhi Memorial Museum, Madurai",
    "Pazhamudhircholai": "Pazhamudhircholai",
    "Kamakshi Amman Temple": "Kamakshi Amman Temple",
    "Varadharaja Perumal Temple": "Varadharaja Perumal Temple, Kanchipuram",
    "Sim's Park": "Sim's Park",
    "Avalanche Lake": "Avalanche Lake"
}

def read_json(path: str):
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def wiki_search_title(query: str):
    params = {
        "action": "opensearch",
        "search": query,
        "limit": 1,
        "namespace": 0,
        "format": "json",
    }
    r = SESSION.get(WIKI_API, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if len(data) >= 2 and data[1]:
        return data[1][0]
    return None

def wiki_page_image(title: str):
    params = {
        "action": "query",
        "prop": "pageimages",
        "titles": title,
        "format": "json",
        "pithumbsize": 1200,
        "piprop": "thumbnail|name",
        "redirects": 1,
    }
    r = SESSION.get(WIKI_API, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    pages = data.get("query", {}).get("pages", {})
    for _, page in pages.items():
        thumb = page.get("thumbnail", {})
        if thumb.get("source"):
            return thumb["source"]
    return None

def enrich_image(item: dict):
    item = dict(item)
    name = item.get("place_name", "").strip()
    location = item.get("location", "").strip()
    district = item.get("district", "").strip()

    query = PAGE_TITLE_OVERRIDES.get(name, name)

    title = wiki_search_title(query)
    if not title:
        title = wiki_search_title(f"{name} {location} Tamil Nadu")
    if not title:
        title = wiki_search_title(f"{name} {district} Tamil Nadu")

    image_url = ""
    if title:
        image_url = wiki_page_image(title) or ""

    item["image_url"] = image_url
    return item

def dedupe_items(items):
    seen = set()
    final = []
    for item in items:
        key = (
            item.get("place_name", "").strip().lower(),
            item.get("location", "").strip().lower(),
            item.get("district", "").strip().lower(),
        )
        if key not in seen:
            seen.add(key)
            final.append(item)
    return final

def apply_name_fixes(items):
    final = []
    for item in items:
        item = dict(item)
        old_name = item.get("place_name", "")
        if old_name in NAME_FIXES:
            item["place_name"] = NAME_FIXES[old_name]
        final.append(item)
    return final

def main():
    base_items = read_json(BASE_FILE)
    extra_items = read_json(EXTRA_FILE)

    all_items = base_items + extra_items
    all_items = apply_name_fixes(all_items)
    all_items = dedupe_items(all_items)

    enriched = []
    for idx, item in enumerate(all_items, start=1):
        try:
            new_item = enrich_image(item)
            enriched.append(new_item)
            print(f"[{idx}/{len(all_items)}] {new_item.get('place_name')} ✅")
        except Exception as e:
            item["image_url"] = item.get("image_url", "")
            enriched.append(item)
            print(f"[{idx}/{len(all_items)}] {item.get('place_name')} ⚠ {e}")
        time.sleep(0.2)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Final file created: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()