# import os
# import re
# from datetime import datetime
# import time 
# import sys
# import logging
# import pandas as pd
# import gc
# import json
# from flask import Flask
# from bs4 import BeautifulSoup

# # Selenium imports
# from selenium import webdriver
# from selenium.webdriver.common.by import By
# from selenium.webdriver.common.keys import Keys
# from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from webdriver_manager.chrome import ChromeDriverManager
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC

# # Database imports
# from sqlalchemy import create_engine, text
# from sqlalchemy.orm import sessionmaker
# from database_config import SQLALCHEMY_DATABASE_URI, engine

# # Create session for standalone use
# Session = sessionmaker(bind=engine)

# # Memory optimization settings
# BATCH_SIZE = 5
# BROWSER_RESTART_FREQUENCY = 10
# ENABLE_MEMORY_OPTIMIZATION = True

# # Incremental processing settings
# MAX_CONSECUTIVE_EXISTING = 15
# MAX_PAGES_TO_CHECK = 15
# NEW_THRESHOLD_PERCENT = 15
# ONLY_PROCESS_NEW = True

# # Browser stability settings
# MAX_BROWSER_FAILURES = 3
# BROWSER_RESTART_DELAY = 3
# PAGE_LOAD_TIMEOUT = 30
# IMPLICIT_WAIT_TIME = 8
# ELEMENT_INTERACTION_DELAY = 2
# NAVIGATION_DELAY = 6

# # Pagination and content detection settings
# MAX_PAGINATION_RETRIES = 2
# CONTENT_CHANGE_TIMEOUT = 10
# PAGES_WITH_NO_NEW_CONTENT_LIMIT = 2

# # Error handling and recovery settings
# OPERATION_RETRY_DELAY = 2
# MAX_ELEMENT_SEARCH_TIME = 15
# RECOVERY_ATTEMPT_DELAY = 5

# DOWNLOAD_FOLDER = "cppp_bids"

# # Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler("cppp_tenders.log", encoding='utf-8'),
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__)

# class BrowserContext:
#     """Context manager for browser to ensure proper cleanup"""
#     def __init__(self, scraper):
#         self.scraper = scraper
    
#     def __enter__(self):
#         self.scraper.start_browser()
#         return self.scraper
    
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         self.scraper.close()

# def cleanup_memory():
#     """Perform memory cleanup"""
#     gc.collect()
    
#     try:
#         import psutil
#         process = psutil.Process(os.getpid())
#         memory_info = process.memory_info()
#         logger.info(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")
#     except ImportError:
#         logger.info("psutil not installed, skipping detailed memory reporting")
#     except Exception as e:
#         logger.error(f"Error in memory cleanup: {e}")

# def get_existing_tender_ids(organization_id):
#     """Get a set of tender IDs that already exist in the database for a specific organization"""
#     from sqlalchemy import text
#     from database_config import engine
    
#     try:
#         with engine.connect() as conn:
#             result = conn.execute(
#                 text("SELECT tender_id FROM gem_tenders WHERE organization_id = :org_id AND tender_id IS NOT NULL AND tender_id != 'unknown_bid'"),
#                 {"org_id": organization_id}
#             )
#             existing_ids = {row[0] for row in result if row[0]}
#             logger.info(f"Found {len(existing_ids)} existing tender IDs for organization {organization_id}")
#             return existing_ids
#     except Exception as e:
#         logger.error(f"Error retrieving existing tender IDs: {e}")
#         return set()

# class GEMCPPPTenderScraper:
#     """Scraper for GEM CPPP portal using Selenium and BeautifulSoup"""
    
#     def __init__(self):
#         self.base_url = "https://gem.gov.in/cppp"
#         self.driver = None
#         self._last_search_keyword = None
#         self._browser_failure_count = 0
#         self._last_successful_page = 1
#         self._processed_bid_ids = set()

#     def _is_browser_alive(self):
#         """Check if the browser is still alive and responsive with multiple checks"""
#         try:
#             if self.driver is None:
#                 return False
            
#             # Multiple health checks
#             # Check 1: Get current URL
#             current_url = self.driver.current_url
#             if not current_url:
#                 return False
            
#             # Check 2: Try to execute simple script
#             result = self.driver.execute_script("return document.readyState;")
#             if not result:
#                 return False
                
#             # Check 3: Try to find any element
#             self.driver.find_element(By.TAG_NAME, "body")

#             return True
#         except (WebDriverException, Exception) as e:
#             logger.warning(f"Browser health check failed: {e}")
#             return False
    
#     def _force_browser_restart(self, reason="Unknown"):
#         """Force restart the browser with proper cleanup"""
#         logger.warning(f"Forcing browser restart due to: {reason}")
#         try:
#             # Close current browser
#             if self.driver:
#                 try:
#                     self.driver.quit()
#                 except:
#                     pass
#             self.driver = None

#             # Wait before restart
#             time.sleep(BROWSER_RESTART_DELAY)

#             # Start new browser
#             self.start_browser()
#             return True
#         except Exception as e:
#             logger.error(f"Failed to restart browser: {e}")
#             return False
    
#     def _restart_browser_if_needed(self):
#         """Restart browser if it's not responsive"""
#         if not self._is_browser_alive():
#             logger.warning("Browser is not responsive, restarting...")
#             return self._force_browser_restart("Browser not responsive")
#         return False
    
#     def start_browser(self):
#         """Initialize and start the browser for GEM CPPP portal with visible window"""
#         try:
#             if self.driver:
#                 self.close()
            
#             chrome_options = Options()
            
#             # Enhanced headless mode configuration
#             chrome_options.add_argument("--headless=new")  # Use new headless mode
#             chrome_options.add_argument('--window-size=1920,1080')  # Set proper window size
#             chrome_options.add_argument('--start-maximized')
#             chrome_options.add_argument("--disable-gpu")
#             chrome_options.add_argument("--no-sandbox")
#             chrome_options.add_argument("--disable-dev-shm-usage")
#             chrome_options.add_argument("--disable-extensions")
#             chrome_options.add_argument("--disable-plugins")
#             chrome_options.add_argument("--disable-images")  # Disable images for faster loading
#             chrome_options.add_argument("--disable-javascript-harmony-shipping")
#             chrome_options.add_argument("--disable-background-timer-throttling")
#             chrome_options.add_argument("--disable-backgrounding-occluded-windows")
#             chrome_options.add_argument("--disable-renderer-backgrounding")
#             chrome_options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
#             chrome_options.add_argument("--force-device-scale-factor=1")  # Prevent scaling issues
#             chrome_options.add_argument("--enable-features=NetworkService,NetworkServiceLogging")
            
#             # Additional stability arguments
#             chrome_options.add_argument("--disable-blink-features=AutomationControlled")
#             chrome_options.add_argument("--disable-web-security")
#             chrome_options.add_argument("--allow-running-insecure-content")
#             chrome_options.add_argument("--disable-features=VizDisplayCompositor")
#             chrome_options.add_argument("--remote-debugging-port=9222")
            
#             # Suppress Chrome noise/error messages
#             chrome_options.add_argument('--disable-logging')
#             chrome_options.add_argument('--log-level=3')  # Only fatal errors
#             chrome_options.add_argument('--silent')
#             chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
#             chrome_options.add_experimental_option('useAutomationExtension', False)
            
#             # User agent to avoid detection
#             chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
#             service = Service(ChromeDriverManager().install())
#             self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
#             # Set timeouts
#             self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
#             self.driver.implicitly_wait(IMPLICIT_WAIT_TIME)
            
#             # Reset failure count on successful start
#             self._browser_failure_count = 0
            
#             logger.info("Started Chrome browser successfully in Docker container")
            
#         except Exception as e:
#             self._browser_failure_count += 1
#             logger.error(f"Error starting browser (attempt {self._browser_failure_count}): {e}")
#             if self._browser_failure_count >= MAX_BROWSER_FAILURES:
#                 raise Exception(f"Failed to start browser after {MAX_BROWSER_FAILURES} attempts")
#             raise

#     def close(self):
#         """Close the browser"""
#         if self.driver:
#             try:
#                 self.driver.quit()
#                 logger.info("Closed Chrome browser")
#             except Exception as e:
#                 logger.warning(f"Error closing browser: {e}")
#             finally:
#                 self.driver = None
    
#     def _wait_for_page_load(self, timeout=30):
#         """Wait for page to fully load"""
#         try:
#             WebDriverWait(self.driver, timeout).until(
#                 lambda driver: driver.execute_script("return document.readyState") == "complete"
#             )
#             time.sleep(2)
#             return True
#         except TimeoutException:
#             logger.warning("Page load timeout")
#             return False
    
#     def search_bids(self, keyword=None):
#         """Search for tenders using a keyword, or browse all tenders if no keyword is provided"""
#         max_retries = 3
#         for attempt in range(max_retries):
#             try:
#                 # Store the keyword for use in case of browser restarts
#                 self._last_search_keyword = keyword
                
#                 # Check if browser is alive before proceeding
#                 if not self._is_browser_alive():
#                     logger.warning("Browser not alive, restarting...")
#                     self.start_browser()
                
#                 self.driver.get(self.base_url)
                
#                 # Add a bit more wait time for the page to fully load
#                 if not self._wait_for_page_load(timeout=PAGE_LOAD_TIMEOUT):
#                     logger.warning("Page load timeout, but continuing...")
                
#                 time.sleep(NAVIGATION_DELAY)
                
#                 if keyword:
#                     logger.info(f"Searching for keyword: '{keyword}'")
                    
#                     # Find the search input field using name='title' for GEM CPPP
#                     try:
#                         search_input = WebDriverWait(self.driver, 10).until(
#                             EC.presence_of_element_located((By.NAME, "title"))
#                         )
#                         logger.info("Found search input field with name='title'")
#                     except (NoSuchElementException, TimeoutException):
#                         logger.error("Could not find search input field with name='title'")
#                         # Try alternative selectors
#                         search_selectors = [
#                             (By.XPATH, "//input[@name='title']"),
#                             (By.XPATH, "//input[@placeholder='Search']"),
#                             (By.XPATH, "//input[@type='text' and @id]"),
#                         ]
#                         search_input = None
#                         for selector in search_selectors:
#                             try:
#                                 search_input = self.driver.find_element(*selector)
#                                 logger.info(f"Found search input with selector: {selector}")
#                                 break
#                             except NoSuchElementException:
#                                 continue
#                         if not search_input:
#                             raise Exception("Could not find the search input field")
                    
#                     # Clear and set the input value
#                     search_input.clear()
#                     search_input.send_keys(keyword)
#                     logger.info(f"Entered keyword: '{keyword}' in search field")
#                     time.sleep(1)
                    
#                     # Press Enter to search
#                     search_input.send_keys(Keys.RETURN)
#                     logger.info("Pressed ENTER key to submit search")
#                     time.sleep(5)
#                 else:
#                     logger.info("No keyword provided. Browsing all tenders.")
                
#                 return True
                
#             except Exception as e:
#                 logger.error(f"Error during search attempt {attempt + 1}: {e}")
#                 if attempt < max_retries - 1:
#                     logger.info("Retrying search...")
#                     self._restart_browser_if_needed()
#                     time.sleep(5)
#                 else:
#                     logger.error("All search attempts failed")
#                     raise
    
#     def scrape_tenders(self, max_tenders=10, existing_ids=None):
#         """Scrape tender information with incremental processing"""
#         scraped_tenders = []
#         tender_info = {}
#         current_page = 1
        
#         # Tracking metrics for incremental processing
#         consecutive_existing = 0
#         total_seen = 0
#         total_new = 0
#         pages_with_no_new_content = 0
#         seen_bid_ids_across_pages = set()
        
#         # Initialize the set of existing IDs if not provided
#         if existing_ids is None:
#             existing_ids = set()
        
#         RESTART_AFTER = BROWSER_RESTART_FREQUENCY
        
#         try:
#             while len(scraped_tenders) < max_tenders and current_page <= MAX_PAGES_TO_CHECK:
#                 logger.info(f"Processing page {current_page}...")
                
#                 # ... [browser health checks and restart logic] ...
                
#                 # Extract and process tenders from the current page
#                 page_tenders, page_info, page_stats = self._process_current_page(
#                     max_tenders - len(scraped_tenders),
#                     existing_ids,
#                     seen_bid_ids_across_pages
#                 )
                
#                 # Update statistics
#                 total_seen += page_stats['total']
#                 total_new += page_stats['new']
#                 consecutive_existing = page_stats['consecutive_existing']
                
#                 # Add results to our collections
#                 scraped_tenders.extend(page_tenders)
#                 tender_info.update(page_info)
                
#                 # IMPORTANT FIX: Check if we found ANY tenders on this page (even if we skipped them all)
#                 # If page_stats['total'] > 0, we had tenders on the page (just all existing)
#                 if page_stats['page_has_repeated_content']:
#                     logger.warning(f"PAGINATION CYCLE DETECTED: Page {current_page} contains tender IDs we've seen before")
#                     logger.info("Stopping pagination to avoid infinite loop")
#                     break
                
#                 # Track pages with no new content
#                 # FIX: Use page_stats['new'] == 0 AND we actually had some tenders on the page
#                 if page_stats['new'] == 0 and page_stats['total'] > 0 and current_page > 1:
#                     pages_with_no_new_content += 1
#                     logger.info(f"Page {current_page} had no new content (consecutive: {pages_with_no_new_content})")
#                     if pages_with_no_new_content >= PAGES_WITH_NO_NEW_CONTENT_LIMIT:
#                         logger.info(f"Stopping: {pages_with_no_new_content} consecutive pages with no new content")
#                         break
#                 else:
#                     pages_with_no_new_content = 0
                
#                 if ENABLE_MEMORY_OPTIMIZATION:
#                     cleanup_memory()
                
#                 # FIX: Only check consecutive_existing if we actually processed tenders
#                 if page_stats['total'] > 0 and consecutive_existing >= MAX_CONSECUTIVE_EXISTING:
#                     logger.info(f"Stopping after seeing {consecutive_existing} consecutive existing tenders")
#                     break
                    
#                 new_percentage = 0 if total_seen == 0 else (total_new / total_seen) * 100
#                 logger.info(f"New tenders: {total_new}/{total_seen} ({new_percentage:.1f}%)")
                
#                 # FIX: Only check percentage if we've seen enough tenders
#                 if total_seen > 30 and new_percentage < NEW_THRESHOLD_PERCENT:
#                     logger.info(f"Stopping as percentage of new tenders ({new_percentage:.1f}%) is below threshold ({NEW_THRESHOLD_PERCENT}%)")
#                     break
                
#                 # FIXED CONDITION: Check if we've collected enough NEW tenders
#                 # Don't break just because page_tenders is empty (we might have skipped all)
#                 if len(scraped_tenders) >= max_tenders:
#                     break
                    
#                 # Go to next page if we found ANY tenders on this page
#                 if page_stats['total'] > 0:
#                     if not self._go_to_next_page(current_page):
#                         logger.info("No more pages available")
#                         break
#                 else:
#                     # If no tenders found at all on this page, we've probably reached the end
#                     logger.info("No tenders found on this page - likely reached the end")
#                     break
                    
#                 current_page += 1
#                 time.sleep(3)
            
#             logger.info(f"Scraped {len(scraped_tenders)} tender documents across {current_page} pages")
#             new_percentage = 0 if total_seen == 0 else (total_new / total_seen) * 100
#             logger.info(f"New tenders: {total_new}/{total_seen} ({new_percentage:.1f}%)")
#             return scraped_tenders, tender_info
                
#         except Exception as e:
#             logger.error(f"Error in scrape_tenders method: {e}")
#             return scraped_tenders, tender_info

#     def _extract_tender_id_from_gem_table(self, link_element, row_element):
#         """Extract tender ID from GEM table row - specifically look for tender ID pattern in the row"""
#         try:
#             # Get the entire row text
#             row_text = row_element.text
#             logger.debug(f"Row text: {row_text[:200]}...")
            
#             # Look for tender ID patterns in the row text
#             patterns = [
#                 r'(\d{4}_[A-Z]+_\d+_\d)',  # 2026_MNGL_263868_1
#                 r'([A-Z]{2,}/\d{4}/\d+/[A-Z0-9_-]+)',  # MNGL/CP/2025-26/130/2026_MNGL_263868_1
#                 r'/(\d{6,})/',  # /5257280/
#                 r'Tender[:\s]*([A-Z0-9_-]+)',  # Tender: 2026-ABC-123
#                 r'Ref[.\s]*No[.\s]*[:#]?\s*([A-Z0-9_-]+)',  # Ref.No.: 2026_MNGL_263868_1
#             ]
            
#             for pattern in patterns:
#                 match = re.search(pattern, row_text, re.IGNORECASE)
#                 if match:
#                     tender_id = match.group(1).strip()
#                     if tender_id:
#                         logger.info(f"Extracted tender ID from row: {tender_id}")
#                         return tender_id
            
#             # Try to find tender ID in link text
#             link_text = link_element.text.strip()
#             link_patterns = [
#                 r'(\d{4}_[A-Z]+_\d+_\d)',  # 2026_MNGL_263868_1
#                 r'([A-Z0-9_-]{6,}_\d{4,})',  # ABC123_2024
#             ]
            
#             for pattern in link_patterns:
#                 match = re.search(pattern, link_text, re.IGNORECASE)
#                 if match:
#                     tender_id = match.group(1).strip()
#                     if tender_id:
#                         logger.info(f"Extracted tender ID from link text: {tender_id}")
#                         return tender_id
            
#             # Try to get from URL - UPDATED TO EXTRACT NUMBER BEFORE viewNitPdf
#             href = link_element.get_attribute('href')
#             if href:
#                 # UPDATED: Extract whatever is there before viewNitPdf in the URL path
#                 # Improved pattern to capture number before viewNitPdf
#                 url_patterns = [
#                     # Pattern for: /pdfdocs/022026/106944866/viewNitPdf_5259071.pdf
#                     # Extract the number before viewNitPdf (106944866)
#                     # More specific pattern that captures numbers in the path before viewNitPdf
#                     r'/(\d+)/viewNitPdf[_\d]*\.pdf$',
#                     r'/(\d+)/viewNitPdf_',
#                     r'/(\d+)/viewNitPdf\.',
#                     r'/(\d+)/viewNitPdf',
                    
#                     # Alternative pattern for different URL structures
#                     r'/pdfdocs/\d+/(\d+)/viewNitPdf',
#                     r'/supply/pdfdocs/\d+/(\d+)/viewNitPdf',
#                     r'/works/pdfdocs/\d+/(\d+)/viewNitPdf',
                    
#                     # Original patterns kept for other URL formats
#                     r'TenderId=([A-Z0-9_-]+)',
#                     r'tenderId=([a-z0-9_-]+)',
#                     r'/(\d{6,})/',
#                     r'viewNitPdf_(\d+)',
#                 ]
                
#                 logger.debug(f"Trying to extract tender ID from URL: {href}")
#                 for pattern in url_patterns:
#                     match = re.search(pattern, href, re.IGNORECASE)
#                     if match:
#                         tender_id = match.group(1).strip()
#                         if tender_id:
#                             logger.info(f"Extracted tender ID from URL using pattern '{pattern}': {tender_id}")
#                             return tender_id
                
#                 # If no pattern matched, try a more general approach
#                 # Split URL by '/' and look for long numeric strings
#                 url_parts = href.split('/')
#                 for part in reversed(url_parts):  # Check from end to start
#                     if part.isdigit() and len(part) > 5:  # Look for long numeric strings
#                         logger.info(f"Extracted tender ID from URL part: {part}")
#                         return part
            
#             return None
            
#         except Exception as e:
#             logger.error(f"Error extracting tender ID from table: {e}")
#             return None

#     def _extract_tender_details_from_page(self, soup):
#         """Extract tender details from page using separate functions"""
#         tender_data = {
#             'tender_id': '',
#             'description': '',
#             'due_date': ''
#         }
        
#         try:
#             # Use the separate functions that were defined but never called
#             tender_id = self._find_tender_id_in_page(soup)
#             description = self._find_description(soup)
#             due_date = self._find_due_date(soup)
            
#             tender_data['tender_id'] = tender_id if tender_id else ''
#             tender_data['description'] = description if description else ''
#             tender_data['due_date'] = due_date if due_date else 'Not specified'
            
#         except Exception as e:
#             logger.error(f"Error in extracting tender details from page: {e}")
        
#         return tender_data
        
#     def _extract_gem_tender_data(self):
#         """Extract tender data from GEM tender page using BeautifulSoup"""
#         try:
#             # Get page source and parse with BeautifulSoup
#             page_source = self.driver.page_source
#             soup = BeautifulSoup(page_source, 'html.parser')
            
#             # Use the new function that calls the separate functions
#             tender_data = self._extract_tender_details_from_page(soup)
            
#             # Initialize result dictionary
#             tender_data.update({
#                 'scraped_url': self.driver.current_url,
#                 'scraped_timestamp': datetime.now().isoformat(),
#                 'is_pdf': False
#             })
            
#             # Format due date if we have it
#             if tender_data['due_date'] and tender_data['due_date'] != 'Not specified':
#                 try:
#                     # Try to parse and format consistently
#                     date_formats = [
#                         "%d-%b-%Y", "%d/%b/%Y", "%d %b %Y",
#                         "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"
#                     ]
                    
#                     for fmt in date_formats:
#                         try:
#                             dt = datetime.strptime(tender_data['due_date'].split()[0], fmt)
#                             tender_data['due_date'] = dt.strftime("%d-%m-%Y")
#                             break
#                         except:
#                             continue
#                 except:
#                     pass
            
#             logger.info(f"Extracted tender data: ID={tender_data['tender_id'][:30]}, "
#                     f"Desc={tender_data['description'][:50]}..., "
#                     f"Due={tender_data['due_date']}")
            
#             return tender_data
            
#         except Exception as e:
#             logger.error(f"Error extracting GEM tender data: {e}")
#             return {
#                 'tender_id': '',
#                 'description': '',
#                 'due_date': '',
#                 'scraped_url': self.driver.current_url,
#                 'scraped_timestamp': datetime.now().isoformat(),
#                 'is_pdf': False,
#                 'error': str(e)
#             }

#     def _process_current_page(self, max_tenders_to_process, existing_ids=None, seen_bid_ids_across_pages=None):
#         """Process tenders on the current page - COMPLETE ALL TENDERS ON CURRENT PAGE BEFORE MOVING ON"""
#         scraped_tenders = []
#         tender_info = {}
        
#         stats = {
#             'total': 0,
#             'new': 0,
#             'existing': 0,
#             'consecutive_existing': 0,
#             'page_has_repeated_content': False
#         }
        
#         if existing_ids is None:
#             existing_ids = set()
#         if seen_bid_ids_across_pages is None:
#             seen_bid_ids_across_pages = set()

#         try:
#             logger.info("Looking for tender elements on GEM portal...")
            
#             main_page_url = self.driver.current_url
#             tender_links_info = []  # List of tuples: (tender_id, href, title, is_pdf)
#             current_page_tender_ids = set()
            
#             # Wait for the tender table to load
#             time.sleep(3)
            
#             # Strategy: Find the tender table and extract tender title links
#             try:
#                 # Find all table rows that contain tender information
#                 # Look for rows that have the tender title links (usually in a specific column)
#                 tender_rows = self.driver.find_elements(By.XPATH, "//table//tr[.//a[@target='_blank']]")
#                 logger.info(f"Found {len(tender_rows)} tender rows with target='_blank' links")
                
#                 for row in tender_rows:
#                     try:
#                         # Find the tender title link within this row
#                         tender_links = row.find_elements(By.XPATH, ".//a[@target='_blank']")
                        
#                         for link in tender_links:
#                             try:
#                                 if link.is_displayed() and link.is_enabled():
#                                     href = link.get_attribute('href')
#                                     text = link.text.strip()
                                    
#                                     # Check if this looks like a tender title (not "Download" or other navigation)
#                                     if href and text and len(text) > 10 and 'download' not in text.lower():
#                                         # Extract tender ID from the link text or URL
#                                         tender_id = self._extract_tender_id_from_gem_table(link, row)
                                        
#                                         if tender_id:
#                                             current_page_tender_ids.add(tender_id)
#                                             # Check if it's a PDF URL using the dedicated function
#                                             is_pdf = self._is_pdf_url(href)
#                                             tender_links_info.append((tender_id, href, text, is_pdf))
#                                             logger.info(f"Found tender title link: ID={tender_id}, Text='{text[:50]}...', PDF={is_pdf}")
#                                             break  # Only take the first tender link in this row
#                             except Exception as e:
#                                 logger.debug(f"Error processing tender link: {e}")
#                                 continue
#                     except Exception as e:
#                         logger.debug(f"Error processing row: {e}")
#                         continue
            
#             except Exception as e:
#                 logger.error(f"Error finding tender rows: {e}")
#                 # Alternative: try to find all target='_blank' links and filter
#                 try:
#                     all_blank_links = self.driver.find_elements(By.XPATH, "//a[@target='_blank']")
#                     logger.info(f"Found {len(all_blank_links)} links with target='_blank'")
                    
#                     for link in all_blank_links:
#                         try:
#                             href = link.get_attribute('href')
#                             text = link.text.strip()
                            
#                             if href and text and len(text) > 10:
#                                 # Skip navigation links
#                                 if any(nav in text.lower() for nav in ['download', 'print', 'view', 'terms', 'handbook', 'training']):
#                                     continue
                                
#                                 # Extract tender ID from the link text or URL
#                                 tender_id = self._extract_tender_id_from_gem_table(link, link)  # Passing link as both parameters
#                                 if tender_id:
#                                     current_page_tender_ids.add(tender_id)
#                                     # Check if it's a PDF URL using the dedicated function
#                                     is_pdf = self._is_pdf_url(href)
#                                     tender_links_info.append((tender_id, href, text, is_pdf))
#                                     logger.info(f"Found tender via all links: ID={tender_id}, Text='{text[:50]}...', PDF={is_pdf}")
#                         except:
#                             continue
#                 except Exception as e2:
#                     logger.error(f"Error in alternative search: {e2}")
            
#             # Check for pagination cycle
#             if current_page_tender_ids and current_page_tender_ids.issubset(seen_bid_ids_across_pages):
#                 stats['page_has_repeated_content'] = True
#                 logger.warning(f"Detected repeated content: {len(current_page_tender_ids)} tender IDs already seen on previous pages")
#             else:
#                 seen_bid_ids_across_pages.update(current_page_tender_ids)

#             logger.info(f"Total unique tender links extracted on current page: {len(tender_links_info)}")
            
#             # PROCESS ALL TENDERS ON CURRENT PAGE
#             # But only until we reach the global max_tenders limit
#             tender_links_to_process = tender_links_info
#             logger.info(f"Will process {len(tender_links_to_process)} tenders from this page")
            
#             for i, (tender_id, href, title, is_pdf) in enumerate(tender_links_to_process):
#                 # Check if we've reached the global limit
#                 if len(scraped_tenders) >= max_tenders_to_process:
#                     logger.info(f"Reached global limit of {max_tenders_to_process} tenders. Stopping page processing.")
#                     break
                    
#                 try:
#                     stats['total'] += 1
                    
#                     logger.info(f"Processing tender {i+1}/{len(tender_links_to_process)}: {href} (ID: {tender_id})")
                    
#                     if not self._is_browser_alive():
#                         logger.error("Browser disconnected during tender processing")
#                         break
                    
#                     # Check if this tender ID already exists
#                     is_new_tender = tender_id not in existing_ids
                    
#                     if is_new_tender:
#                         stats['new'] += 1
#                         stats['consecutive_existing'] = 0
#                         logger.info(f"New tender found: {tender_id}")
#                     else:
#                         stats['existing'] += 1
#                         stats['consecutive_existing'] += 1
#                         logger.info(f"Existing tender found: {tender_id}")
                        
#                         if ONLY_PROCESS_NEW:
#                             logger.info(f"Skipping existing tender: {tender_id}")
#                             continue
                    
#                     tender_data = {}
                    
#                     # Check if it's a PDF URL
#                     if is_pdf:
#                         # For PDF tenders, just print the URL and capture minimal data
#                         logger.info(f"PDF tender detected: {href}")
#                         tender_data = {
#                             'tender_id': tender_id,
#                             'description': f"PDF Tender: {title}",
#                             'due_date': 'Not specified',
#                             'scraped_url': href,
#                             'scraped_timestamp': datetime.now().isoformat(),
#                             'is_pdf': True,
#                             'pdf_url': href
#                         }
#                     else:
#                         # For HTML tenders, navigate to the page and extract data
#                         # Store current window handle
#                         main_window = self.driver.current_window_handle
                        
#                         # Click the tender link to open in new tab
#                         try:
#                             # Find the link again to click it
#                             link_element = self.driver.find_element(By.XPATH, f"//a[@target='_blank' and contains(@href, '{href.split('/')[-1]}')]")
                            
#                             # Click to open in new tab
#                             link_element.click()
#                             time.sleep(3)
                            
#                             # Switch to new tab
#                             new_window = [window for window in self.driver.window_handles if window != main_window][0]
#                             self.driver.switch_to.window(new_window)
                            
#                             # Wait for page to load
#                             time.sleep(3)
                            
#                             # Extract data using BeautifulSoup
#                             tender_data = self._extract_gem_tender_data()
#                             tender_data['tender_id'] = tender_id
#                             tender_data['scraped_url'] = self.driver.current_url
#                             tender_data['is_pdf'] = False
                            
#                             logger.info(f"Extracted HTML tender data for {tender_id}")
                            
#                             # Close the tender tab
#                             self.driver.close()
                            
#                             # Switch back to main window
#                             self.driver.switch_to.window(main_window)
                            
#                         except Exception as nav_error:
#                             logger.error(f"Error navigating to tender page: {nav_error}")
#                             tender_data = {
#                                 'tender_id': tender_id,
#                                 'description': f"Error accessing tender: {title}",
#                                 'due_date': 'Not specified',
#                                 'scraped_url': href,
#                                 'scraped_timestamp': datetime.now().isoformat(),
#                                 'is_pdf': False,
#                                 'error': str(nav_error)
#                             }
                            
#                             # Try to get back to main window
#                             try:
#                                 if len(self.driver.window_handles) > 1:
#                                     self.driver.close()
#                                 self.driver.switch_to.window(main_window)
#                             except:
#                                 try:
#                                     self.driver.get(main_page_url)
#                                     time.sleep(3)
#                                 except:
#                                     pass
                    
#                     # Store tender information
#                     tender_info[tender_id] = {
#                         'url': href,
#                         'title': title,
#                         'tender_data': tender_data,
#                         'is_pdf': tender_data.get('is_pdf', False)
#                     }
#                     scraped_tenders.append(tender_id)
                    
#                     existing_ids.add(tender_id)
                    
#                     if ENABLE_MEMORY_OPTIMIZATION:
#                         gc.collect()
                
#                 except Exception as e:
#                     logger.error(f"Error processing tender {i+1}: {e}")
#                     if not self._is_browser_alive():
#                         logger.error("Browser connection lost during tender processing")
#                         break
            
#             return scraped_tenders, tender_info, stats

#         except Exception as e:
#             logger.error(f"Error processing page: {e}")
#             return [], {}, stats
    
#     def _is_pdf_url(self, url):
#         """Check if the URL points to a PDF file"""
#         pdf_patterns = [
#             r'\.pdf$',
#             r'\.pdf\?',
#             r'contentType=pdf',
#             r'type=pdf',
#             r'format=pdf',
#             r'file=.*\.pdf'
#         ]
        
#         url_lower = url.lower()
#         for pattern in pdf_patterns:
#             if re.search(pattern, url_lower):
#                 return True, url
#         return False

#     def _find_tender_id_in_page(self, soup):
#         """Find tender ID in the page content"""
#         try:
#             # Look for any td with class 'td_caption' containing "Tender ID"
#             for td in soup.find_all('td', class_='td_caption'):
#                 text = td.get_text(strip=True)
#                 if text and 'Tender ID' in text:
#                     next_td = td.find_next_sibling('td')
#                     if next_td:
#                         # Get the text and clean it
#                         tender_id = next_td.get_text(strip=True)
#                         # Remove any <b> tags but keep the text
#                         if hasattr(tender_id, 'get_text'):
#                             tender_id = tender_id.get_text(strip=True)
#                         logger.info(f"Found tender ID in page: {tender_id}")
#                         return tender_id
#         except Exception as e:
#             logger.error(f"Error finding tender ID: {e}")
        
#         return None

#     def _find_description(self, soup):
#         """Find description in the page using Work Description field"""
#         try:
#             # Look for any td with class 'td_caption' containing "Work Description"
#             for td in soup.find_all('td', class_='td_caption'):
#                 if 'Work Description' in td.get_text(strip=True):
#                     next_td = td.find_next_sibling('td')
#                     if next_td:
#                         description = next_td.get_text(strip=True)
#                         logger.info(f"Found description in page: {description[:50]}...")
#                         return description
#         except Exception as e:
#             logger.error(f"Error finding description: {e}")
        
#         return ''

#     def _find_due_date(self, soup):
#         """Find due date in the page - specifically Bid Submission End Date"""
#         try:
#             # Look for any td with class 'td_caption' containing "Bid Submission End Date"
#             for td in soup.find_all('td', class_='td_caption'):
#                 text = td.get_text(strip=True)
#                 if text and 'Bid Submission End Date' in text:
#                     next_td = td.find_next_sibling('td')
#                     if next_td:
#                         raw_date = next_td.get_text(strip=True)
#                         # Example raw_date = "22-Jan-2026 05:00 PM"

#                         try:
#                             dt = datetime.strptime(raw_date, "%d-%b-%Y %I:%M %p")
#                             # Convert to your system format
#                             formatted_date = dt.strftime("%d-%m-%Y")
#                             logger.info(f"Found due date in page: {formatted_date}")
#                             return formatted_date
#                         except ValueError:
#                             logger.warning(f"Unable to parse due date: {raw_date}")
#                             return raw_date
        
#         except Exception as e:
#             logger.error(f"Error finding due date: {e}")
        
#         return 'Not specified'
    
#     def _go_to_next_page(self, current_page):
#         """Navigate to the next page of results using pagination links"""
#         max_attempts = 3
#         for attempt in range(max_attempts):
#             try:
#                 # Check browser health first
#                 if not self._is_browser_alive():
#                     logger.error("Browser not alive during pagination")
#                     return False
                
#                 # Find the "Next" link in the pagination
#                 try:
#                     # First try to find exact "Next" link
#                     next_links = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Next')]")
                    
#                     if not next_links:
#                         # Try to find pagination links with page numbers
#                         pagination_links = self.driver.find_elements(By.CSS_SELECTOR, ".pagination a")
#                         next_page_num = current_page + 1
                        
#                         for link in pagination_links:
#                             if str(next_page_num) in link.text:
#                                 next_links = [link]
#                                 break
                    
#                     if not next_links:
#                         logger.info("No next page link found - reached end of results")
#                         return False
                    
#                     next_link = next_links[0]
                    
#                     if next_link.is_displayed() and next_link.is_enabled():
#                         # Scroll into view and click
#                         self.driver.execute_script("arguments[0].scrollIntoView(true);", next_link)
#                         time.sleep(1)
#                         self.driver.execute_script("arguments[0].click();", next_link)
#                         logger.info(f"Clicked next page link to go to page {current_page + 1}")
#                         time.sleep(5)
                        
#                         # Wait for content to change
#                         try:
#                             WebDriverWait(self.driver, 15).until(
#                                 lambda d: len(d.find_elements(By.XPATH, "//a[@target='_blank']")) > 0
#                             )
#                             logger.info(f"Successfully navigated to page {current_page + 1}")
#                             return True
#                         except TimeoutException:
#                             logger.warning(f"Content didn't change after clicking next page (attempt {attempt + 1})")
#                             if attempt < max_attempts - 1:
#                                 time.sleep(3)
#                                 continue
#                             else:
#                                 logger.error(f"Failed to navigate to next page after {max_attempts} attempts")
#                                 return False
#                     else:
#                         logger.warning("Next page link not clickable")
#                         return False
                        
#                 except NoSuchElementException:
#                     logger.info("No next page link found - reached end of results")
#                     return False
                
#             except Exception as e:
#                 logger.error(f"Pagination attempt {attempt + 1} failed: {e}")
#                 if attempt < max_attempts - 1:
#                     time.sleep(3)
#                     self._restart_browser_if_needed()
#                 else:
#                     logger.error(f"Pagination failed after {max_attempts} attempts")
#                     return False
        
#         return False

# def save_to_db(tender_data, organization_id):
#     """Save tender data to gem_tenders table - ONLY store tender_id, description, due_date"""
#     from sqlalchemy import text
#     from database_config import engine
    
#     try:
#         # Extract fields from tender data
#         tender_id = tender_data.get('tender_id', '')
#         description = tender_data.get('description', '')[:10000]  # Limit length
#         due_date = tender_data.get('due_date', 'Not specified')
        
#         # NEW: Get PDF URL if available
#         document_url = tender_data.get('scraped_url', '')
#         if not document_url:
#             document_url = tender_data.get('pdf_url', '')  # For PDF tenders
        
#         # Skip if no tender ID
#         if not tender_id:
#             logger.warning(f"No tender ID found in data, skipping save")
#             return
        
#         # DEBUG: Log what we're trying to save
#         logger.debug(f"Attempting to save to DB - Tender ID: {tender_id}, Description length: {len(description)}, Due date: {due_date}, Document URL: {document_url}")
        
#         with engine.connect() as conn:
#             # Check if tender already exists using the ACTUAL tender_id from data
#             result = conn.execute(
#                 text("SELECT id FROM gem_tenders WHERE tender_id = :tender_id AND organization_id = :org_id"),
#                 {
#                     "tender_id": tender_id,
#                     "org_id": organization_id
#                 }
#             )
#             existing_tender = result.fetchone()
            
#             # DEBUG: Log if tender exists
#             logger.debug(f"Tender {tender_id} exists in DB: {existing_tender is not None}")
            
#             if existing_tender:
#                 # Update existing tender - NOW INCLUDING document_url
#                 update_result = conn.execute(text("""
#                     UPDATE gem_tenders SET
#                         description = :description,
#                         due_date = :due_date,
#                         document_url = :document_url,  -- NEW: Store PDF URL
#                         portal = :portal,
#                         updated_at = CURRENT_TIMESTAMP
#                     WHERE tender_id = :tender_id AND organization_id = :org_id
#                 """), {
#                     "description": description,
#                     "due_date": due_date,
#                     "document_url": document_url,  # NEW
#                     "portal": "GEM_CPPP",
#                     "tender_id": tender_id,
#                     "org_id": organization_id
#                 })
#                 logger.info(f"Updated existing tender {tender_id} for organization {organization_id}")
#                 logger.debug(f"Rows affected by update: {update_result.rowcount}")
#             else:
#                 # Create new tender - NOW INCLUDING document_url
#                 insert_result = conn.execute(text("""
#                     INSERT INTO gem_tenders (
#                         tender_id, description, due_date, creation_date, matches_services, match_reason,
#                         document_url, pdf_path, organization_id, match_score, keywords,
#                         match_score_keyword, match_score_combined, api_calls_made, tokens_used,
#                         relevance_percentage, is_central_match, strategic_fit, primary_scope, portal
#                     ) VALUES (
#                         :tender_id, :description, :due_date, :creation_date, :matches_services, :match_reason,
#                         :document_url, :pdf_path, :org_id, :match_score, :keywords,
#                         :match_score_keyword, :match_score_combined, :api_calls_made, :tokens_used,
#                         :relevance_percentage, :is_central_match, :strategic_fit, :primary_scope, :portal
#                     )
#                 """), {
#                     "tender_id": tender_id,
#                     "description": description,
#                     "due_date": due_date,
#                     "creation_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
#                     "matches_services": False,
#                     "match_reason": "",
#                     "document_url": document_url,  # NEW: Store PDF URL here
#                     "pdf_path": "",
#                     "org_id": organization_id,
#                     "match_score": 0.0,
#                     "keywords": "",
#                     "match_score_keyword": 0.0,
#                     "match_score_combined": 0.0,
#                     "api_calls_made": 0,
#                     "tokens_used": 0,
#                     "relevance_percentage": 0.0,
#                     "is_central_match": False,
#                     "strategic_fit": False,
#                     "primary_scope": "",
#                     "portal": "GEM_CPPP"
#                 })
#                 logger.info(f"Created new tender {tender_id} for organization {organization_id}")
#                 logger.debug(f"Rows affected by insert: {insert_result.rowcount}")
            
#             conn.commit()
#             logger.debug(f"Commit successful for tender {tender_id}")

#     except Exception as e:
#         logger.error(f"Database error: {e}")
#         logger.error(f"Full error details: {e.__class__.__name__}: {str(e)}")
#         if hasattr(e, 'orig'):
#             logger.error(f"Original error: {e.orig}")
#         raise

# def main(search_keyword=None, max_tenders=30, organization_id=None, domain_keywords=None):
#     """Main function to run the GEM CPPP scraper"""
#     global ONLY_PROCESS_NEW
    
#     logger.info("=" * 80)
#     logger.info("GEM CPPP Tender Scraper")
#     logger.info("=" * 80)
    
#     # Interactive mode - ask for organization if not provided
#     if organization_id is None:
#         try:
#             organization_id = int(input("Enter organization ID: ").strip())
#         except ValueError:
#             logger.error("Invalid organization ID provided")
#             return
    
#     # Get set of existing tender IDs from the database for this organization
#     existing_ids = get_existing_tender_ids(organization_id)
#     logger.info(f"Retrieved {len(existing_ids)} existing tender IDs for organization {organization_id}")
    
#     # Ask if user wants to do incremental processing in interactive mode
#     if search_keyword is None:  # Interactive mode
#         incremental = input("Do you want to only process new tenders? (y/n, default: y): ").strip().lower()
#         ONLY_PROCESS_NEW = incremental != 'n'
        
#         # Get user input for keyword - allow empty for no filtering
#         search_keyword = input("Enter keyword to search for tenders (leave empty to browse all tenders): ").strip()
#         search_keyword = search_keyword if search_keyword else None

#         max_tenders = input("Enter maximum number of tenders to scrape (default 30): ")
#         max_tenders = int(max_tenders) if max_tenders.strip() else 30

#     if search_keyword:
#         logger.info(f"Searching for keyword: '{search_keyword}'")
#     else:
#         logger.info("Browsing all available tenders")
    
#     # Initialize scraper but don't start browser yet
#     scraper = GEMCPPPTenderScraper()
    
#     # Use context manager to ensure browser is always closed
#     with BrowserContext(scraper) as browser:
#         try:
#             # Search and scrape tenders
#             logger.info("Starting the browser and scraping tenders...")
#             browser.search_bids(search_keyword)
#             scraped_tenders, tender_info = browser.scrape_tenders(max_tenders=max_tenders, existing_ids=existing_ids)
            
#             if not scraped_tenders:
#                 logger.warning("No new tenders were scraped. Try again with a different keyword or disable incremental processing.")
#                 return
            
#             for i, tender_id in enumerate(scraped_tenders):
#                 logger.info(f"Processing tender {i+1} of {len(scraped_tenders)}: {tender_id}")
                
#                 # Get tender details
#                 tender_details = tender_info.get(tender_id, {})
#                 tender_data = tender_details.get('tender_data', {})
                
#                 # Save to database with organization_id - ONLY the 3 fields
#                 save_to_db(tender_data, organization_id)
                
#                 # Update the existing IDs set for future checks
#                 existing_ids.add(tender_id)
                
#                 # Explicitly call garbage collection to free memory
#                 if ENABLE_MEMORY_OPTIMIZATION:
#                     gc.collect()
            
#             # Output summary
#             logger.info("\n=== Scraping Summary ===")
#             logger.info(f"Scraped {len(scraped_tenders)} new tenders")
#             logger.info(f"Portal: GEM CPPP")
            
#             # Save summary CSV
#             try:
#                 # Create a simplified CSV with the 3 fields
#                 csv_data = []
#                 for tender_id in scraped_tenders:
#                     tender_details = tender_info.get(tender_id, {})
#                     tender_data = tender_details.get('tender_data', {})
                    
#                     csv_data.append({
#                         'tender_id': tender_id,
#                         'description': tender_data.get('description', '')[:500],
#                         'due_date': tender_data.get('due_date', ''),
#                         'url': tender_details.get('url', '')
#                     })
                
#                 df = pd.DataFrame(csv_data)
#                 timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
#                 output_file = os.path.join(DOWNLOAD_FOLDER, f"cppp_tenders_org{organization_id}_{timestamp}.csv")
#                 df.to_csv(output_file, index=False, encoding='utf-8-sig')
#                 logger.info(f"Summary CSV saved to {output_file}")
                
#             except Exception as e:
#                 logger.error(f"Error saving CSV file: {e}")
        
#         except Exception as e:
#             logger.error(f"Error in main function: {e}", exc_info=True)
            
#     # Final cleanup and summary
#     if ENABLE_MEMORY_OPTIMIZATION:
#         cleanup_memory()
    
#     logger.info("GEM CPPP scraper completed successfully!")

# def main_cli(search_keyword, max_tenders, organization_id, domain_keywords=None):
#     """Entry point for CLI/scheduled execution"""
#     global ONLY_PROCESS_NEW
#     ONLY_PROCESS_NEW = True
#     logger.info(f"Running GEM CPPP scraper via CLI for organization {organization_id}")
#     main(search_keyword=search_keyword, max_tenders=max_tenders, organization_id=organization_id, domain_keywords=domain_keywords)

# if __name__ == "__main__":
#     try:
#         if len(sys.argv) > 1:
#             search_keyword = sys.argv[1] if sys.argv[1].lower() != "none" else None
#             max_tenders = int(sys.argv[2]) if len(sys.argv) > 2 else 30
#             organization_id = int(sys.argv[3]) if len(sys.argv) > 3 else None
#             domain_keywords = []
#             if len(sys.argv) > 4 and sys.argv[4] != "NONE":
#                 domain_keywords = [kw.strip().lower() for kw in sys.argv[4].split('|')]
#             logger.info("Running GEM CPPP scraper with CLI arguments")
#             main_cli(search_keyword, max_tenders, organization_id, domain_keywords)
#         else:
#             logger.info("Running GEM CPPP scraper in interactive mode")
#             main()
#     except KeyboardInterrupt:
#         logger.info("Operation cancelled by user.")
#     except Exception as e:
#         logger.error(f"An unexpected error occurred: {e}")



























































# def create_new_tender(user_id, organization_id, files):  
#     """Create a new tender with uploaded files and extract proper title"""    
    
#     # Default fallback
#     tender_title = f"Tender {uuid.uuid4().hex[:8]}"
    
#     if files:
#         first_file = files[0]
#         file_extension = os.path.splitext(first_file.filename)[1].lower()
        
#         if file_extension in ['.pdf', '.txt']:
#             try:
#                 # Save temporarily for extraction
#                 unique_filename = secure_filename(f"{uuid.uuid4()}_{first_file.filename}")
#                 temp_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
#                 first_file.save(temp_file_path)

#                 # Extract preview text
#                 temp_content = ""
#                 if file_extension == '.pdf':
#                     with fitz.open(temp_file_path) as doc:
#                         for i, page in enumerate(doc):
#                             if i >= 2:   # only first 2 pages for speed
#                                 break
#                             temp_content += page.get_text() or ""
#                 else:  # .txt
#                     with open(temp_file_path, 'r', encoding='utf-8') as f:
#                         temp_content = f.read()
                
#                 first_file.seek(0)  # reset pointer for later
                
#                 # Use Gemini to extract title
#                 if temp_content.strip():
#                     model = init_gemini()
#                     preview = temp_content[:2000]
#                     prompt = f"""
#                     Extract tender number and title from this document. Return only JSON like:
#                     {{"number": "GEM/2023/B/3292506", "title": "Procurement of Ball Valves on ARC Basis"}}
                    
#                     Text: {preview}
#                     """
#                     response = model.generate_content(prompt)

#                     try:
#                         json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
#                         if json_match:
#                             result = json.loads(json_match.group(0))
#                             number = result.get('number', f"TDR-{datetime.datetime.now().year}-001")
#                             title = result.get('title', "Tender Document")
#                             tender_title = f"{number} - {title}"
#                             print(f"[INFO] Extracted title: {tender_title}")
#                         else:
#                             print("[WARN] No JSON found in Gemini response")
#                     except Exception as e:
#                         print(f"[WARN] Failed to parse title JSON: {e}")
                
#                 os.remove(temp_file_path)

#             except Exception as e:
#                 print(f"[WARN] Title extraction failed: {e}")
#                 first_file.seek(0)  # ensure file is reusable
    
#     # Create tender record
#     new_tender = Tender(
#         title=tender_title,
#         user_id=user_id,
#         organization_id=organization_id
#     )
#     db.session.add(new_tender)
#     db.session.flush()  # Get ID before commit
    
#     # Process uploaded files
#     processed_files, errors = [], []
#     main_document_content = None
#     all_documents_content = []  # New: collect all content
#     processed_documents = []  # Store document objects for hyperlink extraction
    
#     for index, file in enumerate(files):
#         file_extension = os.path.splitext(file.filename)[1].lower()
#         if file_extension not in ['.pdf', '.txt']:
#             errors.append(f"{file.filename}: Only PDF and TXT files are supported")
#             continue

#         try:
#             file_data = save_uploaded_file(file)
#             is_primary = (index == 0)
            
#             document = Document(
#                 filename=file_data['filename'],
#                 original_filename=file_data['original_filename'],
#                 file_path=file_data['file_path'],
#                 file_type=file_data['file_type'],
#                 file_size=file_data['file_size'],
#                 # content_text=file_data['content_text'],
#                 is_primary=is_primary,
#                 tender_id=new_tender.id
#             )
#             db.session.add(document)
#             processed_documents.append(document)  # Store for hyperlink extraction

#             if is_primary:
#                 main_document_content = file_data['content_text']
            
#             # Collect all document content but limit each to prevent overflow
#             if file_data['content_text']:
#                 # Limit each document to 150k characters to prevent processing issues
#                 limited_content = file_data['content_text'][:150000]
#                 all_documents_content.append({
#                     'content': limited_content,
#                     'filename': file.filename,
#                     'is_primary': is_primary
#                 })
            
#             processed_files.append(file.filename)
        
#         except Exception as e:
#             errors.append(f"{file.filename}: {str(e)}")

#     # Extract overview with intelligent content combination AND hyperlink support
#     if all_documents_content:
#         try:
#             if len(all_documents_content) == 1:
#                 # Single document - use as is
#                 content_for_overview = all_documents_content[0]['content']
#                 print(f"[INFO] Single document processing: {len(content_for_overview):,} characters")
#             else:
#                 # Multiple documents - smart combination strategy
#                 print(f"[INFO] Processing {len(all_documents_content)} documents")
                
#                 # Start with primary document
#                 primary_doc = next((doc for doc in all_documents_content if doc['is_primary']), all_documents_content[0])
#                 content_for_overview = primary_doc['content']
                
#                 # Add sections from other documents
#                 for doc in all_documents_content:
#                     if not doc['is_primary']:
#                         # Add a separator and portion of additional documents
#                         additional_content = f"\n\n--- ADDITIONAL DOCUMENT: {doc['filename']} ---\n"
#                         additional_content += doc['content'][:50000]  # Limit additional docs to 80k chars
#                         content_for_overview += additional_content
                
#                 # Final safety check on total content length
#                 if len(content_for_overview) > 400000:
#                     print(f"[WARN] Combined content very large ({len(content_for_overview):,} chars), truncating")
#                     content_for_overview = content_for_overview[:400000]
#                     # Try to end at a sentence boundary
#                     last_period = content_for_overview.rfind('.')
#                     if last_period > 300000:
#                         content_for_overview = content_for_overview[:last_period + 1]
                
#                 print(f"[INFO] Combined content length: {len(content_for_overview):,} characters")
            
#             # Get the primary document path for hyperlink extraction
#             primary_doc_path = None
#             primary_doc = next((doc for doc in processed_documents if doc.is_primary), None)
#             if primary_doc and primary_doc.file_path and os.path.exists(primary_doc.file_path):
#                 primary_doc_path = primary_doc.file_path
#                 print(f"[INFO] Using primary document for hyperlink extraction: {primary_doc_path}")
            
#             # Extract overview data WITH HYPERLINK SUPPORT
#             overview_data = extract_tender_overview(content_for_overview, primary_doc_path)
            
#             # Apply overview data to tender record
#             new_tender.due_date = overview_data.get('due_date')
#             new_tender.bid_opening_date = overview_data.get('bid_opening_date')
#             new_tender.bid_offer_validity = overview_data.get('bid_offer_validity')
#             new_tender.emd_amount = overview_data.get('emd_amount')
#             new_tender.qualification_criteria = overview_data.get('qualification_criteria')
#             new_tender.question_deadline = overview_data.get('question_deadline')
#             new_tender.reverse_auction = overview_data.get('reverse_auction')
#             new_tender.rejection_criteria = overview_data.get('rejection_criteria')
#             new_tender.msme_preferences = overview_data.get('msme_preferences')
#             new_tender.border_country_clause = overview_data.get('border_country_clause')
#             new_tender.tender_number = overview_data.get('tender_number')
#             new_tender.organization_details = overview_data.get('organization_details')
#             new_tender.performance_security = overview_data.get('performance_security')
#             new_tender.payment_terms = overview_data.get('payment_terms')
#             new_tender.technical_specifications = overview_data.get('technical_specifications')
#             new_tender.scope_of_work = overview_data.get('scope_of_work')
#             new_tender.performance_standards = overview_data.get('performance_standards')
#             new_tender.evaluation_criteria = overview_data.get('evaluation_criteria')
#             new_tender.documentation_requirements = overview_data.get('documentation_requirements')
#             new_tender.additional_details = overview_data.get('additional_details')
            
#             print(f"[INFO] Overview extraction completed successfully")

#             # --- Insert Products (if available) for uploaded tender ---
#             try:
#                 products_data = overview_data.get('products_table') or []
#                 if isinstance(products_data, list) and len(products_data) > 0:
#                     print(f"[DEBUG] Inserting {len(products_data)} products for Tender ID={new_tender.id}")
#                     for p in products_data:
#                         product = Product(
#                             tender_id=new_tender.id,
#                             product_name=p.get('product_name', 'Not specified'),
#                             quantity=p.get('quantity', 'Not specified'),
#                             delivery_days=p.get('delivery_days', 'Not specified'),
#                             consignee_name=p.get('consignee_name', 'Not specified'),
#                             delivery_address=p.get('delivery_address', 'Not specified'),
#                             specification_link=p.get('specification_link') or None
#                         )
#                         db.session.add(product)
#                     print(f"[DEBUG] Products queued for insert for Tender ID={new_tender.id}")
#                 else:
#                     print("[INFO] No product data found in overview_data for uploaded tender.")
#             except Exception as e:
#                 print(f"[ERROR] Failed to insert products for uploaded tender: {e}")
#                 import traceback
#                 print(traceback.format_exc())
#                 # Continue — we still want to commit other data

#         except Exception as e:
#             print(f"[ERROR] Overview extraction failed: {e}")
#             import traceback
#             traceback.print_exc()
#             # Continue without overview data rather than failing the entire upload
#             print("[WARN] Continuing without overview data")
    
#     if processed_files:
#         db.session.commit()
#         return {
#             'success': True,
#             'tender_id': new_tender.id,
#             'processed_files': processed_files,
#             'errors': errors
#         }
#     else:
#         db.session.rollback()
#         return {
#             'success': False,
#             'errors': errors or ['No files were processed successfully']
#         }




































































# def create_new_tender(user_id, organization_id, files):  
#     """Create a new tender with uploaded files and extract proper title"""    
    
#     # Process all files first to extract preview content
#     all_file_contents = []
#     processed_files_preview = []
    
#     for file in files:
#         file_extension = os.path.splitext(file.filename)[1].lower()
#         if file_extension not in ['.pdf', '.txt']:
#             continue
            
#         try:
#             # Save temporarily for extraction
#             unique_filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
#             temp_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
#             file.save(temp_file_path)

#             # Extract preview text
#             temp_content = ""
#             if file_extension == '.pdf':
#                 with fitz.open(temp_file_path) as doc:
#                     for i, page in enumerate(doc):
#                         if i >= 2:   # only first 2 pages for speed
#                             break
#                         temp_content += page.get_text() or ""
#             else:  # .txt
#                 with open(temp_file_path, 'r', encoding='utf-8') as f:
#                     temp_content = f.read()
            
#             all_file_contents.append({
#                 'filename': file.filename,
#                 'content': temp_content[:2000],  # Limit to 2000 chars for Gemini
#                 'extension': file_extension
#             })
#             processed_files_preview.append(file.filename)
            
#             file.seek(0)  # reset pointer for later
#             os.remove(temp_file_path)
            
#         except Exception as e:
#             print(f"[WARN] Failed to extract preview from {file.filename}: {e}")
#             file.seek(0)  # ensure file is reusable
    
#     # Default fallback
#     tender_title = f"Tender {uuid.uuid4().hex[:8]}"
#     tender_number = None
    
#     # Use Gemini to identify main file and extract title/number from it
#     if all_file_contents:
#         try:
#             model = init_gemini()
            
#             # Build prompt for Gemini
#             files_info = ""
#             for i, file_data in enumerate(all_file_contents):
#                 files_info += f"File {i+1}: {file_data['filename']}\n"
#                 files_info += f"Preview: {file_data['content']}\n"
#                 files_info += "---\n"
            
#             prompt = f"""
#             Analyze these tender documents. First identify which file is the main tender document (most important).
#             Then extract tender number and title FROM THE MAIN DOCUMENT ONLY.
            
#             Files:
#             {files_info}
            
#             Return JSON format:
#             {{
#                 "main_document_index": 0,
#                 "number": "GEM/2023/B/3292506",
#                 "title": "Procurement of Ball Valves on ARC Basis"
#             }}
#             main_document_index should be 0-based index of the most important file.
#             If tender number not found, use "Unknown"
#             If tender title not found, use "Tender Document"
#             """
            
#             response = model.generate_content(prompt)

#             try:
#                 json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
#                 if json_match:
#                     result = json.loads(json_match.group(0))
                    
#                     # Get main document index
#                     main_doc_index = result.get('main_document_index', 0)
#                     if main_doc_index >= len(files):
#                         main_doc_index = 0
                    
#                     # Get tender number and title
#                     number = result.get('number', f"TDR-{datetime.datetime.now().year}-001")
#                     title = result.get('title', "Tender Document")
                    
#                     # Store tender number for later check
#                     tender_number = number if number != "Unknown" else None
                    
#                     # Update tender title
#                     if tender_number:
#                         tender_title = f"{tender_number} - {title}"
#                     else:
#                         tender_title = title
                    
#                     print(f"[INFO] Gemini identified main document: {files[main_doc_index].filename}")
#                     print(f"[INFO] Extracted title: {tender_title}")
#                     if tender_number:
#                         print(f"[INFO] Extracted tender number: {tender_number}")
                        
#                 else:
#                     print("[WARN] No JSON found in Gemini response")
                    
#             except Exception as e:
#                 print(f"[WARN] Failed to parse title JSON: {e}")
                
#         except Exception as e:
#             print(f"[WARN] Title extraction failed: {e}")
    
#     # --- CHECK IF TENDER ALREADY EXISTS ---
#     existing_tender = None
#     action = "created"  # Default action
    
#     # First try to find by tender number (most reliable)
#     if tender_number and tender_number != "Unknown":
#         existing_tender = Tender.query.filter_by(tender_number=tender_number).first()
    
#     # If not found by number, try by title
#     if not existing_tender:
#         existing_tender = Tender.query.filter_by(title=tender_title).first()
    
#     # --- UPDATE OR CREATE LOGIC ---
#     if existing_tender:
#         # UPDATE EXISTING RECORD
#         print(f"[INFO] Tender already exists with ID: {existing_tender.id}")
#         new_tender = existing_tender
#         action = "updated"
        
#         # Update source name if needed
#         current_source = existing_tender.source or ""
#         if current_source == 'MahaTender_Original':
#             existing_tender.source = 'MahaTender_Analyze'
#             print("[INFO] Updated source from MahaTender_Original to MahaTender_Analyze")
#         elif current_source == 'CPPP_Original':
#             existing_tender.source = 'CPPP_Analyze'
#             print("[INFO] Updated source from CPPP_Original to CPPP_Analyze")
#         # If source is already *_Analyze or External_Analyze, leave it as is
        
#         # Update basic information
#         existing_tender.title = tender_title
#         existing_tender.user_id = user_id
#         existing_tender.organization_id = organization_id
        
#         # Update tender number if we extracted one
#         if tender_number and tender_number != "Unknown":
#             existing_tender.tender_number = tender_number
            
#     else:
#         # CREATE NEW RECORD
#         print("[INFO] Creating new tender record")
#         new_tender = Tender(
#             title=tender_title,
#             user_id=user_id,
#             organization_id=organization_id,
#             source='External_Analyze',  # Default source for new uploads
#             tender_number=tender_number if tender_number and tender_number != "Unknown" else None
#         )
#         db.session.add(new_tender)
    
#     db.session.flush()  # Get ID before commit
    
#     # Process uploaded files (save to disk and database)
#     processed_files, errors = [], []
#     main_document_content = None
#     all_documents_content = []  # Collect all content
#     processed_documents = []  # Store document objects for hyperlink extraction
    
#     for index, file in enumerate(files):
#         file_extension = os.path.splitext(file.filename)[1].lower()
#         if file_extension not in ['.pdf', '.txt']:
#             errors.append(f"{file.filename}: Only PDF and TXT files are supported")
#             continue

#         try:
#             file_data = save_uploaded_file(file)
#             is_primary = (index == 0)  # For now, keep first file as primary
            
#             document = Document(
#                 filename=file_data['filename'],
#                 original_filename=file_data['original_filename'],
#                 file_path=file_data['file_path'],
#                 file_type=file_data['file_type'],
#                 file_size=file_data['file_size'],
#                 is_primary=is_primary,
#                 tender_id=new_tender.id
#             )
#             db.session.add(document)
#             processed_documents.append(document)  # Store for hyperlink extraction

#             if is_primary:
#                 main_document_content = file_data['content_text']
            
#             # Collect all document content but limit each to prevent overflow
#             if file_data['content_text']:
#                 # Limit each document to 150k characters to prevent processing issues
#                 limited_content = file_data['content_text'][:150000]
#                 all_documents_content.append({
#                     'content': limited_content,
#                     'filename': file.filename,
#                     'is_primary': is_primary
#                 })
            
#             processed_files.append(file.filename)
        
#         except Exception as e:
#             errors.append(f"{file.filename}: {str(e)}")

#     # Extract overview with intelligent content combination AND hyperlink support
#     if all_documents_content:
#         try:
#             if len(all_documents_content) == 1:
#                 # Single document - use as is
#                 content_for_overview = all_documents_content[0]['content']
#                 print(f"[INFO] Single document processing: {len(content_for_overview):,} characters")
#             else:
#                 # Multiple documents - smart combination strategy
#                 print(f"[INFO] Processing {len(all_documents_content)} documents")
                
#                 # Start with primary document
#                 primary_doc = next((doc for doc in all_documents_content if doc['is_primary']), all_documents_content[0])
#                 content_for_overview = primary_doc['content']
                
#                 # Add sections from other documents
#                 for doc in all_documents_content:
#                     if not doc['is_primary']:
#                         # Add a separator and portion of additional documents
#                         additional_content = f"\n\n--- ADDITIONAL DOCUMENT: {doc['filename']} ---\n"
#                         additional_content += doc['content'][:50000]  # Limit additional docs to 80k chars
#                         content_for_overview += additional_content
                
#                 # Final safety check on total content length
#                 if len(content_for_overview) > 400000:
#                     print(f"[WARN] Combined content very large ({len(content_for_overview):,} chars), truncating")
#                     content_for_overview = content_for_overview[:400000]
#                     # Try to end at a sentence boundary
#                     last_period = content_for_overview.rfind('.')
#                     if last_period > 300000:
#                         content_for_overview = content_for_overview[:last_period + 1]
                
#                 print(f"[INFO] Combined content length: {len(content_for_overview):,} characters")
            
#             # Get the primary document path for hyperlink extraction
#             primary_doc_path = None
#             primary_doc = next((doc for doc in processed_documents if doc.is_primary), None)
#             if primary_doc and primary_doc.file_path and os.path.exists(primary_doc.file_path):
#                 primary_doc_path = primary_doc.file_path
#                 print(f"[INFO] Using primary document for hyperlink extraction: {primary_doc_path}")
            
#             # Extract overview data WITH HYPERLINK SUPPORT
#             overview_data = extract_tender_overview(content_for_overview, primary_doc_path)
            
#             # UPDATE ALL TENDER FIELDS WITH OVERVIEW DATA (whether new or existing)
#             new_tender.due_date = overview_data.get('due_date')
#             new_tender.bid_opening_date = overview_data.get('bid_opening_date')
#             new_tender.bid_offer_validity = overview_data.get('bid_offer_validity')
#             new_tender.emd_amount = overview_data.get('emd_amount')
#             new_tender.qualification_criteria = overview_data.get('qualification_criteria')
#             new_tender.question_deadline = overview_data.get('question_deadline')
#             new_tender.reverse_auction = overview_data.get('reverse_auction')
#             new_tender.rejection_criteria = overview_data.get('rejection_criteria')
#             new_tender.msme_preferences = overview_data.get('msme_preferences')
#             new_tender.border_country_clause = overview_data.get('border_country_clause')
#             # Update tender_number from overview if available (but keep the one from Gemini if we have it)
#             if overview_data.get('tender_number'):
#                 new_tender.tender_number = overview_data.get('tender_number')
#             new_tender.organization_details = overview_data.get('organization_details')
#             new_tender.performance_security = overview_data.get('performance_security')
#             new_tender.payment_terms = overview_data.get('payment_terms')
#             new_tender.technical_specifications = overview_data.get('technical_specifications')
#             new_tender.scope_of_work = overview_data.get('scope_of_work')
#             new_tender.performance_standards = overview_data.get('performance_standards')
#             new_tender.evaluation_criteria = overview_data.get('evaluation_criteria')
#             new_tender.documentation_requirements = overview_data.get('documentation_requirements')
#             new_tender.additional_details = overview_data.get('additional_details')
            
#             print(f"[INFO] Overview extraction completed successfully")

#             # --- Delete existing products if updating, then insert new ones ---
#             if existing_tender:
#                 # Delete existing products for this tender
#                 Product.query.filter_by(tender_id=new_tender.id).delete()
#                 print(f"[INFO] Deleted existing products for Tender ID={new_tender.id}")
            
#             # Insert Products (if available) for uploaded tender
#             try:
#                 products_data = overview_data.get('products_table') or []
#                 if isinstance(products_data, list) and len(products_data) > 0:
#                     print(f"[DEBUG] Inserting {len(products_data)} products for Tender ID={new_tender.id}")
#                     for p in products_data:
#                         product = Product(
#                             tender_id=new_tender.id,
#                             product_name=p.get('product_name', 'Not specified'),
#                             quantity=p.get('quantity', 'Not specified'),
#                             delivery_days=p.get('delivery_days', 'Not specified'),
#                             consignee_name=p.get('consignee_name', 'Not specified'),
#                             delivery_address=p.get('delivery_address', 'Not specified'),
#                             specification_link=p.get('specification_link') or None
#                         )
#                         db.session.add(product)
#                     print(f"[DEBUG] Products queued for insert for Tender ID={new_tender.id}")
#                 else:
#                     print("[INFO] No product data found in overview_data for uploaded tender.")
#             except Exception as e:
#                 print(f"[ERROR] Failed to insert products for uploaded tender: {e}")
#                 import traceback
#                 print(traceback.format_exc())
#                 # Continue — we still want to commit other data

#         except Exception as e:
#             print(f"[ERROR] Overview extraction failed: {e}")
#             import traceback
#             traceback.print_exc()
#             # Continue without overview data rather than failing the entire upload
#             print("[WARN] Continuing without overview data")
    
#     if processed_files:
#         db.session.commit()
#         return {
#             'success': True,
#             'tender_id': new_tender.id,
#             'action': action,
#             'processed_files': processed_files,
#             'errors': errors
#         }
#     else:
#         db.session.rollback()
#         return {
#             'success': False,
#             'errors': errors or ['No files were processed successfully']
#         }




















# Gem Scheuler : 

import os
import time
import datetime
import logging
import subprocess
import sys
from threading import Thread
import schedule
from sqlalchemy import text
from concurrent.futures import ThreadPoolExecutor
from threading import Semaphore

MAX_WORKERS = 4
# Thread pool with bounded concurrency (backpressure enabled)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
semaphore = Semaphore(MAX_WORKERS)


# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("gem_scheduler.log"),
                              logging.StreamHandler()])
logger = logging.getLogger(__name__)

# def run_job_in_thread(job):
#     """
#     Submit job to thread pool.
#     Backpressure is automatically handled by ThreadPoolExecutor.
#     """
#     logger.info(f"Submitting job {job['id']} to thread pool")
#     executor.submit(run_gem_analyzer_with_notifications, job)

def run_job_in_thread(job):
    logger.info(f"Submitting job {job['id']} to thread pool")
    
    semaphore.acquire()

    def wrapped():
        try:
            run_gem_analyzer_with_notifications(job)
        finally:
            semaphore.release()

    executor.submit(wrapped)



def get_scheduled_jobs():
    """Get all active scheduled jobs from the database with organization info"""
    try:
        from database_config import engine
        
        with engine.connect() as conn:
            # Join with user table to get the organization_id
            result = conn.execute(text('''
            SELECT c.id, c.search_keyword, c.max_tenders, c.execution_time, u.organization_id
            FROM gem_search_configurations c
            JOIN "user" u ON c.created_by = u.id
            WHERE c.is_active = true
            '''))
            
            jobs = []
            for row in result:
                jobs.append({
                    'id': row[0],
                    'search_keyword': row[1],
                    'max_tenders': row[2],
                    'execution_time': row[3],
                    'organization_id': row[4]  # Organization ID from the user table
                })
            
            logger.info(f"Found {len(jobs)} scheduled jobs")
            return jobs
    except Exception as e:
        logger.error(f"Error retrieving scheduled jobs: {e}")
        return []

def update_last_run(job_id):
    """Update the last_run timestamp for a job"""
    try:
        from database_config import engine
        
        with engine.connect() as conn:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute(text('''
            UPDATE gem_search_configurations
            SET last_run = :last_run
            WHERE id = :job_id
            '''), {
                'last_run': now,
                'job_id': job_id
            })
            conn.commit()
            
            logger.info(f"Updated last_run timestamp for job {job_id}")
    except Exception as e:
        logger.error(f"Error updating last_run timestamp: {e}")

def parse_multiple_keywords(keyword_string):
    if not keyword_string:
        return [None]
    
    import re
    domain_pattern = r'(\w+)\s*\(([^)]+)\)'
    domain_matches = re.findall(domain_pattern, keyword_string)
    
    if domain_matches:
        result = []
        for search_term, keywords_str in domain_matches:
            result.append({
                'term': search_term.strip(),
                'keywords': [k.strip() for k in keywords_str.split(',')]
            })
        return result
    else:
        # No domain format = no keywords at all
        keywords = re.split(r'[,;|]|\sand\s', keyword_string)
        return [kw.strip() for kw in keywords if kw.strip()]

def run_single_search(keyword, max_tenders, organization_id, search_number, total_searches):
    """Run a single search with the gem_nlp_api.py"""
    try:
        # Handle domain-specific format
        if isinstance(keyword, dict):
            search_term = keyword['term']
            domain_keywords = "|".join(keyword['keywords'])
            keyword_display = search_term
            cmd_args = [
                "python", 
                "gem_nlp_api.py", 
                search_term,
                str(max_tenders),
                str(organization_id),
                domain_keywords
            ]
        else:
            # Handle simple keyword format
            keyword_display = keyword if keyword else "none"
            cmd_args = [
                "python", 
                "gem_nlp_api.py", 
                str(keyword_display),
                str(max_tenders),
                str(organization_id),
                "NONE"
            ]
        
        logger.info(f"=== run_single_search ENTRY ===")
        logger.info(f"Search {search_number}/{total_searches}: Running search for keyword '{keyword_display}'")
        
        # Debug logging
        logger.info(f"DEBUG: Received parameters:")
        logger.info(f"  keyword='{keyword}' (type: {type(keyword)})")
        logger.info(f"  max_tenders={max_tenders} (type: {type(max_tenders)})")
        logger.info(f"  organization_id={organization_id} (type: {type(organization_id)})")
        logger.info(f"  search_number={search_number} (type: {type(search_number)})")
        logger.info(f"  total_searches={total_searches} (type: {type(total_searches)})")
        
        logger.info(f"DEBUG: Constructed command args: {cmd_args}")
        logger.info(f"DEBUG: Command as string: {' '.join(cmd_args)}")
        
        logger.info(f"About to execute subprocess...")
        
        # Run GEM scraper
        analyzer_process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        analyzer_stdout, analyzer_stderr = analyzer_process.communicate()
        
        logger.info(f"Subprocess completed with return code: {analyzer_process.returncode}")
        
        # Log analyzer output
        if analyzer_stdout:
            stdout_str = analyzer_stdout.decode()
            logger.info(f"Search {search_number} stdout: {stdout_str}")
        if analyzer_stderr:
            stderr_str = analyzer_stderr.decode()
            logger.error(f"Search {search_number} stderr: {stderr_str}")
        
        # Check if analyzer completed successfully
        if analyzer_process.returncode == 0:
            logger.info(f"Search {search_number} completed successfully for keyword '{keyword_display}'")
            
            # ADDED: Now also run CPPP and MahaTender scrapers
            logger.info(f"=== Additional scrapers for keyword '{keyword_display}' ===")
            
            # Run CPPP scraper
            logger.info(f"Running CPPP scraper...")
            cppp_cmd = [
                "python", 
                "cppp_tenders.py", 
                str(keyword_display),
                str(max_tenders),
                str(organization_id)
            ]
            cppp_process = subprocess.Popen(cppp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cppp_stdout, cppp_stderr = cppp_process.communicate()
            
            if cppp_stdout:
                logger.info(f"CPPP stdout: {cppp_stdout.decode()}")
            if cppp_stderr:
                logger.error(f"CPPP stderr: {cppp_stderr.decode()}")
            
            logger.info(f"CPPP scraper completed with return code: {cppp_process.returncode}")
            
            # Small delay
            time.sleep(5)
            
            # Run MahaTender scraper
            logger.info(f"Running MahaTender scraper...")
            maha_cmd = [
                "python", 
                "mahatenders.py", 
                str(keyword_display),
                str(max_tenders),
                str(organization_id)
            ]
            maha_process = subprocess.Popen(maha_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            maha_stdout, maha_stderr = maha_process.communicate()
            
            if maha_stdout:
                logger.info(f"MahaTender stdout: {maha_stdout.decode()}")
            if maha_stderr:
                logger.error(f"MahaTender stderr: {maha_stderr.decode()}")
            
            logger.info(f"MahaTender scraper completed with return code: {maha_process.returncode}")
            
            # Overall success if GEM succeeded
            return True
        else:
            logger.error(f"Search {search_number} failed for keyword '{keyword_display}' (return code: {analyzer_process.returncode})")
            
            # Still try to run CPPP and MahaTender even if GEM failed
            logger.info(f"GEM scraper failed, but trying CPPP and MahaTender scrapers for keyword '{keyword_display}'")
            
            # Run CPPP scraper
            logger.info(f"Running CPPP scraper...")
            cppp_cmd = [
                "python", 
                "cppp_tenders.py", 
                str(keyword_display),
                str(max_tenders),
                str(organization_id)
            ]
            cppp_process = subprocess.Popen(cppp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cppp_stdout, cppp_stderr = cppp_process.communicate()
            
            if cppp_stdout:
                logger.info(f"CPPP stdout: {cppp_stdout.decode()}")
            if cppp_stderr:
                logger.error(f"CPPP stderr: {cppp_stderr.decode()}")
            
            logger.info(f"CPPP scraper completed with return code: {cppp_process.returncode}")
            
            # Small delay
            time.sleep(5)
            
            # Run MahaTender scraper
            logger.info(f"Running MahaTender scraper...")
            maha_cmd = [
                "python", 
                "mahatender.py", 
                str(keyword_display),
                str(max_tenders),
                str(organization_id)
            ]
            maha_process = subprocess.Popen(maha_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            maha_stdout, maha_stderr = maha_process.communicate()
            
            if maha_stdout:
                logger.info(f"MahaTender stdout: {maha_stdout.decode()}")
            if maha_stderr:
                logger.error(f"MahaTender stderr: {maha_stderr.decode()}")
            
            logger.info(f"MahaTender scraper completed with return code: {maha_process.returncode}")
            
            return False
            
    except Exception as e:
        logger.error(f"Error running search {search_number} for keyword '{keyword}': {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False

def run_multi_keyword_search_with_notifications(job):
    """Run multiple keyword searches followed by a single email notification"""
    try:
        job_id = job['id']
        search_keyword_string = job['search_keyword']
        max_tenders = job['max_tenders']
        organization_id = job['organization_id']
        
        logger.info(f"=== DEBUG JOB START ===")
        logger.info(f"job_id: {job_id}")
        logger.info(f"search_keyword_string: '{search_keyword_string}' (type: {type(search_keyword_string)})")
        logger.info(f"max_tenders: {max_tenders} (type: {type(max_tenders)})")
        logger.info(f"organization_id: {organization_id} (type: {type(organization_id)})")
        
        logger.info(f"Starting multi-keyword job {job_id} for organization {organization_id}")
        
        # Parse keywords
        keywords = parse_multiple_keywords(search_keyword_string)
        total_searches = len(keywords)
        
        logger.info(f"DEBUG: Parsed keywords: {keywords}")
        logger.info(f"DEBUG: Keywords type: {type(keywords)}, individual types: {[type(k) for k in keywords]}")
        logger.info(f"Job {job_id}: Will run {total_searches} searches with keywords: {keywords}")
        
        # Track search results
        successful_searches = 0
        failed_searches = 0
        
        # Run each search sequentially
        for i, keyword in enumerate(keywords, 1):
            logger.info(f"=== SEARCH {i}/{total_searches} START ===")
            logger.info(f"About to call run_single_search with:")
            logger.info(f"  keyword: '{keyword}' (type: {type(keyword)})")
            logger.info(f"  max_tenders: {max_tenders} (type: {type(max_tenders)})")
            logger.info(f"  organization_id: {organization_id} (type: {type(organization_id)})")
            logger.info(f"  search_number: {i}")
            logger.info(f"  total_searches: {total_searches}")
            
            success = run_single_search(keyword, max_tenders, organization_id, i, total_searches)
            
            if success:
                successful_searches += 1
                logger.info(f"=== SEARCH {i}/{total_searches} SUCCESS ===")
            else:
                failed_searches += 1
                logger.info(f"=== SEARCH {i}/{total_searches} FAILED ===")
            
            # Small delay between searches to avoid overwhelming the system
            if i < total_searches:
                logger.info(f"Waiting 10 seconds before next search...")
                time.sleep(10)
        
        logger.info(f"Job {job_id}: Completed {successful_searches} successful searches, {failed_searches} failed searches")
        
        # Run email notifications if at least one search succeeded
        if successful_searches > 0:
            # Wait a bit for database writes to complete
            logger.info(f"Job {job_id}: Waiting 5 seconds for database writes to complete...")
            time.sleep(5)
            
            logger.info(f"Job {job_id}: Running consolidated email notifications...")
            email_cmd = f"python gem_email_notifier.py {organization_id} 4"
            
            logger.info(f"Job {job_id}: Email command: {email_cmd}")
            
            email_process = subprocess.Popen(email_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            email_stdout, email_stderr = email_process.communicate()
            
            # Log email output
            if email_stdout:
                logger.info(f"Job {job_id} email stdout: {email_stdout.decode()}")
            if email_stderr:
                logger.error(f"Job {job_id} email stderr: {email_stderr.decode()}")
            
            # Check if email notifications completed successfully
            if email_process.returncode == 0:
                logger.info(f"Job {job_id}: Email notifications completed successfully")
            else:
                logger.error(f"Job {job_id}: Email notifications failed (return code: {email_process.returncode})")
        else:
            logger.warning(f"Job {job_id}: Skipping email notifications due to all searches failing")
        
        # Update last run timestamp
        update_last_run(job_id)
        
        logger.info(f"Job {job_id}: Multi-keyword processing completed")
        logger.info(f"=== DEBUG JOB END ===")
        
    except Exception as e:
        logger.error(f"Error running multi-keyword job {job['id']}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

def run_gem_analyzer_with_notifications(job):
    """Enhanced function that handles both single and multiple keywords"""
    search_keyword_string = job.get('search_keyword', '')
    
    # Check if this looks like multiple keywords
    if search_keyword_string and any(sep in search_keyword_string for sep in [',', ';', '|', ' and ']):
        logger.info(f"Detected multiple keywords in job {job['id']}: '{search_keyword_string}'")
        run_multi_keyword_search_with_notifications(job)
    else:
        # Single keyword - use the original single keyword logic directly
        logger.info(f"Single keyword job {job['id']}: '{search_keyword_string}'")
        # Call the actual implementation, not the wrapper
        try:
            job_id = job['id']
            search_keyword = job['search_keyword'] if job['search_keyword'] else "none"
            max_tenders = job['max_tenders']
            organization_id = job['organization_id']
            
            logger.info(f"Running single keyword job {job_id} for organization {organization_id} with keyword '{search_keyword}' and max_tenders={max_tenders}")
            
            # Step 1: Run the GEM tender analyzer
            analyzer_cmd = f"python gem_nlp_api.py {search_keyword} {max_tenders} {organization_id}"
            
            logger.info(f"Step 1: Running gem_nlp_api.py...")
            analyzer_process = subprocess.Popen(analyzer_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            analyzer_stdout, analyzer_stderr = analyzer_process.communicate()
            
            # Log analyzer output
            if analyzer_stdout:
                logger.info(f"Analyzer stdout: {analyzer_stdout.decode()}")
            if analyzer_stderr:
                logger.error(f"Analyzer stderr: {analyzer_stderr.decode()}")
            
            # Check if analyzer completed successfully
            if analyzer_process.returncode == 0:
                logger.info(f"Step 1 completed successfully for job {job_id}")
            else:
                logger.error(f"Analyzer failed for job {job_id} (return code: {analyzer_process.returncode})")
            
            # ADDED: Step 1.5: Run CPPP scraper
            logger.info(f"Step 1.5: Running CPPP scraper...")
            cppp_cmd = f"python cppp_tenders.py {search_keyword} {max_tenders} {organization_id}"
            cppp_process = subprocess.Popen(cppp_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cppp_stdout, cppp_stderr = cppp_process.communicate()
            
            # Log CPPP output
            if cppp_stdout:
                logger.info(f"CPPP stdout: {cppp_stdout.decode()}")
            if cppp_stderr:
                logger.error(f"CPPP stderr: {cppp_stderr.decode()}")
            
            logger.info(f"CPPP scraper completed with return code: {cppp_process.returncode}")
            
            # Small delay
            time.sleep(5)
            
            # ADDED: Step 1.6: Run MahaTender scraper
            logger.info(f"Step 1.6: Running MahaTender scraper...")
            maha_cmd = f"python mahatender.py {search_keyword} {max_tenders} {organization_id}"
            maha_process = subprocess.Popen(maha_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            maha_stdout, maha_stderr = maha_process.communicate()
            
            # Log MahaTender output
            if maha_stdout:
                logger.info(f"MahaTender stdout: {maha_stdout.decode()}")
            if maha_stderr:
                logger.error(f"MahaTender stderr: {maha_stderr.decode()}")
            
            logger.info(f"MahaTender scraper completed with return code: {maha_process.returncode}")
            
            # Only send email notifications if GEM analyzer succeeded (original logic)
            if analyzer_process.returncode == 0:
                # Step 2: Run email notifications
                time.sleep(5)
                
                logger.info(f"Step 2: Running email notifications...")
                email_cmd = f"python gem_email_notifier.py {organization_id} 4"
                
                email_process = subprocess.Popen(email_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                email_stdout, email_stderr = email_process.communicate()
                
                # Log email output
                if email_stdout:
                    logger.info(f"Email stdout: {email_stdout.decode()}")
                if email_stderr:
                    logger.error(f"Email stderr: {email_stderr.decode()}")
                
                # Check if email notifications completed successfully
                if email_process.returncode == 0:
                    logger.info(f"Step 2 completed successfully for job {job_id}")
                else:
                    logger.error(f"Email notifications failed for job {job_id} (return code: {email_process.returncode})")
            else:
                logger.error(f"GEM analyzer failed for job {job_id} (return code: {analyzer_process.returncode}). Skipping email notifications.")
            
            # Update last run timestamp
            update_last_run(job_id)
            
            logger.info(f"Job {job_id} processing completed")
        
        except Exception as e:
            logger.error(f"Error running job {job['id']}: {e}")

def run_gem_analyzer(job):
    """Original function - kept for backwards compatibility, now calls the enhanced version"""
    run_gem_analyzer_with_notifications(job)

def schedule_jobs():
    """Schedule all jobs from the database"""
    # Clear existing jobs
    schedule.clear()
    
    # Get jobs from database
    jobs = get_scheduled_jobs()
    
    # Schedule each job
    for job in jobs:
        execution_time = job['execution_time']
        # Schedule job to run at specified time with enhanced multi-keyword support
        # schedule.every().day.at(execution_time).do(run_gem_analyzer_with_notifications, job)

        schedule.every().day.at(execution_time).do(run_job_in_thread, job)
        
        # Log scheduling info
        keyword_info = job['search_keyword'] if job['search_keyword'] else 'All tenders'
        if job['search_keyword'] and any(sep in job['search_keyword'] for sep in [',', ';', '|', ' and ']):
            keyword_info += " (multi-keyword)"
        
        logger.info(f"Scheduled job {job['id']} to run at {execution_time} - Keywords: {keyword_info}")
    
    logger.info(f"Scheduled {len(jobs)} jobs with multi-keyword support")

def refresh_schedule():
    """Function to periodically refresh the schedule from the database"""
    logger.info("Refreshing job schedule")
    schedule_jobs()

def run_scheduler():
    """Main function to run the scheduler"""
    logger.info("Starting GEM Tender Scheduler with Multi-Keyword Support and Email Notifications")
    
    # Initial schedule setup
    schedule_jobs()
    
    # Schedule a job to refresh the schedule every hour
    schedule.every().hour.do(refresh_schedule)
    
    # Run pending jobs continuously
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

def test_job(organization_id, search_keyword=None, max_tenders=30):
    """Test function to run a job manually - now supports multiple keywords"""
    test_job_data = {
        'id': 'TEST',
        'search_keyword': search_keyword,
        'max_tenders': max_tenders,
        'organization_id': organization_id
    }
    
    logger.info(f"Running test job for organization {organization_id}")
    if search_keyword and any(sep in search_keyword for sep in [',', ';', '|', ' and ']):
        logger.info(f"Test job will use multi-keyword search: {search_keyword}")
    
    run_gem_analyzer_with_notifications(test_job_data)

if __name__ == "__main__":
    try:
        # Check if this is a test run
        if len(sys.argv) > 1 and sys.argv[1] == "test":
            # Test mode: python gem_scheduler.py test <org_id> [keyword] [max_tenders]
            if len(sys.argv) < 3:
                print("Usage for test mode: python gem_scheduler.py test <organization_id> [keyword] [max_tenders]")
                print("Examples:")
                print("  python gem_scheduler.py test 123 pump 30")
                print("  python gem_scheduler.py test 123 'pump,valve,motor' 25")
                print("  python gem_scheduler.py test 123 'pump;valve;flow control' 30")
                sys.exit(1)
            
            organization_id = int(sys.argv[2])
            search_keyword = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].lower() != "none" else None
            max_tenders = int(sys.argv[4]) if len(sys.argv) > 4 else 30
            
            test_job(organization_id, search_keyword, max_tenders)
        else:
            # Normal scheduler mode
            run_scheduler()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        




# Gem NLP API : 

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


# saved in gem_tenders table, 
# def save_to_db(analysis_result, organization_id):
#     """Save analysis result to database with organization association"""
#     from sqlalchemy import text
#     from database_config import engine
    
#     try:
#         # Prepare values
#         keywords_str = "|".join(analysis_result.get("keywords", [])) if "keywords" in analysis_result else ""
        
#         with engine.connect() as conn:
#             # Check if tender already exists
#             result = conn.execute(
#                 text("SELECT id FROM gem_tenders WHERE tender_id = :tender_id AND organization_id = :org_id"),
#                 {
#                     "tender_id": analysis_result["tender_id"],
#                     "org_id": organization_id
#                 }
#             )
#             existing_tender = result.fetchone()
            
#             if existing_tender:
#                 # Update existing tender
#                 conn.execute(text("""
#                     UPDATE gem_tenders SET
#                         description = :description,
#                         due_date = :due_date,
#                         matches_services = :matches_services,
#                         match_reason = :match_reason,
#                         document_url = :document_url,
#                         pdf_path = :pdf_path,
#                         match_score = :match_score,
#                         keywords = :keywords,
#                         match_score_keyword = :match_score_keyword,
#                         match_score_combined = :match_score_combined,
#                         api_calls_made = :api_calls_made,
#                         tokens_used = :tokens_used,
#                         relevance_percentage = :relevance_percentage,
#                         is_central_match = :is_central_match,
#                         strategic_fit = :strategic_fit,
#                         primary_scope = :primary_scope
#                     WHERE tender_id = :tender_id AND organization_id = :org_id
#                 """), {
#                     "description": analysis_result["description"],
#                     "due_date": analysis_result["due_date"],
#                     "matches_services": bool(analysis_result["matches_services"]),
#                     "match_reason": analysis_result["match_reason"],
#                     "document_url": analysis_result.get("document_url", ""),
#                     "pdf_path": analysis_result.get("pdf_path", ""),
#                     "match_score": analysis_result.get("match_score", 0.0),
#                     "keywords": keywords_str,
#                     "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
#                     "match_score_combined": analysis_result.get("match_score_combined", 0.0),
#                     "api_calls_made": analysis_result.get("api_calls_made", 0),
#                     "tokens_used": analysis_result.get("tokens_used", 0),
#                     "relevance_percentage": analysis_result.get("relevance_percentage", 0),
#                     "is_central_match": bool(analysis_result.get("is_central_match", False)),
#                     "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
#                     "primary_scope": analysis_result.get("primary_scope", ""),
#                     "tender_id": analysis_result["tender_id"],
#                     "org_id": organization_id
#                 })
#             else:
#                 # Create new tender
#                 conn.execute(text("""
#                     INSERT INTO gem_tenders (
#                         tender_id, description, due_date, creation_date, matches_services, match_reason,
#                         document_url, pdf_path, organization_id, match_score, keywords,
#                         match_score_keyword, match_score_combined, api_calls_made, tokens_used,
#                         relevance_percentage, is_central_match, strategic_fit, primary_scope
#                     ) VALUES (
#                         :tender_id, :description, :due_date, :creation_date, :matches_services, :match_reason,
#                         :document_url, :pdf_path, :org_id, :match_score, :keywords,
#                         :match_score_keyword, :match_score_combined, :api_calls_made, :tokens_used,
#                         :relevance_percentage, :is_central_match, :strategic_fit, :primary_scope
#                     )
#                 """), {
#                     "tender_id": analysis_result["tender_id"],
#                     "description": analysis_result["description"],
#                     "due_date": analysis_result["due_date"],
#                     "creation_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
#                     "matches_services": bool(analysis_result["matches_services"]),
#                     "match_reason": analysis_result["match_reason"],
#                     "document_url": analysis_result.get("document_url", ""),
#                     "pdf_path": analysis_result.get("pdf_path", ""),
#                     "org_id": organization_id,
#                     "match_score": analysis_result.get("match_score", 0.0),
#                     "keywords": keywords_str,
#                     "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
#                     "match_score_combined": analysis_result.get("match_score_combined", 0.0),
#                     "api_calls_made": analysis_result.get("api_calls_made", 0),
#                     "tokens_used": analysis_result.get("tokens_used", 0),
#                     "relevance_percentage": analysis_result.get("relevance_percentage", 0),
#                     "is_central_match": bool(analysis_result.get("is_central_match", False)),
#                     "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
#                     "primary_scope": analysis_result.get("primary_scope", "")
#                 })
            
#             conn.commit()
#             print(f"Saved or updated tender {analysis_result['tender_id']} for organization {organization_id}")

#     except Exception as e:
#         print(f"Database error: {e}")
#         raise


def save_to_db(analysis_result, organization_id):
    """Save analysis result to database with organization association"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        # Prepare values
        keywords_str = "|".join(analysis_result.get("keywords", [])) if "keywords" in analysis_result else ""
        
        with engine.connect() as conn:
            # Check if tender already exists in master table
            result = conn.execute(
                text("SELECT id FROM gem_tender_master WHERE tender_id = :tender_id"),
                {
                    "tender_id": analysis_result["tender_id"]
                }
            )
            existing_master = result.fetchone()
            
            if existing_master:
                master_id = existing_master[0]
                # Update existing master record
                conn.execute(text("""
                    UPDATE gem_tender_master SET
                        description = :description,
                        due_date = :due_date,
                        document_url = :document_url,
                        pdf_path = :pdf_path
                    WHERE id = :master_id
                """), {
                    "description": analysis_result["description"],
                    "due_date": analysis_result["due_date"],
                    "document_url": analysis_result.get("document_url", ""),
                    "pdf_path": analysis_result.get("pdf_path", ""),
                    "master_id": master_id
                })
            else:
                # Insert new master record
                result = conn.execute(text("""
                    INSERT INTO gem_tender_master (
                        tender_id, description, due_date, creation_date, document_url, pdf_path
                    ) VALUES (
                        :tender_id, :description, :due_date, :creation_date, :document_url, :pdf_path
                    ) RETURNING id
                """), {
                    "tender_id": analysis_result["tender_id"],
                    "description": analysis_result["description"],
                    "due_date": analysis_result["due_date"],
                    "creation_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "document_url": analysis_result.get("document_url", ""),
                    "pdf_path": analysis_result.get("pdf_path", "")
                })
                master_id = result.fetchone()[0]
            
            # Check if match record exists for this organization and tender
            result = conn.execute(
                text("SELECT id FROM gem_tender_matches WHERE organization_id = :org_id AND master_tender_id = :master_id"),
                {
                    "org_id": organization_id,
                    "master_id": master_id
                }
            )
            existing_match = result.fetchone()
            
            if existing_match:
                # Update existing match record
                conn.execute(text("""
                    UPDATE gem_tender_matches SET
                        matches_services = :matches_services,
                        match_reason = :match_reason,
                        match_score = :match_score,
                        match_score_keyword = :match_score_keyword,
                        match_score_combined = :match_score_combined,
                        relevance_percentage = :relevance_percentage,
                        strategic_fit = :strategic_fit,
                        is_central_match = :is_central_match,
                        primary_scope = :primary_scope,
                        api_calls_made = :api_calls_made,
                        tokens_used = :tokens_used,
                        created_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :org_id AND master_tender_id = :master_id
                """), {
                    "matches_services": bool(analysis_result["matches_services"]),
                    "match_reason": analysis_result["match_reason"],
                    "match_score": analysis_result.get("match_score", 0.0),
                    "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
                    "match_score_combined": analysis_result.get("match_score_combined", 0.0),
                    "relevance_percentage": analysis_result.get("relevance_percentage", 0),
                    "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
                    "is_central_match": bool(analysis_result.get("is_central_match", False)),
                    "primary_scope": analysis_result.get("primary_scope", ""),
                    "api_calls_made": analysis_result.get("api_calls_made", 0),
                    "tokens_used": analysis_result.get("tokens_used", 0),
                    "org_id": organization_id,
                    "master_id": master_id
                })
            else:
                # Insert new match record
                conn.execute(text("""
                    INSERT INTO gem_tender_matches (
                        organization_id, master_tender_id, matches_services, match_reason,
                        match_score, match_score_keyword, match_score_combined,
                        relevance_percentage, strategic_fit, is_central_match,
                        primary_scope, api_calls_made, tokens_used, created_at
                    ) VALUES (
                        :org_id, :master_id, :matches_services, :match_reason,
                        :match_score, :match_score_keyword, :match_score_combined,
                        :relevance_percentage, :strategic_fit, :is_central_match,
                        :primary_scope, :api_calls_made, :tokens_used, CURRENT_TIMESTAMP
                    )
                """), {
                    "org_id": organization_id,
                    "master_id": master_id,
                    "matches_services": bool(analysis_result["matches_services"]),
                    "match_reason": analysis_result["match_reason"],
                    "match_score": analysis_result.get("match_score", 0.0),
                    "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
                    "match_score_combined": analysis_result.get("match_score_combined", 0.0),
                    "relevance_percentage": analysis_result.get("relevance_percentage", 0),
                    "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
                    "is_central_match": bool(analysis_result.get("is_central_match", False)),
                    "primary_scope": analysis_result.get("primary_scope", ""),
                    "api_calls_made": analysis_result.get("api_calls_made", 0),
                    "tokens_used": analysis_result.get("tokens_used", 0)
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

# def get_keywords_for_organization(organization_id, override_keywords=None, search_keyword=None):
#     """Get keywords for organization, optionally filtered by search keyword"""
#     if override_keywords and override_keywords != ["none"]:
#         logger.info(f"Using override keywords: {override_keywords}")
#         return parse_keyword_string(",".join(override_keywords))

#     from sqlalchemy import text
#     from database_config import engine
    
#     try:
#         print(f"DEBUG: Looking for keywords in gem_search_configurations for organization_id: {organization_id}")
        
#         with engine.connect() as conn:
#             # Use JOIN with user table to get organization_id
#             result = conn.execute(text("""
#                 SELECT c.search_keyword FROM gem_search_configurations c
#                 JOIN "user" u ON c.created_by = u.id
#                 WHERE u.organization_id = :org_id AND c.search_keyword IS NOT NULL AND c.search_keyword != ''
#                 ORDER BY c.id DESC LIMIT 1
#             """), {"org_id": organization_id})
            
#             row = result.fetchone()
            
#             if row and row[0]:
#                 raw_keywords = row[0].strip()
#                 print(f"DEBUG: Raw keywords found: '{raw_keywords}'")
#                 parsed_keywords = parse_keyword_string(raw_keywords)
                
#                 # Filter by search keyword if provided
#                 if search_keyword:
#                     search_keyword_lower = search_keyword.lower().strip()
#                     print(f"DEBUG: Filtering keywords for search term: '{search_keyword_lower}'")
                    
#                     filtered_keywords = []
#                     for group in parsed_keywords:
#                         group_search_keyword = group["search_keyword"].lower().strip()
#                         print(f"DEBUG: Comparing '{search_keyword_lower}' with group '{group_search_keyword}'")
                        
#                         if group_search_keyword == search_keyword_lower:
#                             filtered_keywords.append(group)
#                             print(f"DEBUG: MATCH FOUND - Using keyword group: {group}")
                    
#                     if filtered_keywords:
#                         logger.info(f"Retrieved {len(filtered_keywords)} keyword groups for organization {organization_id} filtered by '{search_keyword}'")
#                         return filtered_keywords
#                     else:
#                         logger.warning(f"No keyword groups found for search term '{search_keyword}' in organization {organization_id}")
#                         return []
#                 else:
#                     logger.info(f"Retrieved {len(parsed_keywords)} keyword groups for organization {organization_id}")
#                     return parsed_keywords
#             else:
#                 logger.warning(f"No keywords found in gem_search_configurations for organization {organization_id}")
#                 return []
                
#     except Exception as e:
#         logger.error(f"Error getting keywords from gem_search_configurations: {e}")
#         print(f"DEBUG: Exception details: {str(e)}")
#         return []


def get_keywords_for_organization(organization_id, override_keywords=None, search_keyword=None):
    """Get keywords for organization from gem_org_search_capabilities, optionally filtered by search keyword"""
    if override_keywords and override_keywords != ["none"]:
        logger.info(f"Using override keywords: {override_keywords}")
        return parse_keyword_string(",".join(override_keywords))

    from sqlalchemy import text
    from database_config import engine
    
    try:
        print(f"DEBUG: Looking for keywords in gem_org_search_capabilities for organization_id: {organization_id}")
        
        with engine.connect() as conn:
            # Get all capabilities for this organization with their associated search keywords
            result = conn.execute(text("""
                SELECT 
                    COALESCE(sc.search_keyword, '') as search_keyword,
                    c.keyword as match_keyword
                FROM gem_org_search_capabilities c
                LEFT JOIN gem_search_configurations sc ON c.search_config_id = sc.id
                WHERE c.organization_id = :org_id
                ORDER BY c.id
            """), {"org_id": organization_id})
            
            # Group by search_keyword to create the same structure as parse_keyword_string returns
            keyword_groups = {}
            for row in result:
                config_search_keyword = row[0] or ''  # Handle NULL
                match_keyword = row[1]
                
                if config_search_keyword not in keyword_groups:
                    keyword_groups[config_search_keyword] = {
                        "search_keyword": config_search_keyword,
                        "match_keywords": []
                    }
                
                if match_keyword and match_keyword.strip():  # Add non-empty match keywords
                    # FIX: Split the comma-separated string into individual keywords
                    individual_keywords = [k.strip() for k in match_keyword.split(',') if k.strip()]
                    keyword_groups[config_search_keyword]["match_keywords"].extend(individual_keywords)
            
            # Convert to list format expected by the rest of the code
            all_keyword_groups = list(keyword_groups.values())
            
            print(f"DEBUG: Found {len(all_keyword_groups)} keyword groups for org {organization_id}")
            for group in all_keyword_groups:
                print(f"DEBUG: Group '{group['search_keyword']}' has {len(group['match_keywords'])} individual keywords")
            
            # Filter by search keyword if provided
            if search_keyword and all_keyword_groups:
                search_keyword_lower = search_keyword.lower().strip()
                print(f"DEBUG: Filtering keywords for search term: '{search_keyword_lower}'")
                
                filtered_keywords = []
                for group in all_keyword_groups:
                    group_search_keyword = group["search_keyword"].lower().strip()
                    print(f"DEBUG: Comparing '{search_keyword_lower}' with group '{group_search_keyword}'")
                    
                    if group_search_keyword == group_search_keyword:
                        filtered_keywords.append(group)
                        print(f"DEBUG: MATCH FOUND - Using keyword group with {len(group['match_keywords'])} keywords")
                
                if filtered_keywords:
                    logger.info(f"Retrieved {len(filtered_keywords)} keyword groups for organization {organization_id} filtered by '{search_keyword}'")
                    return filtered_keywords
                else:
                    logger.warning(f"No keyword groups found for search term '{search_keyword}' in organization {organization_id}")
                    return []
            
            logger.info(f"Retrieved {len(all_keyword_groups)} keyword groups for organization {organization_id}")
            return all_keyword_groups
            
    except Exception as e:
        logger.error(f"Error getting keywords from gem_org_search_capabilities: {e}")
        print(f"DEBUG: Exception details: {str(e)}")
        return []

def get_organizations_for_search_keyword(search_keyword):
    """Get all organizations that have this search keyword configured"""
    from sqlalchemy import text
    from database_config import engine
    
    organizations = []
    
    try:
        with engine.connect() as conn:
            # Get distinct organizations with this search keyword
            result = conn.execute(text("""
                SELECT DISTINCT 
                    o.id,
                    spd.definition as service_definition
                FROM organization o
                JOIN gem_org_search_capabilities gosc ON o.id = gosc.organization_id
                JOIN gem_search_configurations gsc ON gosc.search_config_id = gsc.id
                LEFT JOIN service_product_definition spd ON o.id = spd.organization_id
                WHERE LOWER(gsc.search_keyword) = LOWER(:keyword)
                ORDER BY spd.updated_at DESC
            """), {"keyword": search_keyword})
            
            for row in result:
                organizations.append({
                    'id': row[0],
                    'service_definition': row[1] if row[1] else ""
                })
            
            logger.info(f"Found {len(organizations)} organizations with search keyword '{search_keyword}'")
            return organizations
            
    except Exception as e:
        logger.error(f"Error getting organizations for search keyword: {e}")
        return []

def get_all_existing_tender_ids():
    """Get all tender IDs from master table to avoid duplicates"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT tender_id FROM gem_tender_master WHERE tender_id IS NOT NULL")
            )
            existing_ids = {row[0] for row in result if row[0]}
            logger.info(f"Found {len(existing_ids)} existing tender IDs in master table")
            return existing_ids
    except Exception as e:
        logger.error(f"Error retrieving existing tender IDs: {e}")
        return set()

def download_tenders_for_keyword(search_keyword, max_tenders):
    """Download tenders once for a keyword and return the results"""
    # Initialize scraper
    download_dir = "gem_bids"
    scraper = GemBidScraper(download_dir)
    
    try:
        with BrowserContext(scraper) as browser:
            browser.search_bids(search_keyword)
            
            # Get existing tender IDs from master table to avoid duplicates
            existing_ids = get_all_existing_tender_ids()
            
            downloaded_bids, download_info = browser.download_bids(
                max_bids=max_tenders, 
                existing_ids=existing_ids
            )
            
            # Get tender documents
            # Note: Need GEMINI_API_KEY accessible here - make it global or pass it
            global GEMINI_API_KEY
            analyzer = GemTenderAnalyzer(GEMINI_API_KEY, download_dir)
            tender_docs = analyzer.get_tender_documents(downloaded_bids)
            
            return downloaded_bids, download_info, tender_docs
            
    except Exception as e:
        logger.error(f"Error downloading tenders: {e}")
        return [], {}, {}

def analyze_tender_for_organization(tender_id, pdf_path, company_services, org_keywords, document_url, search_keyword):
    """Analyze a tender for a specific organization using their keywords"""
    # Note: Need GEMINI_API_KEY accessible here - make it global or pass it
    global GEMINI_API_KEY
    analyzer = GemTenderAnalyzer(GEMINI_API_KEY, "gem_bids")
    
    # Extract text from PDF
    tender_text = analyzer.extract_text_from_pdf(pdf_path)
    
    # Default values
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
    
    if tender_text:
        # Extract metadata
        description, due_date, extracted_bid_number, _ = analyzer.extract_metadata(tender_text[:5000])
        if extracted_bid_number and extracted_bid_number != "Not specified":
            tender_id = extracted_bid_number
        
        # Compute keyword score using organization's keywords
        keyword_score = 0.0
        matching_keywords = []
        for group in org_keywords:
            score, matches = compute_keyword_score(tender_text, group["match_keywords"])
            keyword_score += score
            matching_keywords.extend(matches)
        
        logger.info(f"Keyword score for {tender_id}: {keyword_score:.3f}")
        
        # Call Gemini for relevance if keyword score is high enough
        if ENABLE_API_FILTERING and keyword_score >= KEYWORD_SCORE_THRESHOLD:
            try:
                # Flatten keywords for Gemini
                flat_keywords = []
                for group in org_keywords:
                    flat_keywords.append(group["search_keyword"])
                    flat_keywords.extend(group["match_keywords"])
                
                relevance_result = analyzer.assess_tender_relevance_with_gemini(
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
        else:
            # Keyword-only mode
            matches_services = keyword_score >= 0.15
            match_reason = f"Keyword-only: score ({keyword_score:.3f}). {'Shortlisted' if matches_services else 'Rejected'}."
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

def process_tenders_for_keyword(search_keyword, max_tenders=30):
    """Download tenders for a keyword and create matches for all relevant organizations"""
    from sqlalchemy import text
    from database_config import engine
    
    # Get all organizations that have this search keyword configured
    organizations = get_organizations_for_search_keyword(search_keyword)
    
    if not organizations:
        logger.info(f"No organizations found with search keyword: {search_keyword}")
        return
    
    logger.info(f"Found {len(organizations)} organizations with search keyword '{search_keyword}'")
    
    # Download tenders for this keyword (once)
    downloaded_bids, download_info, tender_docs = download_tenders_for_keyword(search_keyword, max_tenders)
    
    if not downloaded_bids:
        logger.warning(f"No tenders downloaded for keyword: {search_keyword}")
        return
    
    # Track statistics
    total_matches = 0
    
    # For each organization, process the downloaded tenders
    for org in organizations:
        org_id = org['id']
        company_services = org['service_definition']
        
        logger.info(f"Processing {len(downloaded_bids)} tenders for organization {org_id}")
        
        # Get organization-specific keywords for matching
        org_keywords = get_keywords_for_organization(org_id, search_keyword=search_keyword)
        
        if not org_keywords:
            logger.warning(f"No keywords found for organization {org_id} with search keyword '{search_keyword}'")
            continue
        
        org_matches = 0
        
        # Process each tender for this organization
        for tender_id, pdf_path in tender_docs.items():
            original_url = download_info.get(tender_id, "")
            
            # Analyze tender specifically for this organization
            analysis = analyze_tender_for_organization(
                tender_id, 
                pdf_path, 
                company_services, 
                org_keywords,
                original_url,
                search_keyword
            )
            
            # Save to database with organization_id
            save_to_db(analysis, org_id)
            
            # Track stats
            if analysis.get("matches_services"):
                org_matches += 1
                total_matches += 1
                logger.info(f"Tender {tender_id} matches organization {org_id}")
        
        logger.info(f"Organization {org_id}: {org_matches}/{len(downloaded_bids)} tenders matched")
    
    logger.info(f"Completed processing for keyword '{search_keyword}'. Total matches across all organizations: {total_matches}")

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
    GEMINI_API_KEY = "AIzaSyDF_I0Ojo1Pbbh9VzA6wnyKinxSrUECPYI"  # Replace with your actual API key
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

# def main_cli(search_keyword, max_tenders, organization_id, domain_keywords=None):
#     """Entry point for CLI/scheduled execution with API filtering enabled by default"""
#     global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
#     ONLY_PROCESS_NEW = True
#     ENABLE_API_FILTERING = True  # Enable API filtering by default for CLI
#     logger.info(f"Running FIXED gem_nlp_api.py via CLI for organization {organization_id} with API filtering enabled")
#     main(search_keyword=search_keyword, max_tenders=max_tenders, organization_id=organization_id, domain_keywords=domain_keywords)

def main_cli(search_keyword, max_tenders, organization_id=None, domain_keywords=None):
    """Entry point for CLI/scheduled execution with API filtering enabled by default"""
    global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
    ONLY_PROCESS_NEW = True
    ENABLE_API_FILTERING = True  # Enable API filtering by default for CLI
    
    if organization_id:
        # Legacy mode: process for single organization
        logger.info(f"Running FIXED gem_nlp_api.py via CLI for organization {organization_id} with API filtering enabled")
        main(search_keyword=search_keyword, max_tenders=max_tenders, organization_id=organization_id, domain_keywords=domain_keywords)
    else:
        # New mode: process for all organizations with this search keyword
        logger.info(f"Running in multi-org mode for keyword '{search_keyword}'")
        process_tenders_for_keyword(search_keyword, max_tenders)

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


# Updated Gem NLP : 


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

# Add these new functions at the top after imports

def get_or_create_master_tender(tender_data):
    """Get or create a master tender record and return its ID"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            # Check if master tender exists
            result = conn.execute(
                text("SELECT id FROM gem_tender_master WHERE tender_id = :tender_id"),
                {"tender_id": tender_data["tender_id"]}
            )
            existing = result.fetchone()
            
            if existing:
                master_id = existing[0]
                # Update description if needed (but keep original creation_date)
                conn.execute(text("""
                    UPDATE gem_tender_master SET
                        description = :description,
                        due_date = :due_date,
                        document_url = :document_url,
                        pdf_path = :pdf_path
                    WHERE id = :master_id
                """), {
                    "description": tender_data["description"],
                    "due_date": tender_data["due_date"],
                    "document_url": tender_data.get("document_url", ""),
                    "pdf_path": tender_data.get("pdf_path", ""),
                    "master_id": master_id
                })
                conn.commit()
                return master_id
            else:
                # Insert new master tender
                result = conn.execute(text("""
                    INSERT INTO gem_tender_master (
                        tender_id, description, due_date, creation_date,
                        document_url, pdf_path
                    ) VALUES (
                        :tender_id, :description, :due_date, :creation_date,
                        :document_url, :pdf_path
                    ) RETURNING id
                """), {
                    "tender_id": tender_data["tender_id"],
                    "description": tender_data["description"],
                    "due_date": tender_data["due_date"],
                    "creation_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "document_url": tender_data.get("document_url", ""),
                    "pdf_path": tender_data.get("pdf_path", "")
                })
                master_id = result.fetchone()[0]
                conn.commit()
                return master_id
    except Exception as e:
        logger.error(f"Error in get_or_create_master_tender: {e}")
        raise

def save_organization_match(master_id, organization_id, analysis_result):
    """Save or update organization-specific match data"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            # Check if match exists
            result = conn.execute(text("""
                SELECT id FROM gem_tender_matches 
                WHERE organization_id = :org_id AND master_tender_id = :master_id
            """), {
                "org_id": organization_id,
                "master_id": master_id
            })
            existing = result.fetchone()
            
            keywords_str = "|".join(analysis_result.get("keywords", [])) if "keywords" in analysis_result else ""
            
            if existing:
                # Update existing match
                conn.execute(text("""
                    UPDATE gem_tender_matches SET
                        matches_services = :matches_services,
                        match_reason = :match_reason,
                        match_score = :match_score,
                        match_score_keyword = :match_score_keyword,
                        match_score_combined = :match_score_combined,
                        relevance_percentage = :relevance_percentage,
                        strategic_fit = :strategic_fit,
                        is_central_match = :is_central_match,
                        primary_scope = :primary_scope,
                        api_calls_made = :api_calls_made,
                        tokens_used = :tokens_used
                    WHERE organization_id = :org_id AND master_tender_id = :master_id
                """), {
                    "matches_services": bool(analysis_result["matches_services"]),
                    "match_reason": analysis_result["match_reason"],
                    "match_score": analysis_result.get("match_score", 0.0),
                    "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
                    "match_score_combined": analysis_result.get("match_score_combined", 0.0),
                    "relevance_percentage": analysis_result.get("relevance_percentage", 0),
                    "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
                    "is_central_match": bool(analysis_result.get("is_central_match", False)),
                    "primary_scope": analysis_result.get("primary_scope", ""),
                    "api_calls_made": analysis_result.get("api_calls_made", 0),
                    "tokens_used": analysis_result.get("tokens_used", 0),
                    "org_id": organization_id,
                    "master_id": master_id
                })
            else:
                # Insert new match
                conn.execute(text("""
                    INSERT INTO gem_tender_matches (
                        organization_id, master_tender_id,
                        matches_services, match_reason,
                        match_score, match_score_keyword, match_score_combined,
                        relevance_percentage, strategic_fit, is_central_match,
                        primary_scope, api_calls_made, tokens_used
                    ) VALUES (
                        :org_id, :master_id,
                        :matches_services, :match_reason,
                        :match_score, :match_score_keyword, :match_score_combined,
                        :relevance_percentage, :strategic_fit, :is_central_match,
                        :primary_scope, :api_calls_made, :tokens_used
                    )
                """), {
                    "org_id": organization_id,
                    "master_id": master_id,
                    "matches_services": bool(analysis_result["matches_services"]),
                    "match_reason": analysis_result["match_reason"],
                    "match_score": analysis_result.get("match_score", 0.0),
                    "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
                    "match_score_combined": analysis_result.get("match_score_combined", 0.0),
                    "relevance_percentage": analysis_result.get("relevance_percentage", 0),
                    "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
                    "is_central_match": bool(analysis_result.get("is_central_match", False)),
                    "primary_scope": analysis_result.get("primary_scope", ""),
                    "api_calls_made": analysis_result.get("api_calls_made", 0),
                    "tokens_used": analysis_result.get("tokens_used", 0)
                })
            
            conn.commit()
            logger.info(f"Saved match for organization {organization_id} to tender {analysis_result['tender_id']}")
            
    except Exception as e:
        logger.error(f"Error saving organization match: {e}")
        raise

def get_organizations_for_search_config(config_id):
    """Get all organizations associated with a search configuration"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT organization_id 
                FROM gem_org_search_capabilities 
                WHERE search_config_id = :config_id
            """), {"config_id": config_id})
            
            return [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Error getting organizations for config {config_id}: {e}")
        return []

def get_keywords_for_organization_by_config(organization_id, config_id):
    """Get keywords for an organization from a specific search configuration"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT keyword FROM gem_org_search_capabilities
                WHERE organization_id = :org_id AND search_config_id = :config_id
            """), {
                "org_id": organization_id,
                "config_id": config_id
            })
            
            all_keywords = []
            for row in result.fetchall():
                # Split each comma-separated string into individual keywords
                keyword_string = row[0]
                if keyword_string:
                    # Split by comma and clean up each keyword
                    individual_keywords = [k.strip().lower() for k in keyword_string.split(',') if k.strip()]
                    all_keywords.extend(individual_keywords)
            
            if all_keywords:
                # Return in the expected format with properly split keywords
                return [{
                    "search_keyword": str(config_id),  # Use config_id as group identifier
                    "match_keywords": all_keywords
                }]
            return []
    except Exception as e:
        logger.error(f"Error getting keywords for org {organization_id}, config {config_id}: {e}")
        return []

def update_master_tender(master_id, analysis_result):
    """Update master tender record with improved data from analysis"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            # Only update if we have better data
            update_fields = []
            params = {"master_id": master_id}
            
            if analysis_result.get("description") and analysis_result["description"] != "Not specified":
                update_fields.append("description = :description")
                params["description"] = analysis_result["description"]
            
            if analysis_result.get("due_date") and analysis_result["due_date"] != "Not specified":
                update_fields.append("due_date = :due_date")
                params["due_date"] = analysis_result["due_date"]
            
            if update_fields:
                query = f"UPDATE gem_tender_master SET {', '.join(update_fields)} WHERE id = :master_id"
                conn.execute(text(query), params)
                conn.commit()
                logger.info(f"Updated master tender {master_id} with improved data")
                
    except Exception as e:
        logger.error(f"Error updating master tender {master_id}: {e}")
        # Don't raise - this is non-critical

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


# def get_existing_tender_ids(organization_id):
#     """Get a set of tender IDs that already exist in the database for a specific organization"""
#     from sqlalchemy import text
#     from database_config import engine
    
#     try:
#         with engine.connect() as conn:
#             result = conn.execute(
#                 text("SELECT tender_id FROM gem_tenders WHERE organization_id = :org_id AND tender_id IS NOT NULL AND tender_id != 'unknown_bid'"),
#                 {"org_id": organization_id}
#             )
#             existing_ids = {row[0] for row in result if row[0]}
#             logger.info(f"Found {len(existing_ids)} existing tender IDs for organization {organization_id}")
#             return existing_ids
#     except Exception as e:
#         logger.error(f"Error retrieving existing tender IDs: {e}")
#         return set()

def get_existing_tender_ids(organization_id):
    """
    Get a set of tender IDs that already exist in the master table.
    Note: We check master table because we want to avoid re-downloading.
    """
    from sqlalchemy import text
    from database_config import engine
    
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT tender_id FROM gem_tender_master WHERE tender_id IS NOT NULL AND tender_id != 'unknown_bid'")
            )
            existing_ids = {row[0] for row in result if row[0]}
            logger.info(f"Found {len(existing_ids)} existing tender IDs in master table")
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
    
    # def analyze_tender(self, tender_id, pdf_path, company_services, organization_id, document_url="", search_keyword=None):
    #     """Analyze a tender document with keyword-based matching and optional API enhancement"""
    #     try:
    #         logger.info(f"Analyzing tender: {tender_id}")

    #         tender_text = self.extract_text_from_pdf(pdf_path)

    #         # Default initialization
    #         description = "Not specified"
    #         due_date = "Not specified"
    #         extracted_bid_number = tender_id
    #         matching_keywords = []
    #         keyword_score = 0.0
    #         match_score_combined = 0.0
    #         matches_services = False
    #         match_reason = "Not specified"
    #         total_api_calls = 0
    #         total_tokens_used = 0
    #         relevance_percentage = 0
    #         is_central_match = False
    #         strategic_fit = False
    #         primary_scope = "Not specified"

    #         if not tender_text:
    #             return {
    #                 "tender_id": tender_id,
    #                 "pdf_path": pdf_path,
    #                 "description": description,
    #                 "due_date": due_date,
    #                 "keywords": matching_keywords,
    #                 "matches_services": matches_services,
    #                 "match_reason": match_reason,
    #                 "match_score": match_score_combined,
    #                 "match_score_keyword": keyword_score,
    #                 "match_score_combined": match_score_combined,
    #                 "document_url": document_url,
    #                 "api_calls_made": total_api_calls,
    #                 "tokens_used": total_tokens_used,
    #                 "relevance_percentage": relevance_percentage,
    #                 "is_central_match": is_central_match,
    #                 "strategic_fit": strategic_fit,
    #                 "primary_scope": primary_scope
    #             }

    #         # Extract metadata
    #         description, due_date, extracted_bid_number, _ = self.extract_metadata(tender_text[:5000])
    #         if extracted_bid_number and extracted_bid_number != "Not specified":
    #             tender_id = extracted_bid_number

    #         # --- UPDATED PART: Pass search_keyword to filter keyword groups ---
    #         keyword_groups = get_keywords_for_organization(organization_id, search_keyword=search_keyword)
    #         print(f"DEBUG: Retrieved {len(keyword_groups)} keyword groups for org {organization_id} with search_keyword='{search_keyword}'")

    #         keyword_score = 0.0
    #         matching_keywords = []
    #         for group in keyword_groups:
    #             score, matches = compute_keyword_score(tender_text, group["match_keywords"])
    #             keyword_score += score
    #             matching_keywords.extend(matches)

    #         logger.info(f"Keyword score for {tender_id}: {keyword_score:.3f}")
    #         logger.info(f"Matching keywords: {matching_keywords}")

    #         # Filtering logic
    #         if ENABLE_API_FILTERING and keyword_score < KEYWORD_SCORE_THRESHOLD:
    #             matches_services = keyword_score >= 0.15
    #             match_reason = f"Keyword-only: score ({keyword_score:.3f}) below threshold. {'Shortlisted' if matches_services else 'Rejected'}."

    #         else:
    #             try:
    #                 api_desc, api_due, api_bid, tokens, calls = self.extract_metadata_with_gemini(tender_text)
    #                 total_tokens_used += tokens
    #                 total_api_calls += calls

    #                 if api_desc != "Not specified":
    #                     description = api_desc
    #                 if due_date == "Not specified" and api_due != "Not specified":
    #                     due_date = api_due
    #                 if api_bid != "Not specified":
    #                     tender_id = api_bid

    #             except Exception as e:
    #                 logger.warning(f"Metadata extraction failed: {e}")

    #             try:
    #                 # --- UPDATED PART: flatten keywords for Gemini relevance ---
    #                 flat_keywords = []
    #                 for group in keyword_groups:
    #                     flat_keywords.append(group["search_keyword"])
    #                     flat_keywords.extend(group["match_keywords"])

    #                 relevance_result = self.assess_tender_relevance_with_gemini(
    #                     tender_text, company_services, flat_keywords
    #                 )
    #                 total_tokens_used += relevance_result["tokens_used"]
    #                 total_api_calls += relevance_result["api_calls"]

    #                 relevance_percentage = relevance_result["relevance_percentage"]
    #                 is_central_match = relevance_result["is_central_match"]
    #                 strategic_fit = relevance_result["strategic_fit"]
    #                 primary_scope = relevance_result["primary_scope"]
    #                 recommendation = relevance_result["recommendation"]
    #                 reasoning = relevance_result["reasoning"]

    #                 matches_services = recommendation.upper() == "SHORTLIST"
    #                 match_reason = f"{recommendation.upper()} by AI: {relevance_percentage}% relevance. {reasoning}"
    #                 ai_score = relevance_percentage / 100.0
    #                 match_score_combined = (keyword_score * 0.3) + (ai_score * 0.7)

    #             except Exception as e:
    #                 logger.warning(f"Relevance assessment failed: {e}")
    #                 matches_services = keyword_score >= 0.15
    #                 match_reason = f"AI failed. Using keywords only: score = {keyword_score:.3f}"
    #                 match_score_combined = keyword_score

    #         return {
    #             "tender_id": tender_id,
    #             "pdf_path": pdf_path,
    #             "description": description,
    #             "due_date": due_date,
    #             "keywords": matching_keywords,
    #             "matches_services": matches_services,
    #             "match_reason": match_reason,
    #             "match_score": match_score_combined,
    #             "match_score_keyword": keyword_score,
    #             "match_score_combined": match_score_combined,
    #             "document_url": document_url,
    #             "api_calls_made": total_api_calls,
    #             "tokens_used": total_tokens_used,
    #             "relevance_percentage": relevance_percentage,
    #             "is_central_match": is_central_match,
    #             "strategic_fit": strategic_fit,
    #             "primary_scope": primary_scope
    #         }

    #     except Exception as e:
    #         logger.error(f"Error analyzing tender {tender_id}: {e}", exc_info=True)
    #         if ENABLE_MEMORY_OPTIMIZATION:
    #             gc.collect()
    #         return {
    #             "tender_id": tender_id,
    #             "pdf_path": pdf_path,
    #             "description": description,
    #             "due_date": due_date,
    #             "keywords": matching_keywords,
    #             "matches_services": matches_services,
    #             "match_reason": match_reason,
    #             "match_score": match_score_combined,
    #             "match_score_keyword": keyword_score,
    #             "match_score_combined": match_score_combined,
    #             "document_url": document_url,
    #             "api_calls_made": total_api_calls,
    #             "tokens_used": total_tokens_used,
    #             "relevance_percentage": relevance_percentage,
    #             "is_central_match": is_central_match,
    #             "strategic_fit": strategic_fit,
    #             "primary_scope": primary_scope
    #         }
    def analyze_tender(self, tender_id, pdf_path, company_services, organization_id, document_url="", search_config_id=None):
        """
        Analyze a tender document with keyword-based matching and optional API enhancement.
        Now includes search_config_id to get organization-specific keywords.
        """
        try:
            logger.info(f"Analyzing tender: {tender_id} for organization {organization_id}")
            
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
            
            # Get organization-specific keywords for this config
            keyword_groups = get_keywords_for_organization_by_config(organization_id, search_config_id)
            
            # If no config-specific keywords, fall back to the old method
            if not keyword_groups:
                keyword_groups = get_keywords_for_organization(organization_id, search_keyword=None)
            
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
                    # Flatten keywords for Gemini relevance
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


# def save_to_db(analysis_result, organization_id):
#     """Save analysis result to database with organization association"""
#     from sqlalchemy import text
#     from database_config import engine
    
#     try:
#         # Prepare values
#         keywords_str = "|".join(analysis_result.get("keywords", [])) if "keywords" in analysis_result else ""
        
#         with engine.connect() as conn:
#             # Check if tender already exists
#             result = conn.execute(
#                 text("SELECT id FROM gem_tenders WHERE tender_id = :tender_id AND organization_id = :org_id"),
#                 {
#                     "tender_id": analysis_result["tender_id"],
#                     "org_id": organization_id
#                 }
#             )
#             existing_tender = result.fetchone()
            
#             if existing_tender:
#                 # Update existing tender
#                 conn.execute(text("""
#                     UPDATE gem_tenders SET
#                         description = :description,
#                         due_date = :due_date,
#                         matches_services = :matches_services,
#                         match_reason = :match_reason,
#                         document_url = :document_url,
#                         pdf_path = :pdf_path,
#                         match_score = :match_score,
#                         keywords = :keywords,
#                         match_score_keyword = :match_score_keyword,
#                         match_score_combined = :match_score_combined,
#                         api_calls_made = :api_calls_made,
#                         tokens_used = :tokens_used,
#                         relevance_percentage = :relevance_percentage,
#                         is_central_match = :is_central_match,
#                         strategic_fit = :strategic_fit,
#                         primary_scope = :primary_scope
#                     WHERE tender_id = :tender_id AND organization_id = :org_id
#                 """), {
#                     "description": analysis_result["description"],
#                     "due_date": analysis_result["due_date"],
#                     "matches_services": bool(analysis_result["matches_services"]),
#                     "match_reason": analysis_result["match_reason"],
#                     "document_url": analysis_result.get("document_url", ""),
#                     "pdf_path": analysis_result.get("pdf_path", ""),
#                     "match_score": analysis_result.get("match_score", 0.0),
#                     "keywords": keywords_str,
#                     "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
#                     "match_score_combined": analysis_result.get("match_score_combined", 0.0),
#                     "api_calls_made": analysis_result.get("api_calls_made", 0),
#                     "tokens_used": analysis_result.get("tokens_used", 0),
#                     "relevance_percentage": analysis_result.get("relevance_percentage", 0),
#                     "is_central_match": bool(analysis_result.get("is_central_match", False)),
#                     "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
#                     "primary_scope": analysis_result.get("primary_scope", ""),
#                     "tender_id": analysis_result["tender_id"],
#                     "org_id": organization_id
#                 })
#             else:
#                 # Create new tender
#                 conn.execute(text("""
#                     INSERT INTO gem_tenders (
#                         tender_id, description, due_date, creation_date, matches_services, match_reason,
#                         document_url, pdf_path, organization_id, match_score, keywords,
#                         match_score_keyword, match_score_combined, api_calls_made, tokens_used,
#                         relevance_percentage, is_central_match, strategic_fit, primary_scope
#                     ) VALUES (
#                         :tender_id, :description, :due_date, :creation_date, :matches_services, :match_reason,
#                         :document_url, :pdf_path, :org_id, :match_score, :keywords,
#                         :match_score_keyword, :match_score_combined, :api_calls_made, :tokens_used,
#                         :relevance_percentage, :is_central_match, :strategic_fit, :primary_scope
#                     )
#                 """), {
#                     "tender_id": analysis_result["tender_id"],
#                     "description": analysis_result["description"],
#                     "due_date": analysis_result["due_date"],
#                     "creation_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
#                     "matches_services": bool(analysis_result["matches_services"]),
#                     "match_reason": analysis_result["match_reason"],
#                     "document_url": analysis_result.get("document_url", ""),
#                     "pdf_path": analysis_result.get("pdf_path", ""),
#                     "org_id": organization_id,
#                     "match_score": analysis_result.get("match_score", 0.0),
#                     "keywords": keywords_str,
#                     "match_score_keyword": analysis_result.get("match_score_keyword", 0.0),
#                     "match_score_combined": analysis_result.get("match_score_combined", 0.0),
#                     "api_calls_made": analysis_result.get("api_calls_made", 0),
#                     "tokens_used": analysis_result.get("tokens_used", 0),
#                     "relevance_percentage": analysis_result.get("relevance_percentage", 0),
#                     "is_central_match": bool(analysis_result.get("is_central_match", False)),
#                     "strategic_fit": bool(analysis_result.get("strategic_fit", False)),
#                     "primary_scope": analysis_result.get("primary_scope", "")
#                 })
            
#             conn.commit()
#             print(f"Saved or updated tender {analysis_result['tender_id']} for organization {organization_id}")

#     except Exception as e:
#         print(f"Database error: {e}")
#         raise

def save_to_db(analysis_result, organization_id):
    """
    Save analysis result to database using master/match architecture.
    This function is kept for backward compatibility but now uses the new structure.
    """
    try:
        # First, save to master table
        master_id = get_or_create_master_tender(analysis_result)
        
        # Then save organization-specific match
        save_organization_match(master_id, organization_id, analysis_result)
        
        print(f"Saved tender {analysis_result['tender_id']} for organization {organization_id}")
        
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

# def main(search_keyword=None, max_tenders=30, organization_id=None, domain_keywords=None):
#     """Main function to run the GeM Tender Analyzer with API filtering and improved browser stability"""
#     global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
    
#     logger.info("=" * 80)
#     logger.info("GeM Tender Analyzer with FIXED Pagination and Browser Stability")
#     logger.info("=" * 80)
    
#     # Use environment variable for API key
#     GEMINI_API_KEY = "AIzaSyDF_I0Ojo1Pbbh9VzA6wnyKinxSrUECPYI"  # Replace with your actual API key
#     if not GEMINI_API_KEY:
#         logger.error("GEMINI_API_KEY environment variable not set")
#         return
    
#     # Initialize database
#     init_database()
    
#     # Interactive mode - ask for organization if not provided
#     if organization_id is None:
#         try:
#             organization_id = int(input("Enter organization ID: ").strip())
#         except ValueError:
#             logger.error("Invalid organization ID provided")
#             return
    
#     # Get set of existing tender IDs from the database for this organization
#     existing_ids = get_existing_tender_ids(organization_id)
#     logger.info(f"Retrieved {len(existing_ids)} existing tender IDs for organization {organization_id}")
    
#     # Get service definition from database for this organization
#     company_services = get_service_definition(organization_id)
    
#     if not company_services:
#         logger.error(f"No service definition found for organization {organization_id}. Please define your services in the web application first.")
#         return

#     # Ask if user wants to do incremental processing in interactive mode
#     if search_keyword is None:  # Interactive mode
#         incremental = input("Do you want to only process new tenders? (y/n, default: y): ").strip().lower()
#         ONLY_PROCESS_NEW = incremental != 'n'
        
#         # Get user input for keyword - allow empty for no filtering
#         search_keyword = input("Enter keyword to search for tenders (leave empty to browse all tenders): ").strip()
#         search_keyword = search_keyword if search_keyword else None

#         max_tenders = input("Enter maximum number of tenders to download (default 30): ")
#         max_tenders = int(max_tenders) if max_tenders.strip() else 30

#         # Ask about API filtering
#         api_filtering = input(f"Enable API filtering (only analyze tenders with keyword score > {KEYWORD_SCORE_THRESHOLD})? (y/n, default: y): ").strip().lower()
#         ENABLE_API_FILTERING = api_filtering != 'n'

#     if search_keyword:
#         logger.info(f"Searching for keyword: '{search_keyword}'")
#     else:
#         logger.info("Browsing all available tenders")
    
#     # Limit company services display length to avoid logging issues
#     service_display = company_services[:50] + "..." if len(company_services) > 50 else company_services
#     logger.info(f"Company services: {service_display}")
    
#     if ENABLE_API_FILTERING:
#         logger.info(f"API filtering enabled - only tenders with keyword score >= {KEYWORD_SCORE_THRESHOLD} will be sent to Gemini API")
    
#     # Initialize analyzer with API key
#     download_dir = "gem_bids"
#     analyzer = GemTenderAnalyzer(GEMINI_API_KEY, download_dir)
    
#     # Initialize scraper but don't start browser yet
#     scraper = GemBidScraper(download_dir)
    
#     # Tracking variables for this session
#     session_api_calls = 0
#     session_tokens_used = 0
#     tenders_filtered_out = 0
#     tenders_analyzed_with_api = 0
    
#     # Use context manager to ensure browser is always closed
#     with BrowserContext(scraper) as browser:
#         try:
#             # Search and download tenders
#             logger.info("Starting the browser and downloading tenders...")
#             browser.search_bids(search_keyword)
#             downloaded_bids, download_info = browser.download_bids(max_bids=max_tenders, existing_ids=existing_ids)
            
#             if not downloaded_bids:
#                 logger.warning("No new tenders were downloaded. Try again with a different keyword or disable incremental processing.")
#                 return
                
#             # Get tender documents
#             tender_docs = analyzer.get_tender_documents(downloaded_bids)
            
#             # Process tenders in batches to avoid memory issues
#             all_analysis_results = []
            
#             # Convert to list of tuples for batch processing
#             tender_items = list(tender_docs.items())
            
#             for i in range(0, len(tender_items), BATCH_SIZE):
#                 batch = tender_items[i:i+BATCH_SIZE]
#                 logger.info(f"Processing batch {i//BATCH_SIZE + 1} of {(len(tender_items) + BATCH_SIZE - 1) // BATCH_SIZE}")
                
#                 # Analyze each tender in the batch
#                 batch_results = []
#                 for tender_id, pdf_path in batch:
#                     # Get document URL if available
#                     original_url = download_info.get(tender_id, "")
#                     print(f"DEBUG: Passing URL to analyzer for {tender_id}: '{original_url}'")

#                     # --- UPDATED PART: Pass search_keyword to analyzer ---
#                     analysis = analyzer.analyze_tender(tender_id, pdf_path, company_services, organization_id, original_url, search_keyword)

#                     # Track API usage for this session
#                     session_api_calls += analysis.get("api_calls_made", 0)
#                     session_tokens_used += analysis.get("tokens_used", 0)
                    
#                     # Track filtering statistics
#                     if analysis.get("api_calls_made", 0) > 0:
#                         tenders_analyzed_with_api += 1
#                     else:
#                         tenders_filtered_out += 1

#                     # Now fix document_url if tender_id changed inside analysis
#                     if analysis["tender_id"] != tender_id and not analysis.get("document_url"):
#                         # Attempt to map with new tender_id
#                         analysis["document_url"] = download_info.get(analysis["tender_id"], original_url)
                    
#                     batch_results.append(analysis)
                    
#                     # Save to database with organization_id
#                     save_to_db(analysis, organization_id)
                    
#                     # Update the existing IDs set for future checks
#                     existing_ids.add(analysis["tender_id"])
                    
#                     # Explicitly call garbage collection to free memory
#                     if ENABLE_MEMORY_OPTIMIZATION:
#                         gc.collect()
                
#                 # Add batch results to all results
#                 all_analysis_results.extend(batch_results)
                
#                 # Free memory between batches
#                 if ENABLE_MEMORY_OPTIMIZATION:
#                     batch_results = None
#                     gc.collect()
#                     cleanup_memory()
            
#             # Output enhanced summary with API usage statistics
#             matching_count = len([r for r in all_analysis_results if r["matches_services"]])
#             total_count = len(all_analysis_results)
            
#             logger.info("\n=== Analysis Summary ===")
#             logger.info(f"Found {matching_count} matching tenders out of {total_count} analyzed")
#             logger.info(f"Tenders analyzed with API: {tenders_analyzed_with_api}")
#             logger.info(f"Tenders filtered out (keyword score < {KEYWORD_SCORE_THRESHOLD}): {tenders_filtered_out}")
#             logger.info(f"Total API calls made: {session_api_calls}")
#             logger.info(f"Total tokens used: {session_tokens_used}")
#             if tenders_analyzed_with_api > 0:
#                 logger.info(f"Average tokens per API-analyzed tender: {session_tokens_used / tenders_analyzed_with_api:.1f}")
            
#             # Calculate cost savings
#             if ENABLE_API_FILTERING and tenders_filtered_out > 0:
#                 estimated_tokens_saved = tenders_filtered_out * (session_tokens_used / max(tenders_analyzed_with_api, 1))
#                 logger.info(f"Estimated tokens saved by filtering: {estimated_tokens_saved:.0f}")
            
#             # Save to CSV for easy access
#             try:
#                 matching_tenders = [result for result in all_analysis_results if result["matches_services"]]
#                 matching_df = pd.DataFrame(matching_tenders)
                
#                 if not matching_df.empty:
#                     matching_output_file = os.path.join(download_dir, f"matching_tenders_org{organization_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
#                     matching_df.to_csv(matching_output_file, index=False, encoding='utf-8-sig')
#                     logger.info(f"Matching tenders saved to {matching_output_file}")
                
#                 # All tenders with API usage columns
#                 all_df = pd.DataFrame(all_analysis_results)
#                 all_output_file = os.path.join(download_dir, f"all_tenders_org{organization_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
#                 all_df.to_csv(all_output_file, index=False, encoding='utf-8-sig')
#                 logger.info(f"All tenders saved to {all_output_file}")
#             except Exception as e:
#                 logger.error(f"Error saving CSV files: {e}")
#                 # Try with a more restrictive approach
#                 try:
#                     # Create sanitized versions of the data
#                     sanitized_results = []
#                     for result in all_analysis_results:
#                         sanitized_result = result.copy()
#                         for key in ['description', 'match_reason']:
#                             if key in sanitized_result:
#                                 sanitized_result[key] = ''.join(c if ord(c) < 128 else '_' for c in sanitized_result[key])
#                         sanitized_results.append(sanitized_result)
                    
#                     all_df = pd.DataFrame(sanitized_results)
#                     all_output_file = os.path.join(download_dir, f"all_tenders_org{organization_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_sanitized.csv")
#                     all_df.to_csv(all_output_file, index=False)
#                     logger.info(f"Sanitized tenders saved to {all_output_file}")
#                 except Exception as e2:
#                     logger.error(f"Error saving sanitized CSV files: {e2}")
        
#         except Exception as e:
#             logger.error(f"Error in main function: {e}", exc_info=True)
            
#     # Final cleanup and summary
#     if ENABLE_MEMORY_OPTIMIZATION:
#         cleanup_memory()
    
#     logger.info("GeM Tender Analyzer completed successfully!")

def main(search_keyword=None, max_tenders=30, organization_id=None, domain_keywords=None, search_config_id=None):
    """Main function to run the GeM Tender Analyzer with master/match architecture"""
    global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
    
    logger.info("=" * 80)
    logger.info("GeM Tender Analyzer with Master/Match Architecture")
    logger.info("=" * 80)
    
    # Use environment variable for API key
    GEMINI_API_KEY = "AIzaSyDF_I0Ojo1Pbbh9VzA6wnyKinxSrUECPYI"  # Replace with your actual API key
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY environment variable not set")
        return
    
    # Initialize database
    init_database()
    
    # # Get organizations for this search config
    # if search_config_id:
    #     organizations = get_organizations_for_search_config(search_config_id)
    #     logger.info(f"Found {len(organizations)} organizations for search config {search_config_id}")
    # else:
    #     # Fallback for backward compatibility
    #     organizations = [organization_id] if organization_id else []

    # Determine which organizations to process
    if search_config_id:
        # Multi-org mode: get all organizations for this search config
        organizations = get_organizations_for_search_config(search_config_id)
        logger.info(f"Found {len(organizations)} organizations for search config {search_config_id}")
    elif organization_id:
        # Single-org mode: process just this organization
        organizations = [organization_id]
        logger.info(f"Processing for single organization {organization_id}")
    else:
        # Interactive mode - ask for organization ID
        try:
            organization_id = int(input("Enter organization ID: ").strip())
            organizations = [organization_id]
            logger.info(f"Processing for single organization {organization_id}")
        except ValueError:
            logger.error("Invalid organization ID provided")
            return
        except KeyboardInterrupt:
            logger.info("Operation cancelled by user")
            return
    
    if not organizations:
        logger.warning("No organizations found for this search configuration")
        return
    
    # Get set of existing tender IDs from master table (avoid re-downloading)
    existing_ids = get_existing_tender_ids(None)  # Pass None to get all master tenders
    logger.info(f"Retrieved {len(existing_ids)} existing tender IDs from master table")
    
    # Get service definitions for all organizations
    service_definitions = {}
    for org_id in organizations:
        service_definitions[org_id] = get_service_definition(org_id)
        if not service_definitions[org_id]:
            logger.warning(f"No service definition found for organization {org_id}")
    
    # Initialize analyzer
    download_dir = "gem_bids"
    analyzer = GemTenderAnalyzer(GEMINI_API_KEY, download_dir)
    
    # Initialize scraper
    scraper = GemBidScraper(download_dir)
    
    # Tracking variables
    session_api_calls = 0
    session_tokens_used = 0
    tenders_filtered_out = 0
    tenders_analyzed_with_api = 0
    
    # Use context manager
    with BrowserContext(scraper) as browser:
        try:
            # Search and download tenders
            logger.info("Starting the browser and downloading tenders...")
            browser.search_bids(search_keyword)
            downloaded_bids, download_info = browser.download_bids(max_bids=max_tenders, existing_ids=existing_ids)
            
            if not downloaded_bids:
                logger.warning("No new tenders were downloaded.")
                return
            
            # Get tender documents
            tender_docs = analyzer.get_tender_documents(downloaded_bids)
            
            # Process tenders in batches
            all_analysis_results = []
            tender_items = list(tender_docs.items())
            
            for i in range(0, len(tender_items), BATCH_SIZE):
                batch = tender_items[i:i+BATCH_SIZE]
                logger.info(f"Processing batch {i//BATCH_SIZE + 1} of {(len(tender_items) + BATCH_SIZE - 1) // BATCH_SIZE}")
                
                for tender_id, pdf_path in batch:
                    original_url = download_info.get(tender_id, "")
                    
                    # First, create master tender record
                    master_tender_data = {
                        "tender_id": tender_id,
                        "description": "Not specified",  # Will be updated during analysis
                        "due_date": "Not specified",
                        "document_url": original_url,
                        "pdf_path": pdf_path
                    }
                    
                    # Get or create master tender
                    master_id = get_or_create_master_tender(master_tender_data)
                    
                    # Now analyze for each organization
                    for org_id in organizations:
                        if org_id not in service_definitions or not service_definitions[org_id]:
                            logger.warning(f"Skipping org {org_id} - no service definition")
                            continue
                        
                        # Analyze for this organization
                        analysis = analyzer.analyze_tender(
                            tender_id, 
                            pdf_path, 
                            service_definitions[org_id], 
                            org_id, 
                            original_url,
                            search_config_id
                        )
                        
                        # Track API usage
                        session_api_calls += analysis.get("api_calls_made", 0)
                        session_tokens_used += analysis.get("tokens_used", 0)
                        
                        if analysis.get("api_calls_made", 0) > 0:
                            tenders_analyzed_with_api += 1
                        else:
                            tenders_filtered_out += 1
                        
                        # Save organization-specific match
                        save_organization_match(master_id, org_id, analysis)
                        
                        # Update master tender with better data if available
                        if analysis["description"] != "Not specified" or analysis["due_date"] != "Not specified":
                            update_master_tender(master_id, analysis)
                        
                        all_analysis_results.append(analysis)
                        
                        if ENABLE_MEMORY_OPTIMIZATION:
                            gc.collect()
                    
                    # Update existing IDs set
                    existing_ids.add(tender_id)
                
                # Free memory between batches
                if ENABLE_MEMORY_OPTIMIZATION:
                    gc.collect()
                    cleanup_memory()
            
            # Output summary
            logger.info("\n=== Analysis Summary ===")
            logger.info(f"Processed {len(tender_docs)} unique tenders for {len(organizations)} organizations")
            logger.info(f"Tenders analyzed with API: {tenders_analyzed_with_api}")
            logger.info(f"Tenders filtered out: {tenders_filtered_out}")
            logger.info(f"Total API calls made: {session_api_calls}")
            logger.info(f"Total tokens used: {session_tokens_used}")
            
        except Exception as e:
            logger.error(f"Error in main function: {e}", exc_info=True)
    
    if ENABLE_MEMORY_OPTIMIZATION:
        cleanup_memory()
    
    logger.info("GeM Tender Analyzer completed successfully!")

# def main_cli(search_keyword, max_tenders, organization_id, domain_keywords=None):
#     """Entry point for CLI/scheduled execution with API filtering enabled by default"""
#     global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
#     ONLY_PROCESS_NEW = True
#     ENABLE_API_FILTERING = True  # Enable API filtering by default for CLI
#     logger.info(f"Running FIXED gem_nlp_api.py via CLI for organization {organization_id} with API filtering enabled")
#     main(search_keyword=search_keyword, max_tenders=max_tenders, organization_id=organization_id, domain_keywords=domain_keywords)

def process_tenders_for_keyword(search_keyword, max_tenders=30):
    """Process tenders for a keyword across all organizations that have this search config"""
    from sqlalchemy import text
    from database_config import engine
    
    try:
        # First, get the search configuration ID for this keyword
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id FROM gem_search_configurations 
                WHERE LOWER(search_keyword) = LOWER(:keyword)
                ORDER BY id DESC LIMIT 1
            """), {"keyword": search_keyword})
            
            row = result.fetchone()
            if not row:
                logger.warning(f"No search configuration found for keyword: {search_keyword}")
                return
            
            search_config_id = row[0]
            
        # Get all organizations for this search config
        organizations = get_organizations_for_search_config(search_config_id)
        
        if not organizations:
            logger.info(f"No organizations found with search keyword: {search_keyword}")
            return
        
        logger.info(f"Found {len(organizations)} organizations with search keyword '{search_keyword}'")
        
        # Call main with search_config_id to process for all organizations
        main(
            search_keyword=search_keyword,
            max_tenders=max_tenders,
            organization_id=None,  # Not used when search_config_id is provided
            domain_keywords=None,
            search_config_id=search_config_id
        )
        
    except Exception as e:
        logger.error(f"Error in process_tenders_for_keyword: {e}")

def main_cli(search_keyword, max_tenders, organization_id=None, domain_keywords=None):
    """Entry point for CLI/scheduled execution with API filtering enabled by default"""
    global ONLY_PROCESS_NEW, ENABLE_API_FILTERING
    ONLY_PROCESS_NEW = True
    ENABLE_API_FILTERING = True  # Enable API filtering by default for CLI
    
    if organization_id is not None:
        # Case 1: Specific organization provided - use existing logic
        logger.info(f"Running for single organization {organization_id} with search keyword '{search_keyword}'")
        main(search_keyword=search_keyword, max_tenders=max_tenders, 
             organization_id=organization_id, domain_keywords=domain_keywords)
    else:
        # Case 2: No organization provided - process for all organizations with this keyword
        logger.info(f"Running in multi-org mode for keyword '{search_keyword}'")
        process_tenders_for_keyword(search_keyword, max_tenders)

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