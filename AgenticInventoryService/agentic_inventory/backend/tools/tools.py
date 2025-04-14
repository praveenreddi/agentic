"""
Tools and functions for the HGV Agentic Inventory Service.
"""

import re
import json
import pandas as pd
import requests
from google.cloud import bigquery
from datetime import datetime
from typing import Dict, List, Any, Union
from agentic_inventory.utils import config
from agentic_inventory.backend.tools.clients import bigquery_client
from agentic_inventory.framework.core.framework import FunctionComposer
from agentic_inventory.backend.tools.property_lookup import lookup_name

# Create the composer for registering functions
composer = FunctionComposer(config.FRAMEWORK_NAME)


def extract_id(text: str) -> str:
    """Extract the ID substring after 'ID:' from a given string."""
    try:
        if "ID:" in text:
            id_part = text.split("ID:")[1].strip()
            return id_part.replace(")", "").strip()
        return text
    except Exception as e:
        raise ValueError("Error extracting ID from " + text + ": " + str(e))


@composer.register
def verify_property_name(property_name: str) -> Dict[str, Any]:
    """This function verifies the property name using the property lookup tool.

    Args:
        property_name: Name of the property to verify.

    Returns:
        Dictionary containing if property name is valid, the match type, and the matches,
        or an error message if not found.
    """
    result = lookup_name(property_name)

    if isinstance(result, dict) and "error" not in result:
        # Assuming 'propertyName' exists if no error
        return {"valid": True, "match_type": "lookup", "matches": result.get("propertyName", "Unknown Property")}
    elif isinstance(result, dict) and "error" in result:
        # Handle cases where lookup returns multiple matches or other errors
        return {"valid": False, "error": result["error"]}
    else:
        # Fallback for unexpected result types
        return {"valid": False, "error": f"Could not verify property '{property_name}'."}


@composer.register(
    dependencies=[
        {
            "function": "verify_property_name",
            "map_params": {"property_name": "property_name"},
            "map_result_to": {"property_name": "matches"},
            "validate_result": lambda result: result["valid"],
        },
    ]
)
def get_property_id_by_name(property_name: str) -> str:
    """This function gets the property id from the property name using the property lookup tool.

    Args:
        property_name: name of the property to get the property id for

    Returns:
        property id

    Raises:
        ValueError: If property ID is not found or invalid after verification.
    """
    result = lookup_name(property_name)

    if isinstance(result, dict) and "propertyId" in result:
        property_id = result["propertyId"]
        if property_id:
            return str(property_id)  # Ensure it's a string
        else:
            raise ValueError(f"Property ID is empty for '{property_name}'. Please verify the property name again.")
    elif isinstance(result, dict) and "error" in result:
        # This case should ideally be caught by the dependency validation,
        # but handle it defensively.
        raise ValueError(f"Property '{property_name}' verification failed: {result['error']}")
    else:
        raise ValueError(f"Could not find property ID for '{property_name}'. Please verify the property name.")


@composer.register
def get_segment_codes(property_id: str) -> List[str]:
    """Get segment codes for a property by ID.

    Args:
        property_id: id of the property to get the segment codes for

    Returns:
        List of segment codes or error message.
    """
    match = re.search(r"ID:\s*([A-Za-z0-9]+)\)", property_id)
    clean_property_id = match.group(1) if match else property_id

    query = """
    SELECT DISTINCT PPCC.SEGMENT_CODE
    FROM `dri-it-prod-hgv.cognos_fm.p_pm_control_count` PPCC
    LEFT JOIN `dri-it-prod-hgv.cognos_fm.p_pm_unit_type` PPUT
    ON PPCC.PM_UNIT_TYPE_ID = PPUT.PM_UNIT_TYPE_ID
    WHERE PPUT.PROPERTY_ID = @property_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("property_id", "STRING", clean_property_id)]
    )
    try:
        query_job = bigquery_client.query(query, job_config=job_config)
        segment_codes = [row.SEGMENT_CODE for row in query_job]

        if not segment_codes:
            return "No segment codes found for property ID '" + clean_property_id + "'"
        elif len(segment_codes) > 1:
            options = "\n".join(["- " + code for code in segment_codes])
            return (
                "Multiple segment codes found for property ID '" + clean_property_id + "'. Please specify:\n" + options
            )
        return segment_codes

    except Exception as e:
        return "Error fetching segment codes for property ID '" + clean_property_id + "': " + str(e)


@composer.register
def get_pm_unit_type_ids(property_id: str, segment_code: str) -> List[str]:
    """Get PM Unit Type IDs for a specified property and segment code.

    Args:
        property_id: id of the property to get the PM Unit Type IDs for
        segment_code: code of the segment to get the PM Unit Type IDs for

    Returns:
        List of PM Unit Type IDs or error message
    """
    try:
        clean_property_id = extract_id(property_id)
        query = """
        SELECT DISTINCT PPUT.pm_unit_type_id
        FROM `dri-it-prod-hgv.cognos_fm.p_pm_control_count` PPCC
        LEFT JOIN `dri-it-prod-hgv.cognos_fm.p_pm_unit_type` PPUT
        ON PPCC.PM_UNIT_TYPE_ID = PPUT.PM_UNIT_TYPE_ID
        WHERE PPUT.PROPERTY_ID = @property_id
        AND PPCC.SEGMENT_CODE = @segment_code
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("property_id", "STRING", clean_property_id),
                bigquery.ScalarQueryParameter("segment_code", "STRING", segment_code),
            ]
        )
        query_job = bigquery_client.query(query, job_config=job_config)
        pm_unit_type_ids = [row.pm_unit_type_id for row in query_job]

        if not pm_unit_type_ids:
            raise ValueError(
                "VALIDATION ERROR: PM Unit Type IDs not found for property ID: "
                + property_id
                + " with segment code: "
                + segment_code
            )

        return pm_unit_type_ids

    except Exception as e:
        raise ValueError("Error retrieving PM Unit Type IDs: " + str(e))


@composer.register
def predict_demand_model(segment_code: Union[str, List[str]], pm_unit_type_id: str, num_days: int) -> str:
    """Predicts demand for a specific segment and property management unit type over a given number of days.

    Args:
        segment_code (str or List[str]): segment code for the segment. Can be a string or a list of string.
        pm_unit_type_id (str): The property management unit type ID.
        num_days (int): The number of days for the prediction. This parameter is mandatory and must be provided
        by the user.

    Returns:
        str: A string containing the model prediction results or an error message if inputs are invalid.
    """
    token = config.ML_TOKEN.get_secret_value()
    url = config.ML_URL
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    input_data = [{"segment_code": segment_code, "pm_unit_type_id": pm_unit_type_id, "num_days": num_days}]

    for item in input_data:
        if "prediction_date" in item:
            try:
                target_date = datetime.datetime.strptime(item["prediction_date"], "%Y-%m-%d").date()
            except Exception as e:
                raise ValueError("Invalid prediction_date format. Please use YYYY-MM-DD.") from e
            current_date = datetime.date.today()
            delta_days = (target_date - current_date).days
            item["num_days"] = delta_days
            del item["prediction_date"]

    processed_data = []
    for item in input_data:
        processed_item = {k: str(v) for k, v in item.items()}
        processed_data.append(processed_item)

    try:
        df = pd.DataFrame(processed_data)
        ds_dict = df.to_dict(orient="split")
        data_json = json.dumps({"dataframe_split": ds_dict}, allow_nan=True)

        response = requests.request(method="POST", headers=headers, url=url, data=data_json)

        if response.status_code != 200:
            raise Exception(f"Request failed with status {response.status_code}, {response.text}")

        if not response.text.strip():
            return "Error scoring model: Empty response from API"

        results = response.json()
        predictions = results.get("predictions", {})

        if "error" in predictions:
            return f"Error from model: {predictions['error']}"

        for k in predictions.keys():
            try:
                predictions[k] = json.loads(predictions[k])
            except json.JSONDecodeError:
                return f"Error scoring model: Invalid prediction format for key '{k}': {predictions[k]}"

        for key in predictions:
            dict_temp = predictions[key]["prediction"]
            new_dict = {}
            for k, v in dict_temp.items():
                k = pd.to_datetime(int(k) / 1000, unit="s").strftime("%m-%d-%Y")
                new_dict[k] = str(v)
            predictions[key]["prediction"] = new_dict
        return f"Model predictions: {str(predictions)}"
    except Exception as e:
        return f"Error scoring model: {str(e)}"


@composer.register
def get_availability(property_id: str, segment_code: str, start_date: str, end_date: str) -> str:
    """Fetch availability for a property and segment code.

    Args:
        property_id (str): The ID of the property to check availability.
        segment_code (str): The segment code associated with the property.
        start_date (str): Start date in 'YYYY-MM-DD' format.
        end_date (str): End date in 'YYYY-MM-DD' format.

    Returns:
        str: A string containing the availability results or an error message.
    """
    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("property_id", "STRING", property_id),
                bigquery.ScalarQueryParameter("segment_code", "STRING", segment_code),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        query = """
        SELECT
            PPUT.PROPERTY_ID,
            PPUT.pm_unit_type_id,
            PPUT.PM_UNIT_TYPE AS UNIT_TYPE,
            PPCC.USAGE_DATE,
            PPCC.SEGMENT_CODE,
            SUM(PPCC.AVAIL_SEG) AS AVAIL
        FROM
            `dri-it-prod-hgv.cognos_fm.p_pm_control_count` PPCC
        LEFT JOIN
            `dri-it-prod-hgv.cognos_fm.p_pm_unit_type` PPUT
        ON
            PPCC.PM_UNIT_TYPE_ID = PPUT.PM_UNIT_TYPE_ID
        WHERE
            PPCC.USAGE_DATE BETWEEN @start_date AND @end_date
            AND PPUT.PROPERTY_ID = @property_id
            AND PPCC.SEGMENT_CODE = @segment_code
        GROUP BY
            PPUT.PROPERTY_ID,
            PPUT.pm_unit_type_id,
            PPUT.PM_UNIT_TYPE,
            PPCC.USAGE_DATE,
            PPCC.SEGMENT_CODE
        """

        response = bigquery_client.query(query, job_config=job_config)
        results = list(response)

        if not results:
            return f"No availability found for property ID: {property_id} " f"with segment code {segment_code}"

        availability_data = []
        for row in results:
            availability_data.append(
                {
                    "property_id": row.PROPERTY_ID,
                    "unit_type_id": row.pm_unit_type_id,
                    "unit_type": row.UNIT_TYPE,
                    "usage_date": row.USAGE_DATE.strftime("%Y-%m-%d"),
                    "segment_code": row.SEGMENT_CODE,
                    "availability": row.AVAIL,
                }
            )

        return f"Availability Results: {availability_data}"

    except Exception as e:
        return f"Error retrieving availability: {str(e)}"


function_composer = composer
