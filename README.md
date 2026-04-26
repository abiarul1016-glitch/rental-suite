# Rental Suite

Post rental listings to Facebook Marketplace and Kijiji — automatically, concurrently, and with AI-generated content.

---

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-fff?style=for-the-badge&logo=ollama&logoColor=000)
![Qwen](https://custom-icon-badges.demolab.com/badge/Qwen-605CEC?style=for-the-badge&logo=qwen&logoColor=fff)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-fff?style=for-the-badge&logo=pydantic&logoColor=00527B)

## What is it?

Landlords and property managers spend hours manually copying listing details, filling out forms, and re-posting the same property over and over — only for platforms to flag duplicate content. **Rental Suite** automates all of that.

Define your properties once in a JSON file, and the suite handles the rest: generating fresh titles and descriptions with AI, logging into Facebook and Kijiji, filling out every field, uploading photos, and tracking posting history — all in a single run.

## Features

- **Multi-platform posting** — Posts listings to both Facebook Marketplace and Kijiji concurrently
- **AI-generated content** — Uses Ollama (Qwen 3.5) to generate catchy titles, detailed descriptions, and search-optimized tags for each listing
- **Browser automation** — Uses Playwright to interact with real browser pages, filling out forms and uploading images
- **Login persistence** — Saves and reuses browser authentication state so you only need to log in once per session
- **Listing rotation** — Tracks how many times each property has been posted and regenerates AI content every 5 postings to avoid duplicate listings
- **Structured property data** — All property information is stored in a JSON file, making it easy to manage and extend
- **Async concurrency** — Leverages Python's `asyncio` for parallel execution across platforms

## How it works

Rental Suite operates as a multi-stage pipeline, moving from data ingestion to live listing publication with minimal human intervention.

1. **Data Loading (`houses.json`)** — The system reads all property data from a structured JSON file, filtering only active listings marked for posting.
2. **AI Content Generation (`main.py`)** — Properties that need fresh copy are sent to a local LLM (Qwen 3.5 via Ollama) to generate titles, descriptions, and tags. This happens every 5 postings to keep listings unique.
3. **Browser Launch (`main.py`)** — A Chromium browser is launched via Playwright. Login status is checked on both Facebook and Kijiji.
   - If not logged in, you have **40 seconds** to log in manually — the browser state is then saved for future runs.
4. **Concurrent Posting** — All listings are posted to both platforms simultaneously using async tasks. Rental Suite handles form filling, photo uploads, and property type selection, within the bounds of ad details, such as amenities and pricing.
5. **Data Update** — After posting completes, the `houses.json` file is updated with new posting counts and timestamps.

### Flow Diagram

```
Load houses.json
     │
     ▼
Filter Active Properties
     │
     ▼
Generate AI Content (if needed)
     │
     ▼
Launch Browser (Playwright)
     │
     ├──► Check Facebook Login ──► Post to Facebook (concurrent)
     │
     └──► Check Kijiji Login ──► Post to Kijiji (concurrent)
     │
     ▼
Update houses.json
```

## Tech stack

Rental Suite is a local-first, Python-driven automation tool.

| Layer                  | Technology        | Purpose                                           |
| :--------------------- | :---------------- | :------------------------------------------------ |
| **Core Language**      | Python 3.12+      | Orchestration, data handling, and async execution |
| **Local AI/LLM**       | Ollama (Qwen 3.5) | Generates titles, descriptions, and search tags   |
| **Browser Automation** | Playwright        | Fills out forms, uploads images, manages sessions |
| **Data Validation**    | Pydantic          | Validates AI-generated listing content            |
| **Environment**        | python-dotenv     | Manages credentials and configuration             |

## Running locally

### Prerequisites

- **Python 3.12+**
- **Ollama** — Install from [ollama.com](https://ollama.com) and pull the `qwen3.5` model:
  ```bash
  ollama pull qwen3.5
  ```

### Setup

1. **Install Dependencies:**

   ```bash
   pip install ollama playwright python-dotenv pydantic
   ```

2. **Install Playwright Browsers:**

   ```bash
   playwright install chromium
   ```

3. **Configure Environment Variables:**
   Edit `secrets.env` with your credentials:

   ```env
   EMAIL=your_email@example.com
   PHONE_NUMBER=4166691194
   FORMATTED_PHONE_NUMBER=416-669-1194
   FACEBOOK_PASSWORD=your_facebook_password
   KIJIJI_PASSWORD=your_kijiji_password
   ```

4. **Add Your Properties:**
   Edit `houses.json` and add your rental properties. Set `"active": true` for listings you want to post.

5. **Run the Suite:**

   ```bash
   python main.py
   ```

   _(A browser window will open — log in if needed, then sit back while listings go live.)_

## Property Data Structure

All property data lives in `houses.json`. Here's a minimal example:

```json
{
  "properties": [
    {
      "id": "prop_1",
      "friendly_name": "My Property",
      "address": "123 Main St",
      "city": "Toronto",
      "postal_code": "M5V 1A1",
      "country": "Canada",
      "subsections": [
        {
          "id": "sub_prop_1",
          "facebook_formatted_address": "123 Main",
          "kijiji_formatted_address": "123 Main Street",
          "type": "basement",
          "private_room": false,
          "bedrooms": 1,
          "bathrooms": 1,
          "parking": 1,
          "sqft": 500,
          "images": ["path/to/image1.jpg"],
          "title": "",
          "description": "",
          "tags": [],
          "date_available": "2026-05-01",
          "rent": 1500,
          "number_posted_times": 0,
          "last_posted": "",
          "additional_details": "",
          "active": true
        }
      ]
    }
  ]
}
```

| Field                            | Description                                |
| -------------------------------- | ------------------------------------------ |
| `active`                         | Set to `true` to include in posting        |
| `type`                           | `"basement"` or `"main floor"`             |
| `private_room`                   | Whether it's a private room share          |
| `images`                         | Array of local image paths for the listing |
| `date_available`                 | Available date in `YYYY-MM-DD` format      |
| `rent`                           | Monthly rent as a number                   |
| `title` / `description` / `tags` | Populated automatically by AI              |

## Notes

- **Browser state** is saved to `playwright/.auth/state.json`. Keep this file secure as it contains authentication cookies.
- AI content is regenerated every **5 postings** to keep listings fresh and avoid platform duplicate-content filters.
- The script runs in **headed mode** (`headless=False`) by default so you can monitor progress visually. Set `headless=True` in `main.py` for unattended runs.
- A **40-second timeout** is applied if you need to log in manually. Adjust this value in `main.py` if needed.

## What's next

- [ ] Support for additional listing platforms (Craigslist, Zillow, etc.)
- [ ] Image resizing optimization, and AI-touch ups before upload
- [ ] Image uploads via a cloud server (such as Synology)
- [ ] Scheduled runs via cron or systemd timer
- [ ] Dashboard for monitoring posting history and performance
- [ ] Export listings as PDF or CSV

---

<div align="center">

Detail once, list everywhere. &nbsp;·&nbsp; For those who can't bear listing another ad

</div>
