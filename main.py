import asyncio
import json
import os
import random
from datetime import datetime

from dotenv import load_dotenv
from ollama import AsyncClient
from playwright.async_api import BrowserContext, Page, async_playwright
from pydantic import BaseModel, Field

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
KIJIJI_SELLER_DASHBOARD_URL = "https://www.kijiji.ca/m-my-ads/"
KIJIJI_NEW_LISTING_URL = "https://www.kijiji.ca/p-post-ad.html?categoryId=37"

BROWSER_STATE_PATH = "playwright/.auth/state.json"
PROPERTY_DATA_PATH = "houses.json"

FACEBOOK_POSTING_LIMIT = asyncio.Semaphore(3)
KIJIJI_POSTING_LIMIT = asyncio.Semaphore(3)
FILE_LOCK = asyncio.Lock()

# PERSONAL DETAILS
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
FORMATTED_PHONE_NUMBER = os.getenv("FORMATTED_PHONE_NUMBER")


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
                f"{posting_property['facebook_formatted_address']} - {posting_property['type']}"
            )
        print()

        generate_tasks = [
            asyncio.create_task(generate_property_details(str(property)))
            for property in new_titles_and_descriptions_properties
        ]
        results = await asyncio.gather(*generate_tasks)

        for property, result in zip(new_titles_and_descriptions_properties, results):
            property["title"] = result[0]
            property["description"] = result[1]
            property["tags"] = result[2]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context(storage_state=BROWSER_STATE_PATH)
        facebook_page = await context.new_page()
        kijiji_page = await context.new_page()

        # 1. Check is user logged in to facebook
        await facebook_page.goto(FACEBOOK_NEW_LISTING_URL)

        print("Checking if user is already logged in to facebook...")
        # Check for a visible element that confirms the user is logged in (e.g., the 'Me' button).

        if not await check_logged_in_facebook(facebook_page):
            print(
                "User is not logged in to FACEBOOK. Login manually and save the browser state. You have 40 seconds to log in before the script closes..."
            )
            await facebook_page.wait_for_timeout(
                40000
            )  # Wait for a 40 seconds to allow user to log in manually if automatic login fails.

            # Save current browser state after manual login attempt.
            await context.storage_state(path=BROWSER_STATE_PATH)
            return

        else:
            print("User is already logged in to FACEBOOK. Proceeding...")

        print()

        # 2. Check if user is logged into kijiji
        await kijiji_page.goto(KIJIJI_NEW_LISTING_URL)
        print("Checking if user is already logged in to kijiji...")

        if not await check_logged_in_kijiji(kijiji_page):
            print(
                "User is not logged in to KIJIJI. Login manually and save the browser state. You have 40 seconds to log in before the script closes..."
            )
            await kijiji_page.wait_for_timeout(
                40000
            )  # Wait for a 40 seconds to allow user to log in manually if automatic login fails.

            # Save current browser state after manual login attempt.
            await context.storage_state(path=BROWSER_STATE_PATH)
            return

        else:
            print("User is already logged in to KIJIJI. Proceeding...")

        print()

        facebook_posting_tasks = [
            asyncio.create_task(
                post_single_facebook_listing(context, posting_property, data)
            )
            for posting_property in posting_properties
        ]

        kijiji_posting_tasks = [
            asyncio.create_task(
                post_single_kijiji_listing(context, posting_property, data)
            )
            for posting_property in posting_properties
        ]

        await asyncio.gather(*facebook_posting_tasks)
        await asyncio.gather(*kijiji_posting_tasks)

        await facebook_page.goto(FACEBOOK_SELLER_DASHBOARD_URL)
        print("Facebook posting completed!")

        await facebook_page.goto(KIJIJI_SELLER_DASHBOARD_URL)
        print("Kijiji posting completed!")

        await browser.close()

    # save json changes
    with open(PROPERTY_DATA_PATH, "w") as file:
        json.dump(data, file, indent=2)


# a class could potentially be used for the following two functions due to their similarity. one class for facebook ads, and another for kijiji
async def post_single_facebook_listing(
    context: BrowserContext, relevant_property, all_data
):
    """
    Post a single listing on Facebook Marketplace.
    """

    page = await context.new_page()

    async with FACEBOOK_POSTING_LIMIT:
        delay = random.uniform(3, 7)
        await asyncio.sleep(delay)

        # 1. NAVIGATE TO POSTING AD PAGE
        await page.goto(FACEBOOK_NEW_LISTING_URL)

        # sanity check if user is logged in
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
            # save json changes
            with open(PROPERTY_DATA_PATH, "w") as file:
                json.dump(all_data, file, indent=2)

            # Save the current browser context state (cookies, local storage) for future runs.
            storage = await context.storage_state(path=BROWSER_STATE_PATH)

        print(
            f"Saved update for {relevant_property['facebook_formatted_address']} - {relevant_property['type']}"
        )

        await page.close()


async def post_single_kijiji_listing(
    context: BrowserContext, relevant_property, all_data
):
    """
    Post a single listing on Kijiji.
    """

    page = await context.new_page()

    async with KIJIJI_POSTING_LIMIT:
        delay = random.uniform(3, 7)
        await asyncio.sleep(delay)

        # 1. NAVIGATE TO POSTING AD PAGE
        await page.goto(KIJIJI_NEW_LISTING_URL)

        # sanity check if user is logged in
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
async def generate_property_details(property_details, retries=3):
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

    # messages = [
    #     {
    #         "role": "system",
    #         "content": (
    #             "You are a professional real estate copywriter. "
    #             "Output MUST be raw JSON only. No markdown formatting, no backticks, and no preamble. "
    #             f"Contact: {PHONE_NUMBER}. Use dashes for lists. No emojis or stars."
    #         ),
    #     },
    #     {
    #         "role": "user",
    #         "content": f"Generate rental details for: {property_details}",
    #     },
    # ]

    for attempt in range(retries):
        try:
            response = await AsyncClient().chat(
                model="qwen3.5",
                messages=messages,
                format=PropertyDetails.model_json_schema(),
                think=False,
            )

            content = response.message.content

            # 1. Validate with Pydantic
            details = PropertyDetails.model_validate_json(content)
            return details.title, details.description, details.tags

        except Exception as e:
            if attempt < retries - 1:
                print(f"Retry {attempt + 1} due to error: {e}")
                await asyncio.sleep(1)  # Small delay before retrying
            else:
                print("All retries failed.")
                raise e


async def format_to_kijiji_date(date):
    central_date = datetime.strptime(date, "%Y-%m-%d")
    return central_date.strftime("%d/%m/%Y")


# B. KIJIJI FUNCTIONS
async def check_logged_in_kijiji(page):
    """
    Check if the user is currently logged in to Kijiji.

    This function looks for a specific element (the 'Ad Details' heading) that is only visible when a user is logged in.

    Args:
        page: The Playwright page object representing the current browser page.

    Returns:
        bool: True if the user is logged in, False otherwise.
    """
    return await page.get_by_role("heading", name="Ad Details").is_visible()


# all logic to function below
async def post_on_kijiji(page: Page, relevant_property):
    KIJIJI_DATE = await format_to_kijiji_date(relevant_property["date_available"])

    # property type
    if relevant_property["type"] == "basement":
        await page.get_by_text("Basement").click()
    else:
        await page.get_by_text("House", exact=True).click()

    # number of beds and baths
    await page.locator("#numberbedrooms_s").select_option(
        str(relevant_property["bedrooms"])
    )
    await page.locator("#numberbathrooms_s").select_option(
        f"{relevant_property['bathrooms']}0"
    )

    await page.get_by_text("Year").click()

    # date available
    await page.locator("#dateavailable").click()
    await page.locator("#dateavailable").fill(
        KIJIJI_DATE
    )  # TODO: edit must be applied here
    await page.locator("#dateavailable").press("Enter")

    # pet-friendly - always no
    await page.get_by_text("No").first.click()

    # size
    await page.locator("#areainfeet_i").click()
    await page.locator("#areainfeet_i").fill(str(relevant_property["sqft"]))

    # funished - always no
    await page.get_by_text("No").nth(1).click()

    # appliances
    await page.get_by_text("Laundry (In Building):").click()
    await page.get_by_text("Fridge / Freezer:").click()

    # air conditioning
    await page.get_by_text("Yes").nth(2).click()

    # personal outdoor space
    await page.get_by_text("Yard:").click()

    if not relevant_property["type"] == "basement":
        await page.get_by_text(
            "Balcony:"
        ).click()  # add logic to only click this if property is main floor

    # smoking - always no
    await page.locator("label").filter(has_text="No").nth(3).click()

    # accessibility - always no
    await page.locator("label").filter(has_text="No").nth(4).click()

    # parking spots
    await page.locator("#numberparkingspots_s").select_option("2")

    # ad title
    await page.get_by_role("textbox", name="Ad title:").click()
    await page.get_by_role("textbox", name="Ad title:").fill(relevant_property["title"])

    # ad description
    await page.get_by_role("textbox", name="Description:").click()
    await page.get_by_role("textbox", name="Description:").fill(
        relevant_property["description"]
    )

    # tags
    # add logic for this to be generated by llm, and formatted to fit json properly
    for tag in relevant_property["tags"]:
        await page.get_by_role("textbox", name="Tags: (optional)").click()
        await page.get_by_role("textbox", name="Tags: (optional)").fill(tag)
        await page.get_by_role("textbox", name="Tags: (optional)").press("Enter")

    # 1. add photos
    property_images = relevant_property["images"]

    # This bypasses the click and the file browser window entirely
    await page.set_input_files(
        "input[type='file']",
        property_images,
    )

    # # WAIT FOR IMAGES TO UPLOAD
    await page.wait_for_timeout(5000)

    # location
    await page.get_by_role("button", name="Change my location").click()
    await page.locator('textarea[name="location"]').fill(
        relevant_property["kijiji_formatted_address"]
    )  # TODO: add kijiji_formatted address field
    await page.get_by_role("option", name="49 Wantanopa Crescent,").click()
    await (
        page.locator(".slider-1136925655").first.click()
    )  # click to show exact property location, useful, so no annoying questions

    # price
    await page.locator("#PriceAmount").click()
    await page.locator("#PriceAmount").fill(str(relevant_property["rent"]))

    # phone number
    await page.get_by_role("textbox", name="e.g. 123 456").click()
    await page.get_by_role("textbox", name="e.g. 123 456").fill(
        FORMATTED_PHONE_NUMBER
    )  # don't hardcode this + expose in program

    # posting
    await page.get_by_test_id("package-0-bottom-select").click()
    await page.get_by_test_id("checkout-post-btn").click()

    # processing time
    await page.wait_for_timeout(10000)


# 3. ADS MANAGER
# REPUSH AD, IF AVAILABLE
# MANAGE SIMPLE CHATS

if __name__ == "__main__":
    asyncio.run(main())
