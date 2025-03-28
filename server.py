"""
    Scrape Master
    Created by: Miłosz Jurek
    © 2025 All rights reserved.

"""

import os
import time
import re
import platform
import subprocess
import zipfile
import threading  
import uuid      

from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode
from pathlib import Path

import requests
from flask import Flask, request, jsonify, send_from_directory
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)
from flask_cors import CORS
CORS(app)

# === Global Cache for ChromeDriver Path ===
CHROMEDRIVER_PATH = None

def get_chromedriver_path():
    global CHROMEDRIVER_PATH
    if CHROMEDRIVER_PATH is None:
        CHROMEDRIVER_PATH = ChromeDriverManager().install()
    return CHROMEDRIVER_PATH

# NEW: In-memory dictionary to track scraping jobs
# job_id -> {"status": "pending"/"finished"/"error",
#            "zip_filename": <str or None>,
#            "error": <str or None>}
SCRAPE_JOBS = {}

# === Functions for Scrolling and Interaction ===
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

# --- URL Cleaning and Generation ---
# Combined function to remove dimensions and generate full-size image URLs
def remove_query_dimensions(url):
    """
    Removes common dimension parameters like 'width' and 'height'
    from a URL's query string (e.g., ?width=123&height=456).
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    filtered_qs = {}
    for key, values in qs.items():
        # If key is something other than width or height, keep it
        if key.lower() not in ["width", "height"]:
            filtered_qs[key] = values

    # Reconstruct the final URL without those dimension keys
    new_query = urlencode(filtered_qs, doseq=True)
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    return new_url

def clean_and_generate_urls(url):
    # Step 1: Remove /thumbs/ and /thumb/ Directories
    url = url.replace("/thumbs/", "/").replace("/thumb/", "/")

    # Step 1.5: Remove dimension-based query parameters (?width=..., ?height=...)
    url = remove_query_dimensions(url)

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

# === NEW: The background thread function that runs the actual scraping ===
def do_scrape_background(website_url, job_id):
    """This function is executed in a separate thread."""
    try:
        # Mark job as pending (in case the user checks immediately)
        SCRAPE_JOBS[job_id]["status"] = "in_progress"

        chrome_options = Options()
        chrome_options.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/google-chrome")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")
        driver = webdriver.Chrome(service=Service(get_chromedriver_path()), options=chrome_options)

        print(f"[Thread] Processing: {website_url}")
        driver.get(website_url)
        time.sleep(5)
        scroll_page(driver)
        trigger_slider(driver)

        page_title = get_meta_title(driver)
        image_urls = extract_full_res_images(driver)
        driver.quit()

        if not image_urls:
            SCRAPE_JOBS[job_id]["status"] = "finished"
            SCRAPE_JOBS[job_id]["zip_filename"] = None
            return

        folder_name = os.path.join("downloaded_images", page_title)
        os.makedirs(folder_name, exist_ok=True)

        for img_url in image_urls:
            download_image(img_url, folder_name, website_url)

        saved_files = [f for f in os.listdir(folder_name)
                       if os.path.isfile(os.path.join(folder_name, f))]
        count = len(saved_files)

        SCRAPE_JOBS[job_id]["imagesCount"] = count

        # Create a zip
        zip_filename = f"{page_title}.zip"
        zip_filepath = os.path.join("downloaded_images", zip_filename)
        with zipfile.ZipFile(zip_filepath, 'w') as zipf:
            for root, dirs, files in os.walk(folder_name):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, arcname=file)

        # Mark the job as finished
        SCRAPE_JOBS[job_id]["status"] = "finished"
        SCRAPE_JOBS[job_id]["zip_filename"] = zip_filename
        print(f"[Thread] Scrape job {job_id} done. Downloaded {count} images.")

    except Exception as e:
        SCRAPE_JOBS[job_id]["status"] = "error"
        SCRAPE_JOBS[job_id]["error"] = str(e)
        print(f"[Thread] Error in job {job_id}: {e}")

# === NEW: 1) Start Scrape Endpoint
@app.route('/start_scrape', methods=['POST'])
def start_scrape():
    """
    The extension calls this endpoint to begin scraping.
    We immediately return a job_id and run the actual logic in a thread.
    """
    data = request.json
    website_url = data.get("url")
    if not website_url:
        return jsonify({"error": "No URL provided"}), 400

    # Generate a unique job ID
    job_id = str(uuid.uuid4())

    # Initialize job record
    SCRAPE_JOBS[job_id] = {
        "status": "pending",
        "zip_filename": None,
        "error": None
    }

    # Spawn a background thread
    thread = threading.Thread(target=do_scrape_background, args=(website_url, job_id))
    thread.start()

    # Immediately return job_id to the client
    return jsonify({"job_id": job_id}), 202

# === NEW: 2) Poll for Status
@app.route('/job_status', methods=['GET'])
def job_status():
    """
    The extension can call GET /job_status?job_id=XYZ to see if it's done.
    """
    job_id = request.args.get("job_id")
    if not job_id or job_id not in SCRAPE_JOBS:
        return jsonify({"error": "Invalid or missing job_id"}), 400

    job_info = SCRAPE_JOBS[job_id]
    return jsonify({
        "status": job_info["status"],
        "zip_filename": job_info["zip_filename"],
        "error": job_info["error"],
        "imagesCount": job_info.get("imagesCount", 0)
    })

# === NEW: 3) Download Result
@app.route('/download_result', methods=['GET'])
def download_result():
    """
    Once the status is 'finished', the extension can call
    GET /download_result?job_id=XYZ to get the ZIP file.
    """
    job_id = request.args.get("job_id")
    if not job_id or job_id not in SCRAPE_JOBS:
        return jsonify({"error": "Invalid or missing job_id"}), 400

    job_info = SCRAPE_JOBS[job_id]
    if job_info["status"] != "finished":
        return jsonify({"error": "Job not finished or in error state"}), 400

    zip_filename = job_info["zip_filename"]
    if not zip_filename:
        return jsonify({"error": "No images found"}), 400

    # Serve the zip file from downloaded_images folder
    return send_from_directory(
        "downloaded_images",
        zip_filename,
        as_attachment=True
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
