import json
import http.client
import re
import urllib.error
import urllib.request
from datetime import date, datetime

from flask import current_app


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


def _zen_chat(messages: list[dict], *, temperature: float = 0.2, max_tokens: int = 500):
    api_key = (current_app.config.get("ZEN_API_KEY") or "").strip()
    if not api_key:
        return None

    request_body = json.dumps(
        {
            "model": current_app.config.get("ZEN_MODEL", "gpt-4o-mini"),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        current_app.config.get("ZEN_API_URL", "https://gateway.theturbo.ai/v1/chat/completions"),
        data=request_body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, http.client.HTTPException, OSError):
        return None


def _parse_named_date(snippet: str, *, fallback_year: int):
    cleaned = re.sub(r"(\d)(st|nd|rd|th)", r"\1", snippet.strip(), flags=re.IGNORECASE)
    match = re.match(r"^(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})(?:,?\s*(?P<year>\d{4}))?$", cleaned)
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

    iso_single = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if iso_single:
        value = iso_single.group(1)
        return value, value

    named_range = re.search(
        r"([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?)\s*(?:to|through|until|\-)\s*([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?)",
        text,
        re.IGNORECASE,
    )
    if named_range:
        return (
            _parse_named_date(named_range.group(1), fallback_year=today.year),
            _parse_named_date(named_range.group(2), fallback_year=today.year),
        )

    shared_month_range = re.search(
        r"([A-Za-z]+)\s+(\d{1,2})\s*(?:to|through|\-)\s*(\d{1,2})(?:,\s*(\d{4}))?",
        text,
        re.IGNORECASE,
    )
    if shared_month_range:
        month = shared_month_range.group(1)
        year_value = int(shared_month_range.group(4) or today.year)
        start = _parse_named_date(f"{month} {shared_month_range.group(2)}, {year_value}", fallback_year=year_value)
        end = _parse_named_date(f"{month} {shared_month_range.group(3)}, {year_value}", fallback_year=year_value)
        return start, end

    named_single = re.search(r"([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?)", text)
    if named_single:
        value = _parse_named_date(named_single.group(1), fallback_year=today.year)
        return value, value

    raise ValueError("I could not find a usable date or date range in that request.")


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


def _fallback_parse(prompt: str, manageable_physicians: list[dict], default_physician: dict):
    today = date.today()
    start_date, end_date = _parse_dates_fallback(prompt, today)
    physician = _match_physician(prompt, manageable_physicians, default_physician)
    return {
        "physicianId": physician["id"],
        "physicianName": physician["fullName"],
        "startDate": start_date,
        "endDate": end_date,
        "note": prompt.strip(),
        "explanation": "Parsed locally from the free-text request.",
        "usedRemoteModel": False,
    }


def parse_natural_language_request(prompt: str, manageable_physicians: list[dict], default_physician: dict):
    cleaned_prompt = (prompt or "").strip()
    if not cleaned_prompt:
        raise ValueError("Enter a free-text vacation request before sending it to the assistant.")

    physician_lines = "\n".join(f"- {item['fullName']} (@{item['username']}) id={item['id']}" for item in manageable_physicians)
    system_prompt = (
        "You extract physician vacation scheduling requests.\n"
        "Return strict JSON with keys physicianId, startDate, endDate, note, explanation.\n"
        "Use ISO dates. Pick only from the provided physicians. If the request implies one day, set startDate and endDate to the same date."
    )
    user_prompt = (
        f"Available physicians:\n{physician_lines}\n\n"
        f"Default physician if not specified: {default_physician['fullName']} (id={default_physician['id']})\n\n"
        f"Request:\n{cleaned_prompt}"
    )
    remote = _zen_chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=350,
    )
    if remote:
        parsed = _extract_json(remote)
        return {
            "physicianId": int(parsed.get("physicianId") or default_physician["id"]),
            "physicianName": next(
                (item["fullName"] for item in manageable_physicians if item["id"] == int(parsed.get("physicianId") or default_physician["id"])),
                default_physician["fullName"],
            ),
            "startDate": parsed["startDate"],
            "endDate": parsed["endDate"],
            "note": (parsed.get("note") or cleaned_prompt).strip(),
            "explanation": (parsed.get("explanation") or "Parsed by the assistant.").strip(),
            "usedRemoteModel": True,
        }
    return _fallback_parse(cleaned_prompt, manageable_physicians, default_physician)


def explain_conflict_naturally(prompt: str, conflict_message: str) -> str:
    cleaned_prompt = (prompt or "").strip()
    system_prompt = (
        "You explain schedule conflicts to physicians in plain language.\n"
        "Use 1-3 concise sentences. Do not add medical advice or unsupported details."
    )
    user_prompt = (
        f"Original request:\n{cleaned_prompt or 'No original prompt available.'}\n\n"
        f"Scheduling engine response:\n{conflict_message}"
    )
    remote = _zen_chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=180,
    )
    if remote:
        return remote.strip()
    return conflict_message
