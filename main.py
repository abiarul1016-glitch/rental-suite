import asyncio
import json
import os
import random
from datetime import datetime

from dotenv import load_dotenv
from ollama import AsyncClient
from playwright.async_api import BrowserContext, async_playwright
from pydantic import BaseModel, Field

from facebook_functions import check_logged_in_facebook, post_on_facebook
from kijiji_functions import check_logged_in_kijiji, post_on_kijiji

load_dotenv("secrets.env")


# === ENVIRONMENT VARIABLES ===
# Main user credentials
EMAIL = os.getenv("EMAIL")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
FORMATTED_PHONE_NUMBER = os.getenv("FORMATTED_PHONE_NUMBER")

# Facebook credentials and URLs
FACEBOOK_PASSWORD = os.getenv("FACEBOOK_PASSWORD")
FACEBOOK_SELLER_DASHBOARD_URL = "https://www.facebook.com/marketplace/you/selling"
FACEBOOK_NEW_LISTING_URL = "https://www.facebook.com/marketplace/create/rental"

# Kijiji credentials and URLs
KIJIJI_PASSWORD = os.getenv("KIJIJI_PASSWORD")
KIJIJI_SELLER_DASHBOARD_URL = "https://www.kijiji.ca/m-my-ads/"
KIJIJI_NEW_LISTING_URL = "https://www.kijiji.ca/p-post-ad.html?categoryId=37"

# === FILE PATHS ===
BROWSER_STATE_PATH = "playwright/.auth/state.json"
PROPERTY_DATA_PATH = "houses.json"

# === CONCURRENCY CONTROLS ===
FACEBOOK_POSTING_LIMIT = asyncio.Semaphore(3)
KIJIJI_POSTING_LIMIT = asyncio.Semaphore(3)
FILE_LOCK = asyncio.Lock()


class PropertyDetails(BaseModel):
    title: str = Field(
        ...,
        description="A catchy, professional headline under 100 characters. No emojis.",
    )
    description: str = Field(
        ...,
        description="A detailed description including layout, utilities, and location highlights. Use dashes for lists.",
    )
    tags: list[str] = Field(
        ...,
        min_length=5,
        max_length=5,
        description="Exactly 5 relevant search tags for Facebook/Kijiji.",
    )


async def main():
    """
    Main orchestration function for property posting to Facebook and Kijiji.

    This function:
    1. Loads property data from JSON file
    2. Filters properties eligible for posting
    3. Generates new titles/descriptions for properties that need them
    4. Launches browser and handles login
    5. Posts listings to both platforms concurrently
    6. Updates property data and saves changes
    """
    print("Hello from rental-suite!\n")

    # Load property data from JSON file
    with open(PROPERTY_DATA_PATH, "r") as file:
        data = json.load(file)

    # Filter properties that are eligible for posting (active subsections only)
    posting_properties = await get_posting_properties(data["properties"])

    # If no properties are eligible for posting, exit
    if not posting_properties:
        print("No posting properties found. Check your config and try again.")
        return
    else:
        print(f"Found {len(posting_properties)} posting properties. Posting...")
        for property in posting_properties:
            print(f"{property['facebook_formatted_address']} - {property['type']}")
        print()

    # Determine which properties need new titles and descriptions
    # (i.e., those that have been posted 0 times or every 5 times)
    new_titles_and_descriptions_properties = [
        posting_property
        for posting_property in posting_properties
        if posting_property["number_posted_times"] % 5 == 0
    ]

    # If any properties need new titles/descriptions, generate them using AI
    if new_titles_and_descriptions_properties:
        print("Generating titles and descriptions for:")

        for posting_property in new_titles_and_descriptions_properties:
            print(
                f"{posting_property['facebook_formatted_address']} - {posting_property['type']}"
            )
        print()

        # Create tasks to generate AI-based titles and descriptions
        generate_tasks = [
            asyncio.create_task(generate_property_details(str(property)))
            for property in new_titles_and_descriptions_properties
        ]
        results = await asyncio.gather(*generate_tasks)

        # Update the properties with the new titles, descriptions, and tags
        for property, result in zip(new_titles_and_descriptions_properties, results):
            property["title"] = result[0]
            property["description"] = result[1]
            property["tags"] = result[2]

    # Launch browser with Playwright for concurrent posting
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context(storage_state=BROWSER_STATE_PATH)
        facebook_page = await context.new_page()
        kijiji_page = await context.new_page()

        # Check if user is logged in to Facebook
        await facebook_page.goto(FACEBOOK_NEW_LISTING_URL)

        print("Checking if user is already logged in to Facebook...")
        if not await check_logged_in_facebook(facebook_page):
            print(
                "User is not logged in to FACEBOOK. Login manually and save the browser state. You have 40 seconds to log in before the script closes..."
            )

            # Wait for user to log in manually
            await facebook_page.wait_for_timeout(40000)
            # Save browser state after manual login
            await context.storage_state(path=BROWSER_STATE_PATH)
            return

        else:
            print("User is already logged in to FACEBOOK. Proceeding...")

        print()

        # Check if user is logged in to Kijiji
        await kijiji_page.goto(KIJIJI_NEW_LISTING_URL)

        print("Checking if user is already logged in to Kijiji...")

        if not await check_logged_in_kijiji(kijiji_page):
            print(
                "User is not logged in to KIJIJI. Login manually and save the browser state. You have 40 seconds to log in before the script closes..."
            )

            # Wait for user to log in manually
            await kijiji_page.wait_for_timeout(40000)
            # Save browser state after manual login
            await context.storage_state(path=BROWSER_STATE_PATH)
            return

        else:
            print("User is already logged in to KIJIJI. Proceeding...")

        print()

        # Create tasks for posting to Facebook (concurrent execution)
        facebook_posting_tasks = [
            asyncio.create_task(
                post_single_facebook_listing(context, posting_property, data)
            )
            for posting_property in posting_properties
        ]

        # Create tasks for posting to Kijiji (concurrent execution)
        kijiji_posting_tasks = [
            asyncio.create_task(
                post_single_kijiji_listing(context, posting_property, data)
            )
            for posting_property in posting_properties
        ]

        # Execute all Facebook posting tasks concurrently
        await asyncio.gather(*facebook_posting_tasks)
        # Execute all Kijiji posting tasks concurrently
        await asyncio.gather(*kijiji_posting_tasks)

        # Navigate to seller dashboards to confirm posting completion
        await facebook_page.goto(FACEBOOK_SELLER_DASHBOARD_URL)
        print("Facebook posting completed!")

        await kijiji_page.goto(KIJIJI_SELLER_DASHBOARD_URL)
        print("Kijiji posting completed!")

        # Close the browser
        await browser.close()

    # Save updated property data back to JSON file
    with open(PROPERTY_DATA_PATH, "w") as file:
        json.dump(data, file, indent=2)


async def get_posting_properties(properties):
    """
    Filter and return only active properties that are eligible for posting.

    This function processes the full property data structure and extracts only
    subsections that have the 'active' flag set to True.

    Args:
        properties (list): A list of property objects containing subsections

    Returns:
        posting_properties (list): A list of active subsections eligible for posting
    """

    posting_properties = []
    for property in properties:
        subsections = property["subsections"]
        for subsection in subsections:
            if subsection["active"]:
                posting_properties.append(subsection)

    return posting_properties


# === AI GENERATION FUNCTIONS ===
async def generate_property_details(property_details, retries=3):
    """
    Generate professional property titles, descriptions, and tags using AI.

    This function sends property data to an AI model to generate compelling
    marketing content for Facebook and Kijiji listings.

    Args:
        property_details (str): Raw property data to be processed by AI
        retries (int): Number of retry attempts for AI generation (default: 3)

    Returns:
        tuple: (title, description, tags) generated by the AI model

    Raises:
        Exception: If all retry attempts fail
    """
    user_prompt = (
        f"DATA: {property_details}\n\n"
        "INSTRUCTION: Generate a professional 'title', 'description', and 'tags' for this property. Only 5 tags must be generated"
        "Return ONLY these three fields in your JSON response. Do not include IDs from the input data."
    )

    messages = [
        {
            "role": "system",
            "content": "You are a JSON generator. You only output valid JSON matching the schema. No chat, no preamble.",
        },
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(retries):
        try:
            response = await AsyncClient().chat(
                model="qwen3.5",
                messages=messages,
                format=PropertyDetails.model_json_schema(),
                think=False,
            )

            content = response.message.content

            # Validate the AI response with Pydantic
            details = PropertyDetails.model_validate_json(content)
            return details.title, details.description, details.tags

        except Exception as e:
            if attempt < retries - 1:
                print(f"Retry {attempt + 1} due to error: {e}")
                await asyncio.sleep(1)  # Small delay before retrying
            else:
                print("All retries failed.")
                raise e


# === BROWSER POSTING FUNCTIONS ===
async def post_single_facebook_listing(
    context: BrowserContext, relevant_property, all_data
):
    """
    Post a single property listing on Facebook Marketplace.

    This function handles the complete Facebook posting workflow including:
    - Navigating to the listing page
    - Checking login status
    - Filling out the listing form
    - Updating property metadata
    - Saving changes to the data file and browser state

    Args:
        context (BrowserContext): Playwright browser context
        relevant_property (dict): Property data to be posted
        all_data (dict): Complete data structure containing all properties

    Returns:
        None
    """

    page = await context.new_page()

    async with FACEBOOK_POSTING_LIMIT:
        delay = random.uniform(3, 7)
        await asyncio.sleep(delay)

        # Navigate to Facebook Marketplace new listing page
        await page.goto(FACEBOOK_NEW_LISTING_URL)

        # Sanity check if user is logged in
        if not await check_logged_in_facebook(page):
            print(
                "An error has occurred. Please check if user is logged in to FACEBOOK."
            )
            return

        await post_on_facebook(page, relevant_property)
        # Update property details
        relevant_property["last_posted"] = datetime.now().strftime("%Y-%m-%d")
        relevant_property["number_posted_times"] += 1

        # Wait for a few seconds to allow the page to process the save action.
        await page.wait_for_timeout(15000)

        async with FILE_LOCK:
            # Save JSON changes to file
            with open(PROPERTY_DATA_PATH, "w") as file:
                json.dump(all_data, file, indent=2)

            # Save the current browser context state (cookies, local storage) for future runs.
            await context.storage_state(path=BROWSER_STATE_PATH)

        print(
            f"Saved update for {relevant_property['facebook_formatted_address']} - {relevant_property['type']}"
        )

        await page.close()


async def post_single_kijiji_listing(
    context: BrowserContext, relevant_property, all_data
):
    """
    Post a single property listing on Kijiji.

    This function handles the complete Kijiji posting workflow including:
    - Navigating to the listing page
    - Checking login status
    - Filling out the listing form
    - Updating property metadata
    - Saving changes to the data file and browser state

    Args:
        context (BrowserContext): Playwright browser context
        relevant_property (dict): Property data to be posted
        all_data (dict): Complete data structure containing all properties

    Returns:
        None
    """

    page = await context.new_page()

    async with KIJIJI_POSTING_LIMIT:
        delay = random.uniform(3, 7)
        await asyncio.sleep(delay)

        # Navigate to Kijiji new listing page
        await page.goto(KIJIJI_NEW_LISTING_URL)

        # Sanity check if user is logged in
        if not await check_logged_in_kijiji(page):
            print("An error has occurred. Please check if user is logged in to KIJIJI.")
            return

        await post_on_kijiji(page, relevant_property)
        # Update property details
        relevant_property["last_posted"] = datetime.now().strftime("%Y-%m-%d")
        relevant_property["number_posted_times"] += 1

        # Wait for a few seconds to allow the page to process the save action.
        await page.wait_for_timeout(15000)

        async with FILE_LOCK:
            # Save JSON changes to file
            with open(PROPERTY_DATA_PATH, "w") as file:
                json.dump(all_data, file, indent=2)

            # Save the current browser context state (cookies, local storage) for future runs.
            await context.storage_state(path=BROWSER_STATE_PATH)

        print(
            f"Saved update for {relevant_property['facebook_formatted_address']} - {relevant_property['type']}"
        )

        await page.close()


# === ADDITIONAL FEATURES ===
# TODO: Implement ads manager functionality
# TODO: Implement repush ad functionality
# TODO: Implement simple chat management


if __name__ == "__main__":
    asyncio.run(main())
