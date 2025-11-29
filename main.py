import json
import sys
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.options import Options
import itertools

URL = "https://www.pagibigfundservices.com/OnlinePublicAuction/"
SHEET_NAME = "Pag-IBIG Web Scrape Data"
SHEET_KEY = "asgfiletransfer-11f3f14d4baf.json"
REGION_BLACKLIST = ["AUTONOMOUS REGION IN MUSLIM MINDANAO (ARMM)","Region 6 (western visayas)", "Region 7 (central visayas)", 
                    "Region 8 (eastern visayas)", "Region 9 (zamboanga peninsula)", "Region 10 (northern mindanao)",
                    "Region 11 (davao region)", "Region 12 (soccsksargen)", "Region 13 (caraga)"]
REGION_BLACKLIST = [r.upper() for r in REGION_BLACKLIST]

def scrape_cards(cards, region, province, city):

    results = []

    for card in cards:

        # IMAGE
        try:
            img_el = card.find_element(By.CSS_SELECTOR, "div[id^='property-images-'] img")
            img_src = f"=IMAGE(\"{img_el.get_attribute('src')}\",1)"
        except NoSuchElementException:
            img_src = None

        # TITLE (Subdivision)
        title = card.find_element(By.CSS_SELECTOR, "h3 strong").text.strip()

        # PROPERTY TYPE (Lot Only / Condo / etc)
        prop_type = card.find_element(By.CSS_SELECTOR, ".bi-houses").find_element(By.XPATH, "..").text.strip()

        # ACCEPTANCE DATES
        dates = card.find_element(By.ID, "acceptance_offer").text.replace("|", "").strip()

        # BASIC FIELDS AREA/PRICE
        fields = card.find_elements(By.CSS_SELECTOR, ".row.align-items-end .col-12")

        occupancy = fields[0].text.replace("Occupancy Status", "").strip()
        lot_area = fields[1].text.replace("Lot Area", "").strip()
        floor_area = fields[2].text.replace("Floor Area", "").strip()
        min_price = fields[3].text.replace("Minimum Bid/Selling Price", "").strip()

        # JSON WITH FULL DETAILS
        raw_json = card.find_element(By.CSS_SELECTOR, ".view-more-details").get_attribute("data-property")
        info = json.loads(raw_json)

        results.append({
            "area": f"{region} / {province} / {city}",
            "title": title,
            "property_type": prop_type,
            "img_url": img_src,
            "dates": dates,
            "occupancy": occupancy,
            "lot_area": lot_area,
            "floor_area": floor_area,
            "req_gross_income": info.get("req_gross"),
            "price": min_price,
            "location": info.get("prop_location"),
            "batch_no": info.get("batch_no"),
            "prop_no": info.get("ropa_id"),
            "subdivision": info.get("subdivision"),
            "inspection_date": info.get("inspection_date"),
            "appraisal_date": info.get("appr_date"),
            "handling_branch": info.get("contact_hbc"),
            "email": info.get("email_hbc"),
            "bidding_time": info.get("opening_datetime"),
            "remarks": info.get("remarks")
        })

    return results

def search_filters():
    data = []
    options = Options()
    options.headless = True
    driver = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=options)
    driver.get(URL)

    wait = WebDriverWait(driver, 20)
    
    driver.implicitly_wait(2)
    [region_dropdown_el, region_dropdown] = reload_dropdown(driver, "region")
    region_dropdown = [
        opt for opt in region_dropdown 
        if opt.text.strip().upper() not in REGION_BLACKLIST
    ]

    region_select = Select(region_dropdown_el)

    # Loop through ALL regions
    for region_option in region_dropdown:
        region_value = region_option.get_attribute("value")
        region_text = region_option.text.strip()

        old_province_options = old_data(driver, "province")
        region_select.select_by_value(region_value)

        # WAIT until province options change
        wait.until(
            lambda d: [
                opt.text.strip()
                for opt in Select(d.find_element(By.ID, "province")).options
                if opt.get_attribute("value") not in ["", None]
            ] != old_province_options
        )

        [province_dropdown_el, province_dropdown] = reload_dropdown(driver, "province")
        province_select = Select(province_dropdown_el)

        # Loop through ALL provinces
        for prov_option in province_dropdown:
            prov_value = prov_option.get_attribute("value")
            prov_text = prov_option.text.strip()

            old_city_options = old_data(driver, "city")
            province_select.select_by_value(prov_value)

            driver.implicitly_wait(2)
            wait.until(EC.invisibility_of_element_located((By.ID, "overlay")))

            # WAIT until city options change
            wait.until(
                lambda d: [
                    opt.text.strip()
                    for opt in Select(d.find_element(By.ID, "city")).options
                    if opt.get_attribute("value") not in ["", None]
                ] != old_city_options
            )

            wait.until(EC.invisibility_of_element_located((By.ID, "overlay")))
            [city_dropdown_el, city_dropdown] = reload_dropdown(driver, "city")
            city_select = Select(city_dropdown_el)

            # Loop through ALL cities
            for city_option in city_dropdown:
                city_value = city_option.get_attribute("value")
                city_text = city_option.text.strip()

                city_select.select_by_value(city_value)

                # Search Button
                search_btn = wait.until(EC.presence_of_element_located((By.ID, "search-button")))
                search_btn.click()
                wait.until(EC.invisibility_of_element_located((By.ID, "overlay")))
                while True:
                    cards = driver.find_elements(By.CSS_SELECTOR, ".container-fluid.p-3.rounded-2 .card")
                    data.append(scrape_cards(cards, region_text, prov_text, city_text))
                    try:
                        next_button = driver.find_element(By.CSS_SELECTOR, "#paginationControls-nego button.btn-secondary.ms-1:not([disabled])")
                        driver.execute_script("arguments[0].click();", next_button)
                        wait.until(EC.invisibility_of_element_located((By.ID, "overlay")))
                    except NoSuchElementException:
                        break

    driver.quit()
    return data

def reload_dropdown(driver, select_id):
    select_el = driver.find_element(By.ID, select_id)
    select_obj = Select(select_el)
    options = [
        opt for opt in select_obj.options
        if opt.get_attribute("value") not in ["", None] and not opt.get_attribute("disabled")
    ]
    return [select_el, options]

def old_data(driver, id):
    select_obj = Select(driver.find_element(By.ID, id))
    data = [
        opt.text.strip() for opt in select_obj.options
        if opt.get_attribute("value") not in ["", None]
    ]
    return data

def update_sheet(data, sheet_name, creds_file_path=SHEET_KEY):

    flat_data = list(itertools.chain.from_iterable(data))
    df=pd.DataFrame(flat_data)

    gc = gspread.service_account(filename=creds_file_path)
    spreadsheet = gc.open(sheet_name)
    worksheet = spreadsheet.sheet1 

    worksheet.clear() 
    set_with_dataframe(worksheet, df)


if __name__ == "__main__":
    data = search_filters()
    #print(data)
    update_sheet(data, SHEET_NAME)
    print("Updated!")

    sys.exit(0)

