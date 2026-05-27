import os
import sys
from datetime import date
from typing import Any

import requests


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
DATE_PROPERTY = "Date"
PREVIOUS_NAME_PROPERTY = "Previous Name"
GAP_DAYS_PROPERTY = "Gap Days"


class NotionSyncError(Exception):
    pass


class NotionClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def get_database(self, database_id: str) -> dict[str, Any]:
        response = self.session.get(f"{NOTION_API_BASE}/databases/{database_id}", timeout=30)
        return self._parse_response(response, f"Failed to fetch database {database_id}")

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        response = self.session.get(f"{NOTION_API_BASE}/data_sources/{data_source_id}", timeout=30)
        return self._parse_response(response, f"Failed to fetch data source {data_source_id}")

    def update_data_source_properties(
        self,
        data_source_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.session.patch(
            f"{NOTION_API_BASE}/data_sources/{data_source_id}",
            json={"properties": properties},
            timeout=30,
        )
        return self._parse_response(response, f"Failed to update data source {data_source_id}")

    def query_data_source(self, data_source_id: str, start_cursor: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page_size": 100,
            "sorts": [
                {"property": DATE_PROPERTY, "direction": "ascending"},
                {"timestamp": "created_time", "direction": "ascending"},
            ],
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor

        response = self.session.post(
            f"{NOTION_API_BASE}/data_sources/{data_source_id}/query",
            json=payload,
            timeout=30,
        )
        return self._parse_response(response, "Failed to query data source")

    def update_page_fields(
        self,
        page_id: str,
        previous_name: str | None,
        gap_days: int | None,
    ) -> None:
        rich_text = [] if not previous_name else [{"type": "text", "text": {"content": previous_name}}]
        payload = {
            "properties": {
                PREVIOUS_NAME_PROPERTY: {
                    "rich_text": rich_text,
                },
                GAP_DAYS_PROPERTY: {
                    "number": gap_days,
                },
            }
        }
        response = self.session.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            json=payload,
            timeout=30,
        )
        self._parse_response(response, f"Failed to update page {page_id}")

    @staticmethod
    def _parse_response(response: requests.Response, context: str) -> dict[str, Any]:
        if response.ok:
            return response.json()

        body = response.text.strip()
        raise NotionSyncError(f"{context}: HTTP {response.status_code} - {body}")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise NotionSyncError(f"{name} is not set.")


def extract_single_data_source_id(database: dict[str, Any], database_id: str) -> str:
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise NotionSyncError(f"No data sources found in database {database_id}.")
    if len(data_sources) != 1:
        raise NotionSyncError(
            f"Expected exactly 1 data source in database {database_id}, found {len(data_sources)}."
        )
    return data_sources[0]["id"]


def ensure_schema(client: NotionClient, data_source_id: str, data_source: dict[str, Any]) -> dict[str, Any]:
    properties = data_source.get("properties", {})

    date_property = properties.get(DATE_PROPERTY)
    if date_property is None:
        raise NotionSyncError(f'Missing required property "{DATE_PROPERTY}".')
    if date_property.get("type") != "date":
        raise NotionSyncError(f'Property "{DATE_PROPERTY}" must be type "date".')

    schema_updates: dict[str, Any] = {}

    previous_name_property = properties.get(PREVIOUS_NAME_PROPERTY)
    if previous_name_property is None:
        schema_updates[PREVIOUS_NAME_PROPERTY] = {"rich_text": {}}
    elif previous_name_property.get("type") != "rich_text":
        raise NotionSyncError(
            f'Property "{PREVIOUS_NAME_PROPERTY}" must be type "rich_text".'
        )

    gap_days_property = properties.get(GAP_DAYS_PROPERTY)
    if gap_days_property is None:
        schema_updates[GAP_DAYS_PROPERTY] = {"number": {"format": "number"}}
    elif gap_days_property.get("type") != "number":
        raise NotionSyncError(f'Property "{GAP_DAYS_PROPERTY}" must be type "number".')

    if not schema_updates:
        return data_source

    return client.update_data_source_properties(data_source_id, schema_updates)


def fetch_all_pages(client: NotionClient, data_source_id: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    next_cursor: str | None = None

    while True:
        response = client.query_data_source(data_source_id, start_cursor=next_cursor)
        pages.extend(item for item in response.get("results", []) if item.get("object") == "page")
        if not response.get("has_more"):
            return pages
        next_cursor = response.get("next_cursor")


def get_date_value(page: dict[str, Any]) -> str | None:
    properties = page.get("properties", {})
    date_property = properties.get(DATE_PROPERTY, {})
    date_value = date_property.get("date")
    if not date_value:
        return None
    return date_value.get("start")


def parse_notion_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def get_page_label(page: dict[str, Any]) -> str:
    properties = page.get("properties", {})
    for prop in properties.values():
        if prop.get("type") != "title":
            continue
        title_items = prop.get("title", [])
        text = "".join(item.get("plain_text", "") for item in title_items).strip()
        return text or page["id"]
    return page["id"]


def get_current_previous_name(page: dict[str, Any]) -> str | None:
    rich_text_items = page.get("properties", {}).get(PREVIOUS_NAME_PROPERTY, {}).get("rich_text", [])
    if not rich_text_items:
        return None
    value = "".join(item.get("plain_text", "") for item in rich_text_items).strip()
    return value or None


def get_current_gap_days(page: dict[str, Any]) -> int | None:
    value = page.get("properties", {}).get(GAP_DAYS_PROPERTY, {}).get("number")
    if value is None:
        return None
    return int(value)


def sync_previous_fields(client: NotionClient, pages: list[dict[str, Any]]) -> tuple[int, int]:
    updated = 0
    skipped = 0
    previous_page: dict[str, Any] | None = None

    for page in pages:
        current_previous_name = get_current_previous_name(page)
        current_gap_days = get_current_gap_days(page)

        expected_previous_name = None if previous_page is None else get_page_label(previous_page)
        expected_gap_days = None
        if previous_page is not None:
            current_date = parse_notion_date(get_date_value(page) or "")
            previous_date = parse_notion_date(get_date_value(previous_page) or "")
            expected_gap_days = (current_date - previous_date).days

        if current_previous_name != expected_previous_name or current_gap_days != expected_gap_days:
            client.update_page_fields(page["id"], expected_previous_name, expected_gap_days)
            updated += 1
        else:
            skipped += 1

        previous_page = page

    return updated, skipped


def main() -> int:
    try:
        notion_token = require_env("NOTION_TOKEN")
        database_id = require_env("NOTION_DATABASE_ID")

        client = NotionClient(notion_token)
        database = client.get_database(database_id)
        data_source_id = extract_single_data_source_id(database, database_id)
        data_source = client.get_data_source(data_source_id)
        ensure_schema(client, data_source_id, data_source)

        pages = fetch_all_pages(client, data_source_id)
        dated_pages = [page for page in pages if get_date_value(page) is not None]
        updated, skipped = sync_previous_fields(client, dated_pages)

        print(f"Fetched pages: {len(pages)}")
        print(f"Dated pages: {len(dated_pages)}")
        print(f"Updated: {updated}")
        print(f"Skipped: {skipped}")
        print("Done.")
        return 0
    except NotionSyncError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
