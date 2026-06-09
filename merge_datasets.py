import csv
import json
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOATS_COM_CSV = os.path.join(SCRIPT_DIR, "boats_com_dataset.csv")
BOATDEALERS_CA_CSV = os.path.join(SCRIPT_DIR, "boatdealers_ca_dataset.csv")

OUTPUT_CSV = os.path.join(SCRIPT_DIR, "boats_scraped_dataset.csv")
OUTPUT_JSON = os.path.join(SCRIPT_DIR, "boats_scraped_dataset.json")

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

def format_price(price, source):
    if not price:
        return ""
    price_upper = str(price).upper()
    
    # Determine currency code (default USD for boats.com, CAD for boatdealers.ca)
    currency = "USD" if "boats.com" in source else "CAD"
    if "USD" in price_upper or "US" in price_upper:
        currency = "USD"
    elif "CAD" in price_upper or "CA" in price_upper:
        currency = "CAD"
        
    match = re.search(r'([\d,]+\.?\d*)', str(price))
    if match:
        num_str = match.group(1)
        num_clean = num_str.replace(",", "")
        try:
            val = float(num_clean)
            return f"${val:,.2f} {currency}"
        except (ValueError, TypeError):
            pass
            
    return price

def main():
    print("🔄 Merging datasets...")
    
    combined_records = []
    seen_keys = set()
    
    # Function to add records from a CSV file
    def add_from_csv(csv_path):
        if not os.path.exists(csv_path):
            print(f"⚠️ Warning: File {csv_path} does not exist. Skipping.")
            return
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            count = 0
            for row in reader:
                # Clean fields (strip whitespaces/newlines just in case)
                for k, v in row.items():
                    if isinstance(v, str):
                        row[k] = " ".join(v.split()).strip()
                
                # Format price consistently
                row["price"] = format_price(row.get("price", ""), row.get("source", ""))
                
                # Format length and dimension fields consistently
                row["length_loa"] = format_length(row.get("length_loa", ""))
                row["beam"] = format_length(row.get("beam", ""))
                row["draft"] = format_length(row.get("draft", ""))
                
                key = (row["source"], row["manufacturer"].lower(), row["model_name"].lower(), row["year"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    combined_records.append(row)
                    count += 1
            print(f"✅ Added {count} records from {csv_path}")

    # Add from both sources
    add_from_csv(BOATS_COM_CSV)
    add_from_csv(BOATDEALERS_CA_CSV)
    
    if not combined_records:
        print("❌ No records found to merge!")
        return

    # Ensure parent directories exist
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_CSV)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_JSON)), exist_ok=True)

    # Write merged CSV
    headers = combined_records[0].keys()
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(combined_records)
    print(f"💾 Merged CSV dataset saved to: {OUTPUT_CSV} ({len(combined_records)} total rows)")

    # Write merged JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(combined_records, f, indent=2)
    print(f"💾 Merged JSON dataset saved to: {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
