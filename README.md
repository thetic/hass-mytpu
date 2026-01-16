# MyTPU - Tacoma Public Utilities Integration

A Home Assistant custom component for tracking energy and water usage from [Tacoma Public Utilities](https://www.mytpu.org/).

## Features

- Track daily electricity consumption (kWh)
- Track daily water consumption (CCF)
- Compatible with Home Assistant's Energy Dashboard
- Automatic hourly updates

## Requirements

- Home Assistant 2025.12.0 or newer
- A MyTPU online account at [myaccount.mytpu.org](https://myaccount.mytpu.org)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu and select "Custom repositories"
3. Add this repository URL and select "Integration" as the category
4. Click "Add"
5. Search for "Tacoma Public Utilities" and install it
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/mytpu` folder to your Home Assistant `config/custom_components/` directory
2. Copy the `mytpu` library folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Tacoma Public Utilities"
4. Enter your MyTPU username and password
5. Enter your meter information (found in your MyTPU account under Usage)

### Finding Your Meter Information

1. Log in to [myaccount.mytpu.org](https://myaccount.mytpu.org)
2. Navigate to **Usage** → **Usage Dashboard**
3. Open your browser's Developer Tools (F12)
4. Go to the Network tab and look for requests to `/rest/usage/month`
5. The request body contains your `meterNumber`, `serviceId`, and `serviceNumber`

## Sensors

This integration creates the following sensors:

| Sensor | Description | Unit | Device Class |
|--------|-------------|------|--------------|
| Energy Consumption | Total electricity usage | kWh | energy |
| Water Consumption | Total water usage | CCF | water |

Both sensors use `state_class: total_increasing` for proper Energy Dashboard integration.

## Energy Dashboard Setup

1. Go to **Settings** → **Dashboards** → **Energy**
2. Under "Electricity grid", click "Add consumption"
3. Select the "Energy Consumption" sensor
4. Under "Water consumption", click "Add water source"
5. Select the "Water Consumption" sensor

## Python Library

This repository also includes a standalone Python library for interacting with the MyTPU API:

```python
from mytpu import MyTPUClient
from datetime import datetime, timedelta

async with MyTPUClient("username", "password") as client:
    readings = await client.get_power_usage(
        meter_number="12345678",
        service_id="800000000",
        service_number="ABC123",
        from_date=datetime.now() - timedelta(days=7),
    )
    for r in readings:
        print(f"{r.date}: {r.consumption} {r.unit}")
```

## License

MIT
