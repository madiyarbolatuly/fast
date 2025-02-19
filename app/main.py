import os
import logging
import re
import asyncio
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
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

logging.basicConfig(
    
    format='%(asctime)s - %(levelname)s - %(message)s',

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

executor = ThreadPoolExecutor(max_workers=4)
driver_path = r"C:/Users/Madiyar/.wdm/drivers/chromedriver/win64/132.0.6834.159/chromedriver-win64/chromedriver.exe"
# Global driver initialization
def get_driver():
    """Initialize and return a new WebDriver instance."""
    logging.info("Initializing WebDriver instance...")
    driver = webdriver.Chrome(
        executable_path=driver_path,
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
    selector_map = {
        'nur-electro.kz': (By.CLASS_NAME, 'products', By.CLASS_NAME, 'price'),
        'euroelectric.kz': (By.CLASS_NAME, 'product-item', By.CLASS_NAME, 'product-price'),
        'volt.kz': (By.CLASS_NAME, 'multi-snippet', By.XPATH, ".//span[@class='multi-price']"),
        '220volt.kz': (By.CLASS_NAME, 'cards__list', By.CLASS_NAME, 'product__buy-info-price-actual_value'),
        'ekt.kz': (By.CLASS_NAME, 'left-block', By.CLASS_NAME, 'price'),
        'intant.kz': (By.CLASS_NAME, 'product_card__block_item_inner', By.CLASS_NAME, 'product-card-inner__new-price'),
        'elcentre.kz': (By.CLASS_NAME, 'b-product-gallery', By.XPATH, ".//span[@class='b-product-gallery__current-price']"),
        'albion-group.kz': (By.CLASS_NAME, 'cs-product-gallery', By.CSS_SELECTOR, "span.cs-goods-price__value.cs-goods-price__value_type_current"),
    }
    for domain, selectors in selector_map.items():
        if domain in target_url:
            return selectors
    raise ValueError("Unsupported URL")

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"input_{uuid.uuid4()}.xlsx")
        
        # Save uploaded file
        with open(file_path, "wb") as f:
            f.write(await file.read())

        # Process file
        result_file = os.path.join(OUTPUT_FOLDER, f"result_{uuid.uuid4()}.xlsx")
        await process_excel_file(file_path, result_file)

        return FileResponse(
            path=result_file,
            filename="result.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        logging.error(f"Error processing file: {str(e)}")
        return {"status": "error", "message": str(e)}

async def process_excel_file(input_path: str, output_path: str):
    dfs = pd.read_excel(input_path, sheet_name=None)
    search_queries = {sheet: df['Артикул'].dropna().tolist() for sheet, df in dfs.items() if 'Артикул' in df.columns}
    
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
    
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        for sheet_name, data in final_data.items():
            df = pd.DataFrame(data, columns=['Артикул'] + [urlparse(url).netloc for url in TARGET_URLS])
            df.to_excel(writer, sheet_name=sheet_name, index=False)

async def run_selenium_task(func, *args):
    return await asyncio.get_event_loop().run_in_executor(executor, func, *args)

def scrape_prices(target_url: str, query: str) -> List[str]:
    driver = get_driver()
    try:
        driver.get(f"{target_url}{query}")
        product_selector, price_selector = get_selectors(target_url)
        WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((product_selector[0], product_selector[1])))
        
        products = driver.find_elements(product_selector[0], product_selector[1])
        prices = []
        for product in products[:5]:  # Limit to top 5 results
            try:
                price_element = product.find_element(price_selector[0], price_selector[1])
                prices.append(clean_price(price_element.text))
            except NoSuchElementException:
                continue
        return prices
    finally:
        driver.quit()

# Target URLs
TARGET_URLS = [
    "https://220volt.kz/search?query=",
    "https://elcentre.kz/site_search?search_term=",
    "https://intant.kz/catalog/?q=",
    "https://albion-group.kz/site_search?search_term=",
    "https://volt.kz/#/search/",
    "https://ekt.kz/catalog/?q=",
    "https://nur-electro.kz/search?controller=search&s=",
]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
