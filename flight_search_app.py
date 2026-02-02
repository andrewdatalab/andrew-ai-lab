# date : 20251203
# owner : andrew nam

from dotenv import load_dotenv
load_dotenv()

import os
import json
import datetime
import requests
import streamlit as st

# ================== CONFIG ==================
# Local LLM (Ollama via WSL)
OLLAMA_MODEL = "llama3.1:8b"  # or "llama3", etc.
OLLAMA_URL = "http://localhost:11434/api/generate"  # use /api/generate for broad compatibility

# Amadeus (test environment)
AMADEUS_BASE_URL = "https://test.api.amadeus.com"  # test env
AMADEUS_CLIENT_ID = os.getenv("AMADEUS_CLIENT_ID")
AMADEUS_CLIENT_SECRET = os.getenv("AMADEUS_CLIENT_SECRET")


# ================== LLM (Ollama) ==================
def call_llm(prompt: str) -> str:
    """
    Call local Ollama /api/generate endpoint with a simple prompt.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        # /api/generate returns: { "model": "...", "response": "...", "done": true, ... }
        return data.get("response", "").strip()
    except requests.exceptions.RequestException as e:
        return f"ERROR calling Ollama: {e}"


# ================== Amadeus helpers ==================
class AmadeusError(Exception):
    pass


def get_amadeus_access_token() -> str:
    """
    Get OAuth2 access token from Amadeus using client credentials.
    Reads client_id/secret from environment variables.
    """
    if not AMADEUS_CLIENT_ID or not AMADEUS_CLIENT_SECRET:
        raise AmadeusError(
            "AMADEUS_CLIENT_ID or AMADEUS_CLIENT_SECRET not set. "
            "Set them in your Windows terminal before running Streamlit."
        )

    token_url = f"{AMADEUS_BASE_URL}/v1/security/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_CLIENT_ID,
        "client_secret": AMADEUS_CLIENT_SECRET,
    }

    try:
        resp = requests.post(token_url, data=data, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise AmadeusError(f"No access_token in response: {payload}")
        return access_token
    except requests.exceptions.RequestException as e:
        raise AmadeusError(f"Error getting Amadeus token: {e}") from e


def parse_duration_to_hours(duration: str) -> float | None:
    """
    Amadeus duration format example: 'PT10H30M'
    We convert to hours as float.
    If format unexpected, return None.
    """
    if not duration or not duration.startswith("PT"):
        return None

    hours = 0
    minutes = 0
    # Very simple parse, good enough for PTxHxM
    current = duration[2:]  # strip "PT"
    num = ""
    for ch in current:
        if ch.isdigit():
            num += ch
        else:
            if ch == "H" and num:
                hours = int(num)
            elif ch == "M" and num:
                minutes = int(num)
            num = ""

    return round(hours + minutes / 60.0, 2)


def extract_iata(code_or_city: str) -> str:
    """
    Try to extract IATA code if user types 'Sydney (SYD)'.
    Otherwise, uppercase first 3 chars as a naive fallback.
    """
    text = code_or_city.strip()
    if "(" in text and ")" in text:
        start = text.rfind("(") + 1
        end = text.rfind(")")
        iata = text[start:end].strip()
        if len(iata) == 3:
            return iata.upper()
    # fallback: assume user typed 'SYD' or 'syd'
    return text.strip().upper()[:3]


def search_flights_amadeus(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    return_date: str | None,
    max_stops: int,
):
    """
    Call Amadeus Flight Offers Search API and normalize results.
    - origin_city/destination_city: city or 'City (IATA)'
    - departure_date / return_date: 'YYYY-MM-DD'
    - max_stops: 0 for direct only, 1 to allow 1+ stops (Amadeus 'nonStop' filter)
    """
    access_token = get_amadeus_access_token()

    origin_iata = extract_iata(origin_city)
    dest_iata = extract_iata(destination_city)

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    params = {
        "originLocationCode": origin_iata,
        "destinationLocationCode": dest_iata,
        "departureDate": departure_date,
        "adults": 1,
        "currencyCode": "AUD",
        "max": 20,
    }

    # If you want return trip
    if return_date and return_date != departure_date:
        params["returnDate"] = return_date

    # Amadeus supports 'nonStop=true' (no connections)
    if max_stops == 0:
        params["nonStop"] = "true"

    url = f"{AMADEUS_BASE_URL}/v2/shopping/flight-offers"

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise AmadeusError(f"Error calling Amadeus Flight Offers Search: {e}") from e

    data = resp.json()
    offers = data.get("data", [])
    normalized = []

    for offer in offers:
        price_info = offer.get("price", {})
        itineraries = offer.get("itineraries", [])
        validating_airlines = offer.get("validatingAirlineCodes", [])

        if not itineraries:
            continue

        # For simplicity, just take the first itinerary (outbound)
        itinerary = itineraries[0]
        segments = itinerary.get("segments", [])
        if not segments:
            continue

        first_seg = segments[0]
        last_seg = segments[-1]

        airline = (
            validating_airlines[0]
            if validating_airlines
            else first_seg.get("carrierCode", "N/A")
        )
        origin_code = first_seg.get("departure", {}).get("iataCode", "")
        dest_code = last_seg.get("arrival", {}).get("iataCode", "")

        departure_time = first_seg.get("departure", {}).get("at", "")
        arrival_time = last_seg.get("arrival", {}).get("at", "")
        duration_iso = itinerary.get("duration", "")
        duration_hours = parse_duration_to_hours(duration_iso)

        stops = max(len(segments) - 1, 0)

        # If user said allow 1 stop max, we can filter here as well:
        if max_stops == 0 and stops > 0:
            continue
        elif max_stops == 1 and stops > 1:
            # Allow up to 1 stop; filter out 2+ stops.
            continue

        normalized.append(
            {
                "airline": airline,
                "origin": origin_code,
                "destination": dest_code,
                "departure_time": departure_time,
                "arrival_time": arrival_time,
                "stops": stops,
                "price": float(price_info.get("grandTotal", 0.0)),
                "currency": price_info.get("currency", "AUD"),
                "duration_hours": duration_hours,
            }
        )

    return normalized


# ================== Prompt builder ==================
def build_prompt(origin, destination, start_date, end_date, max_stops, flights):
    """
    Build the prompt for the LLM: give context, user prefs, and the candidate flights in JSON.
    Ask the model to pick the best deals and respond in markdown.
    """
    flights_json = json.dumps(flights, ensure_ascii=False, indent=2)

    prompt = f"""
You are a travel assistant that selects the best flight deals from a list of candidate flights.

User preferences:
- Origin: {origin}
- Destination: {destination}
- Earliest departure: {start_date}
- Latest return: {end_date}
- Maximum stops allowed: {max_stops} (0 = direct only, 1 = allow 1 stop)

Here is the list of candidate flights in JSON format:

{flights_json}

Please:
1. Choose up to 3 of the best options (balance of price and total duration).
2. Output a short markdown table with columns:
   - Airline
   - Origin
   - Destination
   - Stops
   - Price (with currency)
   - Duration (hours if available)
3. Then add a brief explanation in plain text (2–4 sentences) about why you picked these.

Reply ONLY in markdown.
"""
    return prompt.strip()


# ================== Streamlit UI ==================
def main():
    st.title("🔍 Local Flight Deal Agent (Amadeus API + Ollama + Streamlit)")
    st.write("Running on Windows 11 with a local LLM inside WSL (Ollama) and real flight data from Amadeus (test environment).")

    st.subheader("Search Parameters")

    today = datetime.date.today()
    default_return = today + datetime.timedelta(days=7)

    origin_input = st.text_input("Departure city / airport", value="Sydney (SYD)")
    destination_input = st.text_input("Destination city / airport", value="Seoul (ICN)")

    date_range = st.date_input(
        "Travel dates (single date or range)",
        value=(today, default_return),
    )

    if isinstance(date_range, (list, tuple)):
        if len(date_range) == 2:
            start_date_obj, end_date_obj = date_range
        elif len(date_range) == 1:
            start_date_obj = end_date_obj = date_range[0]
        else:
            start_date_obj = end_date_obj = today
    else:
        start_date_obj = end_date_obj = date_range

    start_date_str = start_date_obj.isoformat()
    end_date_str = end_date_obj.isoformat()

    flight_option = st.radio(
        "Flight option",
        options=["Direct only", "Allow 1 stop"],
        index=0,
        horizontal=True,
    )

    max_stops = 0 if flight_option == "Direct only" else 1

    st.markdown("---")

    if st.button("✈️ Search Real Flights (Amadeus)"):
        if not origin_input or not destination_input:
            st.error("Please enter both departure and destination.")
            return

        try:
            with st.spinner("Contacting Amadeus API for live offers..."):
                flights = search_flights_amadeus(
                    origin_city=origin_input,
                    destination_city=destination_input,
                    departure_date=start_date_str,
                    return_date=end_date_str,
                    max_stops=max_stops,
                )
        except AmadeusError as e:
            st.error(str(e))
            return

        if not flights:
            st.warning("No flights found for these criteria. Try changing dates or allowing more stops.")
            return

        st.write("Found the following flight offers (Amadeus test data):")
        st.dataframe(flights, use_container_width=True)

        st.markdown("-----")
        st.write("Asking the local LLM (Ollama) to pick the best options...")

        prompt = build_prompt(
            origin=origin_input,
            destination=destination_input,
            start_date=start_date_str,
            end_date=end_date_str,
            max_stops=max_stops,
            flights=flights,
        )

        llm_response = call_llm(prompt)

        if llm_response.startswith("ERROR calling Ollama"):
            st.error(llm_response)
        else:
            st.markdown("### LLM Recommendation")
            st.markdown(llm_response)


if __name__ == "__main__":
    main()
