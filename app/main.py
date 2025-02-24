import os
import logging
import re
import asyncio
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse
from typing import List
import pandas as pd


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

app = FastAPI()

# Configuration
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"


# Setup templates
templates = Jinja2Templates(directory="templates")

# Selenium configuration
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920x1080")
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
chrome_options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})

# WebDriver Singleton
class WebDriverManager:
    def __init__(self):
        self.driver = None

    def get_driver(self):
        if self.driver is None:
            self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        return self.driver

    def quit_driver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

# Helper functions
def clean_price(price_text: str) -> str:
    price_text = price_text.replace('\xa0', ' ')
    match = re.search(r'(\d[\d\s]*[.,]?\d{0,2})', price_text)
    return f"{match.group(1).replace(' ', '').replace(',', '.')} " if match else "Цена по запросу"

def get_selectors(target_url: str):
    domain = urlparse(target_url).netloc
    selector_map = {
        'nur-electro.kz': (By.CLASS_NAME, 'products', By.CLASS_NAME, 'price'),
        'euroelectric.kz': (By.CLASS_NAME, 'product-item', By.CLASS_NAME, 'product-price'),
        '220volt.kz': (By.CLASS_NAME, 'cards__list', By.CLASS_NAME, 'product__buy-info-price-actual_value'),
        'ekt.kz': (By.CLASS_NAME, 'left-block', By.CLASS_NAME, 'price'),
        'intant.kz': (By.CLASS_NAME, 'product_card__block_item_inner', By.CLASS_NAME, 'product-card-inner__new-price'),
        'elcentre.kz': (By.CLASS_NAME, 'b-product-gallery', By.XPATH, ".//span[@class='b-product-gallery__current-price']"),
        'albion-group.kz': (By.CLASS_NAME, 'cs-product-gallery', By.CSS_SELECTOR, "span.cs-goods-price__value.cs-goods-price__value_type_current"),
        'volt.kz': (By.CLASS_NAME, 'multi-snippet', By.XPATH, ".//span[@class='multi-price']"),
    }
    for domain_key, selectors in selector_map.items():
        if domain_key in domain:
            if len(selectors) == 2:
                return selectors
            elif len(selectors) == 4:
                return (selectors[0], selectors[1]), (selectors[2], selectors[3])
    raise ValueError(f"Unsupported URL: {domain}")

# Async Scraping Functions
async def process_excel_file(input_path: str, output_path: str):
    logging.info(f"Processing file: {input_path}")
    try:
        dfs = load_excel_sheets(input_path)
        search_queries = extract_search_queries(dfs)
        final_data = await process_all_sheets(search_queries)
        save_results(final_data, output_path)
    except Exception as e:
        logging.error(f"Error processing Excel file: {e}")

def load_excel_sheets(input_path: str) -> dict:
    return pd.read_excel(input_path, sheet_name=None, engine='openpyxl')

def extract_search_queries(dfs: dict) -> dict:
    return {
        sheet: df['Артикул'].dropna().tolist()
        for sheet, df in dfs.items()
        if 'Артикул' in df.columns
    }

async def process_all_sheets(search_queries: dict) -> dict:
    final_data = {}
    for sheet, queries in search_queries.items():
        sheet_data = await process_sheet_queries(queries)
        final_data[sheet] = sheet_data
    return final_data

async def process_sheet_queries(queries: list) -> list:
    sheet_data = await asyncio.gather(*[process_single_query(query) for query in queries])
    return sheet_data

async def process_single_query(query: str) -> list:
    row = [query]
    tasks = [run_selenium_task(scrape_prices, query, target_url) for target_url in TARGET_URLS]
    results = await asyncio.gather(*tasks)
    for result in results:
        row.append(result if result else "Не найдено")
    return row

def save_results(final_data: dict, output_path: str) -> None:
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        for sheet_name, data in final_data.items():
            df = pd.DataFrame(data, columns=['Артикул'] + [urlparse(url).netloc for url in TARGET_URLS])
            df.to_excel(writer, sheet_name=sheet_name, index=False)

async def run_selenium_task(func, *args):
    return await asyncio.get_event_loop().run_in_executor(None, func, *args)

def scrape_prices(query: str, target_url: str) -> List[str]:
    driver = WebDriverManager().get_driver()
    prices = []
    try:
        full_url = f"{target_url}{query}"
        driver.get(full_url)

        product_selector, price_selector = get_selectors(target_url)
        WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((product_selector[0], product_selector[1])))

        products = driver.find_elements(product_selector[0], product_selector[1])
        for product in products[:5]:
            try:
                price_element = product.find_element(price_selector[0], price_selector[1])
                price = clean_price(price_element.text)
                prices.append(price)
            except NoSuchElementException:
                continue

        return prices if prices else ["Не найдено"]
    except Exception as e:
        logging.error(f"Error scraping {target_url} for artikul '{query}': {str(e)}")
        return []
    finally:
        logging.info(f"Scraping for artikul '{query}' completed.")

# Target URLs
TARGET_URLS = [
    "https://220volt.kz/search?query=", 
    "https://elcentre.kz/site_search?search_term=",
]

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})

@app.post("/search")
async def search_artikul(artikul: str = Form(...)):
    try:
        result_data = []
        tasks = [run_selenium_task(scrape_prices, artikul, url) for url in TARGET_URLS]
        results = await asyncio.gather(*tasks)

        for url, prices in zip(TARGET_URLS, results):
            result_data.append({
                "Artikul": artikul,
                "URL": url,
                "Prices": prices if prices else ["Не найдено"]
            })
        return {"results": result_data}
    except Exception as e:
        logging.error(f"Error searching for Artikul '{artikul}': {e}")
        return {"error": f"Failed to fetch prices for Artikul {artikul}"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{file.filename}")
        with open(file_path, "wb") as f:
            f.write(await file.read())

        result_file = os.path.join(OUTPUT_FOLDER, f"merged.xlsx")
        await process_excel_file(file_path, result_file)
        return FileResponse(result_file, filename="result.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        logging.error(f"Error processing file: {str(e)}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
