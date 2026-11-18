"""Self storage operating model, stored as JSON on the property (`self_storage_assumptions_json`).

Rates are $ per unit per month; percentages are fractions (0.05 = 5%).
"""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StorageUnitType(_Model):
    name: str = Field(min_length=1)
    sf_per_unit: Decimal = Field(gt=0)
    climate_controlled: bool = False
    access: Literal["interior", "drive_up", "parking"] = "interior"
    count: int = Field(ge=0)
    occupied_units: Decimal = Field(ge=0)
    in_place_rate: Decimal = Field(ge=0, description="Average rent of occupied units, $/unit/month")
    street_rate: Decimal = Field(ge=0, description="Asking rent for new move-ins, $/unit/month")
    stabilized_occupancy: Decimal | None = Field(
        default=None, ge=0, le=1, description="Units occupied at stabilization; default = today's occupancy"
    )

    @model_validator(mode="after")
    def _occupied_within_count(self):
        if self.occupied_units > self.count:
            raise ValueError(f"{self.name}: occupied units ({self.occupied_units}) exceed the unit count ({self.count})")
        return self


class StorageChurn(_Model):
    monthly_move_out_pct: Decimal = Field(default=Decimal(0), ge=0, le=1)


class StorageEcri(_Model):
    """Existing-customer rate increases."""
    enabled: bool = False
    first_after_months: int = Field(default=12, ge=1, le=120)
    interval_months: int = Field(default=12, ge=1, le=120)
    increase_pct: Decimal = Field(default=Decimal(0), ge=0, le=1)
    extra_move_out_pct: Decimal = Field(default=Decimal(0), ge=0, le=1)


class StorageConcessions(_Model):
    first_month_discount_pct: Decimal = Field(default=Decimal(0), ge=0, le=1)


class StorageLeaseUp(_Model):
    monthly_net_absorption_units: Decimal | None = Field(default=None, gt=0)


class StorageAncillaryLine(_Model):
    name: str = Field(min_length=1)
    basis: Literal["annual_fixed", "per_occupied_unit_month", "per_move_in", "pct_of_rental"]
    amount: Decimal = Field(ge=0)
    participation_pct: Decimal = Field(default=Decimal(1), ge=0, le=1)
    growth_pct: Decimal = Field(default=Decimal(0), ge=-1, le=1)

    @model_validator(mode="after")
    def _pct_of_rental_is_fraction(self):
        if self.basis == "pct_of_rental" and self.amount > 1:
            raise ValueError(f"{self.name}: a percent-of-rental amount is a fraction (0.05 = 5%)")
        return self


class SelfStorageOperatingModel(_Model):
    unit_types: list[StorageUnitType] = Field(min_length=1)
    street_rate_growth_pct: Decimal = Field(default=Decimal(0), ge=-1, le=1)
    street_rate_growth_schedule: list[Decimal] = Field(
        default_factory=list, description="Growth by analysis year: Year 1, Year 2, …; last rate carries forward"
    )
    churn: StorageChurn = Field(default_factory=StorageChurn)
    ecri: StorageEcri = Field(default_factory=StorageEcri)
    concessions: StorageConcessions = Field(default_factory=StorageConcessions)
    lease_up: StorageLeaseUp = Field(default_factory=StorageLeaseUp)
    credit_loss_pct: Decimal = Field(default=Decimal(0), ge=0, le=1)
    ancillary_lines: list[StorageAncillaryLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self):
        names = [u.name for u in self.unit_types]
        if len(names) != len(set(names)):
            raise ValueError("Unit type names must be unique")
        return self

    @property
    def rentable_sf(self) -> Decimal:
        return sum((u.sf_per_unit * u.count for u in self.unit_types), Decimal(0))


def parse_storage_model(raw: str | None) -> SelfStorageOperatingModel | None:
    """Parse and validate the stored JSON; None when absent."""
    if not raw:
        return None
    return SelfStorageOperatingModel.model_validate_json(raw)
