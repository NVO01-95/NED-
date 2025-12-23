

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationError:
    field: str
    message: str


def is_valid_lat(lat: float) -> bool:
    return -90.0 <= lat <= 90.0


def is_valid_lon(lon: float) -> bool:
    return -180.0 <= lon <= 180.0


def validate_lat_lon(lat: float, lon: float) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not is_valid_lat(lat):
        errors.append(ValidationError("lat", "Latitude must be between -90 and 90."))
    if not is_valid_lon(lon):
        errors.append(ValidationError("lon", "Longitude must be between -180 and 180."))
    return errors
