import asyncio
import csv
import json
import os
import re
import argparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Import shared helpers from utils.py
from utils import (
    get_browser_ws_url,
    bypass_turnstile_if_present,
    update_field_by_label,
    clean_engine_make_type,
    parse_from_url
)

BOATDEALERS_CA_SEARCH_URL = "https://www.boatdealers.ca/boats-for-sale"

def parse_detail_page(html, url, source):
    """
    Parses a single boat detail page from boatdealers.ca.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    data = {
        "source": source,
        "manufacturer": "",
        "model_name": "",
        "year": "",
        "boat_type": "",
        "length_loa": "",
        "beam": "",
        "draft": "",
        "dry_weight": "",
        "hull_material": "",
        "max_hp": "",
        "engine_make_type": "",
        "_engine_make": "",
        "_engine_type": "",
        "_engine_model": "",
        "number_of_engines": "",
        "fuel_type": "",
        "fuel_capacity": "",
        "passenger_capacity": "",
        "price": "",
        "dealer_name": "",
        "dealer_location": "",
        "source_listing_url": url,
        "description": ""
    }
    
    # 1. Parse JSON-LD Schema
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            content = script.string.strip() if script.string else ""
            if not content:
                continue
            item = json.loads(content)
            nodes = item if isinstance(item, list) else [item]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                t = node.get("@type", "")
                if t in ["Product", "Vehicle", "Boat"]:
                    name_val = node.get("Name") or node.get("name")
                    if name_val and (not data["model_name"] or "boat for sale" in data["model_name"].lower()):
                        data["model_name"] = name_val
                    if node.get("brand"):
                        brand = node.get("brand")
                        data["manufacturer"] = brand.get("name") if isinstance(brand, dict) else brand
                    if node.get("description"):
                        data["description"] = node.get("description")
                    if node.get("offers"):
                        offers = node.get("offers")
                        if isinstance(offers, dict):
                            data["price"] = offers.get("price") or offers.get("lowPrice")
                            curr = offers.get("priceCurrency", "")
                            if data["price"] and curr:
                                data["price"] = f"{curr} {data['price']}"
                            seller = offers.get("seller")
                            if isinstance(seller, dict) and seller.get("name"):
                                data["dealer_name"] = seller.get("name")
                            loc = offers.get("availableAtOrFrom")
                            if isinstance(loc, dict) and loc.get("address"):
                                addr = loc.get("address")
                                if isinstance(addr, dict):
                                    city = addr.get("addressLocality")
                                    region = addr.get("addressRegion")
                                    if city or region:
                                        data["dealer_location"] = ", ".join([p for p in [city, region] if p])
        except Exception:
            pass

    # 2. Parse dataLayer Scripts
    for script in soup.find_all("script"):
        content = script.string
        if content and "dataLayer" in content:
            try:
                make_match = re.search(r"['\"]Make['\"]\s*:\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
                model_match = re.search(r"['\"]Model['\"]\s*:\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
                year_match = re.search(r"['\"]Year['\"]\s*:\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
                city_match = re.search(r"['\"]City['\"]\s*:\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
                prov_match = re.search(r"['\"]Province['\"]\s*:\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
                length_match = re.search(r"['\"]Length['\"]\s*:\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
                type_match = re.search(r"['\"](?:BoatType|Type|Category)['\"]\s*:\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
                
                if make_match and not data["manufacturer"]:
                    data["manufacturer"] = make_match.group(1).strip()
                if model_match and (not data["model_name"] or "boat for sale" in data["model_name"].lower()):
                    data["model_name"] = model_match.group(1).strip()
                if year_match and not data["year"]:
                    data["year"] = year_match.group(1).strip()
                if length_match and not data["length_loa"]:
                    raw_len = length_match.group(1).strip()
                    # Fix #3: skip junk "0" values for length
                    if raw_len and raw_len != "0" and raw_len != "0.0":
                        data["length_loa"] = raw_len + " ft"
                if type_match and not data["boat_type"]:
                    data["boat_type"] = type_match.group(1).strip()
                    
                city = city_match.group(1).strip() if city_match else ""
                prov = prov_match.group(1).strip() if prov_match else ""
                if city or prov:
                    loc_parts = [p for p in [city, prov] if p]
                    if not data["dealer_location"]:
                        data["dealer_location"] = ", ".join(loc_parts)
            except Exception:
                pass

    # 2b. Extract boat_type from breadcrumb navigation (most reliable source on boatdealers.ca)
    if not data["boat_type"]:
        for nav in soup.find_all(["nav", "ol", "ul"], class_=re.compile(r'breadcrumb', re.IGNORECASE)):
            crumbs = [a.get_text(strip=True) for a in nav.find_all("a")]
            # boatdealers.ca breadcrumb: Home > Boats For Sale > [Type] > [Make] > ...
            skip_words = {"home", "boats for sale", "bateaux à vendre", "bateaux a vendre", ""}
            for crumb in crumbs:
                if crumb.lower() not in skip_words and len(crumb) < 40:
                    data["boat_type"] = crumb
                    break

    # 2c. Extract boat_type from <meta> keywords or description
    if not data["boat_type"]:
        meta_kw = soup.find("meta", attrs={"name": "keywords"})
        if meta_kw and meta_kw.get("content"):
            kw_content = meta_kw["content"]
            type_kw_match = re.search(
                r'\b(bowrider|pontoon|center console|cuddy|runabout|walkaround|express cruiser|'
                r'deck boat|fishing|sailboat|catamaran|inflatable|jet boat|ski boat|'
                r'aluminum|bass boat|bay boat|cruiser|yacht|dinghy|canoe|kayak|'
                r'personal watercraft|pwc|houseboat|trawler|power boat|powerboat)\b',
                kw_content, re.IGNORECASE
            )
            if type_kw_match:
                data["boat_type"] = type_kw_match.group(1).title()

    # 3. Parse Specifications Container (id='specs')
    specs_container = soup.find(id="specs")
    if specs_container:
        # A. Look for definition lists inside specs container
        for dl in specs_container.find_all("dl"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            if len(dts) == len(dds):
                for dt, dd in zip(dts, dds):
                    lbl = dt.get_text(strip=True)
                    val = dd.get_text(strip=True)
                    update_field_by_label(data, lbl, val)
                    
        # B. Look for tables inside specs container
        for table in specs_container.find_all("table"):
            for tr in table.find_all("tr"):
                th = tr.find(["th", "td"])
                tds = tr.find_all("td")
                if th and len(tds) > 0:
                    lbl = th.get_text(strip=True)
                    val = tds[-1].get_text(strip=True)
                    update_field_by_label(data, lbl, val)
                elif len(tds) >= 2:
                    lbl = tds[0].get_text(strip=True)
                    val = tds[1].get_text(strip=True)
                    update_field_by_label(data, lbl, val)
                    
        # C. Look for list items inside specs container
        for li in specs_container.find_all("li"):
            text = li.get_text(strip=True)
            if ":" in text:
                parts = text.split(":", 1)
                lbl = parts[0].strip()
                val = parts[1].strip()
                if len(lbl) < 30:
                    update_field_by_label(data, lbl, val)
                    
        # D. Look for bootstrap-like key-value rows inside specs container
        for row in specs_container.find_all(class_=re.compile(r'row|spec-item|detail-row', re.IGNORECASE)):
            for b in row.find_all("b"):
                lbl = b.get_text(strip=True).rstrip(":")
                sibling = b.next_sibling
                val = sibling.strip() if sibling and isinstance(sibling, str) else ""
                if not val and b.next_sibling:
                    val = b.next_sibling.get_text(strip=True)
                if len(lbl) < 30 and val:
                    update_field_by_label(data, lbl, val)
    else:
        # Fallback to general tables and list items if #specs container is absent
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                th = tr.find(["th", "td"])
                tds = tr.find_all("td")
                if th and len(tds) > 0:
                    lbl = th.get_text(strip=True)
                    val = tds[-1].get_text(strip=True)
                    update_field_by_label(data, lbl, val)
                elif len(tds) >= 2:
                    lbl = tds[0].get_text(strip=True)
                    val = tds[1].get_text(strip=True)
                    update_field_by_label(data, lbl, val)

        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if ":" in text:
                parts = text.split(":", 1)
                lbl = parts[0].strip()
                val = parts[1].strip()
                if len(lbl) < 30:
                    update_field_by_label(data, lbl, val)

    # 3e. Dedicated Class/boat_type extraction — handles label+value as sibling elements
    # (e.g., boatdealers.ca renders "Class" and "Cruisers" in adjacent <span>/<td> without colon)
    if not data["boat_type"]:
        # Pattern A: Look for any element whose text is exactly "Class" or "Classe",
        # then grab the next sibling element's text as the value
        for tag in soup.find_all(["span", "div", "td", "dt", "th", "strong", "b", "label"]):
            tag_text = tag.get_text(strip=True)
            if tag_text.lower() in ("class", "classe", "boat class", "class:", "classe:"):
                # Try next sibling element
                sibling = tag.find_next_sibling()
                if sibling:
                    val = sibling.get_text(strip=True)
                    if val and len(val) < 50 and val.lower() not in ("class", "classe"):
                        data["boat_type"] = val
                        break
                # Try parent's next sibling (for dt/dd pattern)
                if not data["boat_type"] and tag.parent:
                    parent_sibling = tag.parent.find_next_sibling()
                    if parent_sibling:
                        val = parent_sibling.get_text(strip=True)
                        if val and len(val) < 50:
                            data["boat_type"] = val
                            break

        # Pattern B: Look for any element containing "Class" + value concatenated
        # e.g., <span>ClassCruisers</span> or <li>Class: Cruisers</li>
        if not data["boat_type"]:
            for tag in soup.find_all(["span", "li", "td", "p"]):
                text = tag.get_text(strip=True)
                # Match "Class" followed immediately by value (no space or colon)
                class_concat = re.match(r'^[Cc]lasse?\s*:?\s*([A-Za-z\u00C0-\u00ff][A-Za-z\u00C0-\u00ff\s\-]{1,40})$', text)
                if class_concat:
                    val = class_concat.group(1).strip()
                    if val.lower() not in ("class", "classe"):
                        data["boat_type"] = val
                        break

    # 4. Parse Description text & inline Bold Tag Specs
    desc_div = (
        soup.find(id="desc") or
        soup.find(id="description") or
        soup.find("div", class_="desc-text") or 
        soup.find("div", class_="oem-model-description") or 
        soup.find("section", class_="boat-description")
    )
    if desc_div:
        for b in desc_div.find_all("b"):
            lbl = b.get_text(strip=True)
            sibling = b.next_sibling
            val = sibling.strip() if sibling and isinstance(sibling, str) else ""
            if not val and b.next_sibling:
                val = b.next_sibling.get_text(strip=True)
            update_field_by_label(data, lbl, val)
            
        # Parse a clean version of the description text (without UI buttons/links/etc)
        desc_soup = BeautifulSoup(str(desc_div), "html.parser")
        for tag in desc_soup.find_all(["a", "button", "script", "style"]):
            tag.decompose()
        for tag in desc_soup.find_all(class_=lambda c: c and any(x in " ".join(c).lower() for x in ["button", "modal", "share", "social", "contact", "gallery"])):
            tag.decompose()
            
        desc_text = desc_soup.get_text(separator=" ").strip()
        desc_text = " ".join(desc_text.split())
        if desc_text.lower().startswith("description"):
            desc_text = desc_text[len("description"):].strip()
        data["description"] = desc_text

    # 6. Parse Seller Info fallback
    seller_div = soup.find("div", class_="seller-info") or soup.find("div", class_="dealer-info")
    if seller_div:
        h3 = seller_div.find("h3")
        if h3:
            if not data["dealer_name"]:
                data["dealer_name"] = h3.get_text(strip=True)
        else:
            if not data["dealer_name"]:
                data["dealer_name"] = seller_div.get_text(strip=True)
            
    # Clean up fields
    for k, v in data.items():
        if isinstance(v, str):
            data[k] = " ".join(v.split()).strip()

    # Fix #3: Remove junk "0 ft" length values — treat as empty
    if data.get("length_loa"):
        stripped_len = data["length_loa"].strip()
        if re.match(r'^0(\.0+)?\s*(ft|m|feet|metres?)?$', stripped_len, re.IGNORECASE):
            data["length_loa"] = ""

    # Title parsing fallback
    title_tag = soup.title
    if title_tag:
        title_text = title_tag.get_text(strip=True)
        match_year = re.search(r"\b(19\d\d|20\d\d)\b", title_text)
        if match_year:
            year_val = match_year.group(1)
            if not data["year"]:
                data["year"] = year_val
            
            title_clean = title_text.replace("for sale", "").replace("For Sale", "")
            title_clean = title_clean.split("-")[0].split("|")[0].strip()
            parts = title_clean.split(year_val, 1)
            if len(parts) > 0 and parts[0].strip():
                before_year = parts[0].strip()
                words = before_year.split()
                if words:
                    candidate = words[0]
                    # Fix #2: Reject junk manufacturers — must be a plain word (no digits/quotes/apostrophes/dimensions)
                    if re.match(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]{1,30}$", candidate):
                        if not data["manufacturer"]:
                            data["manufacturer"] = candidate
                    if not data["model_name"] or "boat for sale" in data["model_name"].lower():
                        data["model_name"] = " ".join(words[1:])
 
    # URL Fallback
    if not data["manufacturer"] or not data["model_name"]:
        parsed_mfg, parsed_mdl, parsed_yr = parse_from_url(url)
        if not data["manufacturer"] and parsed_mfg:
            data["manufacturer"] = parsed_mfg
        if not data["model_name"] and parsed_mdl:
            data["model_name"] = parsed_mdl
        if not data["year"] and parsed_yr:
            data["year"] = parsed_yr

    # 7. Apply Regex Fallbacks on Description for missing fields
    if data["description"]:
        desc_lower = data["description"].lower()
        
        # 7a. Extract Number of Engines
        if not data["number_of_engines"]:
            if re.search(r'\b(twin|double|2\s?x)\b[^.!?]{1,100}\b(engine|motor|outboard|inboard|drive|propulsion|hp|horsepower|mercury|yamaha|suzuki|honda|volvo|mercruiser|crusader|cummins|perkins)s?\b', desc_lower):
                data["number_of_engines"] = "2"
            elif re.search(r'\b(triple|3\s?x)\b[^.!?]{1,100}\b(engine|motor|outboard|inboard|drive|propulsion|hp|horsepower|mercury|yamaha|suzuki|honda|volvo|mercruiser|crusader|cummins|perkins)s?\b', desc_lower):
                data["number_of_engines"] = "3"
            elif re.search(r'\b(quad|4\s?x)\b[^.!?]{1,100}\b(engine|motor|outboard|inboard|drive|propulsion|hp|horsepower|mercury|yamaha|suzuki|honda|volvo|mercruiser|crusader|cummins|perkins)s?\b', desc_lower):
                data["number_of_engines"] = "4"
            elif re.search(r'\b(single|1\s?x)\b[^.!?]{1,100}\b(engine|motor|outboard|inboard|drive|propulsion|hp|horsepower|mercury|yamaha|suzuki|honda|volvo|mercruiser|crusader|cummins|perkins)s?\b', desc_lower):
                data["number_of_engines"] = "1"
                
        # 7b. Extract Draft
        if not data["draft"]:
            draft_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:\'|foot|feet|ft)?\s*draft\b', data["description"], re.IGNORECASE)
            if draft_match:
                data["draft"] = draft_match.group(1) + " ft"
                
        # 7c. Extract Passenger Capacity
        if not data["passenger_capacity"]:
            pass_match = re.search(r'\b(\d+)\s*(?:people|person|passenger|pax)\s*(?:max|capacity)?\b', data["description"], re.IGNORECASE)
            if pass_match:
                data["passenger_capacity"] = pass_match.group(1)

        # 7d. Fix #2: Extract manufacturer from French description ("Marque : Lavy", "Marque: SomeBrand")
        if not data["manufacturer"]:
            marque_match = re.search(r'(?:Marque|Make|Fabricant)\s*:\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-]{1,30}?)(?:\s*[|\n,]|$)', data["description"], re.IGNORECASE)
            if marque_match:
                data["manufacturer"] = marque_match.group(1).strip()

        # 7e. Extract boat_type from description if still missing
        if not data["boat_type"]:
            type_desc_match = re.search(
                r'\b(bowrider|pontoon|center console|centre console|cuddy cabin|runabout|'
                r'walkaround|express cruiser|deck boat|bass boat|bay boat|'
                r'ski boat|jet boat|aluminum fishing|fishing boat|sailboat|catamaran|'
                r'cruiser|yacht|houseboat|trawler|inflatable|pwc|personal watercraft)\b',
                data["description"], re.IGNORECASE
            )
            if type_desc_match:
                data["boat_type"] = type_desc_match.group(1).title()

    # Compile engine_make_type cleanly
    parts = []
    if data.get("_engine_make"):
        parts.append(data["_engine_make"])
    if data.get("_engine_type"):
        parts.append(data["_engine_type"])
    if data.get("_engine_model"):
        parts.append(data["_engine_model"])
        
    data["engine_make_type"] = clean_engine_make_type(" | ".join(parts))
    
    # Remove temporary helper fields
    data.pop("_engine_make", None)
    data.pop("_engine_type", None)
    data.pop("_engine_model", None)

    # Clean model_name redundancy
    if data.get("model_name"):
        model_name = data["model_name"]
        mfg = data.get("manufacturer")
        if mfg:
            model_name = re.sub(rf"\b{re.escape(mfg)}\b", "", model_name, flags=re.IGNORECASE)
        yr = data.get("year")
        if yr:
            model_name = re.sub(rf"\b{re.escape(yr)}\b", "", model_name)
        model_name = re.sub(r"\s+", " ", model_name)
        model_name = model_name.strip(" ,-–—/")
        data["model_name"] = model_name

    # Final cleanup of all string fields
    for k, v in data.items():
        if isinstance(v, str):
            data[k] = " ".join(v.split()).strip()

    return data

async def main(max_pages, limit_per_page, csv_path, json_path, country):
    print("🕷️ Starting Playwright Scraper for boatdealers.ca...")
    print("=" * 70)
    print(f"Configuration:")
    print(f"  - Max search pages to scan: {max_pages}")
    print(f"  - Target detail limit: {max_pages * limit_per_page}")
    print(f"  - Output files: {csv_path} and {json_path}")
    print(f"  - Country session: {country.upper()}")
    print("-" * 70)
    
    scraped_dataset = []
    detail_links = []
    
    # Step 1: Connect to browser to extract detail page links
    ws_url = get_browser_ws_url(country)
    async with async_playwright() as p:
        print(f"🌐 Connecting to CDP browser to fetch search pages...")
        try:
            browser = await p.chromium.connect_over_cdp(ws_url)
            context = await browser.new_context()
            page = await context.new_page()
            
            for page_num in range(1, max_pages + 1):
                url = BOATDEALERS_CA_SEARCH_URL if page_num == 1 else f"{BOATDEALERS_CA_SEARCH_URL}?page={page_num}"
                print(f"🚤 Navigating to search page {page_num}: {url}")
                try:
                    await page.goto(url, wait_until="commit", timeout=60000)
                    await bypass_turnstile_if_present(page)
                    print("Waiting 5s for search items to render...")
                    await page.wait_for_timeout(5000)
                    
                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    
                    page_links = []
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if re.search(r"/boats-for-sale/\d+", href):
                            full_url = href if href.startswith("http") else f"https://www.boatdealers.ca{href}"
                            if full_url not in detail_links and full_url not in page_links:
                                page_links.append(full_url)
                                
                    print(f"  Found {len(page_links)} detail links on page {page_num}.")
                    detail_links.extend(page_links)
                except Exception as e:
                    print(f"  ❌ Error fetching search page {page_num}: {e}")
            await browser.close()
        except Exception as e:
            print(f"❌ Error during search link extraction: {e}")
            
    if not detail_links:
        print("⚠️ No detail links found to scrape!")
        return

    # Step 2: Scrape each detail page using a fresh browser session
    if limit_per_page > 0:
        target_limit = max_pages * limit_per_page
        links_to_scrape = detail_links[:target_limit]
        print(f"\nTotal boatdealers.ca detail links found: {len(detail_links)}.")
        print(f"Scraping top {target_limit} listing details...")
    else:
        links_to_scrape = detail_links
        print(f"\nTotal boatdealers.ca detail links found: {len(detail_links)}.")
        print(f"Scraping all {len(links_to_scrape)} listing details...")
        
    total_to_scrape = len(links_to_scrape)
    async with async_playwright() as p:
        for idx, url in enumerate(links_to_scrape):
            print(f" [{idx+1}/{total_to_scrape}] Scraping: {url} ...")
            fresh_ws_url = get_browser_ws_url(country)
            try:
                browser = await p.chromium.connect_over_cdp(fresh_ws_url)
                context = await browser.new_context()
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="commit", timeout=60000)
                    success = await bypass_turnstile_if_present(page)
                    if not success:
                        print("   ⚠️ Failed to bypass WAF. Skipping...")
                        continue
                        
                    if "/login" in page.url:
                        print("   ⚠️ Blocked by login wall! Skipping...")
                        continue
                        
                    await page.wait_for_timeout(3000)
                    detail_html = await page.content()
                    boat_data = parse_detail_page(detail_html, url, "boatdealers.ca")
                    
                    if not boat_data["manufacturer"] and not boat_data["model_name"]:
                        print("   ⚠️ Parsed data is empty. Skipping...")
                        continue
                        
                    scraped_dataset.append(boat_data)
                    print(f"   Saved: {boat_data['manufacturer']} {boat_data['model_name']} ({boat_data['year']})")
                except Exception as e:
                    print(f"   ❌ Error during detail page scrape: {e}")
                finally:
                    await browser.close()
            except Exception as e:
                print(f"   ❌ Failed to connect to browser session: {e}")
        print("🔒 CDP connection closed.")

    # Deduplicate and Export
    if scraped_dataset:
        print("\n🔄 Deduplicating records...")
        unique_records = {}
        for r in scraped_dataset:
            key = (r["source"], r["manufacturer"].lower(), r["model_name"].lower(), r["year"])
            if key not in unique_records:
                unique_records[key] = r
            else:
                exist_len = len([v for v in unique_records[key].values() if v])
                new_len = len([v for v in r.values() if v])
                if new_len > exist_len:
                    unique_records[key] = r
                    
        final_list = list(unique_records.values())
        print(f"Reduced dataset from {len(scraped_dataset)} to {len(final_list)} unique records.")
        
        # Fix #4: Ensure 'year' is exported as plain integer string (no decimal like 2018.0)
        for record in final_list:
            yr = record.get("year", "")
            if yr:
                try:
                    record["year"] = str(int(float(str(yr))))
                except (ValueError, TypeError):
                    pass

        # Save CSV
        headers = final_list[0].keys()
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            writer = csv.DictWriter(cf, fieldnames=headers)
            writer.writeheader()
            writer.writerows(final_list)
            
        # Save JSON
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(final_list, jf, indent=2)
            
        print(f"💾 CSV dataset saved to: {csv_path}")
        print(f"💾 JSON dataset saved to: {json_path}")
        
        # Sparsity Analysis
        print("\n📊 Column Sparsity Analysis:")
        total = len(final_list)
        for col in headers:
            empty = len([r for r in final_list if not r[col]])
            pct = (empty / total) * 100
            print(f"  - {col}: {pct:.1f}% empty ({empty}/{total})")
            
        print(f"\n📝 Summary Note: Scraped {total} total unique record(s) from boatdealers.ca.")
    else:
        print("\n⚠️ No data was scraped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper for boatdealers.ca")
    parser.add_argument("--pages", type=int, default=2, help="Number of search pages to parse")
    parser.add_argument("--limit", type=int, default=0, help="Number of detail pages to scrape per search page (0 to scrape all found links)")
    parser.add_argument("--csv", type=str, default="/workspaces/trheads/boatdealers_ca_dataset.csv", help="Path to save output CSV")
    parser.add_argument("--json", type=str, default="/workspaces/trheads/boatdealers_ca_dataset.json", help="Path to save output JSON")
    parser.add_argument("--country", type=str, default="ca", help="Bright Data session country code (e.g. ca, us)")
    
    args = parser.parse_args()
    asyncio.run(main(args.pages, args.limit, args.csv, args.json, args.country))
