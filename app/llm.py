import json
import re
from collections.abc import Mapping
from datetime import date
import http.client
import urllib.error
import urllib.request

from flask import current_app

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency
    requests = None


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

ASSISTANT_ACTIONS = {"create", "update", "cancel", "remove_days"}
MONTH_PATTERN = r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"


def _extract_json(text: str):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _extract_response_text(payload: dict):
    if "output" in payload:
        parts = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        if parts:
            return "\n".join(parts).strip()
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def _zen_text(prompt: str):
    api_key = (current_app.config.get("ZEN_API_KEY") or "").strip()
    if not api_key:
        return None

    url = current_app.config.get("ZEN_API_URL", "https://opencode.ai/zen/v1/responses")
    if "/responses" in url:
        request_body = json.dumps(
            {
                "model": current_app.config.get("ZEN_MODEL", "gpt-5.4-nano"),
                "input": prompt,
            }
        ).encode("utf-8")
    else:
        request_body = json.dumps(
            {
                "model": current_app.config.get("ZEN_MODEL", "gpt-5.4-nano"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 600,
            }
        ).encode("utf-8")

    try:
        if requests is not None:
            response = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                data=request_body,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        else:
            request = urllib.request.Request(
                url,
                data=request_body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        return _extract_response_text(payload)
    except (
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
        requests.RequestException if requests is not None else Exception,
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        http.client.HTTPException,
        OSError,
    ):
        current_app.logger.warning("Assistant API request failed.", exc_info=True)
        return None


def _parse_named_date(snippet: str, *, fallback_year: int):
    cleaned = re.sub(r"(\d)(st|nd|rd|th)", r"\1", snippet.strip(), flags=re.IGNORECASE)
    match = re.match(rf"^(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}})(?:,?\s*(?P<year>\d{{4}}))?$", cleaned, re.IGNORECASE)
    if not match:
        raise ValueError("Unable to parse date")
    month = MONTHS[match.group("month").lower()]
    day_value = int(match.group("day"))
    year_value = int(match.group("year") or fallback_year)
    return date(year_value, month, day_value).isoformat()


def _parse_dates_fallback(prompt: str, today: date):
    text = prompt.strip()
    iso_range = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|through|\-|until)\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if iso_range:
        return iso_range.group(1), iso_range.group(2)

    named_range = re.search(
        rf"({MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?)\s*(?:to|through|until|\-)\s*({MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
        text,
        re.IGNORECASE,
    )
    if named_range:
        return (
            _parse_named_date(named_range.group(1), fallback_year=today.year),
            _parse_named_date(named_range.group(2), fallback_year=today.year),
        )

    shared_month_range = re.search(
        rf"({MONTH_PATTERN})\s+(\d{{1,2}})\s*(?:to|through|\-)\s*(\d{{1,2}})(?:,\s*(\d{{4}}))?",
        text,
        re.IGNORECASE,
    )
    if shared_month_range:
        month = shared_month_range.group(1)
        year_value = int(shared_month_range.group(4) or today.year)
        start = _parse_named_date(f"{month} {shared_month_range.group(2)}, {year_value}", fallback_year=year_value)
        end = _parse_named_date(f"{month} {shared_month_range.group(3)}, {year_value}", fallback_year=year_value)
        return start, end

    iso_single = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if iso_single:
        value = iso_single.group(1)
        return value, value

    named_single = re.search(rf"({MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?)", text, re.IGNORECASE)
    if named_single:
        value = _parse_named_date(named_single.group(1), fallback_year=today.year)
        return value, value

    raise ValueError("I could not find a usable date or date range in that request.")


def _extract_date_ranges(prompt: str, today: date):
    range_matches = []
    single_matches = []

    range_patterns = [
        r"(\d{4}-\d{2}-\d{2})\s*(?:to|through|\-|until)\s*(\d{4}-\d{2}-\d{2})",
        rf"({MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?)\s*(?:to|through|until|\-)\s*({MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
        rf"({MONTH_PATTERN})\s+(\d{{1,2}})\s*(?:to|through|\-)\s*(\d{{1,2}})(?:,\s*(\d{{4}}))?",
    ]
    single_patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        rf"({MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
    ]

    for pattern in range_patterns:
        for match in re.finditer(pattern, prompt, re.IGNORECASE):
            try:
                if pattern.startswith(r"(\d{4}"):
                    start, end = match.group(1), match.group(2)
                elif pattern.startswith("(") and "january" in pattern:
                    start = _parse_named_date(match.group(1), fallback_year=today.year)
                    end = _parse_named_date(match.group(2), fallback_year=today.year)
                else:
                    month = match.group(1)
                    year_value = int(match.group(4) or today.year)
                    start = _parse_named_date(f"{month} {match.group(2)}, {year_value}", fallback_year=year_value)
                    end = _parse_named_date(f"{month} {match.group(3)}, {year_value}", fallback_year=year_value)
                range_matches.append((match.start(), match.end(), start, end))
            except ValueError:
                continue

    for pattern in single_patterns:
        for match in re.finditer(pattern, prompt, re.IGNORECASE):
            if any(range_start <= match.start() and match.end() <= range_end for range_start, range_end, _, _ in range_matches):
                continue
            try:
                if pattern.startswith(r"(\d{4}"):
                    start = end = match.group(1)
                else:
                    start = end = _parse_named_date(match.group(1), fallback_year=today.year)
                single_matches.append((match.start(), match.end(), start, end))
            except ValueError:
                continue

    matches = range_matches + single_matches
    matches.sort(key=lambda item: item[0])
    ranges = []
    seen = set()
    for _, _, start, end in matches:
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        ranges.append(key)
    return ranges


def _match_physician(prompt: str, manageable_physicians: list[dict], default_physician: dict):
    lowered = prompt.lower()
    for physician in manageable_physicians:
        if physician["fullName"].lower() in lowered:
            return physician
        last_name = physician["fullName"].split()[-1].lower()
        if re.search(rf"\b{re.escape(last_name)}\b", lowered):
            return physician
        if physician["username"].lower() in lowered:
            return physician
    return default_physician


def _active_requests_for_physician(existing_requests: list[dict], physician_id: int):
    return [
        item
        for item in existing_requests
        if item["physicianId"] == physician_id and item["status"] not in {"canceled"}
    ]


def _find_request(existing_requests: list[dict], physician_id: int, start_date: str | None = None, end_date: str | None = None):
    active = _active_requests_for_physician(existing_requests, physician_id)
    if start_date and end_date:
        exact = [item for item in active if item["startDate"] == start_date and item["endDate"] == end_date]
        if exact:
            return exact[0]
        overlapping = [item for item in active if item["startDate"] <= end_date and item["endDate"] >= start_date]
        if len(overlapping) == 1:
            return overlapping[0]
    if len(active) == 1:
        return active[0]
    return None


def _fallback_parse(prompt: str, manageable_physicians: list[dict], default_physician: dict, existing_requests: list[dict]):
    today = date.today()
    lowered = prompt.lower()
    physician = _match_physician(prompt, manageable_physicians, default_physician)
    mentioned_ranges = _extract_date_ranges(prompt, today)

    if any(word in lowered for word in ("change", "reschedule", "move", "shift", "update")):
        if len(mentioned_ranges) < 2:
            raise ValueError("I could not tell which dates to change from and to. Include the old dates and the new dates.")
        source_start, source_end = mentioned_ranges[0]
        target_start, target_end = mentioned_ranges[1]
        request_row = _find_request(existing_requests, physician["id"], source_start, source_end)
        if not request_row:
            raise ValueError("I could not match the existing vacation you want to change.")
        return {
            "action": "update",
            "physicianId": physician["id"],
            "physicianName": physician["fullName"],
            "requestId": request_row["id"],
            "startDate": target_start,
            "endDate": target_end,
            "removeStartDate": None,
            "removeEndDate": None,
            "note": prompt.strip(),
            "explanation": "Parsed locally as a vacation update request.",
            "usedRemoteModel": False,
        }

    if any(word in lowered for word in ("cancel", "delete", "remove", "unassign")):
        if mentioned_ranges:
            request_row = _find_request(existing_requests, physician["id"], mentioned_ranges[0][0], mentioned_ranges[0][1])
        else:
            request_row = _find_request(existing_requests, physician["id"])
        if not request_row:
            raise ValueError("I could not match the existing vacation you want to remove.")
        if mentioned_ranges:
            overlap_start = max(mentioned_ranges[0][0], request_row["startDate"])
            overlap_end = min(mentioned_ranges[0][1], request_row["endDate"])
        else:
            overlap_start = request_row["startDate"]
            overlap_end = request_row["endDate"]
        action = "cancel" if overlap_start == request_row["startDate"] and overlap_end == request_row["endDate"] else "remove_days"
        return {
            "action": action,
            "physicianId": physician["id"],
            "physicianName": physician["fullName"],
            "requestId": request_row["id"],
            "startDate": None,
            "endDate": None,
            "removeStartDate": overlap_start,
            "removeEndDate": overlap_end,
            "note": prompt.strip(),
            "explanation": "Parsed locally as a vacation removal request.",
            "usedRemoteModel": False,
        }

    start_date, end_date = _parse_dates_fallback(prompt, today)
    return {
        "action": "create",
        "physicianId": physician["id"],
        "physicianName": physician["fullName"],
        "requestId": None,
        "startDate": start_date,
        "endDate": end_date,
        "removeStartDate": None,
        "removeEndDate": None,
        "note": prompt.strip(),
        "explanation": "Parsed locally from the free-text request.",
        "usedRemoteModel": False,
    }


def _normalize_remote_parse(parsed: dict, cleaned_prompt: str, manageable_physicians: list[dict], default_physician: dict, existing_requests: list[dict]):
    if isinstance(parsed, list):
        parsed = next(
            (
                item
                for item in parsed
                if isinstance(item, Mapping) and any(key in item for key in ("action", "physicianId", "requestId", "startDate", "endDate"))
            ),
            parsed[0] if parsed and isinstance(parsed[0], Mapping) else None,
        )
    if not isinstance(parsed, Mapping):
        raise ValueError("Assistant returned JSON in an unexpected shape.")

    action = str(parsed.get("action") or "create").strip().lower()
    if action not in ASSISTANT_ACTIONS:
        raise ValueError("Assistant returned an invalid action.")

    physician_id = int(parsed.get("physicianId") or default_physician["id"])
    physician = next((item for item in manageable_physicians if item["id"] == physician_id), None)
    if not physician:
        raise ValueError("Assistant selected an unavailable physician.")

    request_id = parsed.get("requestId")
    if request_id in {"", None, "null"}:
        request_id = None
    elif request_id is not None:
        request_id = int(request_id)

    request_row = None
    if request_id is not None:
        request_row = next((item for item in existing_requests if item["id"] == request_id), None)
        if not request_row:
            raise ValueError("Assistant selected an unavailable vacation entry.")
        physician_id = request_row["physicianId"]
        physician = next((item for item in manageable_physicians if item["id"] == physician_id), None) or physician

    start_date = parsed.get("startDate")
    end_date = parsed.get("endDate")
    remove_start = parsed.get("removeStartDate")
    remove_end = parsed.get("removeEndDate")

    if action in {"create", "update"}:
        start_date = date.fromisoformat(start_date).isoformat()
        end_date = date.fromisoformat(end_date).isoformat()
    else:
        start_date = None
        end_date = None

    if action == "remove_days":
        remove_start = date.fromisoformat(remove_start or parsed.get("startDate")).isoformat()
        remove_end = date.fromisoformat(remove_end or parsed.get("endDate")).isoformat()
    else:
        remove_start = None
        remove_end = None

    if action in {"update", "cancel", "remove_days"} and request_id is None:
        raise ValueError("Assistant did not identify the existing vacation entry to modify.")

    return {
        "action": action,
        "physicianId": physician_id,
        "physicianName": physician["fullName"],
        "requestId": request_id,
        "startDate": start_date,
        "endDate": end_date,
        "removeStartDate": remove_start,
        "removeEndDate": remove_end,
        "note": (parsed.get("note") or cleaned_prompt).strip(),
        "explanation": (parsed.get("explanation") or "Parsed by the assistant.").strip(),
        "usedRemoteModel": True,
    }


def parse_natural_language_request(prompt: str, manageable_physicians: list[dict], default_physician: dict, existing_requests: list[dict] | None = None):
    cleaned_prompt = (prompt or "").strip()
    if not cleaned_prompt:
        raise ValueError("Enter a free-text vacation request before sending it to the assistant.")

    existing_requests = existing_requests or []
    remote_enabled = bool((current_app.config.get("ZEN_API_KEY") or "").strip())
    physician_lines = "\n".join(f"- {item['fullName']} (@{item['username']}) id={item['id']}" for item in manageable_physicians)
    request_lines = "\n".join(
        f"- requestId={item['id']} physicianId={item['physicianId']} physician={item['physician']} status={item['status']} dates={item['startDate']} to {item['endDate']}"
        for item in existing_requests
        if item["status"] != "canceled"
    ) or "- none"

    instruction_prompt = (
        "You are extracting structured vacation scheduler actions.\n"
        "Return strict JSON only.\n"
        "Allowed actions: create, update, cancel, remove_days.\n"
        "Fields: action, physicianId, requestId, startDate, endDate, removeStartDate, removeEndDate, note, explanation.\n"
        "Use ISO dates.\n"
        "Use only physicianId values from the provided physician list.\n"
        "For update/cancel/remove_days, use only requestId values from the provided request list.\n"
        "For remove_days, removeStartDate/removeEndDate must describe only the subrange being removed.\n"
        "If the user is creating a new vacation, action=create and requestId=null.\n"
        "If the user is deleting the whole vacation, action=cancel.\n"
        "If the user is deleting only part of a vacation, action=remove_days.\n"
        "If the user is changing dates, action=update."
    )
    prompt_block = (
        f"{instruction_prompt}\n\n"
        f"Today's date: {date.today().isoformat()}\n\n"
        f"Available physicians:\n{physician_lines}\n\n"
        f"Existing manageable vacation requests:\n{request_lines}\n\n"
        f"Default physician if not specified: {default_physician['fullName']} (id={default_physician['id']})\n\n"
        f"User request:\n{cleaned_prompt}"
    )
    remote = _zen_text(prompt_block)
    if remote:
        try:
            parsed = _extract_json(remote)
            return _normalize_remote_parse(parsed, cleaned_prompt, manageable_physicians, default_physician, existing_requests)
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            current_app.logger.warning("Assistant response was invalid; falling back to local parser.")

    try:
        return _fallback_parse(cleaned_prompt, manageable_physicians, default_physician, existing_requests)
    except ValueError as exc:
        if remote_enabled:
            raise ValueError(
                f"{exc} The assistant gateway is unavailable or returned an unusable response. "
                "Use explicit dates like 2026-06-09 to 2026-06-11, or fix ZEN_API_KEY / ZEN_MODEL / ZEN_API_URL."
            ) from exc
        raise


def explain_conflict_naturally(prompt: str, conflict_message: str) -> str:
    cleaned_prompt = (prompt or "").strip()
    response = _zen_text(
        "Explain this scheduling conflict in 1-3 concise sentences with no extra formatting.\n\n"
        f"Original request:\n{cleaned_prompt or 'No original prompt available.'}\n\n"
        f"Scheduling engine response:\n{conflict_message}"
    )
    if response:
        return response.strip()
    return conflict_message
