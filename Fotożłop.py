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

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import requests
import os
from urllib.parse import urljoin, urlparse
import time
import re
import beepy  # Importing beepy for sound notification

# Function to sanitize filenames
def sanitize_filename(filename):
    return "".join(c if c.isalnum() or c in (' ', '.', '_') else '_' for c in filename)

# Function to generate potential full-size image URLs
def generate_full_size_urls(url):
    variations = [
        re.sub(r'/thumb/\d+x\d+/', '/uploads/', url),    # Replace thumb/dimensions with uploads
        re.sub(r'/thumb/\d+x\d+/', '/', url),            # Remove thumb/dimensions entirely
        url.replace('/thumb/', '/uploads/'),              # Replace only 'thumb' with 'uploads'
        url.replace('/thumb/', '/'),                      # Remove 'thumb' entirely
    ]
    return list(dict.fromkeys(variations))  # Remove duplicates

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
                file_path = os.path.join(folder, filename)

                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                print(f"Downloaded FULL-SIZE: {file_path}")
                return
            else:
                print(f"Attempted: {full_size_url} (HTTP {response.status_code})")

        response = requests.get(url, headers=headers, stream=True)
        if response.status_code == 200:
            filename = sanitize_filename(os.path.basename(urlparse(url).path))
            file_path = os.path.join(folder, filename)

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"Downloaded THUMBNAIL: {file_path}")
        else:
            print(f"Failed to download THUMBNAIL: {url} (HTTP {response.status_code})")

    except Exception as e:
        print(f"Failed to download {url}: {e}")

# Function to scroll the page to trigger lazy loading
def scroll_page(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

# Function to extract background images and data-bg attributes
def extract_images(driver):
    image_urls = set()

    elements_with_bg = driver.find_elements(By.XPATH, "//*[contains(@style, 'background-image')]")
    print(f"Found {len(elements_with_bg)} elements with background-image style")
    for elem in elements_with_bg:
        style = elem.get_attribute('style')
        if 'background-image' in style:
            start = style.find('url(') + 4
            end = style.find(')', start)
            img_url = style[start:end].replace('"', '').replace("'", '')

            if img_url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                image_urls.add(img_url)

    elements_with_data_bg = driver.find_elements(By.XPATH, "//*[@data-bg]")
    for elem in elements_with_data_bg:
        img_url = elem.get_attribute('data-bg')
        if img_url and img_url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            image_urls.add(img_url)

    return image_urls

# Function to simulate slider clicks for lazy-loaded images
def trigger_slider(driver):
    try:
        next_buttons = driver.find_elements(By.CLASS_NAME, 'slick-next')
        for btn in next_buttons:
            for _ in range(5):
                btn.click()
                time.sleep(1)
    except Exception as e:
        print(f"Error interacting with slider: {e}")

# Main function
def scrape_images(website_urls, folder_name="downloaded_images"):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    for website_url in website_urls:
        print(f"Processing: {website_url}")
        driver.get(website_url)

        time.sleep(15)
        scroll_page(driver)
        trigger_slider(driver)

        driver.execute_script("document.querySelectorAll('.lazy-hidden').forEach(el => el.classList.remove('lazy-hidden'));")
        time.sleep(5)

        image_urls = extract_images(driver)
        print(f"Found {len(image_urls)} images on {website_url}:")
        for url in image_urls:
            print(url)

        for img_url in image_urls:
            download_image(img_url, folder_name, website_url)

    driver.quit()

    # Print completion message
    print("\nTask Completed: All images have been successfully downloaded!")

    # Play a sound effect using beepy
    beepy.beep(sound='ready')

if __name__ == "__main__":
    websites = [
        "https://hoteltobaco.pl/restauracja/o-restauracji"
    ]
    scrape_images(websites)
