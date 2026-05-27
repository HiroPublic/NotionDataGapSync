# Notion Date Gap Sync

This tool syncs plain-text and number fields in a Notion database so that each row can show the previous city name and the date gap from the previous `Date` without relying on self-relations.

## Setup

1. Create a Notion Integration.
2. Share the target Notion database with the integration.
3. Add GitHub repository secrets:
   - `NOTION_TOKEN`
   - `NOTION_DATABASE_ID`
4. Ensure the Notion database has:
   - `Date`
5. The script will automatically create these output properties if they do not exist:
   - `Previous Name`
   - `Gap Days`
6. Deploy the Cloudflare Worker in [cloudflare-worker/wrangler.toml](cloudflare-worker/wrangler.toml) and configure these Worker secrets / vars:
   - `WEBHOOK_SECRET`
   - `GITHUB_TOKEN`
   - `GITHUB_OWNER`
   - `GITHUB_REPO`
7. Point your Notion-side webhook or automation to the deployed Worker URL and send the `x-webhook-secret` header.
8. Enable GitHub Actions.

Legacy properties such as `Previous`, `Prev Date`, and `Number` can remain in the database, but they are no longer used by the sync script and can be hidden in the view.

## Current Behavior

The current implementation does not use Notion self-relations.

- `Previous Name` is written directly as plain text
- `Gap Days` is written directly as a number
- pages are ordered by `Date` ascending, then `created_time` ascending
- pages without `Date` are ignored until a date is added

## Trigger Mode

This project uses the following primary trigger:

Notion Database Automation
-> Cloudflare Workers
-> GitHub `repository_dispatch`
-> GitHub Actions

This provides near real-time sync.

## Cloudflare Worker

The Worker accepts any JSON payload, validates the `x-webhook-secret` header, and triggers this repository with:

```json
{
  "event_type": "notion-date-gap-sync"
}
```

Optional incoming JSON is forwarded inside `client_payload.webhook_payload` for debugging.

Suggested Worker secret / variable setup:

1. `WEBHOOK_SECRET`: shared secret checked against the `x-webhook-secret` header.
2. `GITHUB_TOKEN`: GitHub fine-grained or classic token allowed to call `repository_dispatch` on the target repository.
3. `GITHUB_OWNER`: `HiroPublic`
4. `GITHUB_REPO`: `NotionDataGapSync`

Suggested GitHub token scope:

- Fine-grained token
- Repository access: `Only select repositories`
- Repository: `HiroPublic/NotionDataGapSync`
- Repository permission: `Contents` = `Read and write`

## Manual Run

Use GitHub Actions > Sync Notion Date Gap > Run workflow.

## Verification

Check these behaviors after setup:

1. Editing a Notion `Date` triggers sync within tens of seconds.
2. A `repository_dispatch` event starts GitHub Actions.
3. Manual runs from GitHub Actions > `Sync Notion Date Gap` > `Run workflow` also succeed when needed.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Author

Copyright (c) 2026 HiroPublic

This project was developed with assistance from generative AI.
