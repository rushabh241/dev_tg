import os
import re
from datetime import datetime
import fitz
import time
import sys
import logging
import numpy as np
import pandas as pd
import gc
from flask import Flask
import google.generativeai as genai

# Import the modified GemBidScraper from app5.py
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# from sqlalchemy import text
# from database_config import db_connect

# Use SQLAlchemy core for standalone script
from sqlalchemy import create_engine, text, MetaData, Table
from sqlalchemy.orm import sessionmaker
from database_config import SQLALCHEMY_DATABASE_URI, engine

# Create session for standalone use
Session = sessionmaker(bind=engine)

IS_DEMO_MODE = True  # Add this flag

# Memory optimization settings
MAX_PDF_TEXT_LENGTH = 450000  # Maximum text length to extract from a single PDF
BATCH_SIZE = 5  # Number of tenders to process in each batch (reduced for stability)
BROWSER_RESTART_FREQUENCY = 10  # Restart browser after processing this many bids (very conservative)
ENABLE_MEMORY_OPTIMIZATION = True  # Master switch for memory optimizations

# Incremental processing settings
MAX_CONSECUTIVE_EXISTING = 15  # Stop after seeing this many consecutive existing tenders (reduced)
MAX_PAGES_TO_CHECK = 15  # Maximum number of pages to check before stopping (reduced for faster execution)
NEW_THRESHOLD_PERCENT = 15  # Stop if percentage of new tenders falls below this threshold (increased sensitivity)
ONLY_PROCESS_NEW = True  # If True, only process tenders not already in the database

# API filtering settings
KEYWORD_SCORE_THRESHOLD = 0.1  # Only send tenders with keyword score >= 0.2 to Gemini API
ENABLE_API_FILTERING = True  # Master switch for API filtering

# API rate limiting settings
MAX_RETRIES = 3  # Maximum number of retry attempts for API calls (reduced to avoid long waits)
INITIAL_RETRY_DELAY = 3  # Initial delay in seconds before retrying (reduced)
ENABLE_API_CACHING = True  # Enable caching of API responses

# Browser stability settings
MAX_BROWSER_FAILURES = 3  # Maximum consecutive browser failures before giving up
BROWSER_RESTART_DELAY = 3  # Delay between browser restarts (reduced)
PAGE_LOAD_TIMEOUT = 30  # Page load timeout in seconds (reduced from 45)
IMPLICIT_WAIT_TIME = 8  # Selenium implicit wait time (reduced from 10)
ELEMENT_INTERACTION_DELAY = 2  # Delay between element interactions
NAVIGATION_DELAY = 6  # Delay after navigation operations

# Pagination and content detection settings
MAX_PAGINATION_RETRIES = 2  # Maximum retries for pagination operations
CONTENT_CHANGE_TIMEOUT = 10  # Timeout for waiting for content changes during pagination
PAGES_WITH_NO_NEW_CONTENT_LIMIT = 2  # Stop after this many consecutive pages with no new content

# Download and file processing settings
DOWNLOAD_WAIT_TIME = 10  # Time to wait for downloads to complete
PDF_PROCESSING_TIMEOUT = 30  # Maximum time to spend processing a single PDF
MAX_DOWNLOAD_RETRIES = 2  # Maximum retries for download operations

# Error handling and recovery settings
OPERATION_RETRY_DELAY = 2  # Delay between operation retries
MAX_ELEMENT_SEARCH_TIME = 15  # Maximum time to search for elements
RECOVERY_ATTEMPT_DELAY = 5  # Delay before attempting recovery operations

# Get database path from Flask instance path
temp_app = Flask(__name__)
# INSTANCE_PATH = temp_app.instance_path
# DB_PATH = os.path.join(INSTANCE_PATH, "tender_analyzer.db")
# DB_PATH = None


# Configure logging with proper Unicode handling
try:
    # Try to configure with UTF-8 encoding
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[
                            logging.FileHandler("gem_tenders.log", encoding='utf-8'),
                            logging.StreamHandler()
                        ])
except Exception as e:
    # Fallback to basic configuration if UTF-8 encoding fails
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

# Context manager for browser to ensure proper cleanup
class BrowserContext:
    """Context manager for browser to ensure proper cleanup"""
    def __init__(self, scraper):
        self.scraper = scraper
    
    def __enter__(self):
        self.scraper.start_browser()
        return self.scraper
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.scraper.close()

# Memory cleanup function
def cleanup_memory():
    """Perform memory cleanup"""
    # Force garbage collection
    gc.collect()
    
    try:
        # Try to get process information if psutil is available
        import psutil
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        
        logger.info(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")
    except ImportError:
        logger.info("psutil not installed, skipping detailed memory reporting")
    except Exception as e:
        logger.error(f"Error in memory cleanup: {e}")

# Function to get existing tender IDs from database
# def get_existing_tender_ids(organization_id):
#     """Get a set of tender IDs that already exist in the database for a specific organization"""
#     conn = db_connect()
#     cursor = conn.cursor()
    
#     try:
#         # Modified query to filter by organization_id
#         cursor.execute("SELECT tender_id FROM gem_tenders WHERE organization_id = ?", (organization_id,))
#         existing_ids = {row[0] for row in cursor.fetchall() if row[0] and row[0] != 'unknown_bid'}
#         logger.info(f"Found {len(existing_ids)} existing tender IDs for organization {organization_id}")
#         return existing_ids
#     except Exception as e:
#         logger.error(f"Error retrieving existing tender IDs: {e}")
#         return set()
#     finally:
#         conn.close()


def get_existing_tender_ids(organization_id):
    """Get a set of tender IDs that already exist in the database for a specific organization"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT tender_id FROM gem_tenders WHERE organization_id = :org_id AND tender_id IS NOT NULL AND tender_id != 'unknown_bid'"),
                {"org_id": organization_id}
            )
            existing_ids = {row[0] for row in result if row[0]}
            logger.info(f"Found {len(existing_ids)} existing tender IDs for organization {organization_id}")
            return existing_ids
    except Exception as e:
        logger.error(f"Error retrieving existing tender IDs: {e}")
        return set()

class GemBidScraper:
    """Scraper for GeM bids using Selenium with improved headless mode support and browser stability"""
    
    def __init__(self, download_dir="gem_bids"):
        self.base_url = "https://bidplus.gem.gov.in/bidlists"
        self.download_dir = download_dir
        self.driver = None
        self._last_search_keyword = None
        self._browser_failure_count = 0
        self._last_successful_page = 1
        self._processed_bid_ids = set()  # Track processed bids to detect cycles
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
    
    def _is_browser_alive(self):
        """Check if the browser is still alive and responsive with multiple checks"""
        try:
            if self.driver is None:
                return False
            
            # Multiple health checks
            # Check 1: Get current URL
            current_url = self.driver.current_url
            if not current_url:
                return False
            
            # Check 2: Try to execute a simple script
            result = self.driver.execute_script("return document.readyState;")
            if not result:
                return False
                
            # Check 3: Try to find any element
            self.driver.find_element(By.TAG_NAME, "body")
            
            return True
        except (WebDriverException, Exception) as e:
            logger.warning(f"Browser health check failed: {e}")
            return False
    
    def _force_browser_restart(self, reason="Unknown"):
        """Force restart the browser with proper cleanup"""
        logger.warning(f"Forcing browser restart due to: {reason}")
        try:
            # Close current browser
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
            self.driver = None
            
            # Wait before restart
            time.sleep(BROWSER_RESTART_DELAY)
            
            # Start new browser
            self.start_browser()
            return True
        except Exception as e:
            logger.error(f"Failed to restart browser: {e}")
            return False
    
    def _restart_browser_if_needed(self):
        """Restart browser if it's not responsive"""
        if not self._is_browser_alive():
            logger.warning("Browser is not responsive, restarting...")
            return self._force_browser_restart("Browser not responsive")
        return False
    
    def start_browser(self):
        """Initialize and start the browser with improved headless mode settings"""
        try:
            # Close existing browser if any
            if self.driver:
                self.close()
            
            chrome_options = Options()
            
            # Enhanced headless mode configuration
            chrome_options.add_argument("--headless=new")  # Use new headless mode
            chrome_options.add_argument('--window-size=1920,1080')  # Set proper window size
            chrome_options.add_argument('--start-maximized')
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-plugins")
            chrome_options.add_argument("--disable-images")  # Disable images for faster loading
            chrome_options.add_argument("--disable-javascript-harmony-shipping")
            chrome_options.add_argument("--disable-background-timer-throttling")
            chrome_options.add_argument("--disable-backgrounding-occluded-windows")
            chrome_options.add_argument("--disable-renderer-backgrounding")
            chrome_options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
            chrome_options.add_argument("--force-device-scale-factor=1")  # Prevent scaling issues
            chrome_options.add_argument("--enable-features=NetworkService,NetworkServiceLogging")
            
            # Additional stability arguments
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-running-insecure-content")
            chrome_options.add_argument("--disable-features=VizDisplayCompositor")
            chrome_options.add_argument("--remote-debugging-port=9222")
            
            # Suppress Chrome noise/error messages
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--log-level=3')  # Only fatal errors
            chrome_options.add_argument('--silent')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # User agent to avoid detection
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            # Configure download settings
            prefs = {
                "download.default_directory": os.path.abspath(self.download_dir),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "plugins.always_open_pdf_externally": True,
                "profile.default_content_setting_values.notifications": 2,  # Block notifications
                "profile.default_content_settings.popups": 0,  # Block popups
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Set timeouts
            self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            self.driver.implicitly_wait(IMPLICIT_WAIT_TIME)
            
            # Reset failure count on successful start
            self._browser_failure_count = 0
            
            logger.info("Started Chrome browser successfully in headless mode")
            
        except Exception as e:
            self._browser_failure_count += 1
            logger.error(f"Error starting browser (attempt {self._browser_failure_count}): {e}")
            if self._browser_failure_count >= MAX_BROWSER_FAILURES:
                raise Exception(f"Failed to start browser after {MAX_BROWSER_FAILURES} attempts")
            raise
    
    def close(self):
        """Close the browser"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Closed Chrome browser")
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            finally:
                self.driver = None
    
    def _wait_for_page_load(self, timeout=30):
        """Wait for page to fully load"""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            time.sleep(2)  # Additional wait for dynamic content
            return True
        except TimeoutException:
            logger.warning("Page load timeout")
            return False
    
    def _is_element_clickable_headless(self, element):
        """Check if element is truly clickable in headless mode"""
        try:
            if not (element.is_displayed() and element.is_enabled()):
                return False
            
            # Critical for headless: check element has actual size
            size = element.size
            if size['height'] == 0 or size['width'] == 0:
                return False
            
            location = element.location
            if location['x'] < 0 or location['y'] < 0:
                return False
            
            return True
        except:
            return False
    
    def search_bids(self, keyword=None):
        """Search for bids using a keyword, or browse all bids if no keyword is provided"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Store the keyword for use in case of browser restarts
                self._last_search_keyword = keyword
                
                # Check if browser is alive before proceeding
                if not self._is_browser_alive():
                    logger.warning("Browser not alive, restarting...")
                    self.start_browser()
                
                self.driver.get(self.base_url)
                
                # Add a bit more wait time for the page to fully load
                if not self._wait_for_page_load(timeout=PAGE_LOAD_TIMEOUT):
                    logger.warning("Page load timeout, but continuing...")
                
                time.sleep(NAVIGATION_DELAY)  # Additional wait for dynamic content
                
                if keyword:
                    logger.info(f"Searching for keyword: '{keyword}'")
                    
                    # Try to find the search input field
                    search_input = None
                    input_selectors = [
                        "//input[@placeholder='Enter Keyword']",
                        "//div[contains(@class, 'search-container')]//input",
                        "//div[contains(@class, 'input-group')]//input[@type='text']",
                        "//input[@type='text' and @id='searchBid']",
                        "//input[@type='text']"
                    ]
                    
                    for selector in input_selectors:
                        try:
                            search_input = self.driver.find_element(By.XPATH, selector)
                            logger.info(f"Found search input with selector: {selector}")
                            break
                        except NoSuchElementException:
                            continue
                    
                    if not search_input:
                        raise Exception("Could not find the search input field")
                    
                    # Clear and set the input value
                    search_input.clear()
                    search_input.send_keys(keyword)
                    logger.info(f"Entered keyword: '{keyword}' in search field")
                    time.sleep(1)
                    
                    # Press Enter to search
                    search_input.send_keys(Keys.RETURN)
                    logger.info("Pressed ENTER key to submit search")
                    time.sleep(5)
                else:
                    logger.info("No keyword provided. Browsing all tenders.")
                
                # Set the sort order to "Bid Start Date: Latest First" regardless of search
                logger.info("Applying sort order...")
                time.sleep(3)
                sort_success = self._set_sort_order()

                if sort_success:
                    logger.info("Sort applied successfully")
                else:
                    logger.warning("Sort may have failed, continuing anyway...")

                time.sleep(3)  # Wait for sort to take effect
                return True  # Success
                
            except Exception as e:
                logger.error(f"Error during search attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    logger.info("Retrying search...")
                    self._restart_browser_if_needed()
                    time.sleep(5)
                else:
                    logger.error("All search attempts failed")
                    raise
    
    def _set_sort_order(self):
        """Set sort order to Latest First with robust error handling"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Check browser health first
                if not self._is_browser_alive():
                    logger.error("Browser not alive during sort operation")
                    if self._force_browser_restart("Browser dead during sort"):
                        # Re-navigate to base URL after restart
                        self.driver.get(self.base_url)
                        time.sleep(5)
                        if self._last_search_keyword:
                            self.search_bids(self._last_search_keyword)
                    else:
                        return False
                
                # Scroll to top
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(2)
                
                # Find dropdown button
                sort_dropdown = None
                dropdown_selectors = [
                    "//button[contains(@class, 'dropdown-toggle')]",
                    "//button[@data-toggle='dropdown']"
                ]
                
                for selector in dropdown_selectors:
                    try:
                        elements = self.driver.find_elements(By.XPATH, selector)
                        for element in elements:
                            if element.is_displayed() and element.is_enabled():
                                # Check if this is the sort dropdown by looking at nearby text
                                element_text = element.text.lower()
                                parent_text = ""
                                try:
                                    parent = element.find_element(By.XPATH, "./..")
                                    parent_text = parent.text.lower()
                                except:
                                    pass
                                
                                if 'sort' in element_text or 'sort' in parent_text or 'date' in element_text:
                                    sort_dropdown = element
                                    logger.info(f"Found sort dropdown: '{element.text}'")
                                    break
                        if sort_dropdown:
                            break
                    except:
                        continue
                
                if not sort_dropdown:
                    logger.warning(f"No sort dropdown found (attempt {attempt + 1})")
                    if attempt < max_attempts - 1:
                        time.sleep(3)
                        continue
                    else:
                        return False
                
                # Click dropdown with error handling
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sort_dropdown)
                    time.sleep(2)
                    self.driver.execute_script("arguments[0].click();", sort_dropdown)
                    logger.info("Clicked dropdown")
                    time.sleep(5)  # Wait for dropdown to open
                except Exception as click_error:
                    logger.error(f"Failed to click dropdown (attempt {attempt + 1}): {click_error}")
                    if attempt < max_attempts - 1:
                        continue
                    else:
                        return False
                
                # Target the sort option
                target_options = [
                    "Bid End Date: Latest First",
                    "End Date: Latest First", 
                    "Latest First"
                ]
                
                for target_text in target_options:
                    strategies = [
                        f"//a[normalize-space(text())='{target_text}']",
                        f"//li[normalize-space(text())='{target_text}']",
                        f"//*[normalize-space(text())='{target_text}']",
                        f"//a[contains(normalize-space(text()), 'Latest First')]",
                        f"//li[contains(normalize-space(text()), 'Latest First')]",
                        f"//*[contains(normalize-space(text()), 'Latest First')]"
                    ]
                    
                    for strategy in strategies:
                        try:
                            elements = self.driver.find_elements(By.XPATH, strategy)
                            for element in elements:
                                try:
                                    if element.is_displayed():
                                        element_text = element.text.strip()
                                        if "Latest First" in element_text:
                                            logger.info(f"Clicking sort option: '{element_text}'")
                                            self.driver.execute_script("arguments[0].click();", element)
                                            time.sleep(3)
                                            return True
                                except Exception as element_error:
                                    continue
                        except Exception as strategy_error:
                            continue
                
                logger.warning(f"Sort option not found (attempt {attempt + 1})")
                if attempt < max_attempts - 1:
                    time.sleep(3)
                    continue
                else:
                    return False
                    
            except Exception as e:
                logger.error(f"Sort method attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    # Try to recover browser
                    if not self._is_browser_alive():
                        self._force_browser_restart("Sort operation failed")
                    time.sleep(3)
                    continue
                else:
                    return False
        
        return False
    
    def download_bids(self, max_bids=10, existing_ids=None):
        """Download bid documents with incremental processing using ID-based tracking and improved pagination cycle detection"""
        downloaded_bids = []
        download_info = {}  # Dictionary to store bid_number -> URL mapping
        current_page = 1
        bids_per_page = 10  # GeM typically shows 10 bids per page
        
        # Tracking metrics for incremental processing
        consecutive_existing = 0
        total_seen = 0
        total_new = 0
        pages_with_no_new_content = 0
        seen_bid_ids_across_pages = set()  # Track bid IDs across all pages to detect cycles
        
        # Initialize the set of existing IDs if not provided
        if existing_ids is None:
            existing_ids = set()
        
        # Maximum bids to process before restarting browser
        RESTART_AFTER = BROWSER_RESTART_FREQUENCY
        
        try:
            while len(downloaded_bids) < max_bids and current_page <= MAX_PAGES_TO_CHECK:
                logger.info(f"Processing page {current_page}...")
                
                # Check browser health before processing each page
                browser_recovered = False
                if not self._is_browser_alive():
                    logger.warning("Browser disconnected, attempting to restart and recover...")
                    try:
                        if self._force_browser_restart("Browser disconnected"):
                            # Re-navigate to search results
                            self.search_bids(self._last_search_keyword)
                            # Navigate to current page
                            for page_num in range(2, current_page + 1):
                                if not self._go_to_next_page(page_num - 1):
                                    logger.warning(f"Could not navigate to page {current_page} after browser restart")
                                    break
                            time.sleep(3)
                            browser_recovered = True
                        else:
                            logger.error("Failed to restart browser")
                            break
                    except Exception as restart_error:
                        logger.error(f"Failed to restart browser and recover: {restart_error}")
                        break
                
                # Check if we need to restart the browser for memory management or errors
                restart_needed = False
                restart_reason = ""
                
                # Condition 1: Processed enough bids for memory management
                if len(downloaded_bids) > 0 and len(downloaded_bids) % RESTART_AFTER == 0:
                    restart_needed = True
                    restart_reason = f"memory management after processing {len(downloaded_bids)} bids"
                
                # Condition 2: Accumulated browser errors
                if hasattr(self, '_browser_failure_count') and self._browser_failure_count >= 2:
                    restart_needed = True
                    restart_reason = f"accumulated browser failures ({self._browser_failure_count})"
                
                # Condition 3: Page has been processing for too long
                if hasattr(self, '_pages_processed_since_restart'):
                    self._pages_processed_since_restart += 1
                    if self._pages_processed_since_restart >= 15:  # Restart after 15 pages regardless
                        restart_needed = True
                        restart_reason = f"processed {self._pages_processed_since_restart} pages"
                else:
                    self._pages_processed_since_restart = 1
                
                if restart_needed:
                    logger.info(f"Restarting browser for {restart_reason}")
                    try:
                        self.close()
                        time.sleep(BROWSER_RESTART_DELAY)
                        self.start_browser()
                        
                        # Reset counters
                        self._pages_processed_since_restart = 0
                        self._browser_failure_count = 0
                        
                        # Need to navigate back to the search results and correct page
                        self.search_bids(self._last_search_keyword)
                        
                        # Navigate to current page
                        for page_num in range(2, current_page + 1):
                            if not self._go_to_next_page(page_num - 1):
                                logger.warning(f"Could not return to page {current_page} after browser restart")
                                break
                        
                        time.sleep(3)
                    except Exception as restart_error:
                        logger.error(f"Error during scheduled browser restart: {restart_error}")
                        # Continue with existing browser if restart fails
                
                # Extract and process bids from the current page
                page_bids, page_info, page_stats = self._process_current_page(
                    min(bids_per_page, max_bids - len(downloaded_bids)),
                    existing_ids,
                    seen_bid_ids_across_pages
                )
                
                # Update the statistics
                total_seen += page_stats['total']
                total_new += page_stats['new']
                consecutive_existing = page_stats['consecutive_existing']
                
                # Add results to our collections
                downloaded_bids.extend(page_bids)
                download_info.update(page_info)

                # IMPROVED PAGINATION CYCLE DETECTION
                if page_stats['page_has_repeated_content']:
                    logger.warning(f"PAGINATION CYCLE DETECTED: Page {current_page} contains bid IDs we've seen before")
                    logger.info("This indicates pagination is cycling back to previous results")
                    logger.info("Stopping pagination to avoid infinite loop")
                    break
                
                # Track pages with no new content
                if page_stats['new'] == 0 and current_page > 1:
                    pages_with_no_new_content += 1
                    logger.info(f"Page {current_page} had no new content (consecutive: {pages_with_no_new_content})")
                    if pages_with_no_new_content >= PAGES_WITH_NO_NEW_CONTENT_LIMIT:
                        logger.info(f"Stopping: {pages_with_no_new_content} consecutive pages with no new content")
                        break
                else:
                    pages_with_no_new_content = 0  # Reset counter when we find new content                
                
                # Free memory
                if ENABLE_MEMORY_OPTIMIZATION:
                    cleanup_memory()
                
                # Check stopping conditions for incremental processing
                if consecutive_existing >= MAX_CONSECUTIVE_EXISTING:
                    logger.info(f"Stopping after seeing {consecutive_existing} consecutive existing tenders")
                    break
                    
                # Calculate percentage of new tenders seen so far
                new_percentage = 0 if total_seen == 0 else (total_new / total_seen) * 100
                logger.info(f"New tenders: {total_new}/{total_seen} ({new_percentage:.1f}%)")
                
                # Stop if percentage of new tenders is too low
                if total_seen > 30 and new_percentage < NEW_THRESHOLD_PERCENT:
                    logger.info(f"Stopping as percentage of new tenders ({new_percentage:.1f}%) is below threshold ({NEW_THRESHOLD_PERCENT}%)")
                    break
                
                # Break if we've collected enough bids or if no bids were found on this page
                if len(downloaded_bids) >= max_bids or not page_bids:
                    break
                    
                # Go to next page
                if not self._go_to_next_page(current_page):
                    logger.info("No more pages available")
                    break
                    
                current_page += 1
                time.sleep(3)  # Wait for the new page to load
            
            logger.info(f"Downloaded {len(downloaded_bids)} tender documents across {current_page} pages")
            new_percentage = 0 if total_seen == 0 else (total_new / total_seen) * 100
            logger.info(f"New tenders: {total_new}/{total_seen} ({new_percentage:.1f}%)")
            return downloaded_bids, download_info
                
        except Exception as e:
            logger.error(f"Error in download_bids method: {e}")
            # Return whatever we managed to download
            return downloaded_bids, download_info
    
    def _process_current_page(self, max_bids_to_process, existing_ids=None, seen_bid_ids_across_pages=None):
        """Process bids on the current page with ID-based incremental processing and cycle detection"""
        downloaded_bids = []
        download_info = {}  # Dictionary to store bid_number -> URL mapping
        
        # Statistics for incremental processing
        stats = {
            'total': 0,            # Total tenders seen on this page
            'new': 0,              # New tenders seen on this page
            'existing': 0,         # Existing tenders seen on this page
            'consecutive_existing': 0,  # Count of consecutive existing tenders
            'page_has_repeated_content': False  # Flag for pagination cycle detection
        }
        
        # Initialize the sets if not provided
        if existing_ids is None:
            existing_ids = set()
        if seen_bid_ids_across_pages is None:
            seen_bid_ids_across_pages = set()
    
        try:
            logger.info("Looking for bid elements containing GEM numbers...")
    
            # Save the main page URL to return to after processing each bid
            main_page_url = self.driver.current_url
    
            # Define the bid pattern and list for storing (bid_number, href) tuples
            bid_pattern = re.compile(r'GEM/\d{4}/B/\d+')
            bid_links_info = []  # List of tuples: (bid_number, href)
            current_page_bid_ids = set()  # Track bid IDs on current page
    
            # Define XPaths to search for bid links
            link_patterns = [
                "//a[contains(text(), 'GEM/') and contains(text(), '/B/')]",
                "//a[contains(@href, 'bid') and contains(text(), 'GEM')]",
                "//a[contains(@href, 'showbidDocument')]",
                "//a[contains(@href, 'GeM-Bidding')]",
                "//div[contains(., 'GEM/') and contains(., '/B/')]//a"
            ]
    
            # Search for bid links once and extract their URLs and bid numbers
            processed_hrefs = set()
            for pattern in link_patterns:
                elements = self.driver.find_elements(By.XPATH, pattern)
                if elements:
                    logger.info(f"Found {len(elements)} elements with pattern: {pattern}")
                    for el in elements:
                        try:
                            if el.is_displayed() and el.is_enabled():
                                href = el.get_attribute('href')
                                if href and href not in processed_hrefs:
                                    text = el.text.strip()
                                    bid_number = None
                                    # Try to extract bid number from element text
                                    m = bid_pattern.search(text)
                                    if m:
                                        bid_number = m.group(0)
                                        current_page_bid_ids.add(bid_number)
                                    # Otherwise, use a placeholder
                                    if not bid_number:
                                        bid_number = "unknown_bid"
                                    bid_links_info.append((bid_number, href))
                                    processed_hrefs.add(href)
                        except Exception as e:
                            logger.error(f"Error processing an element: {e}")
                            continue
    
            # Check for pagination cycle - if we've seen these bid IDs before across pages
            if current_page_bid_ids and current_page_bid_ids.issubset(seen_bid_ids_across_pages):
                stats['page_has_repeated_content'] = True
                logger.warning(f"Detected repeated content: {len(current_page_bid_ids)} bid IDs already seen on previous pages")
            else:
                # Add current page bid IDs to our global tracking set
                seen_bid_ids_across_pages.update(current_page_bid_ids)
    
            logger.info(f"Total unique bid links extracted on current page: {len(bid_links_info)}")
    
            # If not enough bid links were found, try a container-based approach
            if len(bid_links_info) < max_bids_to_process:
                logger.info("Looking for bid containers...")
                container_patterns = [
                    "//div[contains(., 'GEM/') and contains(., '/B/')]",
                    "//tr[contains(., 'GEM/') and contains(., '/B/')]",
                    "//div[contains(., 'BID NO:')]"
                ]
                for pattern in container_patterns:
                    containers = self.driver.find_elements(By.XPATH, pattern)
                    if containers:
                        logger.info(f"Found {len(containers)} containers with pattern: {pattern}")
                        for container in containers:
                            try:
                                container_text = container.text
                                m = bid_pattern.search(container_text)
                                if not m:
                                    continue
                                bid_number = m.group(0)
                                current_page_bid_ids.add(bid_number)
                                # Try to find a link within the container
                                links = container.find_elements(By.TAG_NAME, "a")
                                for link in links:
                                    if link.is_displayed() and link.is_enabled():
                                        href = link.get_attribute('href')
                                        if href and href not in processed_hrefs:
                                            bid_links_info.append((bid_number, href))
                                            processed_hrefs.add(href)
                                            break  # One link per container
                            except Exception as e:
                                logger.error(f"Error extracting link from container: {e}")
                                continue
    
            # Process up to max_bids_to_process from the collected bid_links_info
            logger.info(f"Processing {min(len(bid_links_info), max_bids_to_process)} bid links...")
            
            for i, (bid_number, href) in enumerate(bid_links_info[:max_bids_to_process]):
                try:
                    # Update statistics
                    stats['total'] += 1
                    
                    # Check if this is a new tender
                    is_new_tender = bid_number not in existing_ids and bid_number != "unknown_bid"
                    
                    if is_new_tender:
                        stats['new'] += 1
                        stats['consecutive_existing'] = 0
                        logger.info(f"New tender found: {bid_number}")
                    else:
                        stats['existing'] += 1
                        stats['consecutive_existing'] += 1
                        logger.info(f"Existing tender found: {bid_number}")
                        
                        # Skip processing if we're only processing new tenders
                        if ONLY_PROCESS_NEW:
                            logger.info(f"Skipping existing tender: {bid_number}")
                            continue
                    
                    logger.info(f"Processing bid {i+1}: {href} (Bid: {bid_number})")
                    
                    # Check browser health before each navigation
                    if not self._is_browser_alive():
                        logger.error("Browser disconnected during bid processing")
                        break
                    
                    # Navigate directly to the bid URL
                    try:
                        self.driver.get(href)
                        time.sleep(3)  # Wait for any redirection to occur
                    except Exception as nav_error:
                        logger.error(f"Navigation error for bid {bid_number}: {nav_error}")
                        continue
    
                    current_url = self.driver.current_url
                    
                    logger.info(f"Current URL after navigation: {current_url}")
                    
                    # Actually download the bid documents (with strict filtering to avoid logos)
                    try:
                        # Look for tender-specific download buttons/links with very strict filtering
                        download_selectors = [
                            # Most specific selectors first - look for tender documents only
                            "//a[contains(text(), 'Tender Document') and contains(@href, 'download')]",
                            "//a[contains(text(), 'Download Tender Document')]",
                            "//a[contains(text(), 'Download Document') and not(contains(text(), 'Logo'))]",
                            "//button[contains(text(), 'Download Tender')]",
                            "//a[contains(@href, 'tender') and contains(@href, 'download') and not(contains(@href, 'logo'))]",
                            "//a[contains(@href, 'document') and contains(@href, 'download') and not(contains(@href, 'logo'))]",
                            # Very careful general selectors with explicit exclusions
                            "//a[contains(text(), 'Download') and contains(text(), 'PDF') and not(contains(text(), 'Logo')) and not(contains(text(), 'Form'))]"
                        ]
                        
                        download_successful = False
                        attempted_downloads = 0
                        max_download_attempts = 3
                        
                        for selector in download_selectors:
                            if download_successful or attempted_downloads >= max_download_attempts:
                                break
                                
                            try:
                                download_elements = self.driver.find_elements(By.XPATH, selector)
                                logger.info(f"Found {len(download_elements)} elements with selector: {selector}")
                                
                                if download_elements:
                                    for element in download_elements:
                                        if download_successful or attempted_downloads >= max_download_attempts:
                                            break
                                            
                                        if element.is_displayed() and element.is_enabled():
                                            element_text = element.text.lower().strip()
                                            element_href = (element.get_attribute('href') or "").lower()
                                            
                                            # STRICT filtering to avoid logos, forms, etc.
                                            forbidden_terms = ['logo', 'form', 'template', 'guideline', 'help', 'instruction', 'manual', 'sample']
                                            
                                            # Check if any forbidden term is in the text
                                            if any(term in element_text for term in forbidden_terms):
                                                logger.info(f"SKIPPING non-tender download (text): '{element.text}'")
                                                continue
                                            
                                            # Check if any forbidden term is in the href
                                            if any(term in element_href for term in forbidden_terms):
                                                logger.info(f"SKIPPING non-tender download (href): '{element_href}'")
                                                continue
                                            
                                            # Additional check: must contain tender-related terms
                                            tender_terms = ['tender', 'document', 'bid', 'rfp', 'quotation']
                                            has_tender_term = any(term in element_text for term in tender_terms) or any(term in element_href for term in tender_terms)
                                            
                                            # For general "download" links, be extra strict
                                            if element_text == 'download' and not has_tender_term:
                                                logger.info(f"SKIPPING generic download link without tender context: '{element.text}'")
                                                continue
                                            
                                            # Check browser health before clicking
                                            if not self._is_browser_alive():
                                                logger.error("Browser not alive before download attempt")
                                                break
                                            
                                            logger.info(f"ATTEMPTING download: '{element.text}' | href: '{element_href[:100]}'")
                                            attempted_downloads += 1
                                            
                                            try:
                                                # Scroll element into view and click
                                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                                                time.sleep(1)
                                                self.driver.execute_script("arguments[0].click();", element)
                                                time.sleep(DOWNLOAD_WAIT_TIME)  # Wait for download to start
                                                download_successful = True
                                                logger.info(f"SUCCESS: Downloaded from '{element.text}'")
                                                break
                                            except Exception as click_error:
                                                logger.error(f"Click failed for '{element.text}': {click_error}")
                                                continue
                                                
                            except Exception as selector_error:
                                logger.error(f"Error with download selector {selector}: {selector_error}")
                                continue
                        
                        if not download_successful:
                            logger.warning(f"Could not find any safe tender download for bid {bid_number}")
                            # Try to find what download options are actually available
                            try:
                                all_download_links = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Download') or contains(@href, 'download')]")
                                logger.info(f"Available download options ({len(all_download_links)}):")
                                for i, link in enumerate(all_download_links[:5]):  # Show first 5
                                    try:
                                        logger.info(f"  {i+1}. Text: '{link.text}' | href: '{(link.get_attribute('href') or '')[:100]}'")
                                    except:
                                        logger.info(f"  {i+1}. Could not extract link info")
                            except Exception as debug_error:
                                logger.error(f"Error debugging available downloads: {debug_error}")
                                
                    except Exception as download_ex:
                        logger.error(f"Error during document download for bid {bid_number}: {download_ex}")
    
                    # Return to the main page
                    try:
                        self.driver.get(main_page_url)
                        time.sleep(3)
                        self._set_sort_order()  # Reapply sort after returning to the listing page
                        time.sleep(2)  # Give time for sorting to take effect
                    except Exception as return_error:
                        logger.error(f"Error returning to main page: {return_error}")
                        # Try to recover by restarting browser
                        self._restart_browser_if_needed()
                        continue
                                           
                    download_info[bid_number] = href
                    downloaded_bids.append(bid_number)
                    logger.info(f"Processed bid: {bid_number} with final URL: {current_url}")
                    
                    # Update the existing IDs set for future checks
                    existing_ids.add(bid_number)
                    
                    # Explicitly call garbage collection to free memory
                    if ENABLE_MEMORY_OPTIMIZATION:
                        gc.collect()
                
                except Exception as e:
                    logger.error(f"Error processing bid {i+1}: {e}")
                    # Try to recover browser state
                    if not self._is_browser_alive():
                        logger.error("Browser connection lost during bid processing")
                        break
    
            return downloaded_bids, download_info, stats
    
        except Exception as e:
            logger.error(f"Error processing page: {e}")
            return [], {}, stats
    
    def _go_to_next_page(self, current_page):
        """Navigate to the next page of results with verification of content change and improved error handling"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Check browser health first
                if not self._is_browser_alive():
                    logger.error("Browser not alive during pagination")
                    return False
                
                # Get the first bid number BEFORE navigating
                bid_elements_before = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'GEM/') and contains(text(), '/B/')]")
                first_bid_before = bid_elements_before[0].text.strip() if bid_elements_before else ""

                # Find and click the page number button (e.g., 2, 3, etc.)
                next_page_num = current_page + 1
                page_selector = f"//a[text()='{next_page_num}']"
                
                try:
                    next_page_button = self.driver.find_element(By.XPATH, page_selector)
                except NoSuchElementException:
                    logger.info(f"No page {next_page_num} button found - reached end of results")
                    return False

                if next_page_button.is_displayed() and next_page_button.is_enabled():
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", next_page_button)
                    time.sleep(1)
                    self.driver.execute_script("arguments[0].click();", next_page_button)
                    logger.info(f"Clicked to go to page {next_page_num}")
                    time.sleep(5)  # Increased wait time

                    # Wait until the first bid number changes (i.e., new page is actually loaded)
                    try:
                        WebDriverWait(self.driver, 15).until(
                            lambda d: len(d.find_elements(By.XPATH, "//a[contains(text(), 'GEM/') and contains(text(), '/B/')]")) > 0 and
                                     d.find_elements(By.XPATH, "//a[contains(text(), 'GEM/') and contains(text(), '/B/')]")[0].text.strip() != first_bid_before
                        )
                        logger.info(f"Successfully navigated to page {next_page_num}")
                        return True
                    except TimeoutException:
                        logger.warning(f"Content didn't change after clicking page {next_page_num} (attempt {attempt + 1})")
                        if attempt < max_attempts - 1:
                            time.sleep(3)
                            continue
                        else:
                            logger.error(f"Failed to navigate to page {next_page_num} after {max_attempts} attempts")
                            return False
                else:
                    logger.warning(f"Next page button for page {next_page_num} not clickable")
                    return False

            except Exception as e:
                logger.error(f"Pagination attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(3)
                    # Try to recover browser state
                    self._restart_browser_if_needed()
                else:
                    logger.error(f"Pagination failed after {max_attempts} attempts")
                    return False
        
        return False


class GemTenderAnalyzer:
    """Analyzer for GeM tenders using keyword-based matching and Gemini API for metadata"""
    
    def __init__(self, api_key, download_dir="gem_bids"):
        """Initialize the analyzer"""
        self.api_key = api_key
        self.download_dir = download_dir
        
        # Setup Gemini
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        
        logger.info("Initializing analyzer with keyword-only matching (no embeddings/NLP)")
        
        # Create directories if they don't exist
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
        
        # Initialize API call cache if enabled
        if ENABLE_API_CACHING:
            self._api_cache = {}
    
    def call_gemini_with_retry(self, prompt, max_retries=MAX_RETRIES, initial_delay=INITIAL_RETRY_DELAY):
        """Call Gemini API with exponential backoff retry logic and token tracking"""
        # Check cache first if enabled
        cache_key = hash(prompt)
        if ENABLE_API_CACHING and cache_key in self._api_cache:
            logger.info("Using cached API response")
            cached_response, cached_tokens, cached_calls = self._api_cache[cache_key]
            return cached_response, cached_tokens, cached_calls
        
        api_calls_made = 0
        tokens_used = 0
        
        for attempt in range(max_retries):
            try:
                api_calls_made += 1
                logger.info(f"Making Gemini API call (attempt {attempt + 1})")
                
                response = self.model.generate_content(prompt)
                
                # Extract token usage if available
                try:
                    if hasattr(response, 'usage_metadata') and response.usage_metadata:
                        tokens_used = response.usage_metadata.total_token_count
                        logger.info(f"API response received. Tokens used: {tokens_used}")
                    else:
                        # Estimate tokens if not available (rough approximation: 1 token ≈ 4 characters)
                        tokens_used = len(prompt) // 4 + len(response.text) // 4
                        logger.info(f"Token usage estimated: {tokens_used}")
                except Exception as token_error:
                    logger.warning(f"Could not extract token usage: {token_error}")
                    tokens_used = len(prompt) // 4 + len(response.text) // 4
                
                response_text = response.text.strip()
                
                # Cache the successful response if caching is enabled
                if ENABLE_API_CACHING:
                    self._api_cache[cache_key] = (response_text, tokens_used, api_calls_made)
                
                logger.info(f"API call successful. Calls made: {api_calls_made}, Tokens: {tokens_used}")
                return response_text, tokens_used, api_calls_made
                
            except Exception as e:
                error_str = str(e)
                logger.error(f"API call attempt {attempt + 1} failed: {error_str}")
                
                # Check if it's a rate limit error (429)
                if "429" in error_str and attempt < max_retries - 1:
                    # Calculate wait time with exponential backoff
                    wait_time = initial_delay * (2 ** attempt)
                    logger.warning(f"Rate limit exceeded. Retrying in {wait_time} seconds (Attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    # Log and re-raise the error for non-rate-limit errors or if we've exhausted retries
                    if attempt == max_retries - 1:
                        logger.error(f"Maximum retry attempts ({max_retries}) reached. Giving up.")
                    raise
        
        raise Exception(f"Failed to call Gemini API after {max_retries} attempts")
    
    def extract_text_from_pdf(self, pdf_path):
        """Extract text from PDF using PyMuPDF (fitz) with memory limits and Unicode cleanup."""
        try:
            text_parts = []
            total_len = 0

            def add_chunk(chunk: str):
                nonlocal total_len
                if not chunk:
                    return False
                # keep printable + common whitespace; replace others with space
                cleaned = ''.join(c if (c.isprintable() or c in '\n\r\t') else ' ' for c in chunk)
                remaining = MAX_PDF_TEXT_LENGTH - total_len
                if remaining <= 0:
                    return True  # signal we hit the cap
                if len(cleaned) > remaining:
                    cleaned = cleaned[:remaining]
                text_parts.append(cleaned)
                total_len += len(cleaned)
                return total_len >= MAX_PDF_TEXT_LENGTH

            import fitz  # PyMuPDF
            with fitz.open(pdf_path) as doc:
                # Try to open encrypted PDFs with empty password (common case)
                if doc.is_encrypted:
                    try:
                        doc.authenticate("")
                    except Exception:
                        logger.error(f"PDF is encrypted and could not be opened: {pdf_path}")
                        return ""

                # Pass 1: plain text extraction
                for page_num, page in enumerate(doc):
                    try:
                        page_text = page.get_text("text")  # plain, layout-aware text
                        if page_text and add_chunk(page_text):
                            logger.warning(
                                f"PDF {pdf_path} is very large, truncating text at {MAX_PDF_TEXT_LENGTH} chars"
                            )
                            break
                    except Exception as page_error:
                        logger.warning(f"Error extracting text from page {page_num}: {page_error}. Skipping page.")
                        continue

            text = "".join(text_parts)

            # Fallback: if nothing extracted, try blocks (sometimes better on tricky layouts)
            if not text:
                logger.warning(f"Failed to extract text normally from {pdf_path}, trying fallback method (blocks).")
                text_parts = []
                total_len = 0
                with fitz.open(pdf_path) as doc:
                    if doc.is_encrypted:
                        try:
                            doc.authenticate("")
                        except Exception:
                            logger.error(f"PDF is encrypted and could not be opened: {pdf_path}")
                            return ""
                    for page_num, page in enumerate(doc):
                        try:
                            for block in page.get_text("blocks") or []:
                                # block tuple: (x0, y0, x1, y1, text, block_no, block_type)
                                if len(block) >= 5:
                                    if add_chunk(block[4]):
                                        logger.warning(
                                            f"PDF {pdf_path} is very large, truncating text at {MAX_PDF_TEXT_LENGTH} chars"
                                        )
                                        break
                        except Exception as page_error:
                            logger.warning(f"Fallback block extraction failed on page {page_num}: {page_error}.")
                            continue

                text = "".join(text_parts)

            return text
        except Exception as e:
            logger.error(f"Error reading PDF {pdf_path}: {e}")
            return ""


    def get_tender_documents(self, downloaded_bids):
        """Get paths to downloaded tender documents, only for the current batch"""
        tender_docs = {}
        downloaded_bids_set = set(downloaded_bids)  # For fast lookup
        
        try:
            # List PDF files in download directory
            files = [f for f in os.listdir(self.download_dir) if f.endswith('.pdf')]
            logger.info(f"Found {len(files)} PDF files in download directory")
            
            # Match downloaded bids to PDFs by checking PDF content
            for pdf in files:
                pdf_path = os.path.join(self.download_dir, pdf)
                
                # Read first page to extract bid ID
                try:
                    text = self.extract_text_from_pdf(pdf_path)
                    if text:
                        # Extract bid number from PDF content
                        bid_match = re.search(r'GEM/\d{4}/B/\d+', text[:2000])
                        if bid_match:
                            bid_num = bid_match.group(0)
                            # CRITICAL: Only include if this bid is in downloaded_bids
                            if bid_num in downloaded_bids_set:
                                tender_docs[bid_num] = pdf_path
                                logger.info(f"Matched {bid_num} to {pdf}")
                except Exception as e:
                    logger.warning(f"Could not extract bid ID from {pdf}: {e}")
                    continue
            
            logger.info(f"Found {len(tender_docs)} tender documents for {len(downloaded_bids)} downloaded bids")
            return tender_docs
            
        except Exception as e:
            logger.error(f"Error getting tender documents: {e}")
            return {}

    def extract_metadata_with_gemini(self, text):
        """Extract metadata using Gemini API with proper token tracking"""
        # Limit text size for efficiency
        #first_chunk = text[:5000]
        first_chunk = text[:3000]
        
        # Combined prompt to extract all metadata at once
        combined_prompt = f"""
        Extract the following information from this GeM tender document:
        1. A brief 3-4 line description including the tender title, scope, and purpose.
        2. The bid submission due date in DD-MM-YYYY format.
        3. The bid number in the format GEM/YYYY/B/XXXXX.
        
        Format your response as a JSON object with the following keys:
        {{"description": "...", "due_date": "...", "bid_number": "..."}}
        
        If any information is not found, use "Not specified" as the value.
        
        Tender document excerpt:
        {first_chunk}
        """
        
        try:
            logger.info("Calling Gemini API for metadata extraction")
            # Call API with retry logic and token tracking
            response, tokens_used, api_calls = self.call_gemini_with_retry(combined_prompt)
            
            # Parse the JSON response
            try:
                # Extract JSON using regex in case there's extra text
                json_pattern = r'\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}'
                json_match = re.search(json_pattern, response)
                
                if json_match:
                    import json
                    data = json.loads(json_match.group(0))
                else:
                    import json
                    data = json.loads(response)
                    
                description = data.get("description", "Not specified")
                due_date = data.get("due_date", "Not specified")
                bid_number = data.get("bid_number", "Not specified")
                
                # Validate and clean up bid number format
                if bid_number != "Not specified":
                    bid_match = re.search(r'GEM/\d{4}/B/\d+', bid_number)
                    if bid_match:
                        bid_number = bid_match.group(0)
                    else:
                        # If no valid format found, try cleaning it up
                        bid_number = re.sub(r'[^\w/]', '', bid_number)
                
                logger.info(f"Gemini API extraction successful. API calls: {api_calls}, Tokens: {tokens_used}")
                return description, due_date, bid_number, tokens_used, api_calls
                
            except json.JSONDecodeError:
                logger.error(f"Error parsing API response: {response}")
                return "Error extracting details", "Not specified", "Not specified", tokens_used, api_calls
                
        except Exception as e:
            logger.error(f"API error in extract_metadata_with_gemini: {str(e)}")
            return "API error", "Not specified", "Not specified", 0, 0

    def assess_tender_relevance_with_gemini(self, tender_text, company_services, organization_keywords):
        """Use Gemini API to assess if tender is truly relevant to company services"""
        # Limit text size for efficiency
        #text_chunk = tender_text[:8000]  # Larger chunk for better context
        text_chunk = tender_text[:6000]  # Larger chunk for better context
        keywords_str = ", ".join(organization_keywords[:10])  # Top 10 keywords
        
        relevance_prompt = f"""
        Analyze this GeM tender document to determine if it's truly relevant for a company with the following services and keywords.

        COMPANY SERVICES/CAPABILITIES:
        {company_services[:1000]}

        COMPANY KEYWORDS: {keywords_str}

        TENDER DOCUMENT:
        {text_chunk}

        Please assess:
        1. What is the primary scope and main requirements of this tender?
        2. What percentage of the tender work could realistically be fulfilled by the company's services?
        3. Is the company's expertise central to the tender requirements or just a minor component?
        4. Would this tender be a good strategic fit for the company?

        Provide your assessment as a JSON object:
        {{
            "primary_scope": "Brief description of what this tender is mainly about",
            "relevance_percentage": <number between 0-100>,
            "is_central_match": <true/false - whether company services are central to tender requirements>,
            "strategic_fit": <true/false - whether this is a good strategic opportunity>,
            "reasoning": "2-3 sentence explanation of your assessment",
            "recommendation": "SHORTLIST" or "REJECT"
        }}

        Guidelines for assessment:
        - SHORTLIST if relevance_percentage >= 30% AND (is_central_match OR strategic_fit)
        - SHORTLIST if relevance_percentage >= 60% regardless of other factors
        - REJECT if company services are only tangentially related or minor component
        - REJECT if tender is primarily about domains outside company expertise
        """
        
        try:
            logger.info("Calling Gemini API for tender relevance assessment")
            response, tokens_used, api_calls = self.call_gemini_with_retry(relevance_prompt)
            
            # Parse the JSON response
            try:
                # Extract JSON using regex in case there's extra text
                json_pattern = r'\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}'
                json_match = re.search(json_pattern, response)
                
                if json_match:
                    import json
                    data = json.loads(json_match.group(0))
                else:
                    import json
                    data = json.loads(response)
                
                # Extract assessment data
                primary_scope = data.get("primary_scope", "Not specified")
                relevance_percentage = data.get("relevance_percentage", 0)
                is_central_match = data.get("is_central_match", False)
                strategic_fit = data.get("strategic_fit", False)
                reasoning = data.get("reasoning", "No reasoning provided")
                recommendation = data.get("recommendation", "REJECT")
                
                # Ensure relevance_percentage is a number
                try:
                    relevance_percentage = float(relevance_percentage)
                except (ValueError, TypeError):
                    relevance_percentage = 0
                
                # Validate recommendation
                is_relevant = recommendation.upper() == "SHORTLIST"
                
                logger.info(f"Gemini relevance assessment: {relevance_percentage}% relevant, recommendation: {recommendation}")
                logger.info(f"Reasoning: {reasoning[:100]}...")
                
                return {
                    "is_relevant": is_relevant,
                    "relevance_percentage": relevance_percentage,
                    "is_central_match": is_central_match,
                    "strategic_fit": strategic_fit,
                    "primary_scope": primary_scope,
                    "reasoning": reasoning,
                    "recommendation": recommendation,
                    "tokens_used": tokens_used,
                    "api_calls": api_calls
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing relevance API response: {e}")
                logger.error(f"Response was: {response}")
                return {
                    "is_relevant": False,
                    "relevance_percentage": 0,
                    "is_central_match": False,
                    "strategic_fit": False,
                    "primary_scope": "Error parsing response",
                    "reasoning": f"JSON parse error: {str(e)}",
                    "recommendation": "REJECT",
                    "tokens_used": tokens_used,
                    "api_calls": api_calls
                }
                
        except Exception as e:
            logger.error(f"API error in assess_tender_relevance_with_gemini: {str(e)}")
            return {
                "is_relevant": False,
                "relevance_percentage": 0,
                "is_central_match": False,
                "strategic_fit": False,
                "primary_scope": "API error",
                "reasoning": f"API call failed: {str(e)}",
                "recommendation": "REJECT",
                "tokens_used": 0,
                "api_calls": 0
            }

    def extract_metadata(self, text):
        """Extract metadata from GeM tender documents using regex only"""
        # Limit text size for efficiency
        first_chunk = text[:10000]
        
        # Initialize default values
        description = "Not specified"
        due_date = "Not specified"
        bid_number = "Not specified"
        keywords = []
        
        try:
            # Extract bid number using regex pattern
            bid_match = re.search(r'GEM/\d{4}/B/\d+', first_chunk)
            if bid_match:
                bid_number = bid_match.group(0)
            
            # Extract due date using regex patterns for different date formats
            date_patterns = [
                # DD-MM-YYYY or DD/MM/YYYY format
                r'Bid End Date.*?(\d{2}[-/]\d{2}[-/]\d{4})',
                r'Due Date.*?(\d{2}[-/]\d{2}[-/]\d{4})',
                r'बड़ बंद होने क.*?(\d{2}[-/]\d{2}[-/]\d{4})',  # Hindi pattern for Bid End Date
                r'Submission.*?Date.*?(\d{2}[-/]\d{2}[-/]\d{4})',
                r'(\d{2}[-/]\d{2}[-/]\d{4}).*?Bid End',
                r'Last Date.*?(\d{2}[-/]\d{2}[-/]\d{4})',
                r'Closing Date.*?(\d{2}[-/]\d{2}[-/]\d{4})',
                
                # Common date formats with month names
                r'Bid End Date.*?(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',
                r'Due Date.*?(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',
                r'Closing Date.*?(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',
                r'Last Date.*?(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',
                
                # YYYY-MM-DD format (ISO format)
                r'Bid End Date.*?(\d{4}[-/]\d{2}[-/]\d{2})',
                r'Due Date.*?(\d{4}[-/]\d{2}[-/]\d{2})',
                
                # Look for dates with time stamps
                r'Bid End Date.*?(\d{2}[-/]\d{2}[-/]\d{4}[^\d]*\d{2}:\d{2}(?::\d{2})?)',
                r'Due Date.*?(\d{2}[-/]\d{2}[-/]\d{4}[^\d]*\d{2}:\d{2}(?::\d{2})?)',
                
                # Look for timestamps in common Indian format (DD-MMM-YYYY)
                r'Bid End Date.*?(\d{2}[-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-]\d{4})',
                r'Due Date.*?(\d{2}[-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-]\d{4})'
            ]
            
            for pattern in date_patterns:
                date_match = re.search(pattern, first_chunk, re.IGNORECASE | re.DOTALL)
                if date_match:
                    due_date = date_match.group(1)
                    logger.info(f"Found date: {due_date} using pattern: {pattern}")
                    break
            
            # For GeM tenders, extract the "Searched Strings used in GeMARPTS" as the description
            searched_string_patterns = [
                r'Searched\s+Strings\s+used\s+in\s+GeMARPTS\s*\n+(.*?)\n+GeMARPTS\s+.*?Result',  
                r'Searched\s+Strings\s+used\s+in\s+GeMARPTS\s*[:\-–]?\s*(.*)',
                r'Searched String\s*[:\-–]?\s*(.*)'
            ]

            keyword_sections = [
                r'Keywords?\s*[:\-–]?\s*(.*?)(?:\n|$)',
                r'Search Terms?\s*[:\-–]?\s*(.*?)(?:\n|$)',
                r'Key\s+words?\s*[:\-–]?\s*(.*?)(?:\n|$)'
            ]

            for pattern in searched_string_patterns:
                match = re.search(pattern, first_chunk, re.IGNORECASE | re.DOTALL)
                if match:
                    raw = match.group(1).strip()
                    # Clean up and truncate
                    raw = re.sub(r'\s+', ' ', raw)
                    if raw and raw.lower() != "not specified":
                        description = raw[:300]
                        break
            
            for pattern in keyword_sections:
                keyword_match = re.search(pattern, first_chunk, re.IGNORECASE | re.DOTALL)
                if keyword_match:
                    kw_text = keyword_match.group(1).strip()
                    # These are usually comma or comma+space separated
                    kw_list = re.split(r'[,;|/]', kw_text)
                    keywords.extend([kw.strip() for kw in kw_list if kw.strip()])
                    break
            
            # If no keywords found through patterns, extract from description
            if not keywords and description != "Not specified":
                # Extract nouns and noun phrases
                desc_words = description.lower().split()
                # Simple filtering for potential keywords
                filtered_words = [w for w in desc_words if len(w) > 3 and w not in ['this', 'that', 'with', 'from']]
                keywords = filtered_words[:5]  # Limit to top 5
            
            # Log the extracted metadata (with sanitization for logging)
            try:
                # Clean description of problematic characters for logging
                clean_desc = description
                if description != "Not specified":
                    # Limit description to ASCII characters for logging purposes
                    clean_desc = ''.join(c if ord(c) < 128 else '_' for c in description[:50])
                    if len(description) > 50:
                        clean_desc += "..."
                
                logger.info(f"Extracted metadata - Bid: {bid_number}, Due: {due_date}, Description: {clean_desc}")
            except Exception as e:
                logger.warning(f"Error logging metadata: {str(e)}")
            
            return description, due_date, bid_number, keywords
            
        except Exception as e:
            logger.error(f"Error extracting metadata: {str(e)}")
            return description, due_date, bid_number, []
    
    def analyze_tender(self, tender_id, pdf_path, company_services, organization_id, document_url="", search_keyword=None):
        """Analyze a tender document with keyword-based matching and optional API enhancement"""
        try:
            logger.info(f"Analyzing tender: {tender_id}")

            tender_text = self.extract_text_from_pdf(pdf_path)

            # Default initialization
            description = "Not specified"
            due_date = "Not specified"
            extracted_bid_number = tender_id
            matching_keywords = []
            keyword_score = 0.0
            match_score_combined = 0.0
            matches_services = False
            match_reason = "Not specified"
            total_api_calls = 0
            total_tokens_used = 0
            relevance_percentage = 0
            is_central_match = False
            strategic_fit = False
            primary_scope = "Not specified"

            if not tender_text:
                return {
                    "tender_id": tender_id,
                    "pdf_path": pdf_path,
                    "description": description,
                    "due_date": due_date,
                    "keywords": matching_keywords,
                    "matches_services": matches_services,
                    "match_reason": match_reason,
                    "match_score": match_score_combined,
                    "match_score_keyword": keyword_score,
                    "match_score_combined": match_score_combined,
                    "document_url": document_url,
                    "api_calls_made": total_api_calls,
                    "tokens_used": total_tokens_used,
                    "relevance_percentage": relevance_percentage,
                    "is_central_match": is_central_match,
                    "strategic_fit": strategic_fit,
                    "primary_scope": primary_scope
                }

            # Extract metadata
            description, due_date, extracted_bid_number, _ = self.extract_metadata(tender_text[:5000])
            if extracted_bid_number and extracted_bid_number != "Not specified":
                tender_id = extracted_bid_number

            # --- UPDATED PART: Pass search_keyword to filter keyword groups ---
            keyword_groups = get_keywords_for_organization(organization_id, search_keyword=search_keyword)
            print(f"DEBUG: Retrieved {len(keyword_groups)} keyword groups for org {organization_id} with search_keyword='{search_keyword}'")

            keyword_score = 0.0
            matching_keywords = []
            for group in keyword_groups:
                score, matches = compute_keyword_score(tender_text, group["match_keywords"])
                keyword_score += score
                matching_keywords.extend(matches)

            logger.info(f"Keyword score for {tender_id}: {keyword_score:.3f}")
            logger.info(f"Matching keywords: {matching_keywords}")

            # Filtering logic
            if ENABLE_API_FILTERING and keyword_score < KEYWORD_SCORE_THRESHOLD:
                matches_services = keyword_score >= 0.15
                match_reason = f"Keyword-only: score ({keyword_score:.3f}) below threshold. {'Shortlisted' if matches_services else 'Rejected'}."

            else:
                try:
                    api_desc, api_due, api_bid, tokens, calls = self.extract_metadata_with_gemini(tender_text)
                    total_tokens_used += tokens
                    total_api_calls += calls

                    if api_desc != "Not specified":
                        description = api_desc
                    if due_date == "Not specified" and api_due != "Not specified":
                        due_date = api_due
                    if api_bid != "Not specified":
                        tender_id = api_bid

                except Exception as e:
                    logger.warning(f"Metadata extraction failed: {e}")

                try:
                    # --- UPDATED PART: flatten keywords for Gemini relevance ---
                    flat_keywords = []
                    for group in keyword_groups:
                        flat_keywords.append(group["search_keyword"])
                        flat_keywords.extend(group["match_keywords"])

                    relevance_result = self.assess_tender_relevance_with_gemini(
                        tender_text, company_services, flat_keywords
                    )
                    total_tokens_used += relevance_result["tokens_used"]
                    total_api_calls += relevance_result["api_calls"]

                    relevance_percentage = relevance_result["relevance_percentage"]
                    is_central_match = relevance_result["is_central_match"]
                    strategic_fit = relevance_result["strategic_fit"]
                    primary_scope = relevance_result["primary_scope"]
                    recommendation = relevance_result["recommendation"]
                    reasoning = relevance_result["reasoning"]

                    matches_services = recommendation.upper() == "SHORTLIST"
                    match_reason = f"{recommendation.upper()} by AI: {relevance_percentage}% relevance. {reasoning}"
                    ai_score = relevance_percentage / 100.0
                    match_score_combined = (keyword_score * 0.3) + (ai_score * 0.7)

                except Exception as e:
                    logger.warning(f"Relevance assessment failed: {e}")
                    matches_services = keyword_score >= 0.15
                    match_reason = f"AI failed. Using keywords only: score = {keyword_score:.3f}"
                    match_score_combined = keyword_score

            return {
                "tender_id": tender_id,
                "pdf_path": pdf_path,
                "description": description,
                "due_date": due_date,
                "keywords": matching_keywords,
                "matches_services": matches_services,
                "match_reason": match_reason,
                "match_score": match_score_combined,
                "match_score_keyword": keyword_score,
                "match_score_combined": match_score_combined,
                "document_url": document_url,
                "api_calls_made": total_api_calls,
                "tokens_used": total_tokens_used,
                "relevance_percentage": relevance_percentage,
                "is_central_match": is_central_match,
                "strategic_fit": strategic_fit,
                "primary_scope": primary_scope
            }

        except Exception as e:
            logger.error(f"Error analyzing tender {tender_id}: {e}", exc_info=True)
            if ENABLE_MEMORY_OPTIMIZATION:
                gc.collect()
            return {
                "tender_id": tender_id,
                "pdf_path": pdf_path,
                "description": description,
                "due_date": due_date,
                "keywords": matching_keywords,
                "matches_services": matches_services,
                "match_reason": match_reason,
                "match_score": match_score_combined,
                "match_score_keyword": keyword_score,
                "match_score_combined": match_score_combined,
                "document_url": document_url,
                "api_calls_made": total_api_calls,
                "tokens_used": total_tokens_used,
                "relevance_percentage": relevance_percentage,
                "is_central_match": is_central_match,
                "strategic_fit": strategic_fit,
                "primary_scope": primary_scope
            }



# def save_to_db(analysis_result, organization_id):
#     """Save analysis result to database with organization association, preserving original creation_date."""
#     import sqlite3
#     from datetime import datetime

#     conn = db_connect()
#     cursor = conn.cursor()

#     try:
#         # Prepare values
#         keywords_str = "|".join(analysis_result.get("keywords", [])) if "keywords" in analysis_result else ""

#         # INSERT OR IGNORE so we keep original creation_date
#         cursor.execute('''
#             INSERT OR IGNORE INTO gem_tenders
#             (tender_id, description, due_date, creation_date, matches_services, match_reason,
#              document_url, pdf_path, organization_id, match_score, keywords,
#              match_score_keyword, match_score_combined, api_calls_made, tokens_used,
#              relevance_percentage, is_central_match, strategic_fit, primary_scope)
#             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
#         ''', (
#             analysis_result["tender_id"],
#             analysis_result["description"],
#             analysis_result["due_date"],
#             datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
#             1 if analysis_result["matches_services"] else 0,
#             analysis_result["match_reason"],
#             analysis_result.get("document_url", ""),
#             analysis_result.get("pdf_path", ""),
#             organization_id,
#             analysis_result.get("match_score", 0.0),
#             keywords_str,
#             analysis_result.get("match_score_keyword", 0.0),
#             analysis_result.get("match_score_combined", 0.0),
#             analysis_result.get("api_calls_made", 0),
#             analysis_result.get("tokens_used", 0),
#             analysis_result.get("relevance_percentage", 0),
#             1 if analysis_result.get("is_central_match", False) else 0,
#             1 if analysis_result.get("strategic_fit", False) else 0,
#             analysis_result.get("primary_scope", "")
#         ))

#         # UPDATE all other fields except creation_date
#         cursor.execute('''
#             UPDATE gem_tenders
#             SET description = ?, due_date = ?, matches_services = ?, match_reason = ?, 
#                 document_url = ?, pdf_path = ?, match_score = ?, keywords = ?,
#                 match_score_keyword = ?, match_score_combined = ?, api_calls_made = ?, tokens_used = ?,
#                 relevance_percentage = ?, is_central_match = ?, strategic_fit = ?, primary_scope = ?
#             WHERE tender_id = ? AND organization_id = ?
#         ''', (
#             analysis_result["description"],
#             analysis_result["due_date"],
#             1 if analysis_result["matches_services"] else 0,
#             analysis_result["match_reason"],
#             analysis_result.get("document_url", ""),
#             analysis_result.get("pdf_path", ""),
#             analysis_result.get("match_score", 0.0),
#             keywords_str,
#             analysis_result.get("match_score_keyword", 0.0),
#             analysis_result.get("match_score_combined", 0.0),
#             analysis_result.get("api_calls_made", 0),
#             analysis_result.get("tokens_used", 0),
#             analysis_result.get("relevance_percentage", 0),
#             1 if analysis_result.get("is_central_match", False) else 0,
#             1 if analysis_result.get("strategic_fit", False) else 0,
#             analysis_result.get("primary_scope", ""),
#             analysis_result["tender_id"],
#             organization_id
#         ))

#         conn.commit()
#         print(f"Saved or updated tender {analysis_result['tender_id']} for organization {organization_id} without resetting creation_date.")

#     except Exception as e:
#         print(f"Database error: {e}")
#         conn.rollback()
#     finally:
#         conn.close()


def save_to_db(analysis_result, organization_id):
    """Save analysis result to database with organization association"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        # Prepare values
        keywords_str = "|".join(analysis_result.get("keywords", [])) if "keywords" in analysis_result else ""
        
        with engine.connect() as conn:
            # Check if tender already exists
            result = conn.execute(
                text("SELECT id FROM gem_tenders WHERE tender_id = :tender_id AND organization_id = :org_id"),
                {
                    "tender_id": analysis_result["tender_id"],
                    "org_id": organization_id
                }
            )
            existing_tender = result.fetchone()
            
            if existing_tender:
                # Update existing tender
                conn.execute(text("""
                    UPDATE gem_tenders SET
                        description = :description,
                        due_date = :due_date,
                        matches_services = :matches_services,
                        match_reason = :match_reason,
                        document_url = :document_url,
                        pdf_path = :pdf_path,
                        match_score = :match_score,
                        keywords = :keywords,
                        match_score_keyword = :match_score_keyword,
                        match_score_combined = :match_score_combined,
                        api_calls_made = :api_calls_made,
                        tokens_used = :tokens_used,
                        relevance_percentage = :relevance_percentage,
                        is_central_match = :is_central_match,
                        strategic_fit = :strategic_fit,
                        primary_scope = :primary_scope
                    WHERE tender_id = :tender_id AND organization_id = :org_id
                """), {
                    "description": analysis_result["description"],
                    "due_date": analysis_result["due_date"],
                    "matches_services": bool(analysis_result["matches_services"]),
                    "match_reason": analysis_result["match_reason"],
                    "document_url": analysis_result.get("document_url", ""),
                    "pdf_path": analysis_result.get("pdf_path", ""),
                    "match_score": analysis_result.get("match_score", 0.0),
                    "keywords": keywords_str,
                    "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
                    "match_score_combined": analysis_result.get("match_score_combined", 0.0),
                    "api_calls_made": analysis_result.get("api_calls_made", 0),
                    "tokens_used": analysis_result.get("tokens_used", 0),
                    "relevance_percentage": analysis_result.get("relevance_percentage", 0),
                    "is_central_match": bool(analysis_result.get("is_central_match", False)),
                    "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
                    "primary_scope": analysis_result.get("primary_scope", ""),
                    "tender_id": analysis_result["tender_id"],
                    "org_id": organization_id
                })
            else:
                # Create new tender
                conn.execute(text("""
                    INSERT INTO gem_tenders (
                        tender_id, description, due_date, creation_date, matches_services, match_reason,
                        document_url, pdf_path, organization_id, match_score, keywords,
                        match_score_keyword, match_score_combined, api_calls_made, tokens_used,
                        relevance_percentage, is_central_match, strategic_fit, primary_scope
                    ) VALUES (
                        :tender_id, :description, :due_date, :creation_date, :matches_services, :match_reason,
                        :document_url, :pdf_path, :org_id, :match_score, :keywords,
                        :match_score_keyword, :match_score_combined, :api_calls_made, :tokens_used,
                        :relevance_percentage, :is_central_match, :strategic_fit, :primary_scope
                    )
                """), {
                    "tender_id": analysis_result["tender_id"],
                    "description": analysis_result["description"],
                    "due_date": analysis_result["due_date"],
                    "creation_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "matches_services": bool(analysis_result["matches_services"]),
                    "match_reason": analysis_result["match_reason"],
                    "document_url": analysis_result.get("document_url", ""),
                    "pdf_path": analysis_result.get("pdf_path", ""),
                    "org_id": organization_id,
                    "match_score": analysis_result.get("match_score", 0.0),
                    "keywords": keywords_str,
                    "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
                    "match_score_combined": analysis_result.get("match_score_combined", 0.0),
                    "api_calls_made": analysis_result.get("api_calls_made", 0),
                    "tokens_used": analysis_result.get("tokens_used", 0),
                    "relevance_percentage": analysis_result.get("relevance_percentage", 0),
                    "is_central_match": bool(analysis_result.get("is_central_match", False)),
                    "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
                    "primary_scope": analysis_result.get("primary_scope", "")
                })
            
            conn.commit()
            print(f"Saved or updated tender {analysis_result['tender_id']} for organization {organization_id}")

    except Exception as e:
        print(f"Database error: {e}")
        raise


# def get_service_definition(organization_id):
#     """Get the service definition from the database for a specific organization"""
#     conn = db_connect()
#     cursor = conn.cursor()
    
#     try:
#         # Modified query to filter by organization_id
#         cursor.execute('''
#         SELECT definition FROM service_product_definition 
#         WHERE organization_id = ? 
#         ORDER BY updated_at DESC LIMIT 1
#         ''', (organization_id,))
        
#         result = cursor.fetchone()
        
#         if result:
#             return result[0]
#         else:
#             logger.warning(f"No service definition found for organization {organization_id}")
#             return ""
            
#     except Exception as e:
#         logger.error(f"Error getting service definition: {e}")
#         return ""
#     finally:
#         conn.close()

def get_service_definition(organization_id):
    """Get the service definition from the database for a specific organization"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT definition FROM service_product_definition WHERE organization_id = :org_id ORDER BY updated_at DESC LIMIT 1"),
                {"org_id": organization_id}
            )
            row = result.fetchone()
            
            if row and row[0]:
                return row[0]
            else:
                logger.warning(f"No service definition found for organization {organization_id}")
                return ""
    except Exception as e:
        logger.error(f"Error getting service definition: {e}")
        return ""

import sqlite3
import re
import logging

logger = logging.getLogger(__name__)

# def get_keywords_for_organization(organization_id, override_keywords=None, search_keyword=None):
#     """Get keywords for organization, optionally filtered by search keyword"""
#     if override_keywords and override_keywords != ["none"]:
#         logger.info(f"Using override keywords: {override_keywords}")
#         return parse_keyword_string(",".join(override_keywords))

#     conn = db_connect()
#     cursor = conn.cursor()

#     try:
#         print(f"DEBUG: Looking for keywords in gem_search_configurations for organization_id: {organization_id}")
        
#         # Use JOIN with user table to get organization_id, just like the scheduler does
#         cursor.execute('''
#         SELECT c.search_keyword FROM gem_search_configurations c
#         JOIN user u ON c.created_by = u.id
#         WHERE u.organization_id = ? AND c.search_keyword IS NOT NULL AND c.search_keyword != ''
#         ORDER BY c.id DESC LIMIT 1
#         ''', (organization_id,))
        
#         result = cursor.fetchone()
#         print(f"DEBUG: Query result from gem_search_configurations: {result}")
        
#         if result and result[0]:
#             raw_keywords = result[0].strip()
#             print(f"DEBUG: Raw keywords found: '{raw_keywords}'")
#             parsed_keywords = parse_keyword_string(raw_keywords)
            
#             # NEW: Filter by search keyword if provided
#             if search_keyword:
#                 search_keyword_lower = search_keyword.lower().strip()
#                 print(f"DEBUG: Filtering keywords for search term: '{search_keyword_lower}'")
                
#                 filtered_keywords = []
#                 for group in parsed_keywords:
#                     group_search_keyword = group["search_keyword"].lower().strip()
#                     print(f"DEBUG: Comparing '{search_keyword_lower}' with group '{group_search_keyword}'")
                    
#                     if group_search_keyword == search_keyword_lower:
#                         filtered_keywords.append(group)
#                         print(f"DEBUG: MATCH FOUND - Using keyword group: {group}")
                
#                 if filtered_keywords:
#                     logger.info(f"Retrieved {len(filtered_keywords)} keyword groups for organization {organization_id} filtered by '{search_keyword}'")
#                     return filtered_keywords
#                 else:
#                     logger.warning(f"No keyword groups found for search term '{search_keyword}' in organization {organization_id}")
#                     return []
#             else:
#                 logger.info(f"Retrieved {len(parsed_keywords)} keyword groups for organization {organization_id}")
#                 return parsed_keywords
#         else:
#             logger.warning(f"No keywords found in gem_search_configurations for organization {organization_id}")
#             return []
            
#     except Exception as e:
#         logger.error(f"Error getting keywords from gem_search_configurations: {e}")
#         print(f"DEBUG: Exception details: {str(e)}")
#         return []
#     finally:
#         conn.close()

def get_keywords_for_organization(organization_id, override_keywords=None, search_keyword=None):
    """Get keywords for organization, optionally filtered by search keyword"""
    if override_keywords and override_keywords != ["none"]:
        logger.info(f"Using override keywords: {override_keywords}")
        return parse_keyword_string(",".join(override_keywords))

    from sqlalchemy import text
    from database_config import engine
    
    try:
        print(f"DEBUG: Looking for keywords in gem_search_configurations for organization_id: {organization_id}")
        
        with engine.connect() as conn:
            # Use JOIN with user table to get organization_id
            result = conn.execute(text("""
                SELECT c.search_keyword FROM gem_search_configurations c
                JOIN "user" u ON c.created_by = u.id
                WHERE u.organization_id = :org_id AND c.search_keyword IS NOT NULL AND c.search_keyword != ''
                ORDER BY c.id DESC LIMIT 1
            """), {"org_id": organization_id})
            
            row = result.fetchone()
            
            if row and row[0]:
                raw_keywords = row[0].strip()
                print(f"DEBUG: Raw keywords found: '{raw_keywords}'")
                parsed_keywords = parse_keyword_string(raw_keywords)
                
                # Filter by search keyword if provided
                if search_keyword:
                    search_keyword_lower = search_keyword.lower().strip()
                    print(f"DEBUG: Filtering keywords for search term: '{search_keyword_lower}'")
                    
                    filtered_keywords = []
                    for group in parsed_keywords:
                        group_search_keyword = group["search_keyword"].lower().strip()
                        print(f"DEBUG: Comparing '{search_keyword_lower}' with group '{group_search_keyword}'")
                        
                        if group_search_keyword == search_keyword_lower:
                            filtered_keywords.append(group)
                            print(f"DEBUG: MATCH FOUND - Using keyword group: {group}")
                    
                    if filtered_keywords:
                        logger.info(f"Retrieved {len(filtered_keywords)} keyword groups for organization {organization_id} filtered by '{search_keyword}'")
                        return filtered_keywords
                    else:
                        logger.warning(f"No keyword groups found for search term '{search_keyword}' in organization {organization_id}")
                        return []
                else:
                    logger.info(f"Retrieved {len(parsed_keywords)} keyword groups for organization {organization_id}")
                    return parsed_keywords
            else:
                logger.warning(f"No keywords found in gem_search_configurations for organization {organization_id}")
                return []
                
    except Exception as e:
        logger.error(f"Error getting keywords from gem_search_configurations: {e}")
        print(f"DEBUG: Exception details: {str(e)}")
        return []


def parse_keyword_string(raw_string):
    """Helper to parse 'Search(match1, match2), Other(matchA, matchB)' into grouped dicts."""
    print(f"DEBUG: Raw keyword string: '{raw_string}'")
    
    parsed = []
    # Updated regex to handle optional whitespace after ),
    groups = [grp.strip() for grp in re.split(r'\),\s*', raw_string) if grp.strip()]
    print(f"DEBUG: Split groups: {groups}")
    
    for group in groups:
        group = group.strip().rstrip(")")
        print(f"DEBUG: Processing group: '{group}'")
        
        if "(" in group:
            search, inside = group.split("(", 1)
            search = search.strip().lower()
            matches = [kw.strip().lower() for kw in inside.split(",") if kw.strip()]
            parsed.append({
                "search_keyword": search,
                "match_keywords": matches
            })
            print(f"DEBUG: Parsed - search: '{search}', matches: {matches}")
        else:
            search_kw = group.strip().lower()
            parsed.append({
                "search_keyword": search_kw,
                "match_keywords": []
            })
            print(f"DEBUG: Simple keyword: '{search_kw}'")
    
    print(f"DEBUG: Final parsed keywords: {parsed}")
    return parsed


def compute_keyword_score(tender_text, keywords):
    """Compute a score based on keyword matches in tender text and return matching keywords"""
    print(f"DEBUG: === KEYWORD SCORING START ===")
    print(f"DEBUG: Text length: {len(tender_text) if tender_text else 0} chars")
    print(f"DEBUG: Keywords to match: {keywords}")
    
    if not tender_text or not keywords:
        print(f"DEBUG: Early return - no text or no keywords")
        return 0.0, []

    # Normalize text
    text = tender_text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    
    print(f"DEBUG: Normalized text preview (first 300 chars): {text[:300]}")

    keyword_hits = 0
    matching_keywords = []
    
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if kw_lower in text:
            print(f"  ✓ MATCH: '{kw_lower}'")
            keyword_hits += 1
            matching_keywords.append(kw)
        else:
            print(f"  ✗ NO MATCH: '{kw_lower}'")

    score = round(min(keyword_hits / len(keywords), 1.0), 3)
    print(f"DEBUG: Final score: {score} ({keyword_hits}/{len(keywords)} keywords matched)")
    print(f"DEBUG: Matching keywords: {matching_keywords}")
    print(f"DEBUG: === KEYWORD SCORING END ===\n")
    
    return score, matching_keywords

# def init_database():
#     """Initialize the database schema and handle migrations"""
#     conn = db_connect()
#     cursor = conn.cursor()
    
#     try:
#         # Create gem_tenders table with all required columns including new AI assessment fields
#         cursor.execute('''
#         CREATE TABLE IF NOT EXISTS gem_tenders (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             tender_id TEXT,
#             description TEXT,
#             due_date TEXT,
#             creation_date TEXT,
#             matches_services BOOLEAN,
#             match_reason TEXT,
#             match_score REAL DEFAULT 0.0,
#             keywords TEXT DEFAULT '',
#             document_url TEXT,
#             pdf_path TEXT,
#             organization_id INTEGER NOT NULL,
#             match_score_keyword REAL DEFAULT 0.0,
#             match_score_combined REAL DEFAULT 0.0,
#             api_calls_made INTEGER DEFAULT 0,
#             tokens_used INTEGER DEFAULT 0,
#             relevance_percentage REAL DEFAULT 0.0,
#             is_central_match BOOLEAN DEFAULT 0,
#             strategic_fit BOOLEAN DEFAULT 0,
#             primary_scope TEXT DEFAULT '',
#             UNIQUE(tender_id, organization_id)
#         )
#         ''')
        
#         # Check if new columns exist and add them if they don't
#         cursor.execute("PRAGMA table_info(gem_tenders)")
#         existing_columns = {row[1] for row in cursor.fetchall()}
        
#         # Define new columns that need to be added
#         new_columns = {
#             'relevance_percentage': 'REAL DEFAULT 0.0',
#             'is_central_match': 'BOOLEAN DEFAULT 0',
#             'strategic_fit': 'BOOLEAN DEFAULT 0',
#             'primary_scope': 'TEXT DEFAULT ""'
#         }
        
#         # Add missing columns
#         for column_name, column_def in new_columns.items():
#             if column_name not in existing_columns:
#                 try:
#                     cursor.execute(f"ALTER TABLE gem_tenders ADD COLUMN {column_name} {column_def}")
#                     logger.info(f"Added new column {column_name} to gem_tenders table")
#                 except sqlite3.OperationalError as e:
#                     if "duplicate column name" not in str(e).lower():
#                         logger.error(f"Failed to add column {column_name}: {e}")
        
#         # Create service_product_definition table if it doesn't exist
#         cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='service_product_definition'")
#         if not cursor.fetchone():
#             cursor.execute('''
#             CREATE TABLE IF NOT EXISTS service_product_definition (
#                 id INTEGER PRIMARY KEY AUTOINCREMENT,
#                 definition TEXT,
#                 keywords TEXT,
#                 created_at TEXT,
#                 updated_at TEXT,
#                 user_id INTEGER,
#                 organization_id INTEGER NOT NULL
#             )
#             ''')
#             logger.info("Created service_product_definition table")
        
#         conn.commit()
#         logger.info("Database initialized successfully with AI assessment columns")
        
#     except Exception as e:
#         logger.error(f"Error initializing database: {e}")
#         conn.rollback()
#     finally:
#         conn.close()

def init_database():
    """Initialize the database schema - tables should already exist"""
    # after executing migrations, tables should already exist
    logger.info("Database tables should already exist via Flask migrations")

def main(search_keyword=None, max_tenders=30, organization_id=None, domain_keywords=None):
    """Main function to run the GeM Tender Analyzer with API filtering and improved browser stability"""
    global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
    
    logger.info("=" * 80)
    logger.info("GeM Tender Analyzer with FIXED Pagination and Browser Stability")
    logger.info("=" * 80)
    
    # Use environment variable for API key
    GEMINI_API_KEY = "AIzaSyA5OCkUojazM82qJ2x2p_ik_NojIaARXug"  # Replace with your actual API key
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY environment variable not set")
        return
    
    # Initialize database
    init_database()
    
    # Interactive mode - ask for organization if not provided
    if organization_id is None:
        try:
            organization_id = int(input("Enter organization ID: ").strip())
        except ValueError:
            logger.error("Invalid organization ID provided")
            return
    
    # Get set of existing tender IDs from the database for this organization
    existing_ids = get_existing_tender_ids(organization_id)
    logger.info(f"Retrieved {len(existing_ids)} existing tender IDs for organization {organization_id}")
    
    # Get service definition from database for this organization
    company_services = get_service_definition(organization_id)
    
    if not company_services:
        logger.error(f"No service definition found for organization {organization_id}. Please define your services in the web application first.")
        return

    # Ask if user wants to do incremental processing in interactive mode
    if search_keyword is None:  # Interactive mode
        incremental = input("Do you want to only process new tenders? (y/n, default: y): ").strip().lower()
        ONLY_PROCESS_NEW = incremental != 'n'
        
        # Get user input for keyword - allow empty for no filtering
        search_keyword = input("Enter keyword to search for tenders (leave empty to browse all tenders): ").strip()
        search_keyword = search_keyword if search_keyword else None

        max_tenders = input("Enter maximum number of tenders to download (default 30): ")
        max_tenders = int(max_tenders) if max_tenders.strip() else 30

        # Ask about API filtering
        api_filtering = input(f"Enable API filtering (only analyze tenders with keyword score > {KEYWORD_SCORE_THRESHOLD})? (y/n, default: y): ").strip().lower()
        ENABLE_API_FILTERING = api_filtering != 'n'

    if search_keyword:
        logger.info(f"Searching for keyword: '{search_keyword}'")
    else:
        logger.info("Browsing all available tenders")
    
    # Limit company services display length to avoid logging issues
    service_display = company_services[:50] + "..." if len(company_services) > 50 else company_services
    logger.info(f"Company services: {service_display}")
    
    if ENABLE_API_FILTERING:
        logger.info(f"API filtering enabled - only tenders with keyword score >= {KEYWORD_SCORE_THRESHOLD} will be sent to Gemini API")
    
    # Initialize analyzer with API key
    download_dir = "gem_bids"
    analyzer = GemTenderAnalyzer(GEMINI_API_KEY, download_dir)
    
    # Initialize scraper but don't start browser yet
    scraper = GemBidScraper(download_dir)
    
    # Tracking variables for this session
    session_api_calls = 0
    session_tokens_used = 0
    tenders_filtered_out = 0
    tenders_analyzed_with_api = 0
    
    # Use context manager to ensure browser is always closed
    with BrowserContext(scraper) as browser:
        try:
            # Search and download tenders
            logger.info("Starting the browser and downloading tenders...")
            browser.search_bids(search_keyword)
            downloaded_bids, download_info = browser.download_bids(max_bids=max_tenders, existing_ids=existing_ids)
            
            if not downloaded_bids:
                logger.warning("No new tenders were downloaded. Try again with a different keyword or disable incremental processing.")
                return
                
            # Get tender documents
            tender_docs = analyzer.get_tender_documents(downloaded_bids)
            
            # Process tenders in batches to avoid memory issues
            all_analysis_results = []
            
            # Convert to list of tuples for batch processing
            tender_items = list(tender_docs.items())
            
            for i in range(0, len(tender_items), BATCH_SIZE):
                batch = tender_items[i:i+BATCH_SIZE]
                logger.info(f"Processing batch {i//BATCH_SIZE + 1} of {(len(tender_items) + BATCH_SIZE - 1) // BATCH_SIZE}")
                
                # Analyze each tender in the batch
                batch_results = []
                for tender_id, pdf_path in batch:
                    # Get document URL if available
                    original_url = download_info.get(tender_id, "")
                    print(f"DEBUG: Passing URL to analyzer for {tender_id}: '{original_url}'")

                    # --- UPDATED PART: Pass search_keyword to analyzer ---
                    analysis = analyzer.analyze_tender(tender_id, pdf_path, company_services, organization_id, original_url, search_keyword)

                    # Track API usage for this session
                    session_api_calls += analysis.get("api_calls_made", 0)
                    session_tokens_used += analysis.get("tokens_used", 0)
                    
                    # Track filtering statistics
                    if analysis.get("api_calls_made", 0) > 0:
                        tenders_analyzed_with_api += 1
                    else:
                        tenders_filtered_out += 1

                    # Now fix document_url if tender_id changed inside analysis
                    if analysis["tender_id"] != tender_id and not analysis.get("document_url"):
                        # Attempt to map with new tender_id
                        analysis["document_url"] = download_info.get(analysis["tender_id"], original_url)
                    
                    batch_results.append(analysis)
                    
                    # Save to database with organization_id
                    save_to_db(analysis, organization_id)
                    
                    # Update the existing IDs set for future checks
                    existing_ids.add(analysis["tender_id"])
                    
                    # Explicitly call garbage collection to free memory
                    if ENABLE_MEMORY_OPTIMIZATION:
                        gc.collect()
                
                # Add batch results to all results
                all_analysis_results.extend(batch_results)
                
                # Free memory between batches
                if ENABLE_MEMORY_OPTIMIZATION:
                    batch_results = None
                    gc.collect()
                    cleanup_memory()
            
            # Output enhanced summary with API usage statistics
            matching_count = len([r for r in all_analysis_results if r["matches_services"]])
            total_count = len(all_analysis_results)
            
            logger.info("\n=== Analysis Summary ===")
            logger.info(f"Found {matching_count} matching tenders out of {total_count} analyzed")
            logger.info(f"Tenders analyzed with API: {tenders_analyzed_with_api}")
            logger.info(f"Tenders filtered out (keyword score < {KEYWORD_SCORE_THRESHOLD}): {tenders_filtered_out}")
            logger.info(f"Total API calls made: {session_api_calls}")
            logger.info(f"Total tokens used: {session_tokens_used}")
            if tenders_analyzed_with_api > 0:
                logger.info(f"Average tokens per API-analyzed tender: {session_tokens_used / tenders_analyzed_with_api:.1f}")
            
            # Calculate cost savings
            if ENABLE_API_FILTERING and tenders_filtered_out > 0:
                estimated_tokens_saved = tenders_filtered_out * (session_tokens_used / max(tenders_analyzed_with_api, 1))
                logger.info(f"Estimated tokens saved by filtering: {estimated_tokens_saved:.0f}")
            
            # Save to CSV for easy access
            try:
                matching_tenders = [result for result in all_analysis_results if result["matches_services"]]
                matching_df = pd.DataFrame(matching_tenders)
                
                if not matching_df.empty:
                    matching_output_file = os.path.join(download_dir, f"matching_tenders_org{organization_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
                    matching_df.to_csv(matching_output_file, index=False, encoding='utf-8-sig')
                    logger.info(f"Matching tenders saved to {matching_output_file}")
                
                # All tenders with API usage columns
                all_df = pd.DataFrame(all_analysis_results)
                all_output_file = os.path.join(download_dir, f"all_tenders_org{organization_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
                all_df.to_csv(all_output_file, index=False, encoding='utf-8-sig')
                logger.info(f"All tenders saved to {all_output_file}")
            except Exception as e:
                logger.error(f"Error saving CSV files: {e}")
                # Try with a more restrictive approach
                try:
                    # Create sanitized versions of the data
                    sanitized_results = []
                    for result in all_analysis_results:
                        sanitized_result = result.copy()
                        for key in ['description', 'match_reason']:
                            if key in sanitized_result:
                                sanitized_result[key] = ''.join(c if ord(c) < 128 else '_' for c in sanitized_result[key])
                        sanitized_results.append(sanitized_result)
                    
                    all_df = pd.DataFrame(sanitized_results)
                    all_output_file = os.path.join(download_dir, f"all_tenders_org{organization_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_sanitized.csv")
                    all_df.to_csv(all_output_file, index=False)
                    logger.info(f"Sanitized tenders saved to {all_output_file}")
                except Exception as e2:
                    logger.error(f"Error saving sanitized CSV files: {e2}")
        
        except Exception as e:
            logger.error(f"Error in main function: {e}", exc_info=True)
            
    # Final cleanup and summary
    if ENABLE_MEMORY_OPTIMIZATION:
        cleanup_memory()
    
    logger.info("GeM Tender Analyzer completed successfully!")

def main_cli(search_keyword, max_tenders, organization_id, domain_keywords=None):
    """Entry point for CLI/scheduled execution with API filtering enabled by default"""
    global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
    ONLY_PROCESS_NEW = True
    ENABLE_API_FILTERING = True  # Enable API filtering by default for CLI
    logger.info(f"Running FIXED gem_nlp_api.py via CLI for organization {organization_id} with API filtering enabled")
    main(search_keyword=search_keyword, max_tenders=max_tenders, organization_id=organization_id, domain_keywords=domain_keywords)

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            search_keyword = sys.argv[1] if sys.argv[1].lower() != "none" else None
            max_tenders = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            organization_id = int(sys.argv[3]) if len(sys.argv) > 3 else None
            domain_keywords = []
            if len(sys.argv) > 4 and sys.argv[4] != "NONE":
                domain_keywords = [kw.strip().lower() for kw in sys.argv[4].split('|')]
            logger.info("Running FIXED gem_nlp_api.py with CLI arguments")
            main_cli(search_keyword, max_tenders, organization_id, domain_keywords)
        else:
            logger.info("Running FIXED gem_nlp_api.py in interactive mode")
            main()
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")