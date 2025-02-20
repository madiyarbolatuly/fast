import os
import logging
import re
import asyncio
import uuid
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse
from typing import List
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = FastAPI()

# Configuration
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

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
chrome_options.binary_location = os.getenv("CHROME_BIN", "/usr/bin/google-chrome-stable")  # Path to Chrome binary


executor = ThreadPoolExecutor(max_workers=4)

driver = None 

def get_driver():
    global driver  # Reference the global driver variable
    if driver is None:  # If driver is None, it means it hasn't been created yet.
        logging.info("Initializing WebDriver instance...")
        driver = webdriver.Chrome(  # Create a new WebDriver instance.
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
    return driver  

# Helper functions
def clean_price(price_text: str) -> str:
    price_text = price_text.replace('\xa0', ' ')
    match = re.search(r'(\d[\d\s]*[.,]?\d{0,2})', price_text)
    return f"{match.group(1).replace(' ', '').replace(',', '.')} " if match else "Цена по запросу"

def get_selectors(target_url: str):
    domain = urlparse(target_url).netloc  # Extract just the domain
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
        logging.debug(f"Checking if domain {domain_key} matches {domain}")
        if domain_key in domain:  # Match only the domain part
            logging.info(f"Selectors found for {domain}: {selectors}")
            if len(selectors) == 2:
                return selectors  # 2 values: product and price selectors
            elif len(selectors) == 4:
                return (selectors[0], selectors[1]), (selectors[2], selectors[3])  # 4 values: separate product and price selectors
            else:
                logging.error(f"Unexpected number of selector values for domain {domain_key}: {len(selectors)}")
                raise ValueError(f"Unexpected number of selectors for {domain_key}")
    
    logging.error(f"Unsupported URL. No selectors found for domain: {domain}")
    raise ValueError(f"Unsupported URL: {domain}")

# Routes

async def process_excel_file(input_path: str, output_path: str):
    logging.info(f"Processing file: {input_path}")
    
    try:
        dfs = pd.read_excel(input_path, sheet_name=None)
        logging.info(f"Excel file loaded. Sheets found: {list(dfs.keys())}")
        
        search_queries = {sheet: df['Артикул'].dropna().tolist() for sheet, df in dfs.items() if 'Артикул' in df.columns}
        logging.info(f"Artikul queries extracted: {search_queries}")

        final_data = {}
        for sheet, queries in search_queries.items():
            sheet_data = []
            for query in queries:
                row = [query]
                for target_url in TARGET_URLS:
                    try:
                        prices = await run_selenium_task(scrape_prices, target_url, query)
                        row.append(", ".join(prices) if prices else "Не найдено")
                    except Exception as e:
                        row.append("Ошибка")
                        logging.error(f"Error scraping {target_url}: {str(e)}")
                sheet_data.append(row)
            final_data[sheet] = sheet_data
        
        logging.info(f"Saving results to {output_path}")
        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
            for sheet_name, data in final_data.items():
                df = pd.DataFrame(data, columns=['Артикул'] + [urlparse(url).netloc for url in TARGET_URLS])
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        logging.info(f"File processing complete. Results saved to {output_path}")
    except Exception as e:
        logging.error(f"Error processing Excel file: {e}")

async def run_selenium_task(func, *args):
    return await asyncio.get_event_loop().run_in_executor(executor, func, *args)

def scrape_prices(target_url: str, query: str) -> List[str]:
    logging.info(f"Scraping prices for artikul '{query}' from {target_url}...")
    
    # Ensure the Artikul is appended correctly to the URL
    if isinstance(query, str):
        full_url = f"{target_url}{query}"
    else:
        logging.error(f"Invalid Artikul '{query}' passed to scrape_prices. Expected string.")
        return []
    
    logging.info(f"Generated full URL: {full_url}")

    driver = get_driver()
    prices = []
    
    try:
        logging.info(f"Navigating to page: {full_url}")
        driver.get(full_url)
        logging.info(f"Page loaded: {full_url}")
        
        product_selector, price_selector = get_selectors(target_url)
        logging.info(f"Using selectors: Product: {product_selector}, Price: {price_selector}")

        logging.info(f"Waiting for product elements to load...")
        WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((product_selector[0], product_selector[1])))
        logging.info(f"Product elements loaded successfully.")

        products = driver.find_elements(product_selector[0], product_selector[1])
        logging.info(f"Found {len(products)} products on the page.")

        for index, product in enumerate(products[:5]):  # Limit to top 5 results
            try:
                logging.info(f"Processing product {index+1}: {product.text}")
                price_element = product.find_element(price_selector[0], price_selector[1])
                price = clean_price(price_element.text)
                logging.info(f"Found price: {price}")
                prices.append(price)
            except NoSuchElementException:
                logging.warning(f"Price not found for product {index+1}: {product.text}")
                continue
        
        if not prices:
            logging.warning(f"No prices found for artikul '{query}' on {target_url}")
        return prices
    except Exception as e:
        logging.error(f"Error scraping {target_url} for artikul '{query}': {str(e)}")
        return []
    finally:
        logging.info(f"Quitting driver for {target_url}...")
        driver.quit()


# Target URLs
TARGET_URLS = [
    "https://220volt.kz/search?query=",  # Example of correct URL format
    "https://elcentre.kz/site_search?search_term=",
    "https://intant.kz/catalog/?q=",
    "https://albion-group.kz/site_search?search_term=",
    "https://volt.kz/#/search/",
    "https://ekt.kz/catalog/?q=",
    "https://nur-electro.kz/search?controller=search&s=",
]

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})

@app.post("/search")
async def search_artikul(artikul: str = Form(...)):
    logging.info(f"Received search request for Artikul: {artikul}")
    try:
        result_data = []
        for url in TARGET_URLS:
            logging.info(f"Scraping prices for artikul '{artikul}' from {url}")
            prices = scrape_prices(url, artikul)
            
            if isinstance(prices, list):
                result_data.append({
                    "Artikul": artikul,
                    "URL": url,
                    "Prices": prices if prices else ["Не найдено"]
                })
            else:
                result_data.append({
                    "Artikul": artikul,
                    "URL": url,
                    "Prices": ["Не найдено"]
                })
        
        logging.info(f"Search results for Artikul '{artikul}': {result_data}")
        return {"results": result_data}

    except Exception as e:
        logging.error(f"Error searching for Artikul '{artikul}': {e}")
        return {"error": f"Failed to fetch prices for Artikul {artikul}"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        logging.info(f"Received file upload: {file.filename}")
        
        file_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}.xlsx")
        
        with open(file_path, "wb") as f:
            f.write(await file.read())
        logging.info(f"File saved to {file_path}")
        
        result_file = os.path.join(OUTPUT_FOLDER, f"{uuid.uuid4()}.xlsx")
        await process_excel_file(file_path, result_file)
        logging.info(f"File processed successfully. Saving result to {result_file}")
        
        return FileResponse(
            path=result_file,
            filename="result.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        logging.error(f"Error processing file: {str(e)}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
