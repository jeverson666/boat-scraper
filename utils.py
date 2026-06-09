import os
import random
import re
import asyncio

# Attempt to load .env file automatically
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Manual fallback parser for .env to avoid import errors if python-dotenv is not installed
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().strip('"').strip("'")
                        os.environ[key] = val

def get_browser_ws_url(country_code="us", provider=None):
    """
    Generate the WebSocket connection URL for the chosen browser provider.
    Currently supports: 'brightdata' and 'oxylabs'.
    """
    provider = provider or os.getenv("CDP_PROVIDER", "brightdata").lower()
    
    if provider == "brightdata":
        host = os.getenv("BRD_HOST", "brd.superproxy.io")
        port = os.getenv("BRD_PORT", "9222")
        user_base = os.getenv("BRD_USER_BASE", "brd-customer-hl_a1fcaa97-zone-mcp_browser")
        password = os.getenv("BRD_PASS", "on0tw2vl4ru5")
        
        session_id = random.randint(100000, 999999)
        username = f"{user_base}-country-{country_code}-session-{session_id}"
        return f"wss://{username}:{password}@{host}:{port}"
    elif provider == "oxylabs":
        user = os.getenv("OXY_USER", "customer-username")
        password = os.getenv("OXY_PASS", "password")
        return f"wss://realtime.oxylabs.io/v1/co_cdp?customer_id={user}&apiKey={password}&country={country_code}"
    elif provider == "zenrows":
        apikey = os.getenv("ZENROWS_API_KEY", "")
        url = f"wss://browser.zenrows.com?apikey={apikey}"
        if country_code:
            url += f"&proxy_country={country_code}"
        return url
    else:
        # Generic fallback
        return os.getenv("CDP_WS_URL", "")

async def bypass_turnstile_if_present(page, max_wait_sec=30, target_selector=None):
    """
    Monitors the page for Cloudflare or Turnstile challenge page.
    Waits until the challenge is solved by the browser and target_selector (if any) is present.
    """
    print("⏳ Monitoring WAF challenge...")
    challenge_indicators = [
        "just a moment", "un momento", "um momento", "un instant", 
        "einen moment", "tunggu sebentar", "access denied", 
        "security verification", "verify you are human", "cloudflare", 
        "checking your browser", "attention required", "robot", 
        "captcha", "challenge", "chờ một chút", "لحظة", "बस कुछ पल"
    ]
    has_challenge = True
    for i in range(1, (max_wait_sec // 2) + 1):
        await page.wait_for_timeout(2000)
        title = await page.title()
        print(f"  [{i*2}s] Title: '{title}', URL: '{page.url}'")
        title_lower = title.lower() if title else ""
        
        has_challenge = any(indicator in title_lower for indicator in challenge_indicators)
        
        if target_selector:
            try:
                element = await page.query_selector(target_selector)
                if element and not has_challenge:
                    print(f"🎉 Challenge bypassed: '{target_selector}' is present!")
                    return True
            except Exception:
                pass
        else:
            if title and not has_challenge:
                print("🎉 Challenge bypassed/not present!")
                return True
                
    if target_selector:
        try:
            element = await page.query_selector(target_selector)
            if element and not has_challenge:
                print(f"🎉 Challenge bypassed (timed out, but selector '{target_selector}' found)!")
                return True
            elif element and has_challenge:
                print(f"⚠️ Timeout: Selector found but WAF challenge/block page is still active ('{title}').")
        except Exception:
            pass
            
    return False

def update_field_by_label(data, lbl, val):
    """
    Normalize key-value specifications from boat listing pages.
    Updates the 'data' dictionary in-place.
    """
    if not val:
        return
    lbl = lbl.lower().strip().rstrip(":")
    val = " ".join(val.split()).strip()
    
    def clean_prefix(v):
        v_clean = " ".join(v.split()).strip()
        v_lower = v_clean.lower()
        for pfx in ["make:", "type:", "model:", "brand:"]:
            if v_lower.startswith(pfx):
                v_clean = v_clean[len(pfx):].strip()
                v_lower = v_clean.lower()
        return v_clean

    def parse_compound_engine(v, d):
        parts = v.split("|")
        if len(parts) <= 1:
            return False
        matched = False
        for part in parts:
            part = part.strip()
            part_lower = part.lower()
            if "make:" in part_lower or "brand:" in part_lower:
                m = re.sub(r'^(make|brand):\s*', '', part, flags=re.IGNORECASE).strip()
                if m and not d.get("_engine_make"):
                    d["_engine_make"] = m
                    matched = True
            elif "type:" in part_lower:
                t = re.sub(r'^type:\s*', '', part, flags=re.IGNORECASE).strip()
                if t and not d.get("_engine_type"):
                    d["_engine_type"] = t
                    matched = True
            elif "model:" in part_lower:
                mdl = re.sub(r'^model:\s*', '', part, flags=re.IGNORECASE).strip()
                if mdl and not d.get("_engine_model"):
                    d["_engine_model"] = mdl
                    matched = True
        return matched

    if "engine" in lbl and len(val) > 45:
        return

    # Specific/compound terms must be checked before general/single-word terms
    if "engine make" in lbl or "engine brand" in lbl:
        if not data.get("_engine_make"):
            data["_engine_make"] = clean_prefix(val)
    elif "engine type" in lbl:
        if not data.get("_engine_type"):
            data["_engine_type"] = clean_prefix(val)
    elif "engine model" in lbl:
        if not data.get("_engine_model"):
            data["_engine_model"] = clean_prefix(val)
    elif "number of engines" in lbl or "engine count" in lbl or lbl == "engines":
        if not data["number_of_engines"]:
            data["number_of_engines"] = val
    elif "power" in lbl or "hp" in lbl or "horsepower" in lbl:
        if not data["max_hp"]:
            data["max_hp"] = val
    elif "engine" in lbl: # Catch general "Engine" label after power/hp has been checked
        if not parse_compound_engine(val, data):
            cleaned_val = clean_prefix(val)
            if not data.get("_engine_make"):
                data["_engine_make"] = cleaned_val
            elif cleaned_val not in data["_engine_make"] and cleaned_val not in [data.get("_engine_type", ""), data.get("_engine_model", "")]:
                data["_engine_make"] += f" | {cleaned_val}"
    elif "fuel capacity" in lbl or "fuel tank" in lbl or "fuel tanks" in lbl:
        if not data["fuel_capacity"]:
            data["fuel_capacity"] = val
    elif "fuel type" in lbl or lbl == "fuel":
        if not data["fuel_type"]:
            data["fuel_type"] = val
    elif "passenger" in lbl or "person" in lbl or "capacity" in lbl:
        if "fuel" not in lbl and "water" not in lbl:
            if not data["passenger_capacity"]:
                data["passenger_capacity"] = val
    elif ("loa" in lbl or "length" in lbl) and "load" not in lbl and "trailer" not in lbl:
        if not data["length_loa"] or "overall" in lbl or "loa" in lbl or lbl == "length":
            data["length_loa"] = val
    elif "beam" in lbl:
        if not data["beam"]:
            data["beam"] = val
    elif "draft" in lbl:
        if not data["draft"]:
            data["draft"] = val
    elif "weight" in lbl:
        if not data["dry_weight"]:
            data["dry_weight"] = val
    elif "hull" in lbl:
        if not data["hull_material"]:
            data["hull_material"] = val
    elif "price" in lbl or "msrp" in lbl:
        if not data["price"]:
            data["price"] = val
    elif "dealer" in lbl or "seller" in lbl:
        if "location" in lbl or "address" in lbl:
            if not data["dealer_location"]:
                data["dealer_location"] = val
        else:
            if not data["dealer_name"]:
                data["dealer_name"] = val
    elif "location" in lbl:
        if not data["dealer_location"]:
            data["dealer_location"] = val
    elif "make" in lbl or "manufacturer" in lbl or "brand" in lbl:
        if not data["manufacturer"]:
            data["manufacturer"] = val
    elif "model" in lbl:
        if not data["model_name"]:
            data["model_name"] = val
    elif "year" in lbl:
        if not data["year"]:
            data["year"] = val
    elif "class" in lbl or "category" in lbl:
        data["boat_type"] = val
    elif "type" in lbl:
        if not data["boat_type"] or data["boat_type"].lower() in ["power", "sail", "other", "power/sail"]:
            data["boat_type"] = val
def format_length(length_str):
    if not length_str:
        return ""
    length_str = " ".join(length_str.split()).strip()
    
    # 1. Inches only (e.g. 102", 60 in, 96 inch, 102in)
    match_inches = re.search(r'^(\d+(?:\.\d+)?)\s*(?:in|inch|inches|")\s*$', length_str, re.IGNORECASE)
    if match_inches:
        try:
            val_in = float(match_inches.group(1))
            val_ft = val_in / 12.0
            if val_in % 12 == 0:
                return str(int(val_ft))
            feet = int(val_in // 12)
            inches = round(val_in % 12, 1)
            if inches.is_integer():
                inches = int(inches)
            if inches == 0:
                return str(feet)
            return f"{feet}'{inches}"
        except Exception:
            pass

    # 2. Feet and inches (e.g. 25' 6", 25 ft 6 in, 25' 6, 76 ft 3 in)
    match_ft_in = re.search(r"(\d+)\s*(?:'|ft|feet)\s*(\d+(?:\.\d+)?)\s*(?:\"|in|inches|'')?", length_str, re.IGNORECASE)
    if match_ft_in:
        inches = float(match_ft_in.group(2))
        if inches.is_integer():
            inches = int(inches)
        return f"{match_ft_in.group(1)}'{inches}"
    
    # 3. Decimal feet (e.g. 16.6, 16.6 ft, 16.6')
    match_decimal = re.search(r'^(\d+\.\d+)\s*(?:ft|m|feet|\'|\")?$', length_str, re.IGNORECASE)
    if match_decimal:
        return match_decimal.group(1)
        
    # 4. Pure feet (e.g. 16 ft, 16 feet, 16', 38 ft)
    match_pure = re.search(r'^(\d+)\s*(?:ft|feet|\'|\"|ft)?$', length_str, re.IGNORECASE)
    if match_pure:
        return match_pure.group(1)
        
    return length_str

def clean_engine_make_type(val):
    """
    Clean and format the compiled engine_make_type field.
    """
    if not val:
        return ""
    parts = val.split("|")
    cleaned_parts = []
    seen = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_clean = part
        while True:
            match = re.match(r'^(type|make|model|brand|engine|engines):\s*(.*)$', part_clean, re.IGNORECASE)
            if match:
                part_clean = match.group(2).strip()
            else:
                break
        if not part_clean:
            continue
        if len(part_clean) > 45:
            continue
        if part_clean.isdigit():
            continue
        if part_clean.lower() == "yahma":
            part_clean = "Yamaha"
        part_lower = part_clean.lower()
        if part_lower not in seen:
            seen.add(part_lower)
            cleaned_parts.append(part_clean)
    return " | ".join(cleaned_parts)

def parse_from_url(url):
    """
    Fallback parser to extract manufacturer, model, and year from the listing URL.
    Works for both boatdealers.ca and boats.com URL patterns.
    """
    parsed_manufacturer = ""
    parsed_model = ""
    parsed_year = ""
    try:
        from urllib.parse import urlparse
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        
        if "boatdealers.ca" in url:
            if len(parts) >= 2:
                # e.g., /boats-for-sale/592617/bavaria-s36-ht-gatineau-quebec
                slug = parts[-1]
                words = slug.split("-")
                if len(words) >= 2:
                    parsed_manufacturer = words[0].title()
                    parsed_model = " ".join(words[1:]).title()
        elif "boats.com" in url:
            if len(parts) >= 2 and parts[0] == "boats":
                # e.g., /boats/cruisers-yachts/42-cantius-9937800/
                parsed_manufacturer = parts[1].replace("-", " ").title()
                model_part = parts[2]
                model_part = re.sub(r"-\d+$", "", model_part)
                parsed_model = model_part.replace("-", " ").title()
            elif len(parts) >= 2 and parts[0] in ["power-boats", "sailing-boats", "boats-for-sale"]:
                # e.g., /power-boats/2007-regal-commodore-3760-ib-10104022/
                slug = parts[1]
                slug = re.sub(r"-\d+$", "", slug)
                match_year = re.search(r"\b(19\d\d|20\d\d)\b", slug)
                if match_year:
                    parsed_year = match_year.group(1)
                    slug = slug.replace(parsed_year, "").strip("-")
                words = slug.split("-")
                if words:
                    parsed_manufacturer = words[0].title()
                    parsed_model = " ".join(words[1:]).title()
    except Exception as e:
        print(f"Error in URL fallback parsing: {e}")
    return parsed_manufacturer, parsed_model, parsed_year
