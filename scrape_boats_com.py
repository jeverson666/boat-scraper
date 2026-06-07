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

BOATS_COM_SEARCH_URL = "https://www.boats.com/boats-for-sale/"

def parse_detail_page(html, url, source):
    """
    Parses a single boat detail page from boats.com.
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
                
                if make_match and not data["manufacturer"]:
                    data["manufacturer"] = make_match.group(1).strip()
                if model_match and (not data["model_name"] or "boat for sale" in data["model_name"].lower()):
                    data["model_name"] = model_match.group(1).strip()
                if year_match and not data["year"]:
                    data["year"] = year_match.group(1).strip()
                if length_match and not data["length_loa"]:
                    data["length_loa"] = length_match.group(1).strip() + " ft"
                    
                city = city_match.group(1).strip() if city_match else ""
                prov = prov_match.group(1).strip() if prov_match else ""
                if city or prov:
                    loc_parts = [p for p in [city, prov] if p]
                    if not data["dealer_location"]:
                        data["dealer_location"] = ", ".join(loc_parts)
            except Exception:
                pass

    # 3. Parse HTML Tables
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

    # 3b. Parse Description Lists (<dl>, .description-list__row)
    for row in soup.find_all(class_="description-list__row"):
        dt = row.find(class_="description-list__term") or row.find("dt")
        dd = row.find(class_="description-list__description") or row.find("dd")
        if dt and dd:
            lbl = dt.get_text(strip=True)
            val = dd.get_text(strip=True)
            update_field_by_label(data, lbl, val)

    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        if len(dts) == len(dds):
            for dt, dd in zip(dts, dds):
                lbl = dt.get_text(strip=True)
                val = dd.get_text(strip=True)
                update_field_by_label(data, lbl, val)

    # 4. Parse HTML List Items
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        if ":" in text:
            parts = text.split(":", 1)
            lbl = parts[0].strip()
            val = parts[1].strip()
            if len(lbl) < 30:
                update_field_by_label(data, lbl, val)

    # 5. Parse Description text & inline Bold Tag Specs
    desc_div = (
        soup.find("div", class_="desc-text") or 
        soup.find("div", class_="oem-model-description") or 
        soup.find("section", class_="boat-description") or 
        soup.find(id="description") or
        soup.find(id="desc")
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
                    if not data["manufacturer"]:
                        data["manufacturer"] = words[0]
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
    print("🕷️ Starting Playwright Scraper for boats.com...")
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
                url = BOATS_COM_SEARCH_URL if page_num == 1 else f"{BOATS_COM_SEARCH_URL}?page={page_num}"
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
                        if "/explore/" in href or "/directory/" in href or "/articles/" in href:
                            continue
                        if (
                            ("/boats/" in href or "/power-boats/" in href or "/sailing-boats/" in href) 
                            and (re.search(r"-\d+/?$", href) or re.search(r"/\d+/?$", href))
                        ):
                            full_url = href if href.startswith("http") else f"https://www.boats.com{href}"
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
        print(f"\nTotal boats.com detail links found: {len(detail_links)}.")
        print(f"Scraping top {target_limit} listing details...")
    else:
        links_to_scrape = detail_links
        print(f"\nTotal boats.com detail links found: {len(detail_links)}.")
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
                        
                    await page.wait_for_timeout(3000)
                    
                    # Try to expand hidden specs by clicking all "Show More" buttons/toggles
                    try:
                        show_more_locs = page.locator("a:has-text('Show More'), button:has-text('Show More'), .show-more__toggle, .toggle-more")
                        count = await show_more_locs.count()
                        for i in range(count):
                            el = show_more_locs.nth(i)
                            if await el.is_visible():
                                try:
                                    await el.scroll_into_view_if_needed(timeout=2000)
                                    await el.click(timeout=3000)
                                    await page.wait_for_timeout(1000)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                        
                    detail_html = await page.content()
                    boat_data = parse_detail_page(detail_html, url, "boats.com")
                    
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
            
        print(f"\n📝 Summary Note: Scraped {total} total unique record(s) from boats.com.")
    else:
        print("\n⚠️ No data was scraped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper for boats.com")
    parser.add_argument("--pages", type=int, default=2, help="Number of search pages to parse")
    parser.add_argument("--limit", type=int, default=0, help="Number of detail pages to scrape per search page (0 to scrape all found links)")
    parser.add_argument("--csv", type=str, default="/workspaces/trheads/boats_com_dataset.csv", help="Path to save output CSV")
    parser.add_argument("--json", type=str, default="/workspaces/trheads/boats_com_dataset.json", help="Path to save output JSON")
    parser.add_argument("--country", type=str, default="us", help="Bright Data session country code (e.g. us, ca)")
    
    args = parser.parse_args()
    asyncio.run(main(args.pages, args.limit, args.csv, args.json, args.country))
