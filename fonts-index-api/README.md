## Deploy

- `npx wrangler d1 execute fonts-index --remote --file=../data/fonts/4-final/fonts_classified_out.sql`
- `npx wrangler d1 execute fonts-index --remote --file=../data/fonts/4-final/websites_clean_out.sql`

## Scripts

- `pnpm run dev` starts the vinext dev server.
- `pnpm run build` builds the Cloudflare Worker output.
- `pnpm run start` starts the built Worker locally with Wrangler.
- `pnpm run deploy` deploys the Cloudflare Worker.

