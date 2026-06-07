import csv
import json
import os

BOATS_COM_CSV = "/workspaces/trheads/boats_com_dataset.csv"
BOATDEALERS_CA_CSV = "/workspaces/trheads/boatdealers_ca_dataset.csv"

OUTPUT_CSV = "/workspaces/trheads/boats_scraped_dataset.csv"
OUTPUT_JSON = "/workspaces/trheads/boats_scraped_dataset.json"

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
