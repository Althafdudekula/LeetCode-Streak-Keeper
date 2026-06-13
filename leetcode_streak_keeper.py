#!/usr/bin/env python3
"""
LeetCode Streak Keeper
======================
Automatically re-submits one of your past accepted solutions
if you haven't submitted anything today, keeping your streak alive.

Setup:
  1. pip install requests
  2. Fill in LEETCODE_SESSION and CSRF_TOKEN below (see instructions).
  3. Run once manually to test, then schedule via cron or Task Scheduler.

Getting your cookies (Chrome/Edge/Firefox):
  - Go to https://leetcode.com and log in.
  - Open DevTools (F12) → Application → Cookies → leetcode.com
  - Copy the value of `LEETCODE_SESSION` and `csrftoken`.
  - Cookies last ~1 month; update them when the script stops working.
"""

import requests
import json
import time
import random
import logging
import os
from datetime import datetime, timezone

# ──────────────────────────────────────────────
# CONFIGURATION — fill these in
# ──────────────────────────────────────────────
LEETCODE_SESSION = os.environ.get("LEETCODE_SESSION","eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJfYXV0aF91c2VyX2lkIjoiMTQ3MzE3MTkiLCJfYXV0aF91c2VyX2JhY2tlbmQiOiJhbGxhdXRoLmFjY291bnQuYXV0aF9iYWNrZW5kcy5BdXRoZW50aWNhdGlvbkJhY2tlbmQiLCJfYXV0aF91c2VyX2hhc2giOiJlOWRkNjIyMzcwMmVlZGNkZDBmNjhhMTc5YTE2NjlkN2I4NmQzZTQ1MjY3YWU4MWU0NmI1MTNhNGNjMDNjNDEzIiwic2Vzc2lvbl91dWlkIjoiYzlhNDkxMmUiLCJpZCI6MTQ3MzE3MTksImVtYWlsIjoiZHVkZWt1bGFhbHRoYWY2QGdtYWlsLmNvbSIsInVzZXJuYW1lIjoiQWx0aGFmX2R1ZGVrdWxhIiwidXNlcl9zbHVnIjoiQWx0aGFmX2R1ZGVrdWxhIiwiYXZhdGFyIjoiaHR0cHM6Ly9hc3NldHMubGVldGNvZGUuY29tL3VzZXJzL2RlZmF1bHRfYXZhdGFyLmpwZyIsInJlZnJlc2hlZF9hdCI6MTc4MTIzMzc2OSwiaXAiOiIyNDAxOjQ5MDA6OTcxZjoxNjM3OmFjNTQ6ZTZhMjpkYmNhOjIwODEiLCJpZGVudGl0eSI6IjE2ZmVlMzc1NTlkYmQ0MmI0NDgyMDQ0NDZkMDIwODlmIiwiZGV2aWNlX3dpdGhfaXAiOlsiOTZkYmM2MTc5MTMyZmFjNTNkNzI5ZGRlYTA3ZWRmNjMiLCIyNDAxOjQ5MDA6OTZmMjoyYzM3OjE5NDQ6OTgxNDplZTg3Ojk5ODMiXSwiX3Nlc3Npb25fZXhwaXJ5IjoxMjA5NjAwfQ.YchsxRYsnEwaCqgRV6Ki8wUt4j8uDuDudMq3jh4rtEM")
CSRF_TOKEN       = os.environ.get("CSRF_TOKEN", "7ex4ktZe3tQS4MdVrLElC9EPlagvuXDV")

# How many past submissions to fetch and pick from (picks one randomly)
SUBMISSION_POOL_SIZE = 20

# Dry run: set True to test without actually submitting
DRY_RUN = False
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("streak_keeper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

GRAPHQL_URL = "https://leetcode.com/graphql/"
HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "x-csrftoken": CSRF_TOKEN,
    "Cookie": f"LEETCODE_SESSION={LEETCODE_SESSION}; csrftoken={CSRF_TOKEN}",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def graphql(query: str, variables: dict = None) -> dict:
    payload = {"query": query, "variables": variables or {}}
    resp = requests.post(GRAPHQL_URL, headers=HEADERS, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()

user = data.get("data", {}).get("user")

if user is None:
    raise Exception(
        "LeetCode authentication failed. Check LEETCODE_SESSION and CSRF_TOKEN."
    )

return user["username"]


def already_submitted_today() -> bool:
    """Check submission calendar — returns True if there's already a submission today."""
    query = """
    query userProfileCalendar($username: String!, $year: Int) {
      matchedUser(username: $username) {
        userCalendar(year: $year) {
          submissionCalendar
        }
      }
    }
    """
    username = get_username()
    year = datetime.now(timezone.utc).year
    data = graphql(query, {"username": username, "year": year})
    calendar_json = data["data"]["matchedUser"]["userCalendar"]["submissionCalendar"]
    calendar = json.loads(calendar_json)  # {unix_timestamp_str: count, ...}

    # Today's UTC date as unix day start (LeetCode uses day-level timestamps)
    now_utc = datetime.now(timezone.utc)
    today_ts = int(datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc).timestamp())

    # LeetCode stores keys as strings; check ±1 day to be safe
    for ts_str, count in calendar.items():
        if abs(int(ts_str) - today_ts) < 86400 and count > 0:
            return True
    return False


def fetch_accepted_submissions(limit: int = 20) -> list:
    """Fetch recent accepted submissions with their code."""
    query = """
    query recentAcSubmissions($username: String!, $limit: Int!) {
      recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
        lang
      }
    }
    """
    username = get_username()
    data = graphql(query, {"username": username, "limit": limit})
    return data["data"]["recentAcSubmissionList"]


def fetch_submission_code(submission_id: str) -> str | None:
    """Fetch the actual code of a submission by its ID."""
    query = """
    query submissionDetails($submissionId: Int!) {
      submissionDetails(submissionId: $submissionId) {
        code
        lang { name verboseName }
        question { titleSlug questionId }
      }
    }
    """
    data = graphql(query, {"submissionId": int(submission_id)})
    details = data.get("data", {}).get("submissionDetails")
    return details


def get_question_id(title_slug: str) -> str | None:
    """Get the numeric questionId for a problem slug."""
    query = """
    query questionData($titleSlug: String!) {
      question(titleSlug: $titleSlug) {
        questionId
      }
    }
    """
    data = graphql(query, {"titleSlug": title_slug})
    q = data.get("data", {}).get("question")
    return q["questionId"] if q else None


def submit_solution(title_slug: str, question_id: str, lang: str, code: str) -> dict:
    """Submit a solution via POST to LeetCode's submit endpoint."""
    url = f"https://leetcode.com/problems/{title_slug}/submit/"
    payload = {
        "lang": lang,
        "question_id": question_id,
        "typed_code": code,
    }
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()  # contains submission_id


def check_submission_result(submission_id: str, retries: int = 10, delay: int = 3) -> dict:
    """Poll LeetCode for the submission result."""
    url = f"https://leetcode.com/submissions/detail/{submission_id}/check/"
    for attempt in range(retries):
        time.sleep(delay)
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("state") == "SUCCESS":
            return data
        log.info(f"  Waiting for result... (attempt {attempt + 1}/{retries})")
    return {}


def run():
    log.info("=== LeetCode Streak Keeper ===")

    # Validate config
    if "YOUR_" in LEETCODE_SESSION or "YOUR_" in CSRF_TOKEN:
        log.error("Please set your LEETCODE_SESSION and CSRF_TOKEN in the script.")
        return

    # Check if streak is already safe
    log.info("Checking today's submission status...")
    if already_submitted_today():
        log.info("[OK] Already submitted today — streak is safe! Nothing to do.")
        return

    log.info("No submission found today. Fetching past accepted solutions...")

    # Get a pool of past accepted submissions
    submissions = fetch_accepted_submissions(SUBMISSION_POOL_SIZE)
    if not submissions:
        log.error("No accepted submissions found. Solve at least one problem first!")
        return

    # Shuffle and try submissions until we get one with retrievable code
    random.shuffle(submissions)
    chosen = None
    details = None

    for sub in submissions:
        log.info(f"  Trying: {sub['title']} (id={sub['id']}, lang={sub['lang']})")
        details = fetch_submission_code(sub["id"])
        if details and details.get("code"):
            chosen = sub
            break
        time.sleep(1)

    if not chosen or not details:
        log.error("Could not retrieve code for any submission. Cookies may be expired.")
        return

    title_slug = details["question"]["titleSlug"]
    question_id = details["question"]["questionId"]
    lang = details["lang"]["name"]
    code = details["code"]

    log.info(f"[*] Selected: '{chosen['title']}' | Lang: {lang}")

    if DRY_RUN:
        log.info("[DRY_RUN] DRY RUN — skipping actual submission.")
        log.info(f"   Would submit {len(code)} chars of {lang} to '{title_slug}'")
        return

    # Submit
    log.info("[>>>] Submitting solution...")
    result = submit_solution(title_slug, question_id, lang, code)
    submission_id = result.get("submission_id")

    if not submission_id:
        log.error(f"Submission failed. Response: {result}")
        return

    log.info(f"  Submission ID: {submission_id}. Waiting for result...")

    # Poll for result
    outcome = check_submission_result(str(submission_id))
    status = outcome.get("status_msg", "Unknown")
    log.info(f"  Result: {status}")

    if status == "Accepted":
        log.info("[SUCCESS] Accepted! Your LeetCode streak is safe for today.")
    else:
        log.warning(f"[!] Submission status: {status}. Streak may not have updated.")
        log.warning("   This shouldn't happen with a previously accepted solution.")
        log.warning("   Check if cookies have expired or the problem has changed.")


if __name__ == "__main__":
    run()
