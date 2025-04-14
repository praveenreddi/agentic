"""
Property lookup functionality for the Agentic Inventory Service.
"""

import time
import json
import difflib
import requests
from uuid import uuid4
from pathlib import Path
from typing import Dict, List, Optional, Any
from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger
from agentic_inventory.framework.llm.llm_mngmt import llm_client

llm = llm_client.get_llm()


def normalize_property_name(property_name: str) -> str:
    """Normalize property name by removing common suffixes and standardizing format."""
    replacements = [
        (", a Hilton Grand Vacations Club", ""),
        (", a Hilton Vacation Club", ""),
        (", a Hilton Club", ""),
        ("Hilton Grand Vacations Club in ", ""),
        ("Hilton Grand Vacations Club ", ""),
        (", Managed by Hilton Grand Vacations", ""),
        ("Hilton Vacation Club", ""),
        ("Hilton Club", ""),
        ("Great Wolf Lodge", "GW"),
        ("Great Wolf", "GW"),
    ]

    normalized_name = property_name
    for old, new in replacements:
        normalized_name = normalized_name.replace(old, new)
    return normalized_name


def load_properties_from_database() -> Dict[str, Any]:
    """Load properties from the database/API."""
    max_retries = 3
    retry_delay = 1  # seconds

    for attempt in range(max_retries):
        try:
            # Make API request to get properties
            url = f"{config.HGV_BASE_URL}{config.HGV_LOOKUP_PATH}"
            headers = {
                "Ocp-Apim-Subscription-Key": config.HGV_SUBSCRIPTION_KEY,
                "X_HGV_TransactionId": f"agentic_inventory_{uuid4()}",
                "correlationId": f"agentic_inventory_{uuid4()}",
                "Content-Type": "application/json",
            }

            response = requests.get(url, headers=headers, timeout=15.0)

            # Check for authentication errors specifically
            if response.status_code == 401:
                logger.error(f"Authentication error occurred for {url}")
                raise ValueError("Authentication error")

            data = response.json()
            if not isinstance(data, dict) or "properties" not in data:
                logger.error("Invalid response format from API")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                raise ValueError("Invalid response format from API")

            raw_properties = data["properties"]
            if not isinstance(raw_properties, list):
                logger.error("Properties field is not a list")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                raise ValueError("Properties field is not a list")

            # Create lookup dictionary with both raw and normalized names
            lookup = {}
            seen_ids = set()  # Track unique property IDs
            for prop in raw_properties:
                if not isinstance(prop, dict) or "propertyName" not in prop:
                    continue
                # Skip if we've already seen this property ID
                prop_id = prop.get("propertyId")
                if prop_id in seen_ids:
                    continue
                seen_ids.add(prop_id)

                raw_name = prop["propertyName"]
                normalized_name = normalize_property_name(raw_name)

                # Add both raw and normalized names to lookup
                lookup[raw_name] = prop
                if normalized_name != raw_name:
                    lookup[normalized_name] = prop

            logger.info(f"Loaded {len(lookup)} unique properties from database")
            return lookup

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed (attempt {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise ValueError(f"Failed to load properties after {max_retries} attempts: {str(e)}")
        except Exception as e:
            logger.error(f"Error loading properties from database: {str(e)}")
            raise ValueError(f"Error loading properties from database: {str(e)}")

    raise ValueError(f"Failed to load properties after {max_retries} attempts")


def load_property_lookup(attempt_load_from_cache: bool = True) -> Dict[str, Any]:
    """Load property lookup data with caching support."""
    cache_dir = Path(".cache")
    cache_dir.mkdir(exist_ok=True)
    local_file = cache_dir / ".lookup.properties.json"
    cache_expiry = 3600  # 1 hour in seconds

    if attempt_load_from_cache and local_file.is_file():
        try:
            # Check if cache is expired
            file_age = time.time() - local_file.stat().st_mtime
            if file_age < cache_expiry:
                with open(local_file, "r") as infile:
                    return json.load(infile)
            else:
                logger.info("Cache expired, refreshing property data")
        except Exception as e:
            logger.error(f"Error loading from cache: {str(e)}")

    properties = load_properties_from_database()

    if properties:  # Only cache if we got valid data
        try:
            with open(local_file, "w") as outfile:
                json.dump(properties, outfile, indent=4)
        except Exception as e:
            logger.error(f"Error saving to cache: {str(e)}")

    return properties


def fuzzy_match_property_name(name: str, property_list: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find fuzzy matches for property names."""
    matches = difflib.get_close_matches(name, property_list.keys(), n=1, cutoff=0.7)
    if matches:
        return property_list.get(matches[0])
    return None


def llm_match_property_name(query_name: str, available_properties: Dict[str, Any]) -> List[str]:
    """Use LLM to find property name matches."""
    try:
        property_names = list(available_properties.keys())
        if not property_names:
            logger.warning("No properties available for LLM matching")
            return []

        logger.info(f"Attempting LLM match for query: {query_name}")

        prompt = f"""
        You are an expert in property name matching.
        Your task is to find the most accurate match for the provided property name.

        Instructions:
        - Return ONLY the exact name inside list if a clear match is found.
        - If there are multiple potential matches, return them as a list.
        - Return ONLY the list of possible matches, no additional text or explanation.
        - An empty list if no match is found.

        Input:
        - User provided name: "{query_name}".
        - Valid property names: {json.dumps(property_names)}.

        Output:
        - A single name as a list if there is a clear match.
        - A list with multiple names if ambiguity exists or multiple potential matches.
        - An empty list if no match is found.
        """

        logger.debug(f"Sending prompt to LLM: {prompt}")
        response = llm.chat.completions.create(
            model=config.AZURE_OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a property name matching expert."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=500,
        )
        if not response or not response.choices:
            logger.error("Empty response from LLM")
            return []

        content = response.choices[0].message.content.strip()
        if not content:
            logger.error("Empty content in LLM response")
            return []

        logger.debug(f"Raw LLM response: {content}")

        try:
            # Clean up response content
            content = content.replace("```json", "").replace("```", "").strip()
            matches = json.loads(content)

            if not isinstance(matches, list):
                logger.error("LLM response is not a list")
                return []

            # Validate that all matches exist in available properties
            valid_matches = [match for match in matches if match in available_properties]
            if len(valid_matches) != len(matches):
                logger.warning(f"Some LLM matches were invalid: {set(matches) - set(valid_matches)}")

            logger.info(f"LLM found matches: {valid_matches}")
            return valid_matches

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {str(e)}")
            logger.error(f"Raw response: {content}")
            return []

    except Exception as e:
        logger.error(f"Error in LLM matching: {str(e)}")
        return []


def lookup_name(name: str) -> Dict[str, Any]:
    """Main function to look up property names using multiple matching strategies.

    Returns:
        Dictionary containing property data and match_type if successful,
        otherwise a dictionary with an 'error' key.
    """
    property_lookup = load_property_lookup(True)

    # Try exact match
    if name in property_lookup:
        result = property_lookup[name]
        result["match_type"] = "exact"
        logger.info(f"Exact match found for '{name}'")
        return result

    # Try fuzzy match
    fuzzy_match = fuzzy_match_property_name(name, property_lookup)
    if fuzzy_match:
        fuzzy_match["match_type"] = "fuzzy"
        logger.info(f"Fuzzy match found for '{name}': {fuzzy_match.get('propertyName')}")
        return fuzzy_match

    # Try LLM match
    llm_matches = llm_match_property_name(name, property_lookup)
    if llm_matches:
        if len(llm_matches) == 1:
            match_name = llm_matches[0]
            result = property_lookup.get(match_name)
            if result:
                result["match_type"] = "llm"
                logger.info(f"LLM match found for '{name}': {match_name}")
                return result
            else:
                # Should ideally not happen if llm_matches are validated
                logger.error(f"LLM match '{match_name}' not found in lookup table after matching.")
        else:
            logger.warning(f"Multiple LLM matches found for '{name}': {llm_matches}")
            return {
                "error": (
                    f"Multiple possible matches found: {', '.join(llm_matches)}. " "Please specify which one you mean."
                )
            }

    logger.warning(f"No match found for '{name}' using any strategy.")
    return {
        "error": (
            f"I apologize, but I can only check availability for Hilton Grand "
            f"Vacations properties. The property '{name}' is not a Hilton Grand "
            "Vacations resort. Would you like to check availability for a different "
            "HGV property instead?"
        )
    }


def cleanup_cache(max_age_hours: int = 24) -> None:
    """Clean up old cache files.

    Args:
        max_age_hours: Maximum age of cache files in hours before deletion
    """
    try:
        cache_dir = Path(".cache")
        if not cache_dir.exists():
            return

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        for cache_file in cache_dir.glob(".lookup.*.json"):
            file_age = current_time - cache_file.stat().st_mtime
            if file_age > max_age_seconds:
                try:
                    cache_file.unlink()
                    logger.info(f"Cleaned up old cache file: {cache_file}")
                except Exception as e:
                    logger.error(f"Error deleting cache file {cache_file}: {str(e)}")
    except Exception as e:
        logger.error(f"Error during cache cleanup: {str(e)}")


# Initialize property lookups with cache cleanup
cleanup_cache()
static_lookup = load_property_lookup(True)
