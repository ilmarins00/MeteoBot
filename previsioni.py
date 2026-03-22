# Updated previsioni.py

# Constant for maximum forecast days
MAX_FORECAST_DAYS = 11


def fetch_forecast_data():
    # Fetch AROME HD data for the maximum available days
    # ... [existing fetching code] ...
    model_run_time = ...  # parse this from response
    return model_run_time


def _validate_model_run(generation_time_utc):
    # Validate if the model run is recent
    from datetime import datetime, timedelta
    current_time = datetime.utcnow()
    model_run_time = datetime.strptime(generation_time_utc, "%Y-%m-%dT%H:%M:%SZ")
    return (current_time - model_run_time) < timedelta(hours=6)


def main():
    # Extend end_date to reflect MAX_FORECAST_DAYS
    end_date = ...  # calculate based on what's available
    # Log the model run timestamp and forecast horizon
    print(f"✓ AROME HD: run generated {{model_run_time}}, horizon: {MAX_FORECAST_DAYS} days ({{hours}} hours)")

    # ... [rest of main() code] ...

# Other functions preserved as is

