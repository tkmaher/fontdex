import logging
import os
from urllib.parse import urljoin
import cssutils
import requests
from bs4 import BeautifulSoup

cssutils.log.setLevel(logging.CRITICAL)

def get_all_styles(url):
    """Fetches and parses all inline and external styles from a given URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching the website: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    all_css_rules = []

    # 1. Extract internal styles (<style> tags)
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            all_css_rules.append(
                {"source": "Internal <style> tag", "css_text": style_tag.string}
            )

    # 2. Extract external styles (<link rel="stylesheet"> tags)
    for link_tag in soup.find_all("link", rel="stylesheet"):
        href = link_tag.get("href")
        if not href:
            continue

        # Resolve relative URLs to absolute URLs
        css_url = urljoin(url, href)

        try:
            css_response = requests.get(css_url, headers=headers, timeout=5)
            if css_response.status_code == 200:
                all_css_rules.append(
                    {"source": f"External: {css_url}", "css_text": css_response.text}
                )
        except requests.RequestException:
            print(f"Failed to fetch external stylesheet: {css_url}")

    # 3. Extract inline styles (style="..." attributes)
    for element in soup.find_all(style=True):
        inline_css = element["style"]
        # Wrap inline style in a dummy selector for valid CSS parsing later if needed
        all_css_rules.append(
            {
                "source": f"Inline: <{element.name}> tag",
                "css_text": f"inline-element {{ {inline_css} }}",
            }
        )

    return all_css_rules


def parse_styles(styles):
    """Parses raw CSS text for font-family tags."""
    fonts = {}
    for idx, style_source in enumerate(styles, 1):

        sheet = cssutils.parseString(style_source["css_text"])

        for rule in sheet:
            if rule.type == rule.STYLE_RULE:
                for property in rule.style: 
                    if property.name == 'font-family': 
                        font = property.value.strip()
                        font.replace('"', "")
                        font = font.split(',')[0].strip()
                        fonts[font] = fonts.get(font, 0) + 1

    print(f"Found {len(fonts)} unique font families across {len(styles)} styles.")
    return fonts
            


# Example Usage:
if __name__ == "__main__":
    target_url = "https://youtube.com"  # Replace with your target URL
    raw_styles = get_all_styles(target_url)
    parse_styles(raw_styles)