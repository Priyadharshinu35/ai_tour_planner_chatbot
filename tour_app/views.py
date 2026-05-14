import json
import math
import re
import html
from datetime import datetime
from difflib import get_close_matches
from typing import Optional, Dict, Any, List, Tuple

from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .forms import RegisterForm
from .models import UserPreference, ChatHistory


DATASET_JSON_NAME = "tamilnadu_tourism_master_final.json"


def dataset_path() -> str:
    return str(settings.BASE_DIR / DATASET_JSON_NAME)


def load_places():
    with open(dataset_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def distance(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@csrf_exempt
def nearby_places_view(request):
    body = json.loads(request.body)
    user_lat = body["latitude"]
    user_lon = body["longitude"]
    places = load_places()
    nearby = []
    for p in places:
        try:
            dist = distance(user_lat, user_lon, float(p["latitude"]), float(p["longitude"]))
            if dist <= 200:
                p["distance_km"] = round(dist, 1)
                nearby.append(p)
        except Exception:
            pass
    nearby = sorted(nearby, key=lambda x: x["distance_km"])
    return JsonResponse({"places": nearby[:10]})


# ---------------- language ----------------
def is_tamil_text(s: str) -> bool:
    return any("\u0B80" <= ch <= "\u0BFF" for ch in (s or ""))


def normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def is_tanglish_text(s: str) -> bool:
    s = normalize(s)
    tanglish_words = [
        "pakkam", "enga", "inga", "pogalam", "poguma", "epdi", "enna",
        "iruka", "irukuma", "kootam", "illama", "kulir", "veyil",
        "kovil", "koil", "aruvi", "malai", "venum", "suthanum",
        "poi paakanum", "nalla place", "tour poga", "kitta", "pakathula"
    ]
    return any(w in s for w in tanglish_words)


def reply_lang(en: str, ta: str, tg: str, tamil: bool = False, tanglish: bool = False) -> str:
    if tamil:
        return ta
    if tanglish:
        return tg
    return en


def esc(s: str) -> str:
    return html.escape(str(s or ""))


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def save_history(user, message, response):
    try:
        ChatHistory.objects.create(user=user, message=message, response=response)
    except Exception:
        pass


# ---------------- dataset ----------------
_DATA_CACHE: List[Dict[str, Any]] = []


def load_dataset() -> List[Dict[str, Any]]:
    global _DATA_CACHE
    if _DATA_CACHE:
        return _DATA_CACHE
    with open(dataset_path(), "r", encoding="utf-8") as f:
        _DATA_CACHE = json.load(f)
    return _DATA_CACHE


# ---------------- matching helpers ----------------
def fuzzy_match(query: str, choices: List[str], cutoff: float = 0.72) -> Optional[str]:
    q = (query or "").strip()
    if not q:
        return None
    qn = normalize(q)
    for c in choices:
        if qn == normalize(c):
            return c
    for c in choices:
        if qn in normalize(c):
            return c
    m1 = get_close_matches(q, choices, n=1, cutoff=cutoff)
    if m1:
        return m1[0]
    m2 = get_close_matches(q.title(), choices, n=1, cutoff=cutoff)
    return m2[0] if m2 else None


def all_place_names() -> List[str]:
    return [p.get("place_name", "") for p in load_dataset() if p.get("place_name")]


def all_locations() -> List[str]:
    vals = []
    for p in load_dataset():
        if p.get("location"):
            vals.append(p["location"])
    return sorted(set(vals))


def all_districts() -> List[str]:
    vals = []
    for p in load_dataset():
        if p.get("district"):
            vals.append(p["district"])
    return sorted(set(vals))


def match_place_name_in_text(msg: str) -> Optional[str]:
    m = normalize(msg)
    for name in all_place_names():
        if normalize(name) in m:
            return name
    return fuzzy_match(msg, all_place_names(), cutoff=0.76)


def match_location_in_text(msg: str) -> Optional[str]:
    m = normalize(msg)
    # Exact substring match first
    for loc in all_locations():
        if normalize(loc) in m:
            return loc
    # Partial word match — e.g. "ooty" matches location "Ooty" even if "ooty" is also a place name
    for loc in all_locations():
        loc_n = normalize(loc)
        # Check each word of loc against message
        if any(word in m.split() for word in loc_n.split() if len(word) >= 4):
            return loc
    return fuzzy_match(msg, all_locations(), cutoff=0.75)


def match_district_in_text(msg: str) -> Optional[str]:
    m = normalize(msg)
    for d in all_districts():
        if normalize(d) in m:
            return d
    return fuzzy_match(msg, all_districts(), cutoff=0.75)


# ---------------- intent keywords ----------------
HELP_KEYS = ["help", "how to", "format", "example", "examples", "commands", "guide"]
ROUTE_KEYS = ["route", "direction", "navigate", "how to go", "map route"]

LOW_CROWD_KEYS = ["low crowd", "less crowd", "peaceful", "quiet", "not crowded", "no crowd",
                  "crowd illama", "kootam illama", "less people", "empty", "serene", "uncrowded",
                  "peaceful place", "hidden gem", "offbeat", "less tourists"]
HIGH_CROWD_KEYS = ["high crowd", "crowded", "busy", "rush", "heavy crowd", "romba crowd",
                   "kootam", "popular", "famous", "trending"]

WINTER_KEYS = ["winter", "cool", "cold", "kulir", "chill", "december", "january",
               "february", "november", "cool climate", "cold weather"]
SUMMER_KEYS = ["summer", "hot", "heat", "veyil", "april", "may", "june"]
MONSOON_KEYS = ["monsoon", "rain", "rainy", "mazhai", "july", "august", "september"]

FAMILY_KEYS = ["family", "kids", "children", "parents", "kudumbam", "with family",
               "family trip", "family vacation", "kid friendly"]
SOLO_KEYS = ["solo", "alone", "single", "thaniya", "by myself", "just me", "one person", "solo trip"]
FRIENDS_KEYS = ["friends", "gang", "mates", "couple", "with friends", "friend", "buddy",
                "group", "gang trip", "friend trip"]

CATEGORY_MAP = {
    "beach": ["beach", "sea", "shore", "kadal", "coastal", "seaside", "ocean", "sea side"],
    "temple": ["temple", "temples", "kovil", "koil", "murugan", "amman",
               "dargah", "mosque", "shrine", "pilgrimage", "religious", "worship",
               "deity", "shiva", "vishnu", "perumal", "spiritual places",
               "temple visit", "sabari", "tirumala"],
    "church": ["church", "churches", "basilica", "cathedral", "christian", "lourdes"],
    "hill": ["hill", "hill station", "mountain", "mountains", "malai", "peak", "hills",
             "ooty", "kodaikanal", "yercaud", "valparai", "megamalai", "hilltop", "ghats"],
    "waterfall": ["waterfall", "waterfalls", "falls", "aruvi", "cascade", "waterfall visit"],
    "wildlife": ["wildlife", "park", "sanctuary", "bird sanctuary", "national park", "zoo",
                 "safari", "forest", "animals", "birds", "nature", "tiger", "elephant"],
    "heritage": ["heritage", "fort", "palace", "museum", "monument", "statue", "unesco",
                 "history", "historical", "ancient", "ruins", "architecture", "old temple",
                 "heritage site"],
    "science": ["science", "observatory", "fossil", "planetarium"],
    "scenic": ["scenic", "viewpoint", "view", "landscape", "lake", "dam", "river",
               "garden", "botanical", "park", "picnic", "boating"],
}

DISTRICT_QUERY_WORDS = [
    "tourist places", "places", "place", "spots", "visit", "travel", "trip", "tour",
    "things to do", "what to see", "explore", "sightseeing", "attractions", "tourism"
]

GREETING_KEYS = ["hi", "hello", "hey", "hii", "helo", "vanakkam", "hai", "good morning",
                 "good evening", "good afternoon", "wassup", "sup"]
THANKS_KEYS = ["thank you", "thanks", "thank", "nandri", "romba thanks"]
# NOTE: "ty" removed — matches inside "ooty", "beauty" etc.
# Word-boundary helpers used in chatbot_api instead of bare substring match

TN_WIDE_PATTERNS = [
    "beaches in tamilnadu", "beach in tamilnadu", "beaches in tamil nadu",
    "temples in tamilnadu", "temple in tamilnadu", "temples in tamil nadu",
    "hill stations in tamilnadu", "hill station in tamilnadu", "all hill stations",
    "waterfalls in tamilnadu", "waterfall in tamilnadu",
    "wildlife in tamilnadu", "all beaches", "all temples", "all waterfalls",
    "all places", "tamilnadu places", "tamil nadu tourist", "tourist places in tamilnadu",
    "heritage sites in tamilnadu", "forts in tamilnadu", "dams in tamilnadu",
    "best places in tamilnadu", "top places tamilnadu",
]


# ---------------- detectors ----------------
def detect_season(msg: str) -> Optional[str]:
    m = normalize(msg)
    if any(k in m for k in WINTER_KEYS):
        return "Winter"
    if any(k in m for k in SUMMER_KEYS):
        return "Summer"
    if any(k in m for k in MONSOON_KEYS):
        return "Monsoon"
    if "all season" in m or "any season" in m or "anytime" in m:
        return "All"
    return None


def detect_crowd(msg: str) -> Optional[str]:
    m = normalize(msg)
    if any(k in m for k in LOW_CROWD_KEYS):
        return "Low"
    if any(k in m for k in HIGH_CROWD_KEYS):
        return "High"
    return None


def detect_travel_type(msg: str) -> Optional[str]:
    m = normalize(msg)
    if any(k in m for k in FAMILY_KEYS):
        return "Family"
    if any(k in m for k in SOLO_KEYS):
        return "Solo"
    if any(k in m for k in FRIENDS_KEYS):
        return "Friends"
    return None


def detect_category(msg: str) -> Optional[str]:
    m = normalize(msg)
    words = set(m.split())
    for cat, keys in CATEGORY_MAP.items():
        for k in keys:
            # Multi-word keys: substring match is fine
            if " " in k:
                if k in m:
                    return cat
            else:
                # Single-word keys: must match as a whole word to avoid
                # e.g. "velankani church" matching "church" → temple
                # when user actually means a specific place
                if k in words:
                    return cat
    return None


def detect_days(msg: str) -> Optional[int]:
    m = normalize(msg)
    match = re.search(r"(\d+)\s*day", m)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def parse_user_intent(msg: str) -> Dict[str, Any]:
    m = normalize(msg)
    category = detect_category(msg)

    # Is this a TN-wide category query?
    broad_tn = any(pattern in m for pattern in TN_WIDE_PATTERNS)

    # Detect if message is a "places in <location>" style query
    # e.g. "ooty places", "places in ooty", "ooty tourist spots", "madurai visit"
    is_location_query = any(k in m for k in DISTRICT_QUERY_WORDS)

    # Check if any known location or district is mentioned
    districts_mentioned = any(normalize(d) in m for d in all_districts())
    locations_mentioned = any(normalize(l) in m for l in all_locations())

    # SINGLE-WORD / SHORT MESSAGE: if msg is just a location name (with no other intent words),
    # treat it as a location query always — handles "ooty", "madurai", etc. in any conversation turn
    msg_words = m.split()
    is_short_msg = len(msg_words) <= 3  # e.g. "ooty", "kodaikanal", "ooty hills"

    if is_short_msg and (locations_mentioned or districts_mentioned):
        is_location_query = True


    # SPECIFIC PLACE CHECK: Before setting broad_tn, check if the message
    # matches a specific place name (e.g. "velankani church", "dodabetta peak").
    # If yes, the category keyword is PART of the place name, not a search intent.
    # RULE: Only override category if message has a NON-category word that identifies the place.
    # e.g. "velankani church" → "velankani" is non-category → specific place wins
    # e.g. "temple" alone → only category word → broad category search
    # e.g. "kapaleeshwar temple" → "kapaleeshwar" is non-category → specific place wins
    _all_category_words = set()
    for _keys in CATEGORY_MAP.values():
        for _k in _keys:
            _all_category_words.update(_k.split())
    _msg_words = m.split()
    _non_category_words = [w for w in _msg_words if w not in _all_category_words and len(w) >= 3]
    # Only do early place match if message has at least one non-category word
    if _non_category_words and not is_location_query:
        _early_place_match = match_place_name_in_text(msg)
        if _early_place_match:
            category = None  # Non-category word identifies a specific place → no broad search

    # If category is detected but no district/location → broad TN query
    if category and not districts_mentioned and not locations_mentioned:
        broad_tn = True

    # Resolve location and district first
    matched_location = None if broad_tn else match_location_in_text(msg)
    matched_district = None if broad_tn else match_district_in_text(msg)

    # KEY FIX: If message has "places/visit/spots" words + a known location/district,
    # treat it as a location/district list query — NOT an exact place lookup.
    # e.g. "ooty places" → location query for Ooty, NOT exact place "Ooty"
    # Also applies to short messages that are just location names
    force_location_query = is_location_query and (matched_location or matched_district)

    # Only do exact place match if NOT a location-list query
    if broad_tn or force_location_query:
        matched_place_name = None
    else:
        matched_place_name = match_place_name_in_text(msg)
        # If place_name == location name and query has place-list words → treat as location query
        if matched_place_name and is_location_query:
            # Check if matched place name is same as a location (e.g. "Ooty" is both place & location)
            if matched_location and normalize(matched_place_name) == normalize(matched_location):
                matched_place_name = None
                force_location_query = True
            elif matched_district and normalize(matched_place_name) == normalize(matched_district):
                matched_place_name = None
                force_location_query = True

    # SPECIAL: If message exactly matches or closely matches a SPECIFIC place name
    # (not a location/district), AND it's not a broad location query,
    # then treat it as a specific place lookup.
    # e.g. "vellankani temple", "dodabetta peak" → exact place, not category query
    # But "ooty" → location (has many places), "kodaikanal" → location (has many places)
    if not broad_tn and not force_location_query and matched_place_name:
        # If the matched place name is also a location with MULTIPLE places,
        # prefer showing all places in that location
        loc_count = len(places_by_location(matched_place_name)) if matched_place_name else 0
        if loc_count >= 2:
            # This is a multi-place location — treat as location query
            matched_location = matched_location or matched_place_name
            matched_place_name = None
            force_location_query = True

    intent: Dict[str, Any] = {
        "place_name": matched_place_name,
        "location": matched_location,
        "district": matched_district,
        "season": detect_season(msg),
        "crowd": detect_crowd(msg),
        "category": category,
        "travel_type": detect_travel_type(msg),
        "days": detect_days(msg),
        "broad_tn": broad_tn,
        "force_location_query": force_location_query,
    }

    # Expansions
    if any(k in m for k in ["cool places", "cool climate", "chill places", "cold places"]):
        intent["season"] = "Winter"
    if "less crowd" in m or "low crowd" in m:
        intent["crowd"] = "Low"
    if "mountains" in m or "hill station" in m:
        intent["category"] = "hill"

    # If district mentioned WITH category → district + category filter (not broad)
    if intent["district"] and category:
        intent["broad_tn"] = False

    return intent


# ---------------- transport logic ----------------
TRANSPORT_MODES = {
    "hill": {
        "mode": "Car / Cab",
        "why": "Winding ghat roads — safest by car or cab",
        "icon": "🚗",
        "cost_per_km": 14,   # cab rate
    },
    "beach": {
        "mode": "Bus / Train",
        "why": "Coastal highways well served by bus & train",
        "icon": "🚌",
        "cost_per_km": 3,
    },
    "temple": {
        "mode": "Bus / Train",
        "why": "Temple towns have good public transport",
        "icon": "🚌",
        "cost_per_km": 3,
    },
    "waterfall": {
        "mode": "Car / Bike",
        "why": "Forest roads — car or bike recommended",
        "icon": "🏍️",
        "cost_per_km": 8,
    },
    "wildlife": {
        "mode": "Car / Jeep Safari",
        "why": "Safari entry needs own/hired vehicle",
        "icon": "🚙",
        "cost_per_km": 14,
    },
    "heritage": {
        "mode": "Bus / Train",
        "why": "Heritage towns well connected by bus & train",
        "icon": "🚂",
        "cost_per_km": 3,
    },
    "scenic": {
        "mode": "Car / Bus",
        "why": "Scenic spots reachable by car or bus",
        "icon": "🚗",
        "cost_per_km": 8,
    },
    "default": {
        "mode": "Bus / Train",
        "why": "Well connected by Tamil Nadu state transport",
        "icon": "🚌",
        "cost_per_km": 3,
    },
}


def get_transport_info(category: str) -> Dict[str, Any]:
    cat = normalize(category)
    for key in TRANSPORT_MODES:
        if key in cat:
            return TRANSPORT_MODES[key]
    return TRANSPORT_MODES["default"]


# ---------------- budget helpers ----------------
def estimate_travel_hours(distance_km: Optional[float], category: str = "") -> Optional[float]:
    if distance_km is None:
        return None
    # Hill roads slower
    speed = 35.0 if any(k in normalize(category) for k in ["hill", "waterfall", "wildlife"]) else 55.0
    return round(distance_km / speed, 1)


def travel_summary(place: Dict[str, Any], user_loc: Optional[Dict[str, float]],
                   days: int = 1, travel_type: Optional[str] = None) -> Dict[str, Any]:
    distance_km = None
    travel_hours = None
    category = place.get("category", "")
    if user_loc and place.get("latitude") and place.get("longitude"):
        try:
            distance_km = haversine_km(user_loc["lat"], user_loc["lng"],
                                       place["latitude"], place["longitude"])
            travel_hours = estimate_travel_hours(distance_km, category)
        except Exception:
            pass
    transport_info = get_transport_info(category)
    return {
        "distance_km": round(distance_km, 1) if distance_km is not None else None,
        "travel_hours": travel_hours,
        "transport_mode": transport_info["mode"],
        "transport_icon": transport_info["icon"],
        "transport_why": transport_info["why"],
    }


# ---------------- crowd (accurate) ----------------
def dynamic_crowd(place: Dict[str, Any]) -> Tuple[str, str]:
    now = datetime.now()
    month_num = now.month
    is_weekend = now.weekday() >= 5
    festival = normalize(place.get("festival_peak_months") or "")
    pop = int(place.get("popularity_score") or 50)
    base_label = (place.get("normal_crowd_level") or "Medium").strip().title()
    score = {"Low": 1, "Medium": 2, "High": 3, "Very High": 4}.get(base_label, 2)
    month_abbrs = {1:"jan",2:"feb",3:"mar",4:"apr",5:"may",6:"jun",
                   7:"jul",8:"aug",9:"sep",10:"oct",11:"nov",12:"dec"}
    cur = month_abbrs.get(month_num, "")
    if festival and cur in festival:
        score += 2
    if is_weekend:
        score += 1
    if pop >= 100:
        score += 1
    elif pop <= 30:
        score -= 1
    score = max(1, min(score, 4))
    level = {1: "Low", 2: "Medium", 3: "High", 4: "Very High"}[score]
    remark = []
    if festival and cur in festival:
        remark.append("Festival season")
    if is_weekend:
        remark.append("Weekend")
    if pop >= 100:
        remark.append("Very popular")
    elif pop <= 30:
        remark.append("Hidden gem")
    return level, (" • ".join(remark) if remark else "Normal day")


# Season advice per month
MONTH_SEASON_MAP = {
    1: "Winter", 2: "Winter", 3: "Summer", 4: "Summer", 5: "Summer",
    6: "Monsoon", 7: "Monsoon", 8: "Monsoon", 9: "Monsoon",
    10: "Winter", 11: "Winter", 12: "Winter"
}

SEASON_ADVICE = {
    "Winter":  "🌤️ Best: Oct–Feb · Cool, dry & perfect for sightseeing",
    "Summer":  "☀️ Best: Mar–May · Warm & sunny, ideal for hill stations",
    "Monsoon": "🌧️ Best: Jun–Sep · Lush green, waterfalls at peak",
    "All":     "📅 Good all year round · No bad season",
}

SEASON_AVOID = {
    "Winter":  "⚠️ Avoid Jun–Sep (heavy monsoon rain)",
    "Summer":  "⚠️ Avoid Dec–Feb (cold, misty conditions)",
    "Monsoon": "⚠️ Avoid Apr–May (too hot & dry)",
    "All":     "",
}

# Which months are ideal for each season
SEASON_BEST_MONTHS = {
    "Winter":  [10, 11, 12, 1, 2],
    "Summer":  [3, 4, 5],
    "Monsoon": [6, 7, 8, 9],
}

def season_fit_score(place: Dict[str, Any]) -> int:
    """Return 2=perfect, 1=ok, 0=avoid for current month."""
    best = normalize(place.get("best_season") or "all")
    cur_month = datetime.now().month
    cur_season = MONTH_SEASON_MAP.get(cur_month, "Winter")
    if "all" in best:
        return 2
    # Check if current month is in best months for that season
    for season_name, months in SEASON_BEST_MONTHS.items():
        if season_name.lower() in best and cur_month in months:
            return 2
    if cur_season.lower() in best:
        return 1
    return 0


def get_season_status(place: Dict[str, Any]) -> str:
    """Return human-readable season status for current month."""
    best = normalize(place.get("best_season") or "all")
    cur_month = datetime.now().month
    cur_season = MONTH_SEASON_MAP.get(cur_month, "Winter")
    month_names = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                   7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}
    cur_name = month_names[cur_month]

    if "all" in best:
        return f"✅ Great to visit in {cur_name}"
    for season_name, months in SEASON_BEST_MONTHS.items():
        if season_name.lower() in best:
            if cur_month in months:
                return f"✅ Perfect time! {cur_name} is ideal"
            else:
                best_m = [month_names[m] for m in months[:2]]
                return f"⚠️ Better in {'/'.join(best_m)}"
    return f"📅 Visit during {place.get('best_season','any season')}"


def why_this_place(place: Dict[str, Any], travel_type: Optional[str] = None) -> List[str]:
    reasons = []
    cat = normalize(place.get("category", ""))
    best_season = (place.get("best_season") or "All").strip()
    crowd_level, _ = dynamic_crowd(place)
    cur_season = MONTH_SEASON_MAP.get(datetime.now().month, "Winter")

    # Travel type
    type_msgs = {
        "Family": "👨‍👩‍👧 Great for family outings",
        "Solo":   "🧍 Perfect for solo travellers",
        "Friends":"👫 Awesome group destination"
    }
    if travel_type in type_msgs:
        reasons.append(type_msgs[travel_type])

    # Season fit — show actual advice
    best_lower = normalize(best_season)
    season_key = "All"
    for s in ["Winter", "Summer", "Monsoon"]:
        if s.lower() in best_lower:
            season_key = s
            break
    reasons.append(SEASON_ADVICE.get(season_key, f"Best in {best_season}"))
    # Warn if current month is bad season
    if season_key != "All" and cur_season.lower() not in best_lower:
        avoid = SEASON_AVOID.get(season_key, "")
        if avoid:
            reasons.append(avoid)

    # Category reason
    cat_msgs = {
        "hill":      "🌄 Scenic hill destination",
        "beach":     "🏖️ Beautiful coastal getaway",
        "temple":    "⛩️ Significant spiritual site",
        "waterfall": "💧 Stunning natural waterfall",
        "heritage":  "🏰 Rich historical heritage",
        "wildlife":  "🦁 Incredible nature & wildlife",
        "scenic":    "🌅 Breathtaking scenic views",
        "church":    "⛪ Major pilgrimage site",
        "dam":       "💧 Scenic dam & reservoir",
    }
    for k, v in cat_msgs.items():
        if k in cat:
            reasons.append(v)
            break

    # Crowd
    if crowd_level in ["Low", "Medium"]:
        reasons.append("✅ Comfortable crowd levels today")
    elif crowd_level == "Very High":
        reasons.append("⚠️ Very crowded — book ahead!")

    final = []
    for r in reasons:
        if r not in final:
            final.append(r)
    return final[:4]


# ---------------- search helpers ----------------
def find_exact_place(place_name: str) -> Optional[Dict[str, Any]]:
    for p in load_dataset():
        if p.get("place_name") == place_name:
            return p
    return None


def places_by_location(location: str) -> List[Dict[str, Any]]:
    q = normalize(location)
    return [p for p in load_dataset() if q == normalize(p.get("location", ""))]


def places_by_district(district: str) -> List[Dict[str, Any]]:
    q = normalize(district)
    return [p for p in load_dataset() if q == normalize(p.get("district", ""))]


def get_nearby_places(base: Dict[str, Any], limit: int = 6) -> List[Dict[str, Any]]:
    data = load_dataset()
    lat, lng = base.get("latitude"), base.get("longitude")
    if lat and lng:
        rows = []
        for p in data:
            if p.get("place_name") == base.get("place_name"):
                continue
            if p.get("latitude") and p.get("longitude"):
                try:
                    d = haversine_km(lat, lng, p["latitude"], p["longitude"])
                    rows.append((d, p))
                except Exception:
                    pass
        rows.sort(key=lambda x: x[0])
        return [p for _, p in rows[:limit]]
    dist = normalize(base.get("district", ""))
    return [p for p in data if normalize(p.get("district", "")) == dist
            and p.get("place_name") != base.get("place_name")][:limit]


def _apply_category_filter(items, category):
    """Apply broad category filter."""
    c = normalize(category)
    if c == "temple":
        # "temple" search → show temples AND churches/mosques (all spiritual places)
        return [p for p in items if any(k in normalize(p.get("category", ""))
                for k in ["temple", "church", "mosque", "dargah", "shrine", "spiritual", "basilica"])]
    elif c == "church":
        # "church" search → show ONLY churches/basilicas, not temples
        return [p for p in items if any(k in normalize(p.get("category", ""))
                for k in ["church", "basilica", "cathedral", "shrine"])]
    elif c == "hill":
        return [p for p in items if any(k in normalize(p.get("category", ""))
                for k in ["hill", "mountain", "scenic"])]
    elif c == "scenic":
        return [p for p in items if any(k in normalize(p.get("category", ""))
                for k in ["scenic", "lake", "dam", "garden", "park"])]
    elif c == "wildlife":
        return [p for p in items if any(k in normalize(p.get("category", ""))
                for k in ["wildlife", "birding", "national park", "sanctuary", "ecotourism", "zoo"])]
    elif c == "heritage":
        return [p for p in items if any(k in normalize(p.get("category", ""))
                for k in ["heritage", "fort", "palace", "museum", "monument"])]
    else:
        return [p for p in items if c in normalize(p.get("category", ""))]


def recommend_places(
    season: Optional[str],
    crowd: Optional[str],
    district: Optional[str],
    category: Optional[str],
    travel_type: Optional[str],
    user_loc: Optional[Dict[str, float]],
    limit: int = 20,
    broad_tn: bool = False,
) -> List[Dict[str, Any]]:
    items = load_dataset()

    if district and not broad_tn:
        q = normalize(district)
        items = [p for p in items if q in normalize(p.get("district", "")) or q in normalize(p.get("location", ""))]

    if season and season != "All":
        items = [p for p in items if season.lower() in normalize(p.get("best_season", "All"))]

    if category:
        filtered = _apply_category_filter(items, category)
        items = filtered if filtered else items

    if crowd:
        crowd_filtered = []
        for p in items:
            level, _ = dynamic_crowd(p)
            if crowd == "Low" and level in ["Low", "Medium"]:
                crowd_filtered.append(p)
            elif crowd == "High" and level in ["High", "Very High"]:
                crowd_filtered.append(p)
        items = crowd_filtered if crowd_filtered else items

    if user_loc:
        def dist_key(p):
            if p.get("latitude") and p.get("longitude"):
                try:
                    return haversine_km(user_loc["lat"], user_loc["lng"], p["latitude"], p["longitude"])
                except Exception:
                    return 10 ** 9
            return 10 ** 9
        items.sort(key=dist_key)

    def travel_score(p: Dict[str, Any]) -> int:
        cat = normalize(p.get("category", ""))
        score = 0
        if travel_type == "Family":
            if any(k in cat for k in ["beach", "scenic", "dam", "heritage", "monument", "wildlife", "park", "garden", "zoo"]):
                score += 2
        elif travel_type == "Solo":
            if any(k in cat for k in ["heritage", "science", "wildlife", "trek", "spiritual", "observatory"]):
                score += 2
        elif travel_type == "Friends":
            if any(k in cat for k in ["beach", "hill", "waterfall", "scenic", "trek", "ecotourism"]):
                score += 2
        return score

    if travel_type:
        items.sort(key=lambda x: travel_score(x), reverse=True)

    return items[:limit]


# ---------------- itinerary ----------------
def build_itinerary(places: List[Dict[str, Any]], days: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    days = max(1, min(7, int(days or 3)))
    result = {}
    idx = 0
    for day in range(1, days + 1):
        result[f"Day {day}"] = places[idx: idx + 3]
        idx += 3
        if idx >= len(places):
            break
    return result


# Category fallback images
FALLBACK_IMAGES = {
    "beach":     "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=800&q=70",
    "temple":    "https://images.unsplash.com/photo-1582510003544-4d00b7f74220?w=800&q=70",
    "hill":      "https://images.unsplash.com/photo-1501785888041-af3ef285b470?w=800&q=70",
    "waterfall": "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800&q=70",
    "wildlife":  "https://images.unsplash.com/photo-1564760055775-d63b17a55c44?w=800&q=70",
    "heritage":  "https://images.unsplash.com/photo-1524492412937-b28074a5d7da?w=800&q=70",
    "scenic":    "https://images.unsplash.com/photo-1609766418204-94aae0ecfdfc?w=800&q=70",
    "dam":       "https://images.unsplash.com/photo-1501854140801-50d01698950b?w=800&q=70",
    "default":   "https://images.unsplash.com/photo-1598091383021-15ddea10925d?w=800&q=70",
}

def get_fallback_image(category: str) -> str:
    cat = normalize(category)
    for k, v in FALLBACK_IMAGES.items():
        if k in cat:
            return v
    return FALLBACK_IMAGES["default"]


def _render_place_card(r, user_loc_available, travel_type, user_loc, days, show_nearby=True):
    img = r.get("image_url") or ""
    if not img:
        img = get_fallback_image(r.get("category", ""))
    safe_img = esc(img).replace("'", "%27")
    img_html = (f'<img src="{esc(img)}" alt="{esc(r.get("place_name",""))}" '
                f'onclick="showImageModal(\'{safe_img}\')" style="cursor:pointer;">')

    place = r.get("place_name", "")
    loc = r.get("location", "") or r.get("district", "Tamil Nadu")
    best = r.get("best_season", "All")
    crowd_level, crowd_remark = dynamic_crowd(r)
    season_status = get_season_status(r)
    reasons = why_this_place(r, travel_type=travel_type)
    reason_html = "".join([f"<div class='whyLine'>{x}</div>" for x in reasons])

    summary = travel_summary(r, user_loc=user_loc, days=days, travel_type=travel_type)
    distance_line = (f"{summary['distance_km']} km away • ~{summary['travel_hours']} hrs travel"
                     if summary["distance_km"] is not None else "📍 Share location to get distance")

    transport_line = f"{summary['transport_icon']} {summary['transport_mode']} — {summary['transport_why']}"

    fmap = f'https://www.google.com/maps/search/?api=1&query={esc(place + " " + loc)}'
    lat = r.get("latitude")
    lng = r.get("longitude")

    # Route button: if location available, open Google Maps directions directly (no chat message needed)
    # This avoids re-triggering the chat and showing all recommendations again
    if lat and lng and user_loc_available and user_loc:
        origin = f"{user_loc['lat']},{user_loc['lng']}"
        destination = f"{lat},{lng}"
        gmaps_route = f"https://www.google.com/maps/dir/{origin}/{destination}"
        route_btn = f'<a class="cardBtn" href="{gmaps_route}" target="_blank">🗺️ Route</a>'
    elif lat and lng:
        # Location not yet shared — prompt user to share location
        route_btn = (f'<button class="cardBtn" onclick="requestLocationForRoute(\'{lat}\',\'{lng}\')">'
                     f'🗺️ Route</button>')
    else:
        route_btn = ""

    nearby_btn = (f'<button class="cardBtn" onclick="quickAsk(\'nearby::{esc(place)}\')">📍 Nearby</button>'
                  if show_nearby else "")

    crowd_badge = {"Low": "crowdLow", "Medium": "crowdMed", "High": "crowdHigh", "Very High": "crowdVHigh"}.get(crowd_level, "crowdMed")

    return f"""
      <div class="pCard">
        <div class="pImg">{img_html}</div>
        <div class="pBody">
          <div class="pTitle">{esc(place)}</div>
          <div class="pMeta">📍 {esc(loc)}</div>
          <div class="pMeta">🌦️ Best Season: {esc(best)} &nbsp; <span style="opacity:.75">{esc(season_status)}</span></div>
          <div class="pMeta">👥 <span class="crowdBadge {crowd_badge}">{esc(crowd_level)}</span>
            <span class="crowdSub">{esc(crowd_remark)}</span></div>
          <div class="pMeta">🛣️ {esc(distance_line)}</div>
          <div class="pMeta">🚗 {esc(transport_line)}</div>
          <div class="pDesc">{esc((r.get("description") or "")[:180])}</div>
          <div class="whyBox">
            <div class="whyTitle">✨ Why visit?</div>
            {reason_html}
          </div>
          <div class="cardActions">
            <a class="cardBtn mapBtn" href="{fmap}" target="_blank">🗺 Map</a>
            {route_btn}
            {nearby_btn}
          </div>
        </div>
      </div>
    """

def render_itinerary_html(title: str, places: List[Dict[str, Any]], user_loc_available: bool,
                           days: int = 3, travel_type: Optional[str] = None,
                           user_loc: Optional[Dict[str, float]] = None) -> str:
    plan = build_itinerary(places, days=days)
    parts = [f"<div class='secTitle'>🗓️ {esc(title)}</div>"]
    for day, spots in plan.items():
        cards_html = "".join([_render_place_card(r, user_loc_available, travel_type, user_loc, days) for r in spots])
        parts.append(f"<div class='dayLabel'>{esc(day)}</div><div class='cards'>{cards_html}</div>")
    return "".join(parts)


def render_cards(items: List[Dict[str, Any]], user_loc_available: bool, heading: str = "Results",
                 travel_type: Optional[str] = None, user_loc: Optional[Dict[str, float]] = None,
                 days: int = 1) -> str:
    if not items:
        return "<div class='noResult'>😕 No matching places found. Try a different query!</div>"
    cards_html = "".join([_render_place_card(r, user_loc_available, travel_type, user_loc, days) for r in items])
    return f"<div><div class='secTitle'>{esc(heading)}</div><div class='cards'>{cards_html}</div></div>"


# ---------------- pages ----------------
@login_required
def chatbot(request):
    return render(request, "tour_app/chatbot.html", {
        "is_admin": request.user.is_superuser
    })


@login_required
def welcome_api(request):
    return JsonResponse({
        "welcome": f"Vanakkam {request.user.username}! 🙏 Welcome to Tamil Nadu AI Tour Planner.",
        "prompt": "Ask anything — temples in winter with low crowd | family beaches | 3 day ooty trip | chennai places | nearby places"
    })


@login_required
def places_api(request):
    data = load_dataset()
    return JsonResponse({"count": len(data), "places": data})


@login_required
def history_view(request):
    history = ChatHistory.objects.filter(user=request.user).order_by("-created")
    return render(request, "tour_app/history.html", {"history": history})


@login_required
def history_detail_api(request, history_id):
    """Return a single history item's messages as JSON for replaying in chat."""
    try:
        item = ChatHistory.objects.get(id=history_id, user=request.user)
        return JsonResponse({"ok": True, "message": item.message, "response": item.response})
    except ChatHistory.DoesNotExist:
        return JsonResponse({"ok": False}, status=404)


@csrf_exempt
@login_required
@require_POST
def set_location_api(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
        lat = body.get("lat")
        lng = body.get("lng")
        if lat is None or lng is None:
            return JsonResponse({"ok": False, "error": "Missing lat/lng"}, status=400)
        request.session["user_loc"] = {"lat": float(lat), "lng": float(lng)}
        return JsonResponse({"ok": True})
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid payload"}, status=400)


@login_required
@require_POST
def new_chat_api(request):
    """Clear chat context to start fresh."""
    request.session.pop("chat_ctx_json", None)
    return JsonResponse({"ok": True})


# ---------------- chatbot api ----------------
@login_required
def chatbot_api(request):
    msg = (request.GET.get("message", "") or "").strip()
    if not msg:
        return JsonResponse({"type": "text", "reply": "Please type something! 😊"})

    # history_replay=1: read-only replay from history page
    # Skip saving new history entry and skip modifying session context
    is_replay = request.GET.get("history_replay") == "1"

    m = normalize(msg)
    tamil = is_tamil_text(msg)
    tanglish = is_tanglish_text(msg)
    data = load_dataset()
    user_loc = request.session.get("user_loc")
    user_loc_available = bool(user_loc)

    if is_replay:
        import copy
        ctx = copy.deepcopy(request.session.get("chat_ctx_json", {}))
    else:
        ctx = request.session.get("chat_ctx_json", {})
    for key in ["place_name", "location", "district", "season", "crowd",
                "category", "travel_type", "days", "last_place"]:
        ctx.setdefault(key, None)

    # Greetings — only if the ENTIRE message is a greeting (or starts with one as standalone word)
    m_words = set(m.split())
    if any(m == k or m_words == {k} or m.startswith(k + " ") for k in GREETING_KEYS):
        reply = "Vanakkam! 🙏 I'm your Tamil Nadu travel guide. Ask about temples, beaches, hill stations, or any place!"
        if not is_replay:
            save_history(request.user, msg, reply)
        return JsonResponse({"type": "text", "reply": reply})

    # Thanks — only match whole words, not substrings (e.g. "ty" inside "ooty" must NOT match)
    def is_thanks(text):
        words = text.split()
        for k in THANKS_KEYS:
            k_words = k.split()
            # Check if k appears as a whole-word phrase in text
            for i in range(len(words) - len(k_words) + 1):
                if words[i:i+len(k_words)] == k_words:
                    return True
        return False

    if is_thanks(m):
        reply = "Happy to help! 😊 Ask me anything about Tamil Nadu travel!"
        if not is_replay:
            save_history(request.user, msg, reply)
        return JsonResponse({"type": "text", "reply": reply})

    # Help — whole-word match only
    def is_help(text):
        words = text.split()
        for k in HELP_KEYS:
            k_words = k.split()
            for i in range(len(words) - len(k_words) + 1):
                if words[i:i+len(k_words)] == k_words:
                    return True
        return False

    if is_help(m):
        reply = (
            "Here's what you can ask me:\n\n"
            "⛩️  temples in winter with low crowd\n"
            "🏖️  beaches in tamilnadu\n"
            "🌄  hill stations for family\n"
            "🗺️  3 day trip in madurai\n"
            "🏙️  chennai tourist places\n"
            "📍  nearby places (share location first)\n"
            "🌊  waterfalls in monsoon\n"
            "🦁  wildlife sanctuaries\n"
            "🏰  heritage forts\n\n"
            "Mix and match! e.g. 'solo trip to beach in winter with low crowd'"
        )
        if not is_replay:
            request.session["chat_ctx_json"] = ctx
        if not is_replay:
            save_history(request.user, msg, reply)
        return JsonResponse({"type": "text", "reply": reply})

    # Route without location
    if any(k in m for k in ROUTE_KEYS) and not user_loc_available:
        reply = "Click '📍 Use my location' first, then tap Route on any card."
        if not is_replay:
            save_history(request.user, msg, reply)
        return JsonResponse({"type": "text", "reply": reply})

    TRANSPORT_QUERY_KEYS = ["which transport", "best transport", "how to reach",
                            "how to go", "which bus", "train or car", "cab or bus",
                            "transport to", "reach by", "which vehicle"]

    # Transport query for a specific place
    if any(k in m for k in TRANSPORT_QUERY_KEYS):
        place_name = match_place_name_in_text(msg) or match_location_in_text(msg)
        if place_name:
            place = find_exact_place(place_name)
            if not place:
                # try location match
                locs = places_by_location(place_name)
                place = locs[0] if locs else None
            if place:
                t = get_transport_info(place.get("category", ""))
                cat = place.get("category", "")
                reply = (
                    f"🚗 Best transport to {place.get('place_name')}:\n\n"
                    f"{t['icon']} {t['mode']}\n"
                    f"📌 Reason: {t['why']}\n\n"
                    f"📍 Location: {place.get('location','')}, {place.get('district','')}\n"
                    f"🌦️ Best Season: {place.get('best_season','All')}\n"
                    f"\n💡 Tip: Book transport in advance during peak season!"
                )
                if not is_replay:
                    save_history(request.user, msg, reply)
                return JsonResponse({"type": "text", "reply": reply})

    intent = parse_user_intent(msg)

    # Update context (rolling)
    for key in ["season", "crowd", "travel_type", "days"]:
        if intent.get(key):
            ctx[key] = intent[key]
    if not intent.get("broad_tn"):
        # When a NEW location or district is detected, clear the old ones to avoid stale context
        if intent.get("location"):
            ctx["location"] = intent["location"]
            ctx["district"] = None
            ctx["place_name"] = None
        elif intent.get("district"):
            ctx["district"] = intent["district"]
            ctx["location"] = None
            ctx["place_name"] = None
        elif intent.get("place_name"):
            ctx["place_name"] = intent["place_name"]
            ctx["location"] = None
            ctx["district"] = None
        # If force_location_query, clear stale exact place context so district/location wins
        if intent.get("force_location_query"):
            ctx["place_name"] = None
    if intent.get("category"):
        ctx["category"] = intent["category"]

    # SPECIAL FIX: If user typed a specific place name like "velankani church", "dodabetta peak"
    # Only applies when message has a non-category identifying word (e.g. "velankani", "kapaleeshwar")
    # "temple" alone → broad category, NOT a specific place lookup
    if not intent.get("place_name") and not intent.get("location") and not intent.get("district") and not intent.get("broad_tn"):
        _all_cat_words = set()
        for _keys in CATEGORY_MAP.values():
            for _k in _keys:
                _all_cat_words.update(_k.split())
        _non_cat = [w for w in m.split() if w not in _all_cat_words and len(w) >= 3]
        if _non_cat:
            candidate = match_place_name_in_text(msg)
            if candidate:
                intent["place_name"] = candidate


    # 1) Nearby specific place
    if m.startswith("nearby::"):
        place_name = msg.split("::", 1)[1].strip()
        base = find_exact_place(place_name)
        if not base:
            reply = "Couldn't find that place. Try typing the exact name."
            if not is_replay:
                save_history(request.user, msg, reply)
            return JsonResponse({"type": "text", "reply": reply})
        ctx["last_place"] = base
        if not is_replay:
            request.session["chat_ctx_json"] = ctx
        nb = get_nearby_places(base, limit=8)
        html_out = render_cards(nb, user_loc_available,
                                heading=f"Places Near {base.get('place_name')}",
                                travel_type=ctx.get("travel_type"),
                                user_loc=user_loc, days=ctx.get("days") or 1)
        if not is_replay:
            save_history(request.user, msg, f"[nearby: {base.get('place_name')}]")
        return JsonResponse({"type": "html", "html": html_out})

    # 2) Exact place
    if intent.get("place_name") and not intent.get("broad_tn") and not intent.get("force_location_query"):
        exact_place = find_exact_place(intent["place_name"])
        if exact_place:
            ctx["last_place"] = exact_place
            if not is_replay:
                request.session["chat_ctx_json"] = ctx
            base_html = render_cards([exact_place], user_loc_available,
                                     heading=f"{exact_place.get('place_name')} — Details",
                                     travel_type=ctx.get("travel_type"),
                                     user_loc=user_loc, days=ctx.get("days") or 1)
            near_html = render_cards(get_nearby_places(exact_place, limit=6), user_loc_available,
                                     heading=f"Also Near {exact_place.get('place_name')}",
                                     travel_type=ctx.get("travel_type"),
                                     user_loc=user_loc, days=ctx.get("days") or 1)
            if not is_replay:
                save_history(request.user, msg, f"[place: {exact_place.get('place_name')}]")
            return JsonResponse({"type": "html", "html": base_html + near_html})

    # 3) Location-level
    if intent.get("location") and (not intent.get("broad_tn") or intent.get("force_location_query")):
        loc_items = places_by_location(intent["location"])
        if loc_items:
            if intent.get("category"):
                filtered = _apply_category_filter(loc_items, intent["category"])
                loc_items = filtered if filtered else loc_items
            if intent.get("season") and intent["season"] != "All":
                filtered = [p for p in loc_items if intent["season"].lower() in normalize(p.get("best_season", ""))]
                loc_items = filtered if filtered else loc_items
            ctx["location"] = intent["location"]
            ctx["district"] = None
            if not is_replay:
                request.session["chat_ctx_json"] = ctx
            if intent.get("days"):
                html_out = render_itinerary_html(
                    f"{intent['days']} Day Trip in {intent['location']}",
                    loc_items, user_loc_available,
                    days=intent["days"], travel_type=ctx.get("travel_type"), user_loc=user_loc)
                if not is_replay:
                    save_history(request.user, msg, f"[itinerary: {intent['location']}]")
                return JsonResponse({"type": "html", "html": html_out})
            html_out = render_cards(loc_items, user_loc_available,
                                    heading=f"Places in {intent['location']}",
                                    travel_type=ctx.get("travel_type"),
                                    user_loc=user_loc, days=ctx.get("days") or 1)
            if not is_replay:
                save_history(request.user, msg, f"[location: {intent['location']}]")
            return JsonResponse({"type": "html", "html": html_out})

    # 4) District query — return ALL places
    if intent.get("district") and (not intent.get("broad_tn") or intent.get("force_location_query")):
        district_items = places_by_district(intent["district"])
        if district_items:
            if intent.get("category"):
                filtered = _apply_category_filter(district_items, intent["category"])
                district_items = filtered if filtered else district_items
            if intent.get("season") and intent["season"] != "All":
                filtered = [p for p in district_items if intent["season"].lower() in normalize(p.get("best_season", ""))]
                district_items = filtered if filtered else district_items
            if intent.get("crowd"):
                crowd_filtered = []
                for p in district_items:
                    level, _ = dynamic_crowd(p)
                    if intent["crowd"] == "Low" and level in ["Low", "Medium"]:
                        crowd_filtered.append(p)
                    elif intent["crowd"] == "High" and level in ["High", "Very High"]:
                        crowd_filtered.append(p)
                district_items = crowd_filtered if crowd_filtered else district_items
            ctx["district"] = intent["district"]
            ctx["location"] = None
            if not is_replay:
                request.session["chat_ctx_json"] = ctx
            if intent.get("days"):
                html_out = render_itinerary_html(
                    f"{intent['days']} Day Trip in {intent['district']}",
                    district_items, user_loc_available,
                    days=intent["days"], travel_type=ctx.get("travel_type"), user_loc=user_loc)
                if not is_replay:
                    save_history(request.user, msg, f"[itinerary: {intent['district']}]")
                return JsonResponse({"type": "html", "html": html_out})
            html_out = render_cards(district_items, user_loc_available,
                                    heading=f"{intent['district']} — Tourist Places",
                                    travel_type=ctx.get("travel_type"),
                                    user_loc=user_loc, days=ctx.get("days") or 1)
            if not is_replay:
                save_history(request.user, msg, f"[district: {intent['district']}]")
            return JsonResponse({"type": "html", "html": html_out})

    # 5) Nearby (user explicitly asks)
    nearby_triggers = ["nearby places", "near me", "places near me", "close to me",
                       "places nearby", "around me", "what's nearby"]
    if any(t in m for t in nearby_triggers) or m == "nearby":
        if not user_loc_available:
            reply = "Click '📍 Use my location' button to find places near you."
            if not is_replay:
                save_history(request.user, msg, reply)
            return JsonResponse({"type": "text", "reply": reply})
        rows = []
        for p in data:
            if p.get("latitude") and p.get("longitude"):
                try:
                    d = haversine_km(user_loc["lat"], user_loc["lng"], p["latitude"], p["longitude"])
                    if d <= 250:
                        rows.append((d, p))
                except Exception:
                    pass
        rows.sort(key=lambda x: x[0])
        items = [p for _, p in rows[:12]]
        html_out = render_cards(items, user_loc_available, heading="Places Near You",
                                travel_type=ctx.get("travel_type"),
                                user_loc=user_loc, days=ctx.get("days") or 1)
        if not is_replay:
            save_history(request.user, msg, "[nearby from location]")
        return JsonResponse({"type": "html", "html": html_out})

    # 6) Broad TN / filtered recommendation
    results = recommend_places(
        season=intent.get("season") or (ctx.get("season") if not intent.get("broad_tn") else None),
        crowd=intent.get("crowd") or (ctx.get("crowd") if not intent.get("broad_tn") else None),
        district=ctx.get("district") if not intent.get("broad_tn") else None,
        category=intent.get("category") or ctx.get("category"),
        travel_type=ctx.get("travel_type"),
        user_loc=user_loc,
        limit=20,
        broad_tn=intent.get("broad_tn", False),
    )

    if not results:
        results = recommend_places(
            season=None, crowd=None,
            district=None,
            category=intent.get("category"),
            travel_type=ctx.get("travel_type"),
            user_loc=user_loc, limit=20, broad_tn=True)

    if not results:
        reply = "No matching places found. Try a specific district, category, or season!"
        if not is_replay:
            save_history(request.user, msg, reply)
        return JsonResponse({"type": "text", "reply": reply})

    if not is_replay:
        request.session["chat_ctx_json"] = ctx

    # Build heading
    parts = []
    if intent.get("category"):
        parts.append(intent["category"].title() + "s")
    if intent.get("season"):
        parts.append(f"in {intent['season']}")
    if intent.get("crowd") == "Low":
        parts.append("(Low Crowd)")
    elif intent.get("crowd") == "High":
        parts.append("(Popular)")
    if intent.get("travel_type"):
        parts.append(f"for {intent['travel_type']}")
    heading = " ".join(parts) if parts else "Recommended Places"

    if intent.get("days"):
        html_out = render_itinerary_html(
            f"{intent['days']} Day Travel Plan",
            results, user_loc_available,
            days=intent["days"], travel_type=ctx.get("travel_type"), user_loc=user_loc)
        if not is_replay:
            save_history(request.user, msg, f"[{intent['days']} day itinerary]")
        return JsonResponse({"type": "html", "html": html_out})

    html_out = render_cards(results, user_loc_available, heading=heading,
                            travel_type=ctx.get("travel_type"),
                            user_loc=user_loc, days=ctx.get("days") or 1)
    if not is_replay:
        save_history(request.user, msg, f"[results: {heading}]")
    return JsonResponse({"type": "html", "html": html_out})


# ---------------- auth ----------------
def register_view(request):
    # Always show register page — do NOT auto-redirect logged-in users
    # so that a second user can register on same browser
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.set_password(form.cleaned_data["password1"])
        user.save()
        login(request, user)
        return redirect("chatbot")
    return render(request, "tour_app/register.html", {"form": form})


def login_view(request):
    # Always show login page — never auto-redirect
    # so returning users always see the login form
    error = ""
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        # Logout any existing session first
        if request.user.is_authenticated:
            logout(request)
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("chatbot")
        error = "Invalid credentials. Please try again."
    return render(request, "tour_app/login.html", {"error": error})


@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


def is_admin(user):
    return user.is_superuser


@user_passes_test(is_admin, login_url='/api/login/')
def admin_dashboard(request):
    from django.db.models import Max, Count
    from django.utils import timezone
    import datetime
    users_qs = User.objects.annotate(
        chat_count=Count("chathistory"),
        last_chat=Max("chathistory__created")
    ).order_by("-date_joined")
    # Convert to list so we can safely set attributes without re-querying
    users = list(users_qs)
    cutoff = timezone.now() - datetime.timedelta(days=30)
    for u in users:
        u.inactive = (u.last_chat is None or u.last_chat < cutoff)
    total_chats = ChatHistory.objects.count()
    total_users = len(users)
    return render(request, "tour_app/admin_dashboard.html", {
        "users": users,
        "total_chats": total_chats,
        "total_users": total_users,
    })


@user_passes_test(is_admin, login_url='/api/login/')
def delete_user(request, user_id):
    if request.method == "POST":
        try:
            u = User.objects.get(id=user_id)
            if not u.is_superuser:
                u.delete()
        except User.DoesNotExist:
            pass
    return redirect("admin_dashboard")


@login_required
def history_api(request):
    """JSON endpoint for chat history sidebar in chatbot."""
    items = ChatHistory.objects.filter(user=request.user).order_by("-created")[:30]
    return JsonResponse({
        "items": [
            {
                "id": item.id,
                "message": item.message[:60],
                "created": item.created.strftime("%b %d, %H:%M")
            }
            for item in items
        ]
    })