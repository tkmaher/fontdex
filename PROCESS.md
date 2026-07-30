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