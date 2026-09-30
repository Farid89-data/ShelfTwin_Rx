from datetime import datetime, timedelta, timezone
import json

from shelftwin_core import EvidenceEngine, PackageIdentity, SensorReading, StorageProfile

package = PackageIdentity(
    package_id="NL-HOSP-0001",
    product_name="Example High-Value Medicine",
    strength="80 mg",
    dosage_form="film-coated tablet",
    batch_number="BATCH-26A41",
    serial_number="SN-00928172",
    expiry_date="2028-04-30",
)

profile = StorageProfile(
    min_temp_c=15.0,
    max_temp_c=25.0,
    expected_sample_interval_min=15,
    max_data_gap_min=30,
    max_single_excursion_min=0,
)

engine = EvidenceEngine(package, profile)

start = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
temperatures = [21.2, 21.4, 26.8, 27.1, 23.8]
for i, temp in enumerate(temperatures):
    engine.add_reading(
        SensorReading(
            timestamp=start + timedelta(minutes=15 * i),
            temperature_c=temp,
            humidity_pct=48.0 + i,
            tamper_open=False,
            battery_mv=2980 - i,
        )
    )

print(json.dumps(engine.evaluate().to_dict(), indent=2))
