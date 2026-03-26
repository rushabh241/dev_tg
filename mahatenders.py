import os
import re
from datetime import datetime
import time 
import sys
import logging
import pandas as pd
import gc
import json
from flask import Flask
from bs4 import BeautifulSoup

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Database imports
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database_config import SQLALCHEMY_DATABASE_URI, engine

# Create session for standalone use
Session = sessionmaker(bind=engine)

# Memory optimization settings
BATCH_SIZE = 5
BROWSER_RESTART_FREQUENCY = 10
ENABLE_MEMORY_OPTIMIZATION = True

# Incremental processing settings
MAX_CONSECUTIVE_EXISTING = 15
MAX_PAGES_TO_CHECK = 15
NEW_THRESHOLD_PERCENT = 15
ONLY_PROCESS_NEW = True

# Browser stability settings
MAX_BROWSER_FAILURES = 3
BROWSER_RESTART_DELAY = 3
PAGE_LOAD_TIMEOUT = 30
IMPLICIT_WAIT_TIME = 8
ELEMENT_INTERACTION_DELAY = 2
NAVIGATION_DELAY = 6

# Pagination and content detection settings
MAX_PAGINATION_RETRIES = 2
CONTENT_CHANGE_TIMEOUT = 10
PAGES_WITH_NO_NEW_CONTENT_LIMIT = 2

# Error handling and recovery settings
OPERATION_RETRY_DELAY = 2
MAX_ELEMENT_SEARCH_TIME = 15
RECOVERY_ATTEMPT_DELAY = 5

# Configure logging with proper Unicode handling
try:
    # Try to configure with UTF-8 encoding
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[
                            logging.FileHandler("maha_tenders.log", encoding='utf-8'),
                            logging.StreamHandler()
                        ])
except Exception as e:
    # Fallback to basic configuration if UTF-8 encoding fails
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

# Define MahaBids folder
MAHA_BIDS_FOLDER = "maha_bids"

# Create the folder if it doesn't exist
if not os.path.exists(MAHA_BIDS_FOLDER):
    os.makedirs(MAHA_BIDS_FOLDER)
    logger.info(f"Created folder: {MAHA_BIDS_FOLDER}")

class BrowserContext:
    """Context manager for browser to ensure proper cleanup"""
    def __init__(self, scraper):
        self.scraper = scraper
    
    def __enter__(self):
        self.scraper.start_browser()
        return self.scraper
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.scraper.close()

def cleanup_memory():
    """Perform memory cleanup"""
    gc.collect()
    
    try:
        import psutil
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        logger.info(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")
    except ImportError:
        logger.info("psutil not installed, skipping detailed memory reporting")
    except Exception as e:
        logger.error(f"Error in memory cleanup: {e}")

def get_existing_tender_ids(organization_id):
    """
    Get a set of existing tender numbers for a specific organization
    from the tender table (MahaTender source only).
    """
    from sqlalchemy import text
    from database_config import engine

    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT tender_number
                    FROM tender
                    WHERE organization_id = :org_id
                      AND tender_number IS NOT NULL
                      AND tender_number != ''
                      AND source = 'MahaTender_Original'
                """),
                {"org_id": organization_id}
            )

            existing_tender_numbers = {row[0] for row in result}

            logger.info(
                f"Found {len(existing_tender_numbers)} existing MahaTender tenders "
                f"for organization {organization_id}"
            )

            return existing_tender_numbers

    except Exception as e:
        logger.error(
            f"Error retrieving existing tender numbers for organization {organization_id}: {e}",
            exc_info=True
        )
        return set()

class MahaTenderScraper:
    """Scraper for MahaTenders portal using Selenium and BeautifulSoup"""
    
    def __init__(self):
        self.base_url = "https://mahatenders.gov.in/nicgep/app"
        self.driver = None
        self._last_search_keyword = None
        self._browser_failure_count = 0
        self._last_successful_page = 1
        self._processed_bid_ids = set()

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
            
            # Check 2: Try to execute simple script
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
        """Initialize and start the browser for MahaTenders portal with visible window"""
        try:
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
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Set timeouts
            self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            self.driver.implicitly_wait(IMPLICIT_WAIT_TIME)
            
            # Reset failure count on successful start
            self._browser_failure_count = 0
            
            logger.info("Started Chrome browser successfully in Docker container")
            
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
            time.sleep(2)
            return True
        except TimeoutException:
            logger.warning("Page load timeout")
            return False
    
    # def search_bids(self, keyword=None):
    #     """Search for tenders using a keyword, or browse all tenders if no keyword is provided"""
    #     max_retries = 3
    #     for attempt in range(max_retries):
    #         try:
    #             # Store the keyword for use in case of browser restarts
    #             self._last_search_keyword = keyword
                
    #             # Check if browser is alive before proceeding
    #             if not self._is_browser_alive():
    #                 logger.warning("Browser not alive, restarting...")
    #                 self.start_browser()
                
    #             self.driver.get(self.base_url)
                
    #             # Add a bit more wait time for the page to fully load
    #             if not self._wait_for_page_load(timeout=PAGE_LOAD_TIMEOUT):
    #                 logger.warning("Page load timeout, but continuing...")
                
    #             time.sleep(NAVIGATION_DELAY)
                
    #             if keyword:
    #                 logger.info(f"Searching for keyword: '{keyword}'")
                    
    #                 # Find the search input field using name='SearchDescription'
    #                 try:
    #                     search_input = WebDriverWait(self.driver, 10).until(
    #                         EC.presence_of_element_located((By.NAME, "SearchDescription"))
    #                     )
    #                     logger.info("Found search input field with name='SearchDescription'")
    #                 except (NoSuchElementException, TimeoutException):
    #                     logger.error("Could not find search input field with name='SearchDescription'")
    #                     # Try alternative selectors
    #                     search_selectors = [
    #                         (By.XPATH, "//input[@name='SearchDescription']"),
    #                         (By.XPATH, "//input[@placeholder='Search']"),
    #                         (By.XPATH, "//input[@type='text' and @id]"),
    #                     ]
    #                     search_input = None
    #                     for selector in search_selectors:
    #                         try:
    #                             search_input = self.driver.find_element(*selector)
    #                             logger.info(f"Found search input with selector: {selector}")
    #                             break
    #                         except NoSuchElementException:
    #                             continue
    #                     if not search_input:
    #                         raise Exception("Could not find the search input field")
                    
    #                 # Clear and set the input value
    #                 search_input.clear()
    #                 search_input.send_keys(keyword)
    #                 logger.info(f"Entered keyword: '{keyword}' in search field")
    #                 time.sleep(1)
                    
    #                 # Press Enter to search
    #                 search_input.send_keys(Keys.RETURN)
    #                 logger.info("Pressed ENTER key to submit search")
    #                 time.sleep(5)
    #             else:
    #                 logger.info("No keyword provided. Browsing all tenders.")
                
    #             return True
                
    #         except Exception as e:
    #             logger.error(f"Error during search attempt {attempt + 1}: {e}")
    #             if attempt < max_retries - 1:
    #                 logger.info("Retrying search...")
    #                 self._restart_browser_if_needed()
    #                 time.sleep(5)
    #             else:
    #                 logger.error("All search attempts failed")
    #                 raise
    
    def search_bids(self, keyword=None):
        """Search for tenders using a keyword, or browse all tenders if no keyword is provided"""
        max_retries = 3
        
        # EXTRACT ONLY OUTER KEYWORD
        if keyword:
            # If keyword contains parentheses, extract only the part before '('
            if '(' in keyword:
                outer_keyword = keyword.split('(')[0].strip()
                logger.info(f"Original keyword: '{keyword}' - Using outer keyword: '{outer_keyword}'")
                keyword = outer_keyword
            else:
                logger.info(f"Using keyword: '{keyword}'")
        
        for attempt in range(max_retries):
            try:
                # Store the processed keyword for use in case of browser restarts
                self._last_search_keyword = keyword
                
                # Check if browser is alive before proceeding
                if not self._is_browser_alive():
                    logger.warning("Browser not alive, restarting...")
                    self.start_browser()
                
                self.driver.get(self.base_url)
                
                # Add a bit more wait time for the page to fully load
                if not self._wait_for_page_load(timeout=PAGE_LOAD_TIMEOUT):
                    logger.warning("Page load timeout, but continuing...")
                
                time.sleep(NAVIGATION_DELAY)
                
                if keyword:
                    logger.info(f"Searching for keyword: '{keyword}' on MahaTenders")
                    
                    # Find the search input field using name='SearchDescription'
                    try:
                        search_input = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.NAME, "SearchDescription"))
                        )
                        logger.info("Found search input field with name='SearchDescription'")
                    except (NoSuchElementException, TimeoutException):
                        logger.error("Could not find search input field with name='SearchDescription'")
                        # Try alternative selectors
                        search_selectors = [
                            (By.XPATH, "//input[@name='SearchDescription']"),
                            (By.XPATH, "//input[@placeholder='Search']"),
                            (By.XPATH, "//input[@type='text' and @id]"),
                        ]
                        search_input = None
                        for selector in search_selectors:
                            try:
                                search_input = self.driver.find_element(*selector)
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
                
                return True
                
            except Exception as e:
                logger.error(f"Error during search attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    logger.info("Retrying search...")
                    self._restart_browser_if_needed()
                    time.sleep(5)
                else:
                    logger.error("All search attempts failed")
                    raise

    def scrape_tenders(self, max_tenders=10, existing_ids=None):
        """Scrape tender information with incremental processing"""
        scraped_tenders = []
        tender_info = {}
        current_page = 1
        
        # Tracking metrics for incremental processing
        consecutive_existing = 0
        total_seen = 0
        total_new = 0
        pages_with_no_new_content = 0
        seen_bid_ids_across_pages = set()
        
        # Initialize the set of existing IDs if not provided
        if existing_ids is None:
            existing_ids = set()
        
        RESTART_AFTER = BROWSER_RESTART_FREQUENCY
        
        try:
            while len(scraped_tenders) < max_tenders and current_page <= MAX_PAGES_TO_CHECK:
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
                if len(scraped_tenders) > 0 and len(scraped_tenders) % RESTART_AFTER == 0:
                    restart_needed = True
                    restart_reason = f"memory management after processing {len(scraped_tenders)} tenders"
                
                # Condition 2: Accumulated browser errors
                if hasattr(self, '_browser_failure_count') and self._browser_failure_count >= 2:
                    restart_needed = True
                    restart_reason = f"accumulated browser failures ({self._browser_failure_count})"
                
                # Condition 3: Page has been processing for too long
                if hasattr(self, '_pages_processed_since_restart'):
                    self._pages_processed_since_restart += 1
                    if self._pages_processed_since_restart >= 15:
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

                # Extract and process tenders from the current page
                page_tenders, page_info, page_stats = self._process_current_page(
                    max_tenders - len(scraped_tenders),
                    existing_ids,
                    seen_bid_ids_across_pages
                )
                
                # Update statistics
                total_seen += page_stats['total']
                total_new += page_stats['new']
                consecutive_existing = page_stats['consecutive_existing']
                
                # Add results to our collections
                scraped_tenders.extend(page_tenders)
                tender_info.update(page_info)

                if page_stats['page_has_repeated_content']:
                    logger.warning(f"PAGINATION CYCLE DETECTED: Page {current_page} contains tender IDs we've seen before")
                    logger.info("Stopping pagination to avoid infinite loop")
                    break
                
                if page_stats['new'] == 0 and current_page > 1:
                    pages_with_no_new_content += 1
                    logger.info(f"Page {current_page} had no new content (consecutive: {pages_with_no_new_content})")
                    if pages_with_no_new_content >= PAGES_WITH_NO_NEW_CONTENT_LIMIT:
                        logger.info(f"Stopping: {pages_with_no_new_content} consecutive pages with no new content")
                        break
                else:
                    pages_with_no_new_content = 0
                
                if ENABLE_MEMORY_OPTIMIZATION:
                    cleanup_memory()
                
                if consecutive_existing >= MAX_CONSECUTIVE_EXISTING:
                    logger.info(f"Stopping after seeing {consecutive_existing} consecutive existing tenders")
                    break
                    
                new_percentage = 0 if total_seen == 0 else (total_new / total_seen) * 100
                logger.info(f"New tenders: {total_new}/{total_seen} ({new_percentage:.1f}%)")
                
                if total_seen > 30 and new_percentage < NEW_THRESHOLD_PERCENT:
                    logger.info(f"Stopping as percentage of new tenders ({new_percentage:.1f}%) is below threshold ({NEW_THRESHOLD_PERCENT}%)")
                    break
                
                if len(scraped_tenders) >= max_tenders or not page_tenders:
                    break
                    
                if not self._go_to_next_page(current_page):
                    logger.info("No more pages available")
                    break
                    
                current_page += 1
                time.sleep(3)
            
            logger.info(f"Scraped {len(scraped_tenders)} tender documents across {current_page} pages")
            new_percentage = 0 if total_seen == 0 else (total_new / total_seen) * 100
            logger.info(f"New tenders: {total_new}/{total_seen} ({new_percentage:.1f}%)")
            return scraped_tenders, tender_info
                
        except Exception as e:
            logger.error(f"Error in scrape_tenders method: {e}")
            return scraped_tenders, tender_info
    
    def _process_current_page(self, max_tenders_to_process, existing_ids=None, seen_bid_ids_across_pages=None):
        """Process tenders on the current page - FIXED VERSION"""
        scraped_tenders = []
        tender_info = {}
        
        stats = {
            'total': 0,
            'new': 0,
            'existing': 0,
            'consecutive_existing': 0,
            'page_has_repeated_content': False
        }
        
        if existing_ids is None:
            existing_ids = set()
        if seen_bid_ids_across_pages is None:
            seen_bid_ids_across_pages = set()

        try:
            logger.info("Looking for tender elements on MahaTenders portal...")
            
            main_page_url = self.driver.current_url
            tender_links_info = []  # List of tuples: (tender_id, href, title)
            current_page_tender_ids = set()
            
            # Look for tender links using the specific selector: //a[@title='View Tender Information']
            try:
                tender_elements = self.driver.find_elements(By.XPATH, "//a[@title='View Tender Information']")
                logger.info(f"Found {len(tender_elements)} tender links with title='View Tender Information'")
                
                for element in tender_elements:
                    try:
                        if element.is_displayed() and element.is_enabled():
                            href = element.get_attribute('href')
                            text = element.text.strip()
                            
                            if href:
                                # Extract tender ID from URL
                                tender_id = self._extract_tender_id_from_url(href)
                                
                                current_page_tender_ids.add(tender_id)
                                tender_links_info.append((tender_id, href, text))
                                logger.info(f"Found tender link: ID={tender_id}, Text='{text[:50]}...'")
                    except Exception as e:
                        logger.error(f"Error processing tender element: {e}")
                        continue
            except Exception as e:
                logger.error(f"Error finding tender links: {e}")
            
            # Check for pagination cycle
            if current_page_tender_ids and current_page_tender_ids.issubset(seen_bid_ids_across_pages):
                stats['page_has_repeated_content'] = True
                logger.warning(f"Detected repeated content: {len(current_page_tender_ids)} tender IDs already seen on previous pages")
            else:
                seen_bid_ids_across_pages.update(current_page_tender_ids)

            logger.info(f"Total unique tender links extracted on current page: {len(tender_links_info)}")
            
            # We need to check ALL tenders on the page to find new ones
            # max_tenders_to_process is the number of NEW tenders we still need to find
            tenders_to_check = tender_links_info  # Check ALL tenders on the page
            
            logger.info(f"Checking {len(tenders_to_check)} tenders on page (need to find {max_tenders_to_process} more new tenders)...")
            
            for i, (tender_id, href, title) in enumerate(tenders_to_check):
                # Stop if we've already found enough new tenders
                if len(scraped_tenders) >= max_tenders_to_process:
                    logger.info(f"Already found {len(scraped_tenders)} new tenders, stopping page processing")
                    break
                
                try:
                    stats['total'] += 1
                    
                    logger.info(f"Checking tender {i+1}/{len(tenders_to_check)}: {href} (ID: {tender_id})")
                    logger.info(f"Progress: Found {len(scraped_tenders)} new so far, need {max_tenders_to_process - len(scraped_tenders)} more")
                    
                    if not self._is_browser_alive():
                        logger.error("Browser disconnected during tender processing")
                        break
                    
                    # Navigate to the tender details page
                    try:
                        self.driver.get(href)
                        time.sleep(3)
                    except Exception as nav_error:
                        logger.error(f"Navigation error for tender: {nav_error}")
                        continue

                    # Extract tender data using BeautifulSoup - UPDATED TO GET ALL DETAILS
                    tender_data = self._extract_maha_tender_data()
                    
                    # Check if this tender ID already exists
                    actual_tender_id = tender_data.get('tender_number', tender_data.get('tender_id', ''))
                    is_new_tender = not actual_tender_id or actual_tender_id not in existing_ids
                    
                    if is_new_tender:
                        stats['new'] += 1
                        stats['consecutive_existing'] = 0
                        logger.info(f"New tender found: {tender_id}")
                    else:
                        stats['existing'] += 1
                        stats['consecutive_existing'] += 1
                        logger.info(f"Existing tender found: {tender_id}")
                        
                        if ONLY_PROCESS_NEW:
                            logger.info(f"Skipping existing tender: {tender_id}")
                            # Return to main page before continuing
                            try:
                                self.driver.get(main_page_url)
                                time.sleep(3)
                            except Exception as return_error:
                                logger.error(f"Error returning to main page: {return_error}")
                                self._restart_browser_if_needed()
                            continue
                    
                    # Store tender information
                    tender_info[tender_id] = {
                        'url': href,
                        'title': title,
                        'tender_data': tender_data
                    }
                    scraped_tenders.append(tender_id)
                    
                    logger.info(f"Extracted tender data for {tender_id}")
                    
                    existing_ids.add(actual_tender_id)
                    
                    # Return to the main page
                    try:
                        self.driver.get(main_page_url)
                        time.sleep(3)
                    except Exception as return_error:
                        logger.error(f"Error returning to main page: {return_error}")
                        self._restart_browser_if_needed()
                        continue
                    
                    if ENABLE_MEMORY_OPTIMIZATION:
                        gc.collect()
                
                except Exception as e:
                    logger.error(f"Error processing tender {i+1}: {e}")
                    if not self._is_browser_alive():
                        logger.error("Browser connection lost during tender processing")
                        break

            return scraped_tenders, tender_info, stats

        except Exception as e:
            logger.error(f"Error processing page: {e}")
            return [], {}, stats

    def _extract_tender_id_from_url(self, url):
        """Extract tender ID from URL"""
        # Try multiple patterns to extract tender ID
        patterns = [
            r'TenderId=([^&]+)',
            r'tenderId=([^&]+)',
            r'tenderid=([^&]+)',
            r'/(\d{6,}_[^/]+)/',
            r'=(\d{6,}_\d+_\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # If no pattern matches, create a hash from the URL
        url_hash = abs(hash(url)) % 1000000
        return f"maha_{url_hash}"
    
    def _extract_maha_tender_data(self):
        """Extract tender data from MahaTender page using BeautifulSoup - ALL DETAILS LIKE CPPP"""
        try:
            # Get page source and parse with BeautifulSoup
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Use the same extraction functions as CPPP
            tender_data = self._extract_tender_details_from_page(soup)
            
            # Initialize result dictionary with all required fields
            tender_data.update({
                'scraped_url': self.driver.current_url,
                'scraped_timestamp': datetime.now().isoformat(),
                'is_pdf': False,
                # Use the scraped title
                'title': tender_data.get('title', '')[:1000],
                'tender_number': tender_data.get('tender_id', ''),
                'tender_reference_number': tender_data.get('tender_reference_number', ''),
                # Initialize other fields as None
                'question_deadline': None,
                'qualification_criteria': None,
                'reverse_auction': None,
                'rejection_criteria': None,
                'msme_preferences': None,
                'border_country_clause': None,
                'performance_security': None,
                'payment_terms': None,
                'technical_specifications': None,
                'scope_of_work': None,
                'performance_standards': None,
                'evaluation_criteria': None,
                'documentation_requirements': None,
                'additional_details': None
            })
            
            logger.info(f"Extracted MahaTender data: ID={tender_data['tender_id'][:30]}, "
                    f"Title={tender_data['title'][:50]}..., "
                    f"Due={tender_data['due_date']}")
            
            return tender_data
            
        except Exception as e:
            logger.error(f"Error extracting MahaTender data: {e}")
            return {
                'tender_id': '',
                'title': '',
                'description': '',
                'due_date': '',
                'scraped_url': self.driver.current_url,
                'scraped_timestamp': datetime.now().isoformat(),
                'is_pdf': False,
                'bid_opening_date': '',
                'bid_offer_validity': '',
                'emd_amount': '',
                'estimated_cost': '',
                'organization_details': '',
                'tender_number': '',
                'error': str(e)
            }
    
    def _extract_tender_details_from_page(self, soup):
        """Extract tender details from page using separate functions - SAME AS CPPP"""
        tender_data = {
            'tender_id': '',
            'description': '',
            'due_date': '',
            'bid_opening_date': '',
            'bid_offer_validity': '',
            'emd_amount': '',
            'estimated_cost': '',
            'organization_details': ''
        }
        
        try:
            # Use the separate functions - same as CPPP
            tender_id = self._find_tender_id(soup)
            tender_reference_number = self._find_tender_reference_number(soup)  
            title_ = self._find_title(soup)
            description = self._find_description(soup)
            due_date = self._find_due_date(soup)
            bid_opening_date = self._find_bid_opening_date(soup)
            bid_offer_validity = self._find_bid_offer_validity(soup)
            emd_amount = self._find_emd_amount(soup)
            estimated_cost = self._find_estimated_cost(soup)
            organization_details = self._find_organization_details(soup)
            
            tender_data['tender_id'] = tender_id if tender_id else ''
            tender_data['tender_reference_number'] = tender_reference_number if tender_reference_number else 'N/A'
            tender_data['title'] = title_ if title_ else ''
            tender_data['description'] = description if description else ''
            tender_data['due_date'] = due_date if due_date else 'Not specified'
            tender_data['bid_opening_date'] = bid_opening_date if bid_opening_date else ''
            tender_data['bid_offer_validity'] = bid_offer_validity if bid_offer_validity else ''
            tender_data['emd_amount'] = emd_amount if emd_amount else ''
            tender_data['estimated_cost'] = estimated_cost if estimated_cost else ''
            tender_data['organization_details'] = organization_details if organization_details else ''
            
        except Exception as e:
            logger.error(f"Error in extracting tender details from page: {e}")
        
        return tender_data

    def _find_tender_id(self, soup):
        """Find tender ID in the page content"""
        try:
            # Look for any td with class 'td_caption' containing "Tender ID"
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and 'Tender ID' in text:
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        # Get the text and clean it
                        tender_id = next_td.get_text(strip=True)
                        # Remove any <b> tags but keep the text
                        if hasattr(tender_id, 'get_text'):
                            tender_id = tender_id.get_text(strip=True)
                        logger.info(f"Found tender ID in page: {tender_id}")
                        return tender_id
        except Exception as e:
            logger.error(f"Error finding tender ID: {e}")
        
        return None
    
    def _find_tender_reference_number(self, soup):
        """Find tender reference number in the page content"""
        try:
            # Look for any td with class 'td_caption' containing "Tender Reference Number"
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and 'Tender Reference Number' in text:
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        # Get the text and clean it
                        tender_reference_number = next_td.get_text(strip=True)
                        # Remove any <b> tags but keep the text
                        if hasattr(tender_reference_number, 'get_text'):
                            tender_reference_number = tender_reference_number.get_text(strip=True)
                        logger.info(f"Found tender reference number in page: {tender_reference_number}")
                        return tender_reference_number
        except Exception as e:
            logger.error(f"Error finding tender reference number: {e}")
        
        return None

    def _find_title(self, soup):
        """Find Title in the page"""
        try:
            # Look for "Title" in td_caption
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and 'Title' in text:
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        title = next_td.get_text(strip=True)
                        logger.info(f"Found title in page: {title[:50]}...")
                        return title
            
            # Alternative: Look for "Work Description" for title
            for td in soup.find_all('td', class_='td_caption'):
                if 'Work Description' in td.get_text(strip=True):
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        description = next_td.get_text(strip=True)
                        # Use first 100 chars as title
                        title = description[:100] + "..." if len(description) > 100 else description
                        logger.info(f"Using description as title: {title}")
                        return title
        except Exception as e:
            logger.error(f"Error finding title: {e}")
        return ''

    def _find_description(self, soup):
        """Find description in the page using Work Description field"""
        try:
            # Look for any td with class 'td_caption' containing "Work Description"
            for td in soup.find_all('td', class_='td_caption'):
                if 'Work Description' in td.get_text(strip=True):
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        description = next_td.get_text(strip=True)
                        logger.info(f"Found description in page: {description[:50]}...")
                        return description
        except Exception as e:
            logger.error(f"Error finding description: {e}")
        
        return ''

    def _find_due_date(self, soup):
        """Find due date in the page - specifically Bid Submission End Date"""
        try:
            # Look for any td with class 'td_caption' containing "Bid Submission End Date"
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and 'Bid Submission End Date' in text:
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        raw_date = next_td.get_text(strip=True)
                        # Example raw_date = "22-Jan-2026 05:00 PM"

                        try:
                            dt = datetime.strptime(raw_date, "%d-%b-%Y %I:%M %p")
                            # Convert to your system format
                            formatted_date = dt.strftime("%d-%m-%Y")
                            logger.info(f"Found due date in page: {formatted_date}")
                            return formatted_date
                        except ValueError:
                            logger.warning(f"Unable to parse due date: {raw_date}")
                            return raw_date
        
        except Exception as e:
            logger.error(f"Error finding due date: {e}")
        
        return 'Not specified'
    
    def _find_bid_opening_date(self, soup):
        """Find bid opening date in the page - specifically Bid Opening Date"""
        try:
            # Look for any td with class 'td_caption' containing "Bid Opening Date"
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and 'Bid Opening Date' in text:
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        raw_date = next_td.get_text(strip=True)
                        # Example raw_date = "22-Jan-2026 05:00 PM"

                        try:
                            dt = datetime.strptime(raw_date, "%d-%b-%Y %I:%M %p")
                            # Convert to your system format
                            formatted_date = dt.strftime("%d-%m-%Y")
                            logger.info(f"Found bid opening date in page: {formatted_date}")
                            return formatted_date
                        except ValueError:
                            logger.warning(f"Unable to parse bid opening date: {raw_date}")
                            return raw_date
        
        except Exception as e:
            logger.error(f"Error finding bid opening date: {e}")
        
        return 'Not specified'

    def _find_bid_offer_validity(self, soup):
        """Find Bid Offer Validity in the page"""
        try:
            # Look for "Bid Offer Validity" in td_caption
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and ('Bid Validity(Days)' in text or 'Bid Offer Validity' in text):
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        validity = next_td.get_text(strip=True)
                        # Try to extract days
                        import re
                        days_match = re.search(r'(\d+)\s*days?', validity, re.IGNORECASE)
                        if days_match:
                            return days_match.group(1) + " days"
                        return validity
        except Exception as e:
            logger.error(f"Error finding bid offer validity: {e}")
        return ''

    def _find_emd_amount(self, soup):
        """Find EMD Amount in the page"""
        try:
            # Look for "EMD Amount" or "Earnest Money Deposit" in td_caption
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and ('EMD Amount in ₹' in text or 'Earnest Money Deposit' in text or 'EMD' in text):
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        emd = next_td.get_text(strip=True)
                        return emd
        except Exception as e:
            logger.error(f"Error finding EMD amount: {e}")
        return ''

    def _find_estimated_cost(self, soup):
        """Find Estimated Cost (Tender Value) in the page"""
        try:
            # Look for "Tender Value" or "Estimated Cost" in td_caption
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and ('Tender Value in ₹' in text or 'Estimated Cost' in text or 'Tender Value' in text):
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        value = next_td.get_text(strip=True)
                        return value
        except Exception as e:
            logger.error(f"Error finding estimated cost: {e}")
        return ''

    def _find_organization_details(self, soup):
        """Find Organisation Chain in the page"""
        try:
            # Look for "Organisation Chain" or "Organisation" in td_caption
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and ('Organisation Chain' in text or 'Organisation' in text):
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        org_chain = next_td.get_text(strip=True)
                        return org_chain
            
            # Look for "Department" or "Ministry"
            for td in soup.find_all('td', class_='td_caption'):
                text = td.get_text(strip=True)
                if text and ('Department' in text or 'Ministry' in text):
                    next_td = td.find_next_sibling('td')
                    if next_td:
                        dept = next_td.get_text(strip=True)
                        return dept
        except Exception as e:
            logger.error(f"Error finding organization details: {e}")
        return ''
    
    def _go_to_next_page(self, current_page):
        """Navigate to the next page of results using id='linkFwd'"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Check browser health first
                if not self._is_browser_alive():
                    logger.error("Browser not alive during pagination")
                    return False
                
                # Get the first tender ID before navigation
                first_tender_before = ""
                try:
                    first_tender_element = self.driver.find_element(By.XPATH, "//a[@title='View Tender Information']")
                    href = first_tender_element.get_attribute('href')
                    tender_id_match = re.search(r'TenderId=(\d+)', href)
                    if tender_id_match:
                        first_tender_before = tender_id_match.group(1)
                except:
                    pass
                
                # Find and click the next page button using id='linkFwd'
                try:
                    next_page_button = self.driver.find_element(By.ID, "linkFwd")
                    
                    if next_page_button.is_displayed() and next_page_button.is_enabled():
                        # Scroll into view and click
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", next_page_button)
                        time.sleep(1)
                        self.driver.execute_script("arguments[0].click();", next_page_button)
                        logger.info(f"Clicked next page button (id='linkFwd')")
                        time.sleep(5)
                        
                        # Wait for content to change
                        try:
                            WebDriverWait(self.driver, 15).until(
                                lambda d: len(d.find_elements(By.XPATH, "//a[@title='View Tender Information']")) > 0
                            )
                            logger.info(f"Successfully navigated to next page")
                            return True
                        except TimeoutException:
                            logger.warning(f"Content didn't change after clicking next page (attempt {attempt + 1})")
                            if attempt < max_attempts - 1:
                                time.sleep(3)
                                continue
                            else:
                                logger.error(f"Failed to navigate to next page after {max_attempts} attempts")
                                return False
                    else:
                        logger.warning("Next page button not clickable")
                        return False
                        
                except NoSuchElementException:
                    logger.info("No next page button found (id='linkFwd') - reached end of results")
                    return False
                
            except Exception as e:
                logger.error(f"Pagination attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(3)
                    self._restart_browser_if_needed()
                else:
                    logger.error(f"Pagination failed after {max_attempts} attempts")
                    return False
        
        return False

def save_to_db(tender_data, organization_id, user_id=1):
    """Save tender data to tender table - SAME AS CPPP"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        # Extract fields from tender data for tender table - ALL FIELDS LIKE CPPP
        title = tender_data.get('title', 'Untitled Tender')[:1000]
        description = tender_data.get('description', '')[:10000]
        due_date = tender_data.get('due_date', '')
        bid_opening_date = tender_data.get('bid_opening_date', '')
        bid_offer_validity = tender_data.get('bid_offer_validity', '')
        emd_amount = tender_data.get('emd_amount', '')
        estimated_cost = tender_data.get('estimated_cost', '')
        organization_details = tender_data.get('organization_details', '')
        tender_number = tender_data.get('tender_number', '')
        tender_reference_number = tender_data.get('tender_reference_number', 'N/A')
        
        # For MahaTender, if tender_number is empty, use tender_id
        if not tender_number and 'tender_id' in tender_data:
            tender_number = tender_data.get('tender_id', '')
        
        # Skip if no title or tender number
        if not title or not tender_number:
            logger.warning(f"No title or tender number found in data, skipping save. Title: '{title[:50]}', Tender No: '{tender_number}'")
            return
        
        # DEBUG: Log what we're trying to save
        logger.debug(f"Attempting to save to DB - Tender: {title[:50]}, Tender No: {tender_number}")
        
        with engine.connect() as conn:
            # Check if tender already exists using tender_number AND source
            result = conn.execute(
                text("SELECT id FROM tender WHERE tender_number = :tender_number AND organization_id = :org_id"),
                {
                    "tender_number": tender_number,
                    "org_id": organization_id,
                }
            )
            existing_tender = result.fetchone()
            
            tender_id = None
            
            if existing_tender:
                # Update existing tender - ALL FIELDS LIKE CPPP
                tender_id = existing_tender[0]
                update_result = conn.execute(text("""
                    UPDATE tender SET
                        title = :title,
                        tender_reference_number = :tender_reference_number,
                        description = :description,
                        due_date = :due_date,
                        bid_opening_date = :bid_opening_date,
                        bid_offer_validity = :bid_offer_validity,
                        emd_amount = :emd_amount,
                        estimated_cost = :estimated_cost,
                        organization_details = :organization_details,
                        updated_at = CURRENT_TIMESTAMP,
                        source = :source
                    WHERE id = :tender_id AND organization_id = :org_id
                """), {
                    "title": title,
                    "tender_reference_number": tender_reference_number,
                    "description": description,
                    "due_date": due_date,
                    "bid_opening_date": bid_opening_date,
                    "bid_offer_validity": bid_offer_validity,
                    "emd_amount": emd_amount,
                    "estimated_cost": estimated_cost,
                    "organization_details": organization_details,
                    "tender_id": tender_id,
                    "org_id": organization_id,
                    "source": "MahaTender_Original"
                })
                logger.info(f"Updated existing MahaTender {tender_number} for organization {organization_id}")
            else:
                # Create new tender - USE RETURNING id FOR POSTGRESQL
                result = conn.execute(text("""
                    INSERT INTO tender (
                        title, description, due_date, bid_opening_date, 
                        bid_offer_validity, emd_amount, estimated_cost,
                        organization_details, tender_number, tender_reference_number, user_id,
                        organization_id, source, created_at, updated_at
                    ) VALUES (
                        :title, :description, :due_date, :bid_opening_date,
                        :bid_offer_validity, :emd_amount, :estimated_cost,
                        :organization_details, :tender_number, :tender_reference_number, :user_id,
                        :org_id, :source, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    RETURNING id
                """), {
                    "title": title,
                    "description": description,
                    "due_date": due_date,
                    "bid_opening_date": bid_opening_date,
                    "bid_offer_validity": bid_offer_validity,
                    "emd_amount": emd_amount,
                    "estimated_cost": estimated_cost,
                    "organization_details": organization_details,
                    "tender_number": tender_number,
                    "tender_reference_number": tender_reference_number,
                    "user_id": user_id,
                    "org_id": organization_id,
                    "source": "MahaTender_Original"
                })
                
                # Get the newly created tender ID
                tender_id = result.fetchone()[0]
                logger.info(f"Created new MahaTender {tender_number} with ID {tender_id} for organization {organization_id}")
            
            conn.commit()
            logger.info(f"Commit successful for MahaTender {tender_number}")

    except Exception as e:
        logger.error(f"Database error: {e}")
        logger.error(f"Full error details: {e.__class__.__name__}: {str(e)}")
        if hasattr(e, 'orig'):
            logger.error(f"Original error: {e.orig}")
        raise

def main(search_keyword=None, max_tenders=30, organization_id=None, domain_keywords=None):
    """Main function to run the MahaTender scraper"""
    global ONLY_PROCESS_NEW
    
    logger.info("=" * 80)
    logger.info("MahaTender Scraper - ALL DETAILS")
    logger.info("=" * 80)
    
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
    
    # Ask if user wants to do incremental processing in interactive mode
    if search_keyword is None:  # Interactive mode
        incremental = input("Do you want to only process new tenders? (y/n, default: y): ").strip().lower()
        ONLY_PROCESS_NEW = incremental != 'n'
        
        # Get user input for keyword - allow empty for no filtering
        search_keyword = input("Enter keyword to search for tenders (leave empty to browse all tenders): ").strip()
        search_keyword = search_keyword if search_keyword else None

        max_tenders = input("Enter maximum number of tenders to scrape (default 30): ")
        max_tenders = int(max_tenders) if max_tenders.strip() else 30

    if search_keyword:
        logger.info(f"Searching for keyword: '{search_keyword}'")
    else:
        logger.info("Browsing all available tenders")
    
    # Initialize scraper but don't start browser yet
    scraper = MahaTenderScraper()
    
    # Use context manager to ensure browser is always closed
    with BrowserContext(scraper) as browser:
        try:
            # Search and scrape tenders
            logger.info("Starting the browser and scraping tenders...")
            browser.search_bids(search_keyword)
            scraped_tenders, tender_info = browser.scrape_tenders(max_tenders=max_tenders, existing_ids=existing_ids)
            
            if not scraped_tenders:
                logger.warning("No new tenders were scraped. Try again with a different keyword or disable incremental processing.")
                return
            
            for i, tender_id in enumerate(scraped_tenders):
                logger.info(f"Processing tender {i+1} of {len(scraped_tenders)}: {tender_id}")
                
                # Get tender details
                tender_details = tender_info.get(tender_id, {})
                tender_data = tender_details.get('tender_data', {})
                
                # Save to database with organization_id - ALL FIELDS
                save_to_db(tender_data, organization_id)
                
                # Update the existing IDs set for future checks
                actual_tender_id = tender_data.get('tender_number', tender_data.get('tender_id', ''))
                if actual_tender_id:
                    existing_ids.add(actual_tender_id)
                
                # Explicitly call garbage collection to free memory
                if ENABLE_MEMORY_OPTIMIZATION:
                    gc.collect()
            
            # Output summary
            logger.info("\n=== Scraping Summary ===")
            logger.info(f"Scraped {len(scraped_tenders)} new tenders")
            logger.info(f"Portal: MahaTender")
            
            # Save summary CSV
            try:
                # Create a CSV with all fields like CPPP
                csv_data = []
                for tender_id in scraped_tenders:
                    tender_details = tender_info.get(tender_id, {})
                    tender_data = tender_details.get('tender_data', {})
                    
                    csv_data.append({
                        'tender_id': tender_data.get('tender_id', ''),
                        'tender_number': tender_data.get('tender_number', ''),
                        'title': tender_data.get('title', '')[:200],
                        'description': tender_data.get('description', '')[:500],
                        'due_date': tender_data.get('due_date', ''),
                        'bid_opening_date': tender_data.get('bid_opening_date', ''),
                        'bid_offer_validity': tender_data.get('bid_offer_validity', ''),
                        'emd_amount': tender_data.get('emd_amount', ''),
                        'estimated_cost': tender_data.get('estimated_cost', ''),
                        'organization_details': tender_data.get('organization_details', ''),
                        'url': tender_details.get('url', '')
                    })
                
                df = pd.DataFrame(csv_data)
                
                # Generate filename with timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = f"maha_tenders_org{organization_id}_{timestamp}.csv"
                
                # Save to maha_bids folder
                output_path = os.path.join(MAHA_BIDS_FOLDER, output_file)
                df.to_csv(output_path, index=False, encoding='utf-8-sig')
                logger.info(f"Summary CSV saved to {output_path}")
                
            except Exception as e:
                logger.error(f"Error saving CSV file: {e}")

        except Exception as e:
            logger.error(f"Error in main function: {e}", exc_info=True)
            
    # Final cleanup and summary
    if ENABLE_MEMORY_OPTIMIZATION:
        cleanup_memory()
    
    logger.info("MahaTender scraper completed successfully!")

def main_cli(search_keyword, max_tenders, organization_id, domain_keywords=None):
    """Entry point for CLI/scheduled execution"""
    global ONLY_PROCESS_NEW
    ONLY_PROCESS_NEW = True
    logger.info(f"Running MahaTender scraper via CLI for organization {organization_id}")
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
            logger.info("Running MahaTender scraper with CLI arguments")
            main_cli(search_keyword, max_tenders, organization_id, domain_keywords)
        else:
            logger.info("Running MahaTender scraper in interactive mode")
            main()
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")