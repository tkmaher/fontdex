0. Installed Bun and effect-ts, two emergent tools (a package manager and typescript extension, respectively) that I haven't used before.
1. Began writing a Python script for crawling top domains.
    a. Used 20000-domain list from Cloudflare Radar - https://radar.cloudflare.com/domains
    b. Used WebShrinker API to classify sites into WebShrinker's 40 categories - https://docs.webshrinker.com/v3/website-category-api.html
    c. Not using WebShrinker anymore---trying DomScan https://domscan.net/docs/categorization. Example query:

    curl -X POST "https://domscan.net/v1/categorize/bulk" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: $DOMSCAN_API_KEY" \
        -d '{
        "urls": [
            "github.com",
            "amazon.com",
            "bbc.com"
        ]
    }'

    d. Not using DomScan, since the categories are often mislabeled. New process via Curlie+bart-large-mnli:
    Pipeline:
    1. Download Majestic Million (free CSV, no key, updated daily) -> top 10k domains by rank.
        Cached to disk; re-run skips the download if already present.
    2. Download the Curlie directory dump (free, open-license, human-curated categories)
        and join it against the domain list. Cached to disk; parsed result is also cached.
    3. For domains Curlie doesn't cover, fetch the homepage title (politely, with delays)
        and classify it locally with a free zero-shot model (facebook/bart-large-mnli via
        Hugging Face transformers). Progress is written incrementally to a checkpoint file,
        one row at a time, so an interrupted run resumes exactly where it left off with no
        repeated work and no repeated downloads.

    e. 10000 sites have now been categorized on my local machine.
2. Began writing a Python script to scrape the font-family tags of the domains.
    a. Created a font targeting script based on an existing style parser for DOMs that considers stylesheets, inline styles, and variables.
    b. Vibecoded a robust, fault-tolerant scraping program to run locally over the list of domains. The program tracks the top three fonts of each site and logs any sites that error-out for later parsing. I plan to create an additional script to determine the individual qualities of each common font and categorize them that way. (Look into existing font categorization APIs/databases)
    c. From this point, I don't want to vibecode anything else.
    d. Rules for font tag filtering:
        - Replace pattern 'aA' -> 'a A'
        - Replace '_' -> ' '
        - Replace '-' -> ' ' (this means system-ui becomes system ui)
        - Capitalize all words
        - Delete anything with 'icon'
        - Remove '\'
        - Delete anything with '/' or 'px' or ':' or ';'

        After:
        - Shift blank spaces left
        - Remove duplicates after filtering

3. Going back to smooth over the dataset. Classified the pipeline into three stages:
    1. Scraping the fonts---two problems.
        a. One one hand, need to handle dead sites, 403 errors, etc. THere are over 2000 sites like this. ~8000 have been successfully scraped.
        b. Secondarily, need to handle js-rendered sites that don't contain overt fonts in their stylesheets. Using playwright for this.
        c. (Note: errored domains, if successfully re-crawled, get added to the end of the scraped csv which destroys the popularity-order originally from the majestic million list.)
    2. Sanitizing the fonts---pretty straightforward. Documented above.
    3. Classifying the fonts---much more complex. Need a combination of the Google Fonts API and perhaps some other things? Most fonts, even once they're sanitized, don't turn up in the API at all. This will be the hardest challenge, but it's essential if I want true statistical analysis. Will think about this more.
        - Ok, many of the fonts have been categorized using Google Font API + Google Gemini. Still need to:
        - Sanitize the "font descriptions" to remove commas and errors
        - Ensure 1:1 correlation between the domain list fonts and the font list fonts
        - Categorize the ~500 remaining fonts somehow