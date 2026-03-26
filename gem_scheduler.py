# import os
# import time
# import datetime
# import logging
# import subprocess
# import sys
# from threading import Thread
# import schedule
# from sqlalchemy import text
# from concurrent.futures import ThreadPoolExecutor
# from threading import Semaphore

# MAX_WORKERS = 4
# # Thread pool with bounded concurrency (backpressure enabled)
# executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
# semaphore = Semaphore(MAX_WORKERS)


# # Configure logging
# logging.basicConfig(level=logging.INFO, 
#                     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#                     handlers=[logging.FileHandler("gem_scheduler.log"),
#                               logging.StreamHandler()])
# logger = logging.getLogger(__name__)

# # def run_job_in_thread(job):
# #     """
# #     Submit job to thread pool.
# #     Backpressure is automatically handled by ThreadPoolExecutor.
# #     """
# #     logger.info(f"Submitting job {job['id']} to thread pool")
# #     executor.submit(run_gem_analyzer_with_notifications, job)

# def run_job_in_thread(job):
#     logger.info(f"Submitting job {job['id']} to thread pool")
    
#     semaphore.acquire()

#     def wrapped():
#         try:
#             run_gem_analyzer_with_notifications(job)
#         finally:
#             semaphore.release()

#     executor.submit(wrapped)



# def get_scheduled_jobs():
#     """Get all active scheduled jobs from the database with organization info"""
#     try:
#         from database_config import engine
        
#         with engine.connect() as conn:
#             # Join with user table to get the organization_id
#             # result = conn.execute(text('''
#             # SELECT c.id, c.search_keyword, c.max_tenders, c.execution_time, sc.organization_id
#             # FROM gem_search_configurations c
#             # JOIN gem_org_search_capabilities sc ON c.created_by = sc.user_id
#             # WHERE c.is_active = true
#             # '''))

#             result = conn.execute(text('''
#             SELECT 
#                 c.id,
#                 c.search_keyword,
#                 c.max_tenders,
#                 c.execution_time,
#                 array_agg(sc.organization_id) AS organization_ids
#             FROM gem_search_configurations c
#             JOIN gem_org_search_capabilities sc 
#                 ON c.id = sc.search_config_id
#             WHERE c.is_active = true
#             GROUP BY c.id, c.search_keyword, c.max_tenders, c.execution_time;
#             '''))
            
#             jobs = []
#             for row in result:
#                 jobs.append({
#                     'id': row[0],
#                     'search_keyword': row[1],
#                     'max_tenders': row[2],
#                     'execution_time': row[3],
#                     'organization_id': row[4]  # Organization ID from the user table
#                 })
            
#             logger.info(f"Found {len(jobs)} scheduled jobs")
#             return jobs
#     except Exception as e:
#         logger.error(f"Error retrieving scheduled jobs: {e}")
#         return []

# def update_last_run(job_id):
#     """Update the last_run timestamp for a job"""
#     try:
#         from database_config import engine
        
#         with engine.connect() as conn:
#             now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
#             conn.execute(text('''
#             UPDATE gem_search_configurations
#             SET last_run = :last_run
#             WHERE id = :job_id
#             '''), {
#                 'last_run': now,
#                 'job_id': job_id
#             })
#             conn.commit()
            
#             logger.info(f"Updated last_run timestamp for job {job_id}")
#     except Exception as e:
#         logger.error(f"Error updating last_run timestamp: {e}")

# def parse_multiple_keywords(keyword_string):
#     if not keyword_string:
#         return [None]
    
#     import re
#     domain_pattern = r'(\w+)\s*\(([^)]+)\)'
#     domain_matches = re.findall(domain_pattern, keyword_string)
    
#     if domain_matches:
#         result = []
#         for search_term, keywords_str in domain_matches:
#             result.append({
#                 'term': search_term.strip(),
#                 'keywords': [k.strip() for k in keywords_str.split(',')]
#             })
#         return result
#     else:
#         # No domain format = no keywords at all
#         keywords = re.split(r'[,;|]|\sand\s', keyword_string)
#         return [kw.strip() for kw in keywords if kw.strip()]

# # def run_single_search(keyword, max_tenders, organization_id, search_number, total_searches):
# #     """Run a single search with the gem_nlp_api.py"""
# #     try:
# #         # Handle domain-specific format
# #         if isinstance(keyword, dict):
# #             search_term = keyword['term']
# #             domain_keywords = "|".join(keyword['keywords'])
# #             keyword_display = search_term
# #             cmd_args = [
# #                 "python", 
# #                 "gem_nlp_api.py", 
# #                 search_term,
# #                 str(max_tenders),
# #                 str(organization_id),
# #                 domain_keywords
# #             ]
# #         else:
# #             # Handle simple keyword format
# #             keyword_display = keyword if keyword else "none"
# #             cmd_args = [
# #                 "python", 
# #                 "gem_nlp_api.py", 
# #                 str(keyword_display),
# #                 str(max_tenders),
# #                 str(organization_id),
# #                 "NONE"
# #             ]
        
# #         logger.info(f"=== run_single_search ENTRY ===")
# #         logger.info(f"Search {search_number}/{total_searches}: Running search for keyword '{keyword_display}'")
        
# #         # Debug logging
# #         logger.info(f"DEBUG: Received parameters:")
# #         logger.info(f"  keyword='{keyword}' (type: {type(keyword)})")
# #         logger.info(f"  max_tenders={max_tenders} (type: {type(max_tenders)})")
# #         logger.info(f"  organization_id={organization_id} (type: {type(organization_id)})")
# #         logger.info(f"  search_number={search_number} (type: {type(search_number)})")
# #         logger.info(f"  total_searches={total_searches} (type: {type(total_searches)})")
        
# #         logger.info(f"DEBUG: Constructed command args: {cmd_args}")
# #         logger.info(f"DEBUG: Command as string: {' '.join(cmd_args)}")
        
# #         logger.info(f"About to execute subprocess...")
        
# #         # Run GEM scraper
# #         analyzer_process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# #         analyzer_stdout, analyzer_stderr = analyzer_process.communicate()
        
# #         logger.info(f"Subprocess completed with return code: {analyzer_process.returncode}")
        
# #         # Log analyzer output
# #         if analyzer_stdout:
# #             stdout_str = analyzer_stdout.decode()
# #             logger.info(f"Search {search_number} stdout: {stdout_str}")
# #         if analyzer_stderr:
# #             stderr_str = analyzer_stderr.decode()
# #             logger.error(f"Search {search_number} stderr: {stderr_str}")
        
# #         # Check if analyzer completed successfully
# #         if analyzer_process.returncode == 0:
# #             logger.info(f"Search {search_number} completed successfully for keyword '{keyword_display}'")
            
# #             # ADDED: Now also run CPPP and MahaTender scrapers
# #             logger.info(f"=== Additional scrapers for keyword '{keyword_display}' ===")
            
# #             # Run CPPP scraper
# #             logger.info(f"Running CPPP scraper...")
# #             cppp_cmd = [
# #                 "python", 
# #                 "cppp_tenders.py", 
# #                 str(keyword_display),
# #                 str(max_tenders),
# #                 str(organization_id)
# #             ]
# #             cppp_process = subprocess.Popen(cppp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# #             cppp_stdout, cppp_stderr = cppp_process.communicate()
            
# #             if cppp_stdout:
# #                 logger.info(f"CPPP stdout: {cppp_stdout.decode()}")
# #             if cppp_stderr:
# #                 logger.error(f"CPPP stderr: {cppp_stderr.decode()}")
            
# #             logger.info(f"CPPP scraper completed with return code: {cppp_process.returncode}")
            
# #             # Small delay
# #             time.sleep(5)
            
# #             # Run MahaTender scraper
# #             logger.info(f"Running MahaTender scraper...")
# #             maha_cmd = [
# #                 "python", 
# #                 "mahatenders.py", 
# #                 str(keyword_display),
# #                 str(max_tenders),
# #                 str(organization_id)
# #             ]
# #             maha_process = subprocess.Popen(maha_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# #             maha_stdout, maha_stderr = maha_process.communicate()
            
# #             if maha_stdout:
# #                 logger.info(f"MahaTender stdout: {maha_stdout.decode()}")
# #             if maha_stderr:
# #                 logger.error(f"MahaTender stderr: {maha_stderr.decode()}")
            
# #             logger.info(f"MahaTender scraper completed with return code: {maha_process.returncode}")
            
# #             # Overall success if GEM succeeded
# #             return True
# #         else:
# #             logger.error(f"Search {search_number} failed for keyword '{keyword_display}' (return code: {analyzer_process.returncode})")
            
# #             # Still try to run CPPP and MahaTender even if GEM failed
# #             logger.info(f"GEM scraper failed, but trying CPPP and MahaTender scrapers for keyword '{keyword_display}'")
            
# #             # Run CPPP scraper
# #             logger.info(f"Running CPPP scraper...")
# #             cppp_cmd = [
# #                 "python", 
# #                 "cppp_tenders.py", 
# #                 str(keyword_display),
# #                 str(max_tenders),
# #                 str(organization_id)
# #             ]
# #             cppp_process = subprocess.Popen(cppp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# #             cppp_stdout, cppp_stderr = cppp_process.communicate()
            
# #             if cppp_stdout:
# #                 logger.info(f"CPPP stdout: {cppp_stdout.decode()}")
# #             if cppp_stderr:
# #                 logger.error(f"CPPP stderr: {cppp_stderr.decode()}")
            
# #             logger.info(f"CPPP scraper completed with return code: {cppp_process.returncode}")
            
# #             # Small delay
# #             time.sleep(5)
            
# #             # Run MahaTender scraper
# #             logger.info(f"Running MahaTender scraper...")
# #             maha_cmd = [
# #                 "python", 
# #                 "mahatender.py", 
# #                 str(keyword_display),
# #                 str(max_tenders),
# #                 str(organization_id)
# #             ]
# #             maha_process = subprocess.Popen(maha_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# #             maha_stdout, maha_stderr = maha_process.communicate()
            
# #             if maha_stdout:
# #                 logger.info(f"MahaTender stdout: {maha_stdout.decode()}")
# #             if maha_stderr:
# #                 logger.error(f"MahaTender stderr: {maha_stderr.decode()}")
            
# #             logger.info(f"MahaTender scraper completed with return code: {maha_process.returncode}")
            
# #             return False
            
# #     except Exception as e:
# #         logger.error(f"Error running search {search_number} for keyword '{keyword}': {e}")
# #         import traceback
# #         logger.error(f"Full traceback: {traceback.format_exc()}")
# #         return False

# def run_single_search(keyword, max_tenders, organization_id, search_number, total_searches, search_config_id=None):
#     """Run a single search with the gem_nlp_api.py"""
#     try:
#         if isinstance(keyword, dict):
#             search_term = keyword['term']
#             domain_keywords = "|".join(keyword['keywords'])
#             keyword_display = search_term
#             cmd_args = [
#                 "python", 
#                 "gem_nlp_api.py", 
#                 search_term,
#                 str(max_tenders),
#                 str(organization_id),
#                 domain_keywords,
#                 str(search_config_id) if search_config_id else "None"
#             ]
#         else:
#             keyword_display = keyword if keyword else "none"
#             cmd_args = [
#                 "python", 
#                 "gem_nlp_api.py", 
#                 str(keyword_display),
#                 str(max_tenders),
#                 str(organization_id),
#                 "NONE",
#                 str(search_config_id) if search_config_id else "None"
#             ]
        
#         # Rest of the function remains the same...
#     except Exception as e:
#         logger.error(f"Error in run_single_search: {e}")
#         return False

# def run_multi_keyword_search_with_notifications(job):
#     """Run multiple keyword searches followed by a single email notification"""
#     try:
#         job_id = job['id']
#         search_keyword_string = job['search_keyword']
#         max_tenders = job['max_tenders']
#         organization_id = job['organization_id']
        
#         logger.info(f"=== DEBUG JOB START ===")
#         logger.info(f"job_id: {job_id}")
#         logger.info(f"search_keyword_string: '{search_keyword_string}' (type: {type(search_keyword_string)})")
#         logger.info(f"max_tenders: {max_tenders} (type: {type(max_tenders)})")
#         logger.info(f"organization_id: {organization_id} (type: {type(organization_id)})")
        
#         logger.info(f"Starting multi-keyword job {job_id} for organization {organization_id}")
        
#         # Parse keywords
#         keywords = parse_multiple_keywords(search_keyword_string)
#         total_searches = len(keywords)
        
#         logger.info(f"DEBUG: Parsed keywords: {keywords}")
#         logger.info(f"DEBUG: Keywords type: {type(keywords)}, individual types: {[type(k) for k in keywords]}")
#         logger.info(f"Job {job_id}: Will run {total_searches} searches with keywords: {keywords}")
        
#         # Track search results
#         successful_searches = 0
#         failed_searches = 0
        
#         # Run each search sequentially
#         for i, keyword in enumerate(keywords, 1):
#             logger.info(f"=== SEARCH {i}/{total_searches} START ===")
#             logger.info(f"About to call run_single_search with:")
#             logger.info(f"  keyword: '{keyword}' (type: {type(keyword)})")
#             logger.info(f"  max_tenders: {max_tenders} (type: {type(max_tenders)})")
#             logger.info(f"  organization_id: {organization_id} (type: {type(organization_id)})")
#             logger.info(f"  search_number: {i}")
#             logger.info(f"  total_searches: {total_searches}")
            
#             success = run_single_search(keyword, max_tenders, organization_id, i, total_searches)
            
#             if success:
#                 successful_searches += 1
#                 logger.info(f"=== SEARCH {i}/{total_searches} SUCCESS ===")
#             else:
#                 failed_searches += 1
#                 logger.info(f"=== SEARCH {i}/{total_searches} FAILED ===")
            
#             # Small delay between searches to avoid overwhelming the system
#             if i < total_searches:
#                 logger.info(f"Waiting 10 seconds before next search...")
#                 time.sleep(10)
        
#         logger.info(f"Job {job_id}: Completed {successful_searches} successful searches, {failed_searches} failed searches")
        
#         # Run email notifications if at least one search succeeded
#         if successful_searches > 0:
#             # Wait a bit for database writes to complete
#             logger.info(f"Job {job_id}: Waiting 5 seconds for database writes to complete...")
#             time.sleep(5)
            
#             logger.info(f"Job {job_id}: Running consolidated email notifications...")
#             email_cmd = f"python gem_email_notifier.py {organization_id} 4"
            
#             logger.info(f"Job {job_id}: Email command: {email_cmd}")
            
#             email_process = subprocess.Popen(email_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#             email_stdout, email_stderr = email_process.communicate()
            
#             # Log email output
#             if email_stdout:
#                 logger.info(f"Job {job_id} email stdout: {email_stdout.decode()}")
#             if email_stderr:
#                 logger.error(f"Job {job_id} email stderr: {email_stderr.decode()}")
            
#             # Check if email notifications completed successfully
#             if email_process.returncode == 0:
#                 logger.info(f"Job {job_id}: Email notifications completed successfully")
#             else:
#                 logger.error(f"Job {job_id}: Email notifications failed (return code: {email_process.returncode})")
#         else:
#             logger.warning(f"Job {job_id}: Skipping email notifications due to all searches failing")
        
#         # Update last run timestamp
#         update_last_run(job_id)
        
#         logger.info(f"Job {job_id}: Multi-keyword processing completed")
#         logger.info(f"=== DEBUG JOB END ===")
        
#     except Exception as e:
#         logger.error(f"Error running multi-keyword job {job['id']}: {e}")
#         import traceback
#         logger.error(f"Full traceback: {traceback.format_exc()}")

# def run_gem_analyzer_with_notifications(job):
#     """Enhanced function that handles both single and multiple keywords"""
#     search_keyword_string = job.get('search_keyword', '')
    
#     # Check if this looks like multiple keywords
#     if search_keyword_string and any(sep in search_keyword_string for sep in [',', ';', '|', ' and ']):
#         logger.info(f"Detected multiple keywords in job {job['id']}: '{search_keyword_string}'")
#         run_multi_keyword_search_with_notifications(job)
#     else:
#         # Single keyword - use the original single keyword logic directly
#         logger.info(f"Single keyword job {job['id']}: '{search_keyword_string}'")
#         # Call the actual implementation, not the wrapper
#         try:
#             job_id = job['id']
#             search_keyword = job['search_keyword'] if job['search_keyword'] else "none"
#             max_tenders = job['max_tenders']
#             organization_id = job['organization_id']
            
#             logger.info(f"Running single keyword job {job_id} for organization {organization_id} with keyword '{search_keyword}' and max_tenders={max_tenders}")
            
#             # Step 1: Run the GEM tender analyzer
#             analyzer_cmd = f"python gem_nlp_api.py {search_keyword} {max_tenders} {organization_id}"  
            
#             logger.info(f"Step 1: Running gem_nlp_api.py...")
#             analyzer_process = subprocess.Popen(analyzer_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#             analyzer_stdout, analyzer_stderr = analyzer_process.communicate()
            
#             # Log analyzer output
#             if analyzer_stdout:
#                 logger.info(f"Analyzer stdout: {analyzer_stdout.decode()}")
#             if analyzer_stderr:
#                 logger.error(f"Analyzer stderr: {analyzer_stderr.decode()}")
            
#             # Check if analyzer completed successfully
#             if analyzer_process.returncode == 0:
#                 logger.info(f"Step 1 completed successfully for job {job_id}")
#             else:
#                 logger.error(f"Analyzer failed for job {job_id} (return code: {analyzer_process.returncode})")
            
#             # ADDED: Step 1.5: Run CPPP scraper
#             logger.info(f"Step 1.5: Running CPPP scraper...")
#             cppp_cmd = f"python cppp_tenders.py {search_keyword} {max_tenders} {organization_id}"
#             cppp_process = subprocess.Popen(cppp_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#             cppp_stdout, cppp_stderr = cppp_process.communicate()
            
#             # Log CPPP output
#             if cppp_stdout:
#                 logger.info(f"CPPP stdout: {cppp_stdout.decode()}")
#             if cppp_stderr:
#                 logger.error(f"CPPP stderr: {cppp_stderr.decode()}")
            
#             logger.info(f"CPPP scraper completed with return code: {cppp_process.returncode}")
            
#             # Small delay
#             time.sleep(5)
            
#             # ADDED: Step 1.6: Run MahaTender scraper
#             logger.info(f"Step 1.6: Running MahaTender scraper...")
#             maha_cmd = f"python mahatender.py {search_keyword} {max_tenders} {organization_id}"
#             maha_process = subprocess.Popen(maha_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#             maha_stdout, maha_stderr = maha_process.communicate()
            
#             # Log MahaTender output
#             if maha_stdout:
#                 logger.info(f"MahaTender stdout: {maha_stdout.decode()}")
#             if maha_stderr:
#                 logger.error(f"MahaTender stderr: {maha_stderr.decode()}")
            
#             logger.info(f"MahaTender scraper completed with return code: {maha_process.returncode}")
            
#             # Only send email notifications if GEM analyzer succeeded (original logic)
#             if analyzer_process.returncode == 0:
#                 # Step 2: Run email notifications
#                 time.sleep(5)
                
#                 logger.info(f"Step 2: Running email notifications...")
#                 email_cmd = f"python gem_email_notifier.py {organization_id} 4"
                
#                 email_process = subprocess.Popen(email_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#                 email_stdout, email_stderr = email_process.communicate()
                
#                 # Log email output
#                 if email_stdout:
#                     logger.info(f"Email stdout: {email_stdout.decode()}")
#                 if email_stderr:
#                     logger.error(f"Email stderr: {email_stderr.decode()}")
                
#                 # Check if email notifications completed successfully
#                 if email_process.returncode == 0:
#                     logger.info(f"Step 2 completed successfully for job {job_id}")
#                 else:
#                     logger.error(f"Email notifications failed for job {job_id} (return code: {email_process.returncode})")
#             else:
#                 logger.error(f"GEM analyzer failed for job {job_id} (return code: {analyzer_process.returncode}). Skipping email notifications.")
            
#             # Update last run timestamp
#             update_last_run(job_id)
            
#             logger.info(f"Job {job_id} processing completed")
        
#         except Exception as e:
#             logger.error(f"Error running job {job['id']}: {e}")

# def run_gem_analyzer(job):
#     """Original function - kept for backwards compatibility, now calls the enhanced version"""
#     run_gem_analyzer_with_notifications(job)

# def schedule_jobs():
#     """Schedule all jobs from the database"""
#     # Clear existing jobs
#     schedule.clear()
    
#     # Get jobs from database
#     jobs = get_scheduled_jobs()
    
#     # Schedule each job
#     for job in jobs:
#         execution_time = job['execution_time']
#         # Schedule job to run at specified time with enhanced multi-keyword support
#         # schedule.every().day.at(execution_time).do(run_gem_analyzer_with_notifications, job)

#         schedule.every().day.at(execution_time).do(run_job_in_thread, job)
        
#         # Log scheduling info
#         keyword_info = job['search_keyword'] if job['search_keyword'] else 'All tenders'
#         if job['search_keyword'] and any(sep in job['search_keyword'] for sep in [',', ';', '|', ' and ']):
#             keyword_info += " (multi-keyword)"
        
#         logger.info(f"Scheduled job {job['id']} to run at {execution_time} - Keywords: {keyword_info}")
    
#     logger.info(f"Scheduled {len(jobs)} jobs with multi-keyword support")

# def refresh_schedule():
#     """Function to periodically refresh the schedule from the database"""
#     logger.info("Refreshing job schedule")
#     schedule_jobs()

# def run_scheduler():
#     """Main function to run the scheduler"""
#     logger.info("Starting GEM Tender Scheduler with Multi-Keyword Support and Email Notifications")
    
#     # Initial schedule setup
#     schedule_jobs()
    
#     # Schedule a job to refresh the schedule every hour
#     schedule.every().hour.do(refresh_schedule)
    
#     # Run pending jobs continuously
#     while True:
#         schedule.run_pending()
#         time.sleep(60)  # Check every minute

# def test_job(organization_id, search_keyword=None, max_tenders=30):
#     """Test function to run a job manually - now supports multiple keywords"""
#     test_job_data = {
#         'id': 'TEST',
#         'search_keyword': search_keyword,
#         'max_tenders': max_tenders,
#         'organization_id': organization_id
#     }
    
#     logger.info(f"Running test job for organization {organization_id}")
#     if search_keyword and any(sep in search_keyword for sep in [',', ';', '|', ' and ']):
#         logger.info(f"Test job will use multi-keyword search: {search_keyword}")
    
#     run_gem_analyzer_with_notifications(test_job_data)

# if __name__ == "__main__":
#     try:
#         # Check if this is a test run
#         if len(sys.argv) > 1 and sys.argv[1] == "test":
#             # Test mode: python gem_scheduler.py test <org_id> [keyword] [max_tenders]
#             if len(sys.argv) < 3:
#                 print("Usage for test mode: python gem_scheduler.py test <organization_id> [keyword] [max_tenders]")
#                 print("Examples:")
#                 print("  python gem_scheduler.py test 123 pump 30")
#                 print("  python gem_scheduler.py test 123 'pump,valve,motor' 25")
#                 print("  python gem_scheduler.py test 123 'pump;valve;flow control' 30")
#                 sys.exit(1)
            
#             organization_id = int(sys.argv[2])
#             search_keyword = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].lower() != "none" else None
#             max_tenders = int(sys.argv[4]) if len(sys.argv) > 4 else 30
            
#             test_job(organization_id, search_keyword, max_tenders)
#         else:
#             # Normal scheduler mode
#             run_scheduler()
#     except KeyboardInterrupt:
#         logger.info("Scheduler stopped by user")
#     except Exception as e:
#         logger.error(f"Scheduler error: {e}")
        



import os
import os
import time
import datetime
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import schedule
from sqlalchemy import text
import gem_log_metrics_ingest

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("gem_scheduler.log"),
                              logging.StreamHandler()])
logger = logging.getLogger(__name__)

MAX_WORKERS = int(os.getenv("GEM_SCHEDULER_MAX_WORKERS", "4"))
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

def _run_job_safe(job):
    """Run a job with defensive error handling for threaded execution."""
    try:
        run_gem_analyzer_with_notifications(job)
    except Exception:
        logger.error(f"Unhandled exception while running job {job.get('id')}", exc_info=True)

def run_jobs_for_time(execution_time, jobs):
    """Run all jobs for a given execution time, in parallel when >1."""
    if not jobs:
        return

    if len(jobs) == 1:
        job_id = jobs[0].get('id')
        logger.info(f"Running single job {job_id} for time {execution_time}")
        _run_job_safe(jobs[0])
        return

    logger.info(f"Running {len(jobs)} jobs in parallel for time {execution_time}")
    futures = [executor.submit(_run_job_safe, job) for job in jobs]
    for future in as_completed(futures):
        try:
            future.result()
        except Exception:
            logger.error("Unhandled exception in job future", exc_info=True)

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

def run_single_search(keyword, max_tenders, organization_id, search_number, total_searches, job_id):
    """Run a single search with the gem_nlp_api.py and pass the job_id as search_config_id"""
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
                domain_keywords,
                str(job_id)  # Pass job_id as search_config_id
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
                "NONE",
                str(job_id)  # Pass job_id as search_config_id
            ]
        
        logger.info(f"=== run_single_search ENTRY ===")
        logger.info(f"Search {search_number}/{total_searches}: Running search for keyword '{keyword_display}' with config ID {job_id}")
        
        # Debug logging
        logger.info(f"DEBUG: Received parameters:")
        logger.info(f"  keyword='{keyword}' (type: {type(keyword)})")
        logger.info(f"  max_tenders={max_tenders} (type: {type(max_tenders)})")
        logger.info(f"  organization_id={organization_id} (type: {type(organization_id)})")
        logger.info(f"  search_number={search_number} (type: {type(search_number)})")
        logger.info(f"  total_searches={total_searches} (type: {type(total_searches)})")
        logger.info(f"  job_id={job_id} (type: {type(job_id)})")
        
        logger.info(f"DEBUG: Constructed command args: {cmd_args}")
        logger.info(f"DEBUG: Command as string: {' '.join(cmd_args)}")
        
        logger.info(f"About to execute subprocess...")
        
        # Run GEM scraper
        analyzer_process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        analyzer_stdout, analyzer_stderr = analyzer_process.communicate()
        
        logger.info(f"Subprocess completed with return code: {analyzer_process.returncode}")

        gem_log_metrics_ingest.main()
        
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
        
        # Run each search sequentially, passing the job_id to each search
        for i, keyword in enumerate(keywords, 1):
            logger.info(f"=== SEARCH {i}/{total_searches} START ===")
            logger.info(f"About to call run_single_search with:")
            logger.info(f"  keyword: '{keyword}' (type: {type(keyword)})")
            logger.info(f"  max_tenders: {max_tenders} (type: {type(max_tenders)})")
            logger.info(f"  organization_id: {organization_id} (type: {type(organization_id)})")
            logger.info(f"  search_number: {i}")
            logger.info(f"  total_searches: {total_searches}")
            logger.info(f"  job_id: {job_id}")
            
            # Pass job_id to run_single_search
            success = run_single_search(keyword, max_tenders, organization_id, i, total_searches, job_id)
            
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
            
            logger.info(f"Job {job_id}: Running consolidated email notifications for config {job_id}...")
            # UPDATED: Pass both organization_id and search_config_id (job_id) to email notifier
            email_cmd = f"python gem_email_notifier.py {organization_id} {job_id} 4"
            
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
        try:
            job_id = job['id']
            search_keyword = job['search_keyword'] if job['search_keyword'] else "none"
            max_tenders = job['max_tenders']
            organization_id = job['organization_id']
            
            logger.info(f"Running single keyword job {job_id} for organization {organization_id} with keyword '{search_keyword}' and max_tenders={max_tenders}")
            
            # Step 1: Run the GEM tender analyzer - UPDATED to include job_id as search_config_id
            analyzer_cmd = f"python gem_nlp_api.py {search_keyword} {max_tenders} {organization_id} NONE {job_id}"
            
            logger.info(f"Step 1: Running gem_nlp_api.py with config ID {job_id}...")
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
            
            # Only send email notifications if GEM analyzer succeeded
            if analyzer_process.returncode == 0:
                # Step 2: Run email notifications with config ID
                time.sleep(5)
                
                logger.info(f"Step 2: Running email notifications for config {job_id}...")
                # UPDATED: Pass both organization_id and job_id to email notifier
                email_cmd = f"python gem_email_notifier.py {organization_id} {job_id} 4"
                
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
    
    # Group jobs by execution time so same-time jobs can run in parallel
    jobs_by_time = {}
    for job in jobs:
        execution_time = job['execution_time']
        jobs_by_time.setdefault(execution_time, []).append(job)

    # Schedule each time slot
    for execution_time, time_jobs in jobs_by_time.items():
        schedule.every().day.at(execution_time).do(run_jobs_for_time, execution_time, time_jobs)

        # Log scheduling info
        for job in time_jobs:
            keyword_info = job['search_keyword'] if job['search_keyword'] else 'All tenders'
            if job['search_keyword'] and any(sep in job['search_keyword'] for sep in [',', ';', '|', ' and ']):
                keyword_info += " (multi-keyword)"
            logger.info(f"Scheduled job {job['id']} to run at {execution_time} - Keywords: {keyword_info}")

        if len(time_jobs) > 1:
            logger.info(f"Time {execution_time}: {len(time_jobs)} jobs will run in parallel")

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
