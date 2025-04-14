import os
import requests
import pandas as pd
import json
import unittest


class TestMLendpoint(unittest.TestCase):

    @unittest.skipUnless(
        os.environ.get("DEMAND_FORECAST_ENDPOINT_TOKEN") and os.environ.get("DEMAND_FORECAST_ENDPOINT_URL"),
        "Environment variables not set",
    )
    def test_demand_forecast_endpoint(self):

        token = os.environ["DEMAND_FORECAST_ENDPOINT_TOKEN"]
        endpoint_url = os.environ["DEMAND_FORECAST_ENDPOINT_URL"]

        input_example = {"segment_code": "RMK", "pm_unit_type_id": "72672", "num_days": "3"}
        input_example2 = {"segment_code": "GR", "pm_unit_type_id": "15753", "num_days": "3"}
        input_data = pd.DataFrame([input_example, input_example2])

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        ds_dict = input_data.to_dict(orient="split")
        data_json = json.dumps({"dataframe_split": ds_dict}, allow_nan=True)
        response = requests.request(method="POST", headers=headers, url=endpoint_url, data=data_json)
        dict_forecast = response.json()
        self.assertEqual(response.status_code, 200)
        # sinc the input is having 2 samples, api should respond with same as wll
        self.assertEqual(len(dict_forecast["predictions"].keys()), 2)
        # its supposed to give preidictions for n+1 days
        self.assertEqual(len(json.loads(dict_forecast["predictions"]["GR_15753"])["prediction"].keys()), 4)


if __name__ == "__main__":
    unittest.main()
