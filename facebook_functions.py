from datetime import datetime

from playwright.async_api import Page


# FACEBOOK MARKETPLACE FUNCTIONS
async def check_logged_in_facebook(page):
    """
    Check if the user is currently logged in to Facebook.

    This function looks for the 'New property listing' heading that is only visible when a user is logged in.

    Args:
        page: The Playwright page object representing the current browser page.

    Returns:
        bool: True if the user is logged in, False otherwise.
    """
    return await page.get_by_role("heading", name="New property listing").is_visible()


async def format_to_facebook_date(date):
    """Convert date to Facebook's required format."""
    central_date = datetime.strptime(date, "%Y-%m-%d")
    return central_date.strftime("%-d %B %Y")


async def post_on_facebook(page: Page, relevant_property):
    """Post a property listing on Facebook Marketplace."""
    FACEBOOK_DATE = await format_to_facebook_date(relevant_property["date_available"])

    # 1. Add photos
    property_images = relevant_property["images"]

    # Bypass the click and file browser window entirely
    await page.set_input_files(
        "input[type='file']",
        property_images,
    )

    # Wait for images to upload
    await page.wait_for_timeout(5000)

    # 2. Property type - always rental
    await (
        page.get_by_role("combobox", name="Property for sale or rent")
        .locator("i")
        .click()
    )
    await page.get_by_role("option", name="Rent").click()

    # Always house
    await (
        page.get_by_role("combobox", name="Type of property for rent")
        .locator("i")
        .click()
    )
    await page.get_by_role("option", name="House", exact=True).click()

    # 3. Private room? - Changes layout
    if relevant_property["private_room"]:
        await page.get_by_role("switch", name="This is a private room in a").check()
        await page.get_by_role("textbox", name="How many people live here?").click()
        await page.get_by_role("textbox", name="How many people live here?").fill("3")

        # 4. Price
        rent = relevant_property["rent"]
        await page.get_by_role("textbox", name="Price per month").click()
        await page.get_by_role("textbox", name="Price per month").fill(f"${rent}")

        # 5. Bathrooms and bedrooms
        await (
            page.get_by_role("combobox", name="Bathroom type").locator("i").click()
        )  # Only appears if private room is selected
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
        # 4. Bathrooms and bedrooms
        await page.get_by_role("textbox", name="Number of bedrooms").click()
        await page.get_by_role("textbox", name="Number of bedrooms").fill(
            f"{relevant_property['bedrooms']}"
        )
        await page.get_by_role("textbox", name="Number of bathrooms").click()
        await page.get_by_role("textbox", name="Number of bathrooms").fill(
            f"{relevant_property['bathrooms']}"
        )

        # 5. Price
        rent = relevant_property["rent"]
        await page.get_by_role("textbox", name="Price per month").click()
        await page.get_by_role("textbox", name="Price per month").fill(f"${rent}")

    # 6. Location
    address = relevant_property["facebook_formatted_address"]
    await page.get_by_label("", exact=True).nth(2).click()
    await page.get_by_label("", exact=True).nth(2).fill(address)
    await page.locator("li").filter(has_text=address).get_by_role("option").click()

    # 7. Description
    description = relevant_property["description"]
    await page.get_by_role("textbox", name="Property for rent description").click()
    await page.get_by_role("textbox", name="Property for rent description").fill(
        description
    )

    # 8. Square footage
    await page.get_by_role("textbox", name="Property square feet").click()
    await page.get_by_role("textbox", name="Property square feet").fill(
        f"{relevant_property['sqft']}"
    )

    # 9. Date
    # Better technique - just type
    await page.get_by_role("combobox", name="Choose date Choose date").click()
    await page.get_by_role("combobox", name="Choose date Choose date").fill(
        FACEBOOK_DATE
    )
    await page.get_by_role("combobox", name="Choose date Choose date").press("Enter")

    # 10. Washing machine and dryer
    await (
        page.get_by_role("combobox", name="Washing machine/dryer").locator("i").click()
    )
    await page.get_by_role("option", name="Washing machine/dryer").click()

    # 11. Parking
    # TODO: Implement parking selection

    # 12. Cooling and heating
    # TODO: Implement cooling and heating selection

    # 13. Next and post
    await page.get_by_role("button", name="Next", exact=True).click()
    await page.get_by_role("button", name="Publish").click()
    await page.wait_for_timeout(7000)
    print("Ad posted!")
