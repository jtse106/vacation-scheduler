import requests

API_KEY = "sk-X9beINrFGNsX5cLWDnxBClBoOJN9l5r2pWersYG0wghzhDh1jUeDLqxXNiYUp6o1"

url = "https://opencode.ai/zen/v1/responses"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "model": "gpt-5.4-nano",
    "input": "responding only with a number with 2 decimal places, 1.0-10.0, decimals are oK out to 2 points, how serious is a person receiving active compressions in ACLS, no pulse? Don't put any other text. 10 is the most serious "
}

response = requests.post(url, headers=headers, json=data)

print("Status Code:", response.status_code)

try:
    result = response.json()
    print(result)

    # Try to extract text output cleanly
    if "output" in result:
        for item in result["output"]:
            if "content" in item:
                for c in item["content"]:
                    if c.get("type") == "output_text":
                        print("\nModel Output:")
                        print(c["text"])
except:
    print(response.text)