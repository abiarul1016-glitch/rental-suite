import asyncio
import json
import os
import random
from datetime import datetime

from dotenv import load_dotenv
from ollama import AsyncClient
from playwright.async_api import BrowserContext, Page, async_playwright

from facebook_functions import check_logged_in_facebook, post_on_facebook

load_dotenv("secrets.env")


# CREDS
EMAIL = os.getenv("EMAIL")

# FACEBOOK
FACEBOOK_PASSWORD = os.getenv("FACEBOOK_PASSWORD")
FACEBOOK_SELLER_DASHBOARD_URL = "https://www.facebook.com/marketplace/you/selling"
FACEBOOK_NEW_LISTING_URL = "https://www.facebook.com/marketplace/create/rental"

# KIJIJI
KIJIJI_PASSWORD = os.getenv("KIJIJI_PASSWORD")

BROWSER_STATE_PATH = "playwright/.auth/state.json"

PROPERTY_DATA_PATH = "houses.json"

POSTING_LIMIT = asyncio.Semaphore(3)
FILE_LOCK = asyncio.Lock()


async def main():
    print("Hello from rental-suite!\n")

    # TODO: make async with aiofiles
    with open(PROPERTY_DATA_PATH, "r") as file:
        data = json.load(file)

    posting_properties = get_posting_properties(data["properties"])

    if not posting_properties:
        print("No posting properties found. Check your config and try again.")
        return
    else:
        print(f"Found {len(posting_properties)} posting properties. Posting...")
        for property in posting_properties:
            print(f"{property['facebook_formatted_address']} - {property['type']}")
        print()

    # start title and description generations tasks for all properties that need it
    # generate new title and description if ad has been posted 0, or 5 or more times
    new_titles_and_descriptions_properties = [
        posting_property
        for posting_property in posting_properties
        if posting_property["number_posted_times"] % 5 == 0
    ]

    if new_titles_and_descriptions_properties:
        print("Generating titles and descriptions for:")
        for posting_property in new_titles_and_descriptions_properties:  # noqa
            print(
                f"{posting_property['facebook_formatted_address']} - {property['type']}"
            )
        print()

        generate_tasks = [
            asyncio.create_task(generate_title_and_description(property))
            for property in new_titles_and_descriptions_properties
        ]
        results = await asyncio.gather(*generate_tasks)

        for property, result in zip(new_titles_and_descriptions_properties, results):
            property["title"] = result[0]
            property["description"] = result[1]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context(storage_state=BROWSER_STATE_PATH)
        facebook_page = await context.new_page()
        kijiji_page = await context.new_page()

        # check is user logged in to facebook
        await facebook_page.goto(FACEBOOK_NEW_LISTING_URL)

        print("Checking if user is already logged in to facebook...")
        # Check for a visible element that confirms the user is logged in (e.g., the 'Me' button).

        if not await check_logged_in_facebook(facebook_page):
            print(
                "User is not logged in. Login manually and save the browser state. You have 40 seconds to log in before the script closes..."
            )
            await facebook_page.wait_for_timeout(
                40000
            )  # Wait for a 40 seconds to allow user to log in manually if automatic login fails.

            # Save current browser state after manual login attempt.
            await context.storage_state(path=BROWSER_STATE_PATH)
            return

        else:
            print("User is already logged in. Proceeding...")

        print()

        # TODO: Check if user is logged into kijiji

        facebook_posting_tasks = [
            asyncio.create_task(
                post_single_facebook_listing(context, posting_property, data)
            )
            for posting_property in posting_properties
        ]

        await asyncio.gather(*facebook_posting_tasks)

        await facebook_page.goto(FACEBOOK_SELLER_DASHBOARD_URL)
        print("Facebook posting completed!")

        # TODO: launch kijiji tasks

        await browser.close()

    # save json changes
    with open(PROPERTY_DATA_PATH, "w") as file:
        json.dump(data, file, indent=2)


async def post_single_facebook_listing(
    context: BrowserContext, relevant_property, all_data
):
    """
    Post a single listing on Facebook Marketplace.
    """

    page = await context.new_page()

    async with POSTING_LIMIT:
        delay = random.uniform(3, 7)
        asyncio.sleep(delay)

        # 1. NAVIGATE TO POSTING AD PAGE
        await page.goto(FACEBOOK_NEW_LISTING_URL)

        # sanity check if user is logged in
        if not await check_logged_in_facebook(page):
            print("An error has occurred. Please check if user is logged in.")
            return

        await post_on_facebook(page, relevant_property)
        # Update property details
        relevant_property["last_posted"] = datetime.now().strftime("%Y-%m-%d")
        relevant_property["number_posted_times"] += 1

        # Wait for a few seconds to allow the page to process the save action.
        await page.wait_for_timeout(15000)

        async with FILE_LOCK:
            # save json changes
            with open(PROPERTY_DATA_PATH, "w") as file:
                json.dump(all_data, file, indent=2)

            # Save the current browser context state (cookies, local storage) for future runs.
            storage = await context.storage_state(path=BROWSER_STATE_PATH)

        print(
            f"Saved update for {relevant_property['facebook_formatted_address']} - {relevant_property['type']}"
        )

        await page.close()


def get_posting_properties(properties):
    """
    Get posting properties from the data file.
    Args:
        properties (list): A list of properties and their details

    Returns:
        posting_properties (list): A list of posting properties
    """

    posting_properties = []
    for property in properties:
        subsections = property["subsections"]
        for subsection in subsections:
            if subsection["active"]:
                posting_properties.append(subsection)

    return posting_properties


# GENERATE
# NOTE: Might want to add a generate title function
async def generate_title_and_description(property_details):
    messages = [
        {
            "role": "system",
            "content": "You generate professional listings for rental properties. Ensure the text is clean and is optimized for platforms such as Facebook Marketplace and Kijiji. No emojis and no stars, as it looks unprofessional and don't render well on the platform. You can use dashes though for lisiting elements. Interested people can contact me at my phone number: 4166691194",
        },
        {
            "role": "user",
            "content": f"Generate a description for a rental property with the following details: {property_details}",
        },
    ]
    # try playing around with gemma4 and qwen3.5 to see which yields better results
    response = await AsyncClient().chat(model="qwen3.5", messages=messages, think=False)
    description = response.message.content
    messages.append(response.message)

    messages.append(
        {"role": "user", "content": "Now, generate a title for this description."}
    )
    response = await AsyncClient().chat(model="qwen3.5", messages=messages, think=False)
    title = response.message.content

    return title, description


# B. KIJIJI FUNCTIONS

# 3. ADS MANAGER
# REPUSH AD, IF AVAILABLE
# MANAGE SIMPLE CHATS


if __name__ == "__main__":
    asyncio.run(main())
