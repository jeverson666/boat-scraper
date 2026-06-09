# 🚤 Boat Web Scraper (AI-Assisted Project)

This project is a tool that automatically collects boat listing information from **boats.com** and **boatdealers.ca** and merges them into a single, clean Excel/CSV file. 

This project was built entirely using **AI-Assisted Development (AI Pair Programming)**.

---

## 💡 How I Built This (Without Coding Experience)
**I do not write programming code manually.** Instead, I managed this project as the **Product Owner & AI Operator**:
1. **Designing the Logic**: I defined the goals of the project—what data to extract (price, length, capacity, etc.) and how the final spreadsheet should look.
2. **Guiding the AI**: I used advanced AI tools to generate the Python scripts and explained exactly how the scraper should behave.
3. **Problem Solving & Testing**: When the script ran into real-world issues (like being blocked by website security or missing data fields), I analyzed the errors and instructed the AI on how to fix them (e.g., adding retry systems and scanning written descriptions for missing numbers).

---

## 🔍 What This Tool Does & How It Works (Simplified)
Even though this project was guided by a non-coder, it has powerful features that solve real web scraping problems:

1. **Bypasses Security Screens (Anti-Blocking)**: 
   Many websites use security screens (Cloudflare/Turnstile) to block scrapers. This tool connects to proxy networks and automatically waits for the browser to solve these security checks so it can read the pages successfully.
2. **Recovers Missing Data (Smart Fallbacks)**: 
   Sometimes, a boat listing has blank specifications. The script is smart—it reads the written paragraph description of the boat, uses text matching to find missing details (like passenger capacity, engine count, or draft), and fills in the blanks.
3. **Standardizes Formats**: 
   It cleans up messy data. For example, it automatically converts different dimension formats (like `102"`, `60 in`, or `16.6 ft`) into standard feet'inches (like `8'6` or `25'6`) and formats all prices consistently.
4. **Merges & Cleans the Data**: 
   It combines the results from both websites, deletes any duplicate listings, and saves them into a single clean spreadsheet (`boats_scraped_dataset.csv`).

---

## 📂 File Structure

*   `scrape_boatdealers_ca.py`: Collects data from boatdealers.ca.
*   `scrape_boats_com.py`: Collects data from boats.com.
*   `utils.py`: Shared functions for handling security checks, text cleaning, and formatting.
*   `merge_datasets.py`: Combines all scraped data into one final spreadsheet.
*   `boats_scraped_dataset.csv`: The final, clean merged spreadsheet.

---

## 🛠️ How to Run the Project

1. **Install Requirements**:
   ```bash
   pip install playwright beautifulsoup4 python-dotenv
   playwright install chromium
   ```

2. **Run the Scrapers**:
   ```bash
   # Scrape boatdealers.ca
   python3 scrape_boatdealers_ca.py --pages 2 --limit 11

   # Scrape boats.com
   python3 scrape_boats_com.py --pages 2 --limit 11
   ```

3. **Merge the Data**:
   ```bash
   python3 merge_datasets.py
   ```
   The final data will be saved in `boats_scraped_dataset.csv`.
