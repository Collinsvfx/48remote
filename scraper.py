import re
import json
from datetime import datetime, timedelta
import time
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Page, Browser
# --- Imports for Direct API Scraping (Up2Staff) ---
import requests
from bs4 import BeautifulSoup

# --- Configuration ---
JOB_URL_CONFIGS = [
    {"url": "https://dribbble.com/jobs?keyword=product+designer&location=", "type": "dribbble"},
    {"url": "https://dribbble.com/jobs?keyword=ui%2Fux+designer&location=", "type": "dribbble"},
    {"url": "https://www.remoterocketship.com/jobs/ui-ux-designer/?page=1&sort=DateAdded&jobTitle=UI%2FUX+Designer", "type": "remoterocketship"},
    {"url": "https://www.remoterocketship.com/?page=1&sort=DateAdded&jobTitle=Product+Designer&locations=Worldwide", "type": "remoterocketship"}, # Added by user request for Product Designer
    {"url": "https://builtin.com/jobs/remote?search=ui%2Fux+designer&country=USA&allLocations=true", "type": "builtin"}, 
    {"url": "https://up2staff.com/", "type": "up2staff_api"}, 
    {"url": "https://weworkremotely.com/remote-jobs/search?term=ui+ux+designer", "type": "weworkremotely"},
    {"url": "https://justremote.co/remote-ui-ux-jobs", "type": "justremote"},
    {"url": "https://remote4africa.com/jobs/search?q=ui%2Fux+designer", "type": "remote4africa"},
    {"url": "https://www.realworkfromanywhere.com/remote-product-designer-jobs", "type": "realworkfromanywhere"},
    {"url": "https://productjobsanywhere.com/jobs/product-designers/?utm_source=chatgpt.com", "type": "productjobsanywhere"},
]

TIME_THRESHOLD = datetime.now() - timedelta(hours=48)

# --- Helper Function for Time Parsing ---
def parse_job_time(time_str: str) -> Optional[datetime]:
    """Parses various time formats (relative and absolute) into a datetime object."""
    time_str = time_str.lower().strip()
    if 'reposted' in time_str:
        time_str = time_str.replace('reposted', '', 1).strip()

    # Relative time: "X hours ago", "2d ago", etc.
    relative_match = re.search(r'(\d+)\s*(minute|hour|day|week)s?\s*ago', time_str)
    if relative_match:
        value = int(relative_match.group(1))
        unit = relative_match.group(2)
        now = datetime.now()
        if 'minute' in unit:
            return now - timedelta(minutes=value)
        elif 'hour' in unit:
            return now - timedelta(hours=value)
        elif 'day' in unit:
            return now - timedelta(days=value)
        elif 'week' in unit:
            return now - timedelta(weeks=value)

    shorthand_match = re.search(r'(\d+)\s*(m|h|d|w)\s*ago', time_str)
    if shorthand_match:
        value = int(shorthand_match.group(1))
        unit = shorthand_match.group(2)
        now = datetime.now()
        if unit == 'm':
            return now - timedelta(minutes=value)
        elif unit == 'h':
            return now - timedelta(hours=value)
        elif unit == 'd':
            return now - timedelta(days=value)
        elif unit == 'w':
            return now - timedelta(weeks=value)

    # Absolute date: 10/03/2025, 2025-10-03, etc.
    absolute_date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', time_str)
    if absolute_date_match:
        date_part = absolute_date_match.group(1).replace('/', '-')
        formats = ['%Y-%m-%d', '%m-%d-%Y', '%y-%m-%d', '%m-%d-%y']
        for fmt in formats:
            try:
                return datetime.strptime(date_part, fmt)
            except ValueError:
                continue

    # Month Day: "Aug 08"
    month_day_match = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}', time_str, re.IGNORECASE)
    if month_day_match:
        try:
            date_part_str = month_day_match.group(0).capitalize()
            posted_date = datetime.strptime(date_part_str, '%b %d').replace(year=datetime.now().year)
            if posted_date > datetime.now():
                posted_date = posted_date.replace(year=datetime.now().year - 1)
            return posted_date
        except ValueError:
            pass

    return None

# --- SCRAPER FUNCTIONS ---

def scrape_productjobsanywhere_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from Product Jobs Anywhere: {url}")
    jobs = []
    BASE_URL = "https://productjobsanywhere.com"
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'div[class*="relative flex flex-col justify-start p-4"]'
        WORLDWIDE_FILTER = 'div.flex.text-base:has-text("Worldwide")'
        try:
            page.wait_for_selector(f"{JOB_WRAPPER_SELECTOR}:has({WORLDWIDE_FILTER})", timeout=30000) 
            print("  [Info] Product Jobs Anywhere list elements (Worldwide filtered) are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for Product Jobs Anywhere worldwide list items.")
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        if not job_wrappers:
            print("  [Warning] Playwright could not find Product Jobs Anywhere job card wrappers.")
            return jobs
        print(f"  [Info] Playwright found {len(job_wrappers)} Product Jobs Anywhere job cards to process (will filter for 'Worldwide').")
        jobs_processed = 0
        for wrapper in job_wrappers:
            try:
                location_locator = wrapper.locator(WORLDWIDE_FILTER)
                if not location_locator.is_visible():
                    continue
                location = location_locator.inner_text().strip().replace('🌎', '').strip()
                time_tag_locator = wrapper.locator('span.text-sm.text-gray-400').first
                time_tag_text = time_tag_locator.inner_text().strip()
                posted_datetime = parse_job_time(time_tag_text) 
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                title_link_locator = wrapper.locator('a.absolute.inset-0.z-10').first
                job_url = title_link_locator.get_attribute('href')
                title = wrapper.locator('h3').first.inner_text().strip()
                if not job_url:
                    continue
                company_locator = wrapper.locator('a.flex.items-center span.text-lg').first
                company = company_locator.inner_text().strip()
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'Product Jobs Anywhere'
                })
                jobs_processed += 1
            except Exception as e:
                continue
        print(f"Finished processing Product Jobs Anywhere URL: {url} (Found {jobs_processed} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing Product Jobs Anywhere {url}: {e}")
        return jobs

def scrape_dribbble_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from Dribbble: {url}")
    jobs = []
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'li.job-list-item'
        try:
            page.wait_for_selector(JOB_WRAPPER_SELECTOR, timeout=30000) 
            print("  [Info] Dribbble list elements are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for Dribbble list items.")
            return jobs
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        if not job_wrappers:
            print("  [Warning] Playwright could not find Dribbble job card wrappers.")
            return jobs
        print(f"  [Info] Playwright found {len(job_wrappers)} Dribbble job cards to process.")
        for wrapper in job_wrappers:
            try:
                time_tag_text = wrapper.locator('div.posted-on').first.inner_text().strip()
                posted_datetime = parse_job_time(time_tag_text) 
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                job_link_locator = wrapper.locator('a.job-link').first
                job_url = job_link_locator.get_attribute('href')
                job_url = f"https://dribbble.com{job_url}" if job_url and job_url.startswith('/') else job_url
                if not job_url:
                    continue
                details_container = wrapper.locator('div.job-details-container').first
                title = details_container.locator('h4.job-board-job-title').inner_text().strip()
                company = details_container.locator('span.job-board-job-company').inner_text().strip()
                location = details_container.locator('div.location-container').inner_text().strip()
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'Dribbble'
                })
            except Exception as e:
                continue
        print(f"Finished processing Dribbble URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing Dribbble {url}: {e}")
        return jobs

def scrape_remote_rocketship_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from Remote Rocketship: {url}")
    jobs = []
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'div[role="button"][tabindex="0"]'
        CRITICAL_CONTENT_SELECTOR = 'h3.text-lg a'
        try:
            page.wait_for_selector(CRITICAL_CONTENT_SELECTOR, timeout=60000) 
            print("  [Info] Remote Rocketship list elements are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for Remote Rocketship list items.")
            return jobs
        time.sleep(3) 
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        if not job_wrappers:
            print("  [Warning] Playwright could not find Remote Rocketship job card wrappers.")
            return jobs
        print(f"  [Info] Playwright found {len(job_wrappers)} Remote Rocketship job cards to process.")
        for wrapper in job_wrappers:
            try:
                time_tag_locator = wrapper.locator('p.hidden.sm\\:block').first
                if not time_tag_locator.is_visible():
                    time_tag_locator = wrapper.locator('p.sm\\:hidden').first
                time_tag_text = time_tag_locator.inner_text().strip()
                
                title_link_locator_temp = wrapper.locator('h3.text-lg a').first
                temp_title = title_link_locator_temp.inner_text().strip() if title_link_locator_temp.is_visible() else "Unknown Title"
                
                posted_datetime = parse_job_time(time_tag_text) 

                # --- DIAGNOSTIC LOGGING ---
                if posted_datetime:
                    is_recent = posted_datetime > TIME_THRESHOLD
                    print(f"  [DEBUG] Job: {temp_title}, Time Found: '{time_tag_text}', Parsed Date: {posted_datetime.strftime('%Y-%m-%d %H:%M:%S')}, Recent: {is_recent}")
                else:
                    print(f"  [DEBUG] Job: {temp_title}, Time Found: '{time_tag_text}', Parsed Date: FAILED, Recent: False (Skipping)")
                # --- END DIAGNOSTIC LOGGING ---

                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                
                title = temp_title
                job_url = title_link_locator_temp.get_attribute('href')
                job_url = f"https://www.remoterocketship.com{job_url}" if job_url and job_url.startswith('/') else job_url
                if not job_url:
                    continue
                company_locator = wrapper.locator('h4 a').first
                company = company_locator.inner_text().strip()
                location_elements = wrapper.locator('a[href*="/state/"] p').all()
                location_elements_text = [elem.inner_text().strip() for elem in location_elements]
                more_states_locator = wrapper.locator('div p[class*="text-xs sm:text-sm font-semibold text-primary"]:has-text("+")').first
                if more_states_locator.is_visible():
                    location_elements_text.append(more_states_locator.inner_text().strip())
                location = ", ".join(location_elements_text)
                location = re.sub(r'[\U0001F1E6-\U0001F1FF]+', '', location).strip()
                location = location.replace('– Remote', '').replace('Remote', '').replace('+', '').strip()
                location = re.sub(r'\s{2,}', ' ', location).strip(' ,')
                if not location:
                    location = "Remote/Global"
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'Remote Rocketship'
                })
            except Exception as e:
                # print(f"  [DEBUG] Minor error during job extraction: {e}") # Keep silent to avoid clutter unless debugging
                continue
        print(f"Finished processing Remote Rocketship URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing Remote Rocketship {url}: {e}")
        return jobs

def scrape_builtin_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from BuiltIn: {url}")
    jobs = []
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'div[data-id="job-card"]'
        try:
            page.wait_for_selector(JOB_WRAPPER_SELECTOR, timeout=60000) 
            print("  [Info] BuiltIn list elements are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for BuiltIn job cards.")
            return jobs
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3) 
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        if not job_wrappers:
            print("  [Warning] Playwright could not find BuiltIn job card wrappers.")
            return jobs
        print(f"  [Info] Playwright found {len(job_wrappers)} BuiltIn job cards to process.")
        for wrapper in job_wrappers:
            try:
                time_tag_locator = wrapper.locator('span:has(i.fa-regular.fa-clock)').first
                time_tag_text = time_tag_locator.inner_text().strip()
                posted_datetime = parse_job_time(time_tag_text) 
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                title_link_locator = wrapper.locator('h2 a.card-alias-after-overlay').first
                title = title_link_locator.inner_text().strip()
                job_url = title_link_locator.get_attribute('href')
                job_url = f"https://builtin.com{job_url}" if job_url and job_url.startswith('/') else job_url
                if not job_url:
                    continue
                company_locator = wrapper.locator('a[data-id="company-title"] span').first
                company = company_locator.inner_text().strip()
                location_locator = wrapper.locator('div.d-flex.align-items-start.gap-sm:has(i.fa-regular.fa-location-dot) span').last
                location = location_locator.inner_text().strip()
                remote_status_locator = wrapper.locator('div.d-flex.align-items-start.gap-sm:has(i.fa-regular.fa-house-building) span').first
                if remote_status_locator.is_visible():
                    remote_status = remote_status_locator.inner_text().strip()
                    location = f"{location} - {remote_status}"
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'BuiltIn'
                })
            except Exception as e:
                continue
        print(f"Finished processing BuiltIn URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing BuiltIn {url}: {e}")
        return jobs

def scrape_weworkremotely_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from WeWorkRemotely: {url}")
    jobs = []
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'li.feature'
        try:
            page.wait_for_selector(JOB_WRAPPER_SELECTOR, timeout=30000) 
            print("  [Info] WeWorkRemotely list elements are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for WeWorkRemotely list items.")
            return jobs
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        print(f"  [Info] Playwright found {len(job_wrappers)} WeWorkRemotely job cards to process.")
        for wrapper in job_wrappers:
            try:
                link_locator = wrapper.locator('a[href*="/remote-jobs/"]').first
                job_url = link_locator.get_attribute('href')
                job_url = f"https://weworkremotely.com{job_url}" if job_url and job_url.startswith('/') else job_url
                if not job_url:
                    continue
                title = wrapper.locator('span.title').first.inner_text().strip()
                company = wrapper.locator('span.company').first.inner_text().strip()
                time_tag_locator = wrapper.locator('span.date').first
                time_tag_text = time_tag_locator.inner_text().strip()
                posted_datetime = parse_job_time(time_tag_text) 
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                location = "Remote/Global" 
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'WeWorkRemotely'
                })
            except Exception as e:
                continue
        print(f"Finished processing WeWorkRemotely URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing WeWorkRemotely {url}: {e}")
        return jobs

def scrape_justremote_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from Just Remote: {url}")
    jobs = []
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'div[class*="job-card-wrapper"]' 
        try:
            page.wait_for_selector(JOB_WRAPPER_SELECTOR, timeout=60000) 
            print("  [Info] Just Remote list elements are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for Just Remote list items.")
            return jobs
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        if not job_wrappers:
            print("  [Warning] Playwright could not find Just Remote job card wrappers.")
            return jobs
        print(f"  [Info] Playwright found {len(job_wrappers)} Just Remote job cards to process.")
        for wrapper in job_wrappers:
            try:
                title_link_locator = wrapper.locator('a[class*="job-link"]').first
                job_url = title_link_locator.get_attribute('href')
                job_url = f"https://justremote.co{job_url}" if job_url and job_url.startswith('/') else job_url
                if not job_url:
                    continue
                title = title_link_locator.inner_text().strip()
                company_locator = wrapper.locator('div[class*="company-name"]').first
                company = company_locator.inner_text().strip()
                location_locator = wrapper.locator('span[class*="location-text"]').first
                location = location_locator.inner_text().strip() if location_locator.is_visible() else "Remote/Global"
                time_tag_locator = wrapper.locator('span[class*="date-text"]').first
                time_tag_text = time_tag_locator.inner_text().strip()
                posted_datetime = parse_job_time(time_tag_text) 
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'Just Remote'
                })
            except Exception as e:
                continue
        print(f"Finished processing Just Remote URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing Just Remote {url}: {e}")
        return jobs

def scrape_remote4africa_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from Remote4Africa: {url}")
    jobs = []
    BASE_URL = "https://remote4africa.com"
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'div[class*="MuiStack-root"][class*="mui-nguhj9"]' 
        try:
            page.wait_for_selector(JOB_WRAPPER_SELECTOR, timeout=30000) 
            print("  [Info] Remote4Africa list elements are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for Remote4Africa list items.")
            return jobs
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        if not job_wrappers:
            print("  [Warning] Playwright could not find Remote4Africa job card wrappers.")
            return jobs
        print(f"  [Info] Playwright found {len(job_wrappers)} Remote4Africa job cards to process.")
        for wrapper in job_wrappers:
            try:
                title_link_locator = wrapper.locator('a[class*="MuiLink-root"]').first
                job_url = title_link_locator.get_attribute('href')
                job_url = f"{BASE_URL}{job_url}" if job_url and job_url.startswith('/') else job_url
                if not job_url:
                    continue
                title = title_link_locator.inner_text().strip()
                company_locator = wrapper.locator('div[class*="mui-1tik93c"] p[class*="MuiTypography-body1"][class*="MuiTypography-gutterBottom"]').first
                company = company_locator.inner_text().strip()
                location = "Remote/Africa"
                time_tag_locator = wrapper.locator('div[class*="mui-15fepi"] p[class*="MuiTypography-body2"]').first
                time_tag_text = time_tag_locator.inner_text().strip()
                posted_datetime = parse_job_time(time_tag_text) 
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'Remote4Africa'
                })
            except Exception as e:
                continue
        print(f"Finished processing Remote4Africa URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing Remote4Africa {url}: {e}")
        return jobs

def scrape_realworkfromanywhere_jobs(page: Page, url: str) -> List[Dict[str, Any]]:
    print(f"Fetching jobs from Real Work From Anywhere: {url}")
    jobs = []
    BASE_URL = "https://www.realworkfromanywhere.com"
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000) 
        JOB_WRAPPER_SELECTOR = 'div[class*="flex flex-col m-auto ring-1"][style*="background-color"]'
        try:
            page.wait_for_selector(JOB_WRAPPER_SELECTOR, timeout=30000) 
            print("  [Info] Real Work From Anywhere list elements are visible.")
        except PlaywrightTimeoutError:
            print("  [Warning] Timeout exceeded waiting for Real Work From Anywhere list items.")
            return jobs
        job_wrappers = page.locator(JOB_WRAPPER_SELECTOR).all()
        if not job_wrappers:
            print("  [Warning] Playwright could not find Real Work From Anywhere job card wrappers.")
            return jobs
        print(f"  [Info] Playwright found {len(job_wrappers)} Real Work From Anywhere job cards to process.")
        for wrapper in job_wrappers:
            try:
                title_link_locator = wrapper.locator('a[href*="/jobs/"]').first
                job_url = title_link_locator.get_attribute('href')
                job_url = f"{BASE_URL}{job_url}" if job_url and job_url.startswith('/jobs/') else job_url
                if not job_url:
                    continue
                title = wrapper.locator('h3').first.inner_text().strip()
                company_locator = wrapper.locator('div[class*="sm:-ml-10"] div.flex.flex-wrap.items-center.gap-1.text-sm').first
                company = company_locator.inner_text().strip()
                location_locator = wrapper.locator('div.flex.items-center.gap-1\\.5 span.text-sm').first
                location = location_locator.inner_text().strip() if location_locator.is_visible() else "Remote/Worldwide"
                time_tag_locator = wrapper.locator('div.hidden.sm\\:block.text-sm').first
                if not time_tag_locator.is_visible():
                    time_tag_locator = wrapper.locator('div.sm\\:hidden.text-sm.text-right').first
                time_tag_text = time_tag_locator.inner_text().strip()
                posted_datetime = parse_job_time(time_tag_text) 
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'Real Work From Anywhere'
                })
            except Exception as e:
                continue
        print(f"Finished processing Real Work From Anywhere URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An error occurred while processing Real Work From Anywhere {url}: {e}")
        return jobs

def scrape_up2staff_api_jobs(url: str) -> List[Dict[str, Any]]:
    """
    Scrapes Up2Staff by making a direct POST request to their internal API endpoint 
    to retrieve job listings as HTML fragments, then parses the HTML with BeautifulSoup.
    """
    print(f"Fetching jobs from Up2Staff (via Direct API): {url}")
    jobs = []
    API_URL = "https://up2staff.com/admin-ajax.php"
    SKIP_PATHS = ['/cart', '/checkout', '/jobs-dashboard', '/myaccount', '/maltings', '/post-a-job']
    BASE_URL = url.strip('/') 
    PAYLOAD = {
        'action': 'get_listings',
        'key': 'ui/ux designer', 
        'category': 'design',     
        'job_type': 'all',        
        'paged': 1,               
    }
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': url,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
    }
    try:
        response = requests.post(API_URL, data=PAYLOAD, headers=HEADERS, timeout=15)
        response.raise_for_status() 
        html_content = ""
        try:
            data = response.json()
            if isinstance(data, dict) and 'html' in data:
                html_content = data['html']
                print("  [Info] API response successfully parsed JSON containing HTML.")
            else:
                print("  [Warning] API response was valid JSON but did not contain the expected 'html' field.")
                return jobs
        except json.JSONDecodeError:
            html_content = response.text
            print("  [Info] API response was raw HTML content.")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        JOB_WRAPPER_SELECTOR = 'li.job_listing'
        job_wrappers = soup.select(JOB_WRAPPER_SELECTOR)
        
        if not job_wrappers:
            # Fallback selectors if the primary one fails
            job_wrappers = soup.select('li:has(a), div.job-item, div.job-listing')
            
        if not job_wrappers:
            print("  [Warning] BeautifulSoup could not find Up2Staff job card wrappers.")
            return jobs
            
        print(f"  [Info] BeautifulSoup found {len(job_wrappers)} Up2Staff job cards to process.")
        
        for i, wrapper in enumerate(job_wrappers):
            title = 'N/A'
            job_url = 'N/A'
            time_tag_text = 'N/A'
            try:
                title_link = None
                # Try to find the title link within common header tags
                for tag_name in ['h3', 'h4', 'h5']:
                    header = wrapper.find(tag_name)
                    if header:
                        title_link = header.find('a', href=True)
                        if title_link:
                            break
                # If title link wasn't found in a header, look for any top-level link
                if not title_link:
                     title_link = wrapper.find('a', href=True) 

                if not title_link:
                    continue

                job_url = title_link['href']
                # Skip navigation links
                if any(path in job_url for path in SKIP_PATHS):
                    continue
                # Skip links back to the base domain index if not a job post
                if job_url.strip('/') == BASE_URL:
                    continue
                
                title = title_link.get_text(strip=True) 
                
                # Try to find the time tag using common classes or keywords
                time_tag_elem = wrapper.find(lambda tag: tag.name in ['div', 'span', 'p', 'time'] and any(c in tag.get('class', []) for c in ['date', 'posted', 'time', 'wp-job-manager-date']))
                if time_tag_elem:
                    time_tag_text = time_tag_elem.get_text(strip=True)
                else:
                    # Fallback: search all elements for relative time keywords
                    date_elements = wrapper.find_all(['span', 'div', 'p'])
                    for elem in date_elements:
                        text = elem.get_text(strip=True)
                        if any(s in text.lower() for s in ['hour', 'day', 'week', 'minute', 'ago']) or re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text):
                            time_tag_text = text
                            break
                            
                posted_datetime = parse_job_time(time_tag_text)
                if not posted_datetime or posted_datetime <= TIME_THRESHOLD:
                    continue
                
                company = 'N/A'
                location = 'Remote/Global'
                
                # Find company
                company_tag = wrapper.find(lambda tag: tag.name in ['div', 'span', 'p'] and any(c in tag.get('class', ['']) for c in ['company', 'employer', 'job-company']))
                if company_tag:
                    company = company_tag.get_text(strip=True)
                
                # Find location
                location_tag = wrapper.find(lambda tag: tag.name in ['div', 'span', 'p'] and any(c in tag.get('class', ['']) for c in ['location', 'job-location']))
                if location_tag:
                    location = location_tag.get_text(strip=True)
                    
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'posted_ago': time_tag_text,
                    'posted_datetime': posted_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': job_url,
                    'source': 'Up2Staff'
                })
            except Exception as e:
                continue
        print(f"Finished processing Up2Staff API URL: {url} (Found {len(jobs)} new jobs)")
        return jobs
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] An HTTP error occurred during Up2Staff API call: {e}")
        return jobs
    except Exception as e:
        print(f"  [ERROR] An unexpected error occurred while processing Up2Staff API: {e}")
        return jobs

# --- Main Execution Function ---
def scrape_all_jobs():
    all_jobs = []
    print(f"--- Starting Multi-Site Job Scraper (Playwright/Requests) ---")
    print(f"Filtering for jobs posted AFTER: {TIME_THRESHOLD.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        with sync_playwright() as p:
            browser_required_types = ["dribbble", "remoterocketship", "builtin", "weworkremotely", "justremote", "remote4africa", "realworkfromanywhere", "productjobsanywhere"]
            needs_browser = any(config['type'] in browser_required_types for config in JOB_URL_CONFIGS)
            browser: Optional[Browser] = None
            if needs_browser:
                # Launching with headless=True for background execution
                browser = p.chromium.launch(headless=True) 

            for config in JOB_URL_CONFIGS:
                url = config['url']
                scraper_type = config['type']
                page = None
                jobs = []

                # Initialize Playwright page for browser-based scrapers
                if scraper_type in browser_required_types:
                    # Relaunch browser if it was closed or not initialized (shouldn't happen here, but safe)
                    if not browser: 
                        browser = p.chromium.launch(headless=True)
                    page = browser.new_page(
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        viewport={'width': 1280, 'height': 960}
                    )

                # Call the appropriate scraping function
                if scraper_type == "dribbble":
                    jobs = scrape_dribbble_jobs(page, url)
                elif scraper_type == "remoterocketship":
                    jobs = scrape_remote_rocketship_jobs(page, url)
                elif scraper_type == "builtin":
                    jobs = scrape_builtin_jobs(page, url)
                elif scraper_type == "weworkremotely": 
                    jobs = scrape_weworkremotely_jobs(page, url)
                elif scraper_type == "justremote": 
                    jobs = scrape_justremote_jobs(page, url)
                elif scraper_type == "remote4africa":
                    jobs = scrape_remote4africa_jobs(page, url) 
                elif scraper_type == "realworkfromanywhere":
                    jobs = scrape_realworkfromanywhere_jobs(page, url) 
                elif scraper_type == "productjobsanywhere":
                    jobs = scrape_productjobsanywhere_jobs(page, url)
                elif scraper_type == "up2staff_api": 
                    # API scraping does not require Playwright/page object
                    jobs = scrape_up2staff_api_jobs(url) 
                else:
                    print(f"  [ERROR] Unknown scraper type for URL: {url}. Skipping.")

                all_jobs.extend(jobs)
                if page:
                    page.close() 
                # Be polite to the servers
                time.sleep(1) 

            if browser:
                browser.close()

    except Exception as e:
        print(f"  [CRITICAL ERROR] Failed to initialize Playwright or run browser: {e}")
        return 

    # --- PROCESS AND SAVE TO JSON ---
    if all_jobs:
        # Deduplication
        unique_jobs_map = {}
        for job in all_jobs:
            # Use URL as the primary deduplication key
            dedupe_key = job['url'] 
            # For BuiltIn, URL might change due to tracking, so use a normalized title/date as backup key
            if job['source'] in ['BuiltIn']:
                normalized_title = re.sub(r'\s+', ' ', job['title'].strip().lower())
                normalized_posted_ago = job['posted_ago'].strip().lower()
                dedupe_key = f"{job['source']}:{normalized_title}:{normalized_posted_ago}"
            
            if dedupe_key not in unique_jobs_map:
                unique_jobs_map[dedupe_key] = job

        unique_jobs = list(unique_jobs_map.values())
        # Sort by posted date, newest first
        sorted_jobs = sorted(unique_jobs, key=lambda x: datetime.strptime(x['posted_datetime'], '%Y-%m-%d %H:%M:%S'), reverse=True)

        # Save to jobs.json
        with open('jobs.json', 'w', encoding='utf-8') as f:
            json.dump(sorted_jobs, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ SUCCESS: Saved {len(sorted_jobs)} unique jobs to jobs.json")
        print(f"   Sources: {sorted({j['source'] for j in sorted_jobs})}")
    else:
        # Save empty array if no jobs
        with open('jobs.json', 'w', encoding='utf-8') as f:
            json.dump([], f)
        print("\n❌ No jobs found in the last 48 hours. Saved empty jobs.json")

# Run the scraper
if __name__ == "__main__":
    scrape_all_jobs()
