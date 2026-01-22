# MyTPU - Tacoma Public Utilities Integration

[![Test](https://github.com/thetic/hass-mytpu/actions/workflows/test.yml/badge.svg)](https://github.com/thetic/hass-mytpu/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/thetic/hass-mytpu/graph/badge.svg)](https://codecov.io/gh/thetic/hass-mytpu)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom component for tracking energy and water usage from [Tacoma Public Utilities](https://www.mytpu.org/).

> [!NOTE]
> This is an unofficial, community-developed integration and is not affiliated with, endorsed by, or supported by Tacoma Public Utilities (TPU). Use at your own risk.

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

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thetic&repository=hass-mytpu&category=integration)

Or manually:

1. Open HACS in Home Assistant
2. Click the three dots menu and select "Custom repositories"
3. Add `https://github.com/thetic/hass-mytpu` and select "Integration" as the category
4. Click "Add"
5. Search for "Tacoma Public Utilities" and install it
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/mytpu` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Tacoma Public Utilities"
4. Enter your MyTPU username and password
5. Select which meters to track (the integration will automatically discover all available meters on your account)

## Sensors

This integration creates the following sensors:

| Sensor             | Description             | Unit | Device Class |
| ------------------ | ----------------------- | ---- | ------------ |
| Energy Consumption | Daily electricity usage | kWh  | energy       |
| Water Consumption  | Daily water usage       | CCF  | water        |

Historical data and cumulative totals are tracked using Home Assistant's statistics system for proper Energy Dashboard integration.

## Energy Dashboard Setup

1. Go to **Settings** → **Dashboards** → **Energy**
2. Under "Electricity grid", click "Add consumption"
3. Select the "Energy Consumption" sensor
4. Under "Water consumption", click "Add water source"
5. Select the "Water Consumption" sensor

## Acknowledgments

This project was inspired by and builds upon the work of [ex-nerd/mytpu](https://github.com/ex-nerd/mytpu), which provided valuable insights into the MyTPU API authentication flow.

## License

MIT
