"""
    $crape Master
    Created by: Miłosz Jurek
    © 2025 All rights reserved.

"""

import os
import time
import re
import platform
import subprocess
from urllib.parse import urljoin, urlparse
from pathlib import Path
from threading import Thread

import requests
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from pydub import AudioSegment
from pydub.playback import play

app = Flask(__name__)
from flask_cors import CORS
CORS(app)

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

    # Scroll images into view instead of using ActionChains (fix MoveTargetOutOfBoundsException)
    images = driver.find_elements(By.TAG_NAME, "img")
    for img in images:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", img)
            time.sleep(0.2)  # Allow time for lazy loading
        except Exception as e:
            print(f"Skipping image due to error: {e}")

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

# Combined function to remove dimensions and generate full-size image URLs
def clean_and_generate_urls(url):
    # Step 1: Remove /thumbs/ and /thumb/ Directories
    url = url.replace("/thumbs/", "/").replace("/thumb/", "/")

    # Step 2: Remove Dimensions
    url = re.sub(r'/\d+x\d+/', '/', url)

    # Step 3: Generate Variations
    variations = [
        url,  # Base cleaned URL
        re.sub(r'/thumbs?/\d+x\d+/', '/uploads/', url),  # Matches both thumb and thumbs
        re.sub(r'/thumbs?/\d+x\d+/', '/', url),           # Matches both thumb and thumbs
        url.replace('/thumbs/', '/uploads/'),
        url.replace('/thumb/', '/uploads/'),
        url.replace('/thumbs/', '/'),
        url.replace('/thumb/', '/')
    ]

    # Remove duplicates while preserving order
    return list(dict.fromkeys(variations))

# --- URL Cleaning and Generation ---
# Combined function to remove dimensions and generate full-size image URLs
def clean_and_generate_urls(url):
    # Step 1: Remove /thumbs/ Directory
    url = url.replace("/thumbs/", "/")

    # Step 2: Remove Dimensions
    url = re.sub(r'/\d+x\d+/', '/', url)

    # Step 3: Generate Variations
    variations = [
        url,  # Base cleaned URL
        re.sub(r'/thumb/\d+x\d+/', '/uploads/', url),
        re.sub(r'/thumb/\d+x\d+/', '/', url),
        url.replace('/thumb/', '/uploads/'),
        url.replace('/thumb/', '/')
    ]

    # Remove duplicates while preserving order
    return list(dict.fromkeys(variations))

# Function to prioritize JPG over WEBP and remove dimensions
def prioritize_jpg(url):
    # Step 1: Remove dimensions from URL
    original_url = re.sub(r'/\d+x\d+/', '/', url)

    # Step 2: Check for JPEG versions
    if ".webp" in original_url:
        # Try .jpeg and .jpg versions of the cleaned URL
        jpg_url = original_url.replace(".webp", ".jpeg")
        jpg_alt_url = original_url.replace(".webp", ".jpg")

        # Check if .jpeg version exists
        response = requests.head(jpg_url)
        if response.status_code == 200:
            return jpg_url
        
        # Check if .jpg version exists
        response = requests.head(jpg_alt_url)
        if response.status_code == 200:
            return jpg_alt_url

    elif ".jpeg" in original_url or ".jpg" in original_url:
        # Directly check the cleaned URL for JPG versions
        response = requests.head(original_url)
        if response.status_code == 200:
            return original_url

    return url  # Return original URL if no dimension-less version is found

# Function to download image
def download_image(url, folder, base_url):
    try:
        url = urljoin(base_url, url)
        full_size_urls = clean_and_generate_urls(url)

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

# **NEW FUNCTION: Extract Highest-Resolution Image from srcset/data-srcset**
def get_highest_resolution_image(srcset):
    try:
        src_list = [s.strip() for s in srcset.split(",")]
        url_res_pairs = []

        for src in src_list:
            parts = src.split(" ")
            if len(parts) == 2:
                url, res = parts
                res_value = int(re.sub("[^0-9]", "", res))  # Extract numerical value
                url_res_pairs.append((url, res_value))

        if url_res_pairs:
            url_res_pairs.sort(key=lambda x: x[1], reverse=True)  # Sort by resolution (desc)
            return url_res_pairs[0][0]  # Return highest-res image URL

    except Exception as e:
        print(f"Error processing srcset: {e}")
    return None

# **UPDATED FUNCTION: Extract Full-Resolution Images**
def extract_full_res_images(driver):
    image_urls = set()

    # Find all <a> tags wrapping <img> elements
    links = driver.find_elements(By.TAG_NAME, "a")
    for link in links:
        href = link.get_attribute("href")
        img_tag = link.find_elements(By.TAG_NAME, "img")
        
        if href and (".jpg" in href or ".jpeg" in href or ".png" in href or ".webp" in href):
            prioritized_url = prioritize_jpg(href)
            image_urls.add(prioritized_url)

        if img_tag:
            img_src = img_tag[0].get_attribute("src")
            if img_src:
                prioritized_url = prioritize_jpg(img_src)
                image_urls.add(prioritized_url)

    # Extract standalone <img> elements
    images = driver.find_elements(By.TAG_NAME, "img")
    for img in images:
        data_srcset = img.get_attribute("data-srcset")
        srcset = img.get_attribute("srcset")
        src = img.get_attribute("src")

        if data_srcset:
            best_image = get_highest_resolution_image(data_srcset)
            if best_image:
                prioritized_url = prioritize_jpg(best_image)
                image_urls.add(prioritized_url)

        elif srcset:
            best_image = get_highest_resolution_image(srcset)
            if best_image:
                prioritized_url = prioritize_jpg(best_image)
                image_urls.add(prioritized_url)

        elif src:
                prioritized_url = prioritize_jpg(src)
                image_urls.add(prioritized_url)

    # **NEW: Extract images from <picture> and <source> elements**
    pictures = driver.find_elements(By.TAG_NAME, "picture")
    for picture in pictures:
        sources = picture.find_elements(By.TAG_NAME, "source")
        for source in sources:
            srcset = source.get_attribute("srcset")
            if srcset:
                best_image = get_highest_resolution_image(srcset)
                if best_image:
                    prioritized_url = prioritize_jpg(best_image)
                    image_urls.add(prioritized_url)

    # **NEW: Extract OpenGraph images from <meta property="og:image">**
    og_image = driver.find_elements(By.XPATH, "//meta[@property='og:image']")
    for meta in og_image:
        content = meta.get_attribute("content")
        if content:
            prioritized_url = prioritize_jpg(content)
            image_urls.add(prioritized_url)

    # **NEW: Extract lazy-loaded images from data-* attributes**
    lazy_images = driver.find_elements(By.TAG_NAME, "img")
    for img in lazy_images:
        for attr in img.get_property("attributes"):
            if "data-" in attr["name"] and (".jpg" in attr["value"] or ".jpeg" in attr["value"] or ".png" in attr["value"] or ".webp" in attr["value"]):
                prioritized_url = prioritize_jpg(attr["value"])
                image_urls.add(prioritized_url)

    # Extract background images
    elements_with_bg = driver.find_elements(By.XPATH, "//*[contains(@style, 'background-image')]")
    for elem in elements_with_bg:
        style = elem.get_attribute('style')
        if 'background-image' in style:
            start = style.find('url(') + 4
            end = style.find(')', start)
            img_url = style[start:end].replace('"', '').replace("'", '')
            prioritized_url = prioritize_jpg(img_url)
            image_urls.add(prioritized_url)

    return image_urls

# Function to sanitize filenames & folder names
def sanitize_filename(filename):
    return "".join(c if c.isalnum() or c in (' ', '.', '_') else '_' for c in filename)

# **NEW FUNCTION: Get the Page Meta Title**
def get_meta_title(driver):
    try:
        title = driver.title.strip()
        return sanitize_filename(title)  # Make it safe for folders
    except Exception as e:
        print(f"Error retrieving page title: {e}")
        return "Unknown_Page"

# **Play sound in a separate thread**
def play_success_sound():
    sound_path = Path(__file__).parent / "success.wav"

    if not sound_path.exists():
        print("Sound file not found:", sound_path)
        return

    try:
        if platform.system() == "Windows":
            # Use a different player for Windows to avoid playsound errors
            subprocess.run(["powershell", "-c", f"(New-Object Media.SoundPlayer '{sound_path}').PlaySync()"], check=True)
        else:
            # Use pydub for Linux/macOS compatibility
            sound = AudioSegment.from_file(sound_path)
            play(sound)

    except Exception as e:
        print(f"Error playing sound: {e}")

@app.route('/scrape', methods=['POST'])
def scrape_images():
    data = request.json
    website_url = data.get("url")
    if not website_url:
        return jsonify({"error": "No URL provided"}), 400

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--no-sandbox")  # Bypass OS security model, needed for Docker
    chrome_options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    chrome_options.binary_location = "/usr/bin/google-chrome"  # Explicitly set the Chrome binary location
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    print(f"Processing: {website_url}")
    driver.get(website_url)

    time.sleep(5)
    scroll_page(driver)
    trigger_slider(driver)

    page_title = get_meta_title(driver)
    image_urls = extract_full_res_images(driver)
    driver.quit()

    if not image_urls:
        return jsonify({"message": "No images found", "images": []})

    folder_name = os.path.join("downloaded_images", page_title)
    os.makedirs(folder_name, exist_ok=True)

    # Download images (one by one)
    for img_url in image_urls:
        download_image(img_url, folder_name, website_url)

    # Now count the actual files saved in the folder
    saved_files = [f for f in os.listdir(folder_name) if os.path.isfile(os.path.join(folder_name, f))]
    count = len(saved_files)

    # Use the saved_files list (and/or count) in your response
    response = jsonify({
        "message": f"Scraping complete, downloaded {count} images",
        "images": saved_files,
        "folder": folder_name
    })
    response.call_on_close(play_success_sound)
    return response

if __name__ == "__main__":
    app.run(debug=True, port=5000)
