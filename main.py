import asyncio
import json
import os
from datetime import datetime

from dotenv import load_dotenv
from ollama import AsyncClient
from playwright.async_api import async_playwright

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


async def main():
    print("Hello from rental-suite!")

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

        # TODO: create task to generate new title and description for ads that need it, so it runs in background thread, and doesn't block the main thread

        for posting_property in posting_properties:
            # 1. NAVIGATE TO POSTING AD PAGE
            await facebook_page.goto(FACEBOOK_NEW_LISTING_URL)

            # sanity check if user is logged in
            if not check_logged_in_facebook(facebook_page):
                print("An error has occurred. Please check if user is logged in.")
                return

            # generate new title and description if ad has been posted 0, or 5 or more times
            if posting_property["number_posted_times"] % 5 == 0:
                print(
                    f"Generating title and description for {posting_property['facebook_formatted_address']} - {posting_property['type']}"
                )
                title, description = await generate_title_and_description(
                    str(posting_property)
                )
                posting_property["title"] = title
                posting_property["description"] = description

            await post_on_facebook(facebook_page, posting_property)
            # Update property details
            posting_property["last_posted"] = datetime.now().strftime("%Y-%m-%d")
            posting_property["number_posted_times"] += 1

            # Wait for a few seconds to allow the page to process the save action.
            await facebook_page.wait_for_timeout(15000)

            # go to dashboard and check if the listing is there, if so, then we know it was successful
            await facebook_page.goto(FACEBOOK_SELLER_DASHBOARD_URL)
            await facebook_page.wait_for_timeout(10000)

        # Save the current browser context state (cookies, local storage) for future runs.
        storage = await context.storage_state(path=BROWSER_STATE_PATH)
        await browser.close()

    # save json changes
    with open(PROPERTY_DATA_PATH, "w") as file:
        json.dump(data, file, indent=4)


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
            "content": "You generate professional listings for rental properties. Ensure the text is clean and is optimized for platforms such as Facebook Marketplace and Kijiji. No emojis and no stars, as it looks unprofessional and don't render well on the platform. You can use dashes though for lisiting elements.",
        },
        {
            "role": "user",
            "content": f"Generate a description for a rental property with the following details: {property_details}",
        },
    ]
    response = await AsyncClient().chat(model="qwen3.5", messages=messages)
    description = response.message.content
    messages.append(response.message)

    messages.append(
        {"role": "user", "content": "Now, generate a title for this description."}
    )
    response = await AsyncClient().chat(model="qwen3.5", messages=messages)
    title = response.message.content

    return title, description


# FACEBOOK MARKETPLACE FUNCTIONS
async def check_logged_in_facebook(page):
    """
    NEED TO UPDATE TO BE FACEBOOK SPECIFIC -

    Check if the user is currently logged in to Facebook.

    This function looks for a specific element (the 'Me' button) that is only visible when a user is logged in.
    If the element is found and visible, it returns True, indicating that the user is logged in. Otherwise, it returns False.

    Args:
        page: The Playwright page object representing the current browser page.

    Returns:
        bool: True if the user is logged in, False otherwise.
    """
    return await page.get_by_role("heading", name="New property listing").is_visible()


async def post_on_facebook(page, relevant_property):
    # 1. add photos
    property_images = relevant_property["images"]

    # This bypasses the click and the file browser window entirely
    await page.set_input_files(
        "input[type='file']",
        property_images,
    )

    # # WAIT FOR IMAGES TO UPLOAD
    await page.wait_for_timeout(5000)

    # 2. property type - always rental
    await (
        page.get_by_role("combobox", name="Property for sale or rent")
        .locator("i")
        .click()
    )
    await page.get_by_role("option", name="Rent").click()
    # always house
    await (
        page.get_by_role("combobox", name="Type of property for rent")
        .locator("i")
        .click()
    )
    await page.get_by_role("option", name="House", exact=True).click()

    # 3. private room? - CHANGES LAYOUT
    if relevant_property["private_room"]:
        await page.get_by_role("switch", name="This is a private room in a").check()
        await page.get_by_role("textbox", name="How many people live here?").click()
        await page.get_by_role("textbox", name="How many people live here?").fill("3")

        # 4. price
        rent = relevant_property["rent"]
        await page.get_by_role("textbox", name="Price per month").click()
        await page.get_by_role("textbox", name="Price per month").fill(f"${rent}")

        # 5. bathrooms and bedrooms
        await (
            page.get_by_role("combobox", name="Bathroom type").locator("i").click()
        )  # Only appears if private room is selected, I believe
        await page.get_by_role("option", name="Private").click()
        await page.get_by_role("textbox", name="Number of bedrooms").click()
        await page.get_by_role("textbox", name="Number of bedrooms").fill(
            f"{relevant_property['bedrooms']}"
        )
        await page.get_by_role("textbox", name="Number of bathrooms").click()
        await page.get_by_role("textbox", name="Number of bathrooms").fill(
            f"{relevant_property['bathrooms']}"
        )
    else:
        # 4. bathrooms and bedrooms
        await page.get_by_role("textbox", name="Number of bedrooms").click()
        await page.get_by_role("textbox", name="Number of bedrooms").fill(
            f"{relevant_property['bedrooms']}"
        )
        await page.get_by_role("textbox", name="Number of bathrooms").click()
        await page.get_by_role("textbox", name="Number of bathrooms").fill(
            f"{relevant_property['bathrooms']}"
        )

        # 5. price
        rent = relevant_property["rent"]
        await page.get_by_role("textbox", name="Price per month").click()
        await page.get_by_role("textbox", name="Price per month").fill(f"${rent}")

    # 6. location
    address = relevant_property["facebook_formatted_address"]
    await page.get_by_label("", exact=True).nth(2).click()
    await page.get_by_label("", exact=True).nth(2).fill(address)
    await page.locator("li").filter(has_text=address).get_by_role("option").click()

    # 7. description
    description = relevant_property["description"]
    await page.get_by_role("textbox", name="Property for rent description").click()
    await page.get_by_role("textbox", name="Property for rent description").fill(
        description
    )

    # 8. square footage
    await page.get_by_role("textbox", name="Property square feet").click()
    await page.get_by_role("textbox", name="Property square feet").fill(
        f"{relevant_property['sqft']}"
    )

    # 9. date
    # BETTER TECHNIQUE - JUST TYPE
    await page.get_by_role("combobox", name="Choose date Choose date").click()
    await page.get_by_role("combobox", name="Choose date Choose date").fill(
        relevant_property["date_available"]
    )
    await page.get_by_role("combobox", name="Choose date Choose date").press("Enter")

    # 10. washing machine and dryer
    await (
        page.get_by_role("combobox", name="Washing machine/dryer").locator("i").click()
    )
    await page.get_by_role("option", name="Washing machine/dryer").click()

    # 11. SOMETHING GOES HERE

    # 12. parking

    # 13. cooling and heating

    # 14. next and post
    await page.get_by_role("button", name="Next", exact=True).click()
    await page.get_by_role("button", name="Publish").click()
    print("Ad posted!")


# B. KIJIJI FUNCTIONS

# 3. ADS MANAGER
# REPUSH AD, IF AVAILABLE
# MANAGE SIMPLE CHATS


if __name__ == "__main__":
    asyncio.run(main())
