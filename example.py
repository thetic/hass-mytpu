#!/usr/bin/env python3
"""Example usage of the MyTPU library."""

import asyncio
import os
from datetime import datetime, timedelta

from mytpu import MyTPUClient


async def main():
    # Get credentials from environment variables
    username = os.environ.get("MYTPU_USERNAME")
    password = os.environ.get("MYTPU_PASSWORD")

    if not username or not password:
        print("Please set MYTPU_USERNAME and MYTPU_PASSWORD environment variables")
        return

    async with MyTPUClient(username, password) as client:
        # Get account info and available services
        print("Fetching account info...")
        account_info = await client.get_account_info()
        print(f"Account: {account_info.get('accountContext', {}).get('accountHolder')}")

        # Get list of services
        services = await client.get_services()
        print(f"\nFound {len(services)} service(s):")
        for svc in services:
            print(
                f"  - {svc.service_type.name}: Meter {svc.meter_number} ({svc.address})"
            )

        # Fetch power usage for the last 7 days
        # Replace these values with your actual meter info from get_services()
        power_meter = "11399586"  # Your power meter number
        power_service_id = "800366496"
        power_service_number = "AESBYKH2"

        print("\nFetching power usage for last 7 days...")
        from_date = datetime.now() - timedelta(days=7)
        readings = await client.get_power_usage(
            meter_number=power_meter,
            service_id=power_service_id,
            service_number=power_service_number,
            from_date=from_date,
        )

        print(f"Got {len(readings)} readings:")
        for reading in readings[-5:]:  # Show last 5
            print(
                f"  {reading.date.strftime('%Y-%m-%d')}: {reading.consumption:.2f} {reading.unit}"
            )

        # Fetch water usage
        water_meter = "11189080"  # Your water meter number
        water_service_id = "800365849"
        water_service_number = "AW43XCF1"

        print("\nFetching water usage for last 7 days...")
        water_readings = await client.get_water_usage(
            meter_number=water_meter,
            service_id=water_service_id,
            service_number=water_service_number,
            from_date=from_date,
        )

        print(f"Got {len(water_readings)} readings:")
        for reading in water_readings[-5:]:  # Show last 5
            print(
                f"  {reading.date.strftime('%Y-%m-%d')}: {reading.consumption:.2f} {reading.unit}"
            )


if __name__ == "__main__":
    asyncio.run(main())
