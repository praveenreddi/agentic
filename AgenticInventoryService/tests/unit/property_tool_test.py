import pytest
from typing import Dict, Any
from agentic_inventory.backend.tools.tools import (
    verify_property_name,
    get_property_id_by_name,
)

# --- Test Cases ---


@pytest.mark.parametrize(
    "test_input_name, expected_output",
    [
        (
            "Hilton Grand Vacations Club at Tuscany Village",
            {"valid": True, "match_type": "lookup"},
        ),
        (
            "Orlando World Center",
            {
                "valid": False,
                "error": (
                    "I apologize, but I can only check availability for Hilton Grand Vacations properties. "
                    "The property 'Orlando World Center' is not a Hilton Grand Vacations resort. "
                    "Would you like to check availability for a different HGV property instead?"
                ),
            },
        ),
        (
            "Vegas Paradise",
            {"valid": True, "match_type": "lookup"},
        ),
        (
            "Orlando Resort",
            {"valid": True, "match_type": "lookup", "matches": "Oakmont Resort"},
        ),
        (
            "NonExistent Property XYZ",
            {
                "valid": False,
                "error": (
                    "I apologize, but I can only check availability for Hilton Grand Vacations properties. "
                    "The property 'NonExistent Property XYZ' is not a Hilton Grand Vacations resort. "
                    "Would you like to check availability for a different HGV property instead?"
                ),
            },
        ),
    ],
    ids=[
        "exact_match",
        "property_not_found_error",
        "llm_or_other_match",
        "specific_success_oakmont",
        "no_match_error",
    ],
)
def test_verify_property_name(test_input_name: str, expected_output: Dict[str, Any]):
    """
    Tests the verify_property_name function by calling the real lookup_name.
    NOTE: Expected outputs may need adjustment based on real data/API state.
    """
    result = verify_property_name(test_input_name)
    if "error" in expected_output:
        assert "error" in result
        assert result["valid"] is False
    else:
        assert result["valid"] is True, f"Expected valid=True, got {result}"
        assert result["match_type"] == "lookup", f"Expected match_type=lookup, got {result}"
        if "matches" in expected_output:
            assert (
                result["matches"] == expected_output["matches"]
            ), f"Expected matches={expected_output['matches']}, got {result}"


@pytest.mark.parametrize(
    "test_input_name, expected_output",
    [
        (
            "Trump International Hotel Las Vegas, a Hilton Grand Vacations Club",
            "30",
        ),
        (
            "Tuscany Vilge",
            "048",
        ),
        (
            "Vegas Paradise",
            "037",
        ),
    ],
    ids=[
        "exact_match_get_id",
        "alternate_match_get_id",
        "llm_single_match_get_id",
    ],
)
def test_get_property_id_by_name_success(test_input_name: str, expected_output: Any):
    """
    Tests successful cases for get_property_id_by_name using real lookup_name.
    NOTE: Expected outputs may need adjustment based on real data/API state.
    """
    result = get_property_id_by_name(test_input_name)
    assert result == expected_output


@pytest.mark.parametrize(
    "test_input_name, expected_exception_substring",
    [
        (
            "NonExistent Property XYZ",
            "not a Hilton Grand Vacations resort",
        ),
        (
            "Trump htl hgv",
            "Multiple possible matches found",
        ),
        (
            "Trump Hotel",
            "Multiple possible matches found",
        ),
    ],
    ids=[
        "no_match_error",
        "multiple_matches_llm_error",
        "multiple_matches_trump_hotel_error",
    ],
)
def test_get_property_id_by_name_errors(test_input_name: str, expected_exception_substring: str):
    """
    Tests error cases for get_property_id_by_name using real lookup_name.
    NOTE: Expected outputs may need adjustment based on real data/API state.
    """
    with pytest.raises(ValueError) as excinfo:
        get_property_id_by_name(test_input_name)

    assert expected_exception_substring in str(excinfo.value)
