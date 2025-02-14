"""
                                      ██                                                
███████  ██████  ████████  ██████  ███████ ██       ██████  ██████      
██      ██    ██    ██    ██    ██    ███  ██      ██    ██ ██   ██     
█████   ██    ██    ██    ██    ██   ███   ████    ██    ██ ██████      
██      ██    ██    ██    ██    ██  ███    ██      ██    ██ ██          
██       ██████     ██     ██████  ███████ ███████  ██████  ██          

    Fotożłop
    Created by: Miłosz Jurek
    Version: 1.0.0
    © 2025 All rights reserved.

"""

from flask import Flask, request, jsonify
import os
import time
import re
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

# Function to sanitize filenames & folder names
def sanitize_filename(filename):
    return "".join(c if c.isalnum() or c in (' ', '.', '_') else '_' for c in filename)

# Function to generate potential full-size image URLs
def generate_full_size_urls(url):
    variations = [
        re.sub(r'/thumb/\d+x\d+/', '/uploads/', url),
        re.sub(r'/thumb/\d+x\d+/', '/', url),
        url.replace('/thumb/', '/uploads/'),
        url.replace('/thumb/', '/')
    ]
    return list(dict.fromkeys(variations))

# Function to download image
def download_image(url, folder, base_url):
    try:
        url = urljoin(base_url, url)
        full_size_urls = generate_full_size_urls(url)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        for full_size_url in full_size_urls:
            response = requests.get(full_size_url, headers=headers, stream=True)
            if response.status_code == 200:
                filename = sanitize_filename(os.path.basename(urlparse(full_size_url).path))
                if not filename:
                    filename = "image_" + str(int(time.time())) + ".jpg"

                file_path = os.path.join(folder, filename)

                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                return filename
        return None
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return None

# Function to scroll the page for lazy loading
def scroll_page(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

# Function to extract images
def extract_images(driver):
    image_urls = set()

    # Extract <img> tags
    images = driver.find_elements(By.TAG_NAME, "img")
    for img in images:
        src = img.get_attribute("src")
        if src:
            image_urls.add(src)

    # Extract background images
    elements_with_bg = driver.find_elements(By.XPATH, "//*[contains(@style, 'background-image')]")
    for elem in elements_with_bg:
        style = elem.get_attribute('style')
        if 'background-image' in style:
            start = style.find('url(') + 4
            end = style.find(')', start)
            img_url = style[start:end].replace('"', '').replace("'", '')
            image_urls.add(img_url)

    # Extract data-bg attributes
    elements_with_data_bg = driver.find_elements(By.XPATH, "//*[@data-bg]")
    for elem in elements_with_data_bg:
        img_url = elem.get_attribute("data-bg")
        if img_url:
            image_urls.add(img_url)

    return image_urls

# Function to trigger sliders
def trigger_slider(driver):
    try:
        next_buttons = driver.find_elements(By.CLASS_NAME, "slick-next")
        for btn in next_buttons:
            for _ in range(5):
                btn.click()
                time.sleep(1)
    except Exception as e:
        print(f"Error interacting with slider: {e}")

# **NEW FUNCTION: Get the Page Meta Title**
def get_meta_title(driver):
    try:
        title = driver.title.strip()
        return sanitize_filename(title)  # Make it safe for folders
    except Exception as e:
        print(f"Error retrieving page title: {e}")
        return "Unknown_Page"

@app.route('/scrape', methods=['POST'])
def scrape_images():
    data = request.json
    website_url = data.get("url")
    if not website_url:
        return jsonify({"error": "No URL provided"}), 400

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    print(f"Processing: {website_url}")
    driver.get(website_url)

    time.sleep(5)  # Ensure page is fully loaded
    scroll_page(driver)
    trigger_slider(driver)

    driver.execute_script("document.querySelectorAll('.lazy-hidden').forEach(el => el.classList.remove('lazy-hidden'));")
    time.sleep(5)

    # **NEW: Get meta title for folder name**
    page_title = get_meta_title(driver)

    image_urls = extract_images(driver)
    driver.quit()

    if not image_urls:
        return jsonify({"message": "No images found", "images": []})

    # **NEW: Create a folder for each website**
    folder_name = os.path.join("downloaded_images", page_title)
    os.makedirs(folder_name, exist_ok=True)

    downloaded_files = []
    for img_url in image_urls:
        downloaded_file = download_image(img_url, folder_name, website_url)
        if downloaded_file:
            downloaded_files.append(downloaded_file)

    return jsonify({"message": "Scraping complete", "images": downloaded_files, "folder": folder_name})

if __name__ == "__main__":
    app.run(debug=True, port=5000)