from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.comparable import ComparableSale, ComparableSelection
from src.models.property import Property
from src.schemas.comparable import (
    ManualComparableAnalysis,
    ManualComparableRow,
    StatisticalValuationRequest,
    StatisticalValuationResult,
)


def _number(value) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, Decimal)) and math.isfinite(float(value)):
        return float(value)
    return None


class ComparableService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def manual_analysis(self, prop: Property) -> ManualComparableAnalysis:
        selections = list((await self.db.execute(
            select(ComparableSelection)
            .where(ComparableSelection.property_id == prop.id, ComparableSelection.included.is_(True))
            .options(selectinload(ComparableSelection.sale))
        )).scalars().all())
        warnings: list[str] = []
        if not selections:
            return ManualComparableAnalysis(
                rows=[], weighted_price_per_area=None, indicated_value=None,
                low_price_per_area=None, high_price_per_area=None,
                warnings=["No included comparable sales."],
            )
        total_weight = sum((s.weight for s in selections if s.weight > 0), Decimal(0))
        if total_weight <= 0:
            return ManualComparableAnalysis(
                rows=[], weighted_price_per_area=None, indicated_value=None,
                low_price_per_area=None, high_price_per_area=None,
                warnings=["Included comparables have zero total weight."],
            )
        rows: list[ManualComparableRow] = []
        adjusted_values: list[Decimal] = []
        weighted = Decimal(0)
        today = date.today()
        for selection in selections:
            sale = selection.sale
            raw = sale.sale_price / sale.area
            adjustment = sum((Decimal(str(v)) for v in (selection.adjustments or {}).values()), Decimal(0))
            adjusted = raw * (Decimal(1) + adjustment)
            normalized_weight = selection.weight / total_weight
            row_warnings: list[str] = []
            if abs(adjustment) > Decimal("0.25"):
                row_warnings.append("Total adjustment exceeds 25%.")
            if (today - sale.sale_date).days > 730:
                row_warnings.append("Sale is more than two years old.")
            if sale.verification_status != "verified":
                row_warnings.append(f"Sale is {sale.verification_status.replace('_', ' ')}.")
            if sale.is_distressed or sale.is_portfolio_sale or sale.is_partial_interest:
                row_warnings.append("Transaction has a non-standard condition flag.")
            rows.append(ManualComparableRow(
                sale_id=sale.id,
                property_name=sale.property_name,
                raw_price_per_area=raw,
                total_adjustment_pct=adjustment,
                adjusted_price_per_area=adjusted,
                selected_weight=selection.weight,
                normalized_weight=normalized_weight,
                indicated_value=adjusted * prop.total_area,
                warnings=row_warnings,
            ))
            adjusted_values.append(adjusted)
            weighted += adjusted * normalized_weight
        if len(rows) < 3:
            warnings.append("Fewer than three included comparables; reliability is limited.")
        return ManualComparableAnalysis(
            rows=rows,
            weighted_price_per_area=weighted,
            indicated_value=weighted * prop.total_area,
            low_price_per_area=min(adjusted_values),
            high_price_per_area=max(adjusted_values),
            warnings=warnings,
        )

    async def statistical_analysis(
        self, prop: Property, request: StatisticalValuationRequest
    ) -> StatisticalValuationResult:
        query = select(ComparableSale).where(
            ComparableSale.property_type == prop.property_type,
            ComparableSale.area_unit == prop.area_unit,
        )
        if not request.include_distressed:
            query = query.where(
                ComparableSale.is_distressed.is_(False),
                ComparableSale.is_portfolio_sale.is_(False),
                ComparableSale.is_partial_interest.is_(False),
            )
        if request.market_only and prop.market:
            query = query.where(ComparableSale.market == prop.market)
        sales = list((await self.db.execute(query)).scalars().all())
        sales = [s for s in sales if s.sale_price > 0 and s.area > 0]
        if len(sales) < request.minimum_observations:
            return StatisticalValuationResult(
                status="insufficient_data", observation_count=len(sales),
                warnings=[
                    f"Need at least {request.minimum_observations} relevant sales; found {len(sales)}."
                ],
            )

        as_of = request.as_of_date or date.today()
        amenity_keys = sorted({
            key for sale in sales for key, value in (sale.amenities or {}).items()
            if _number(value) is not None
        })
        # Avoid a fragile wide model: amenities must vary and total features are capped relative to sample size.
        varying_amenities = []
        for key in amenity_keys:
            values = [_number((sale.amenities or {}).get(key)) or 0.0 for sale in sales]
            if np.std(values) > 1e-9 and sum(v != 0 for v in values) >= 3:
                varying_amenities.append(key)
        max_amenities = min(12, max(1, len(sales) // 4))
        varying_amenities = varying_amenities[:max_amenities]

        markets = sorted({s.market for s in sales if s.market})
        market_features = markets[:max(0, min(5, len(sales) // 6))]
        observed_occupancy = [float(s.occupancy_pct) for s in sales if s.occupancy_pct is not None]
        observed_noi_per_area = [
            float(s.normalized_noi / s.area) for s in sales if s.normalized_noi is not None
        ]
        occupancy_impute = float(np.median(observed_occupancy)) if observed_occupancy else 0.90
        noi_impute = float(np.median(observed_noi_per_area)) if observed_noi_per_area else 0.0
        feature_names = [
            "sale_year", "log_area", "age", "occupancy", "occupancy_missing",
            "noi_per_area", "noi_missing",
        ]
        feature_names += [f"market:{m}" for m in market_features[1:]]
        feature_names += [f"amenity:{k}" for k in varying_amenities]

        def features(sale: ComparableSale | None) -> list[float]:
            if sale is not None:
                sale_date, area = sale.sale_date, float(sale.area)
                built, occupancy = sale.year_built, sale.occupancy_pct
                noi = sale.normalized_noi
                market, amenities = sale.market, sale.amenities or {}
            else:
                sale_date, area = as_of, float(prop.total_area)
                built, occupancy = prop.year_built, request.occupancy_pct
                noi = request.normalized_noi
                market, amenities = prop.market, prop.amenities or {}
            age = max(0, sale_date.year - built) if built else 0
            row = [
                sale_date.year + sale_date.timetuple().tm_yday / 365.25,
                math.log(max(area, 1e-9)),
                float(age),
                float(occupancy) if occupancy is not None else occupancy_impute,
                1.0 if occupancy is None else 0.0,
                float(noi / Decimal(str(area))) if noi is not None else noi_impute,
                1.0 if noi is None else 0.0,
            ]
            row += [1.0 if market == m else 0.0 for m in market_features[1:]]
            row += [_number(amenities.get(k)) or 0.0 for k in varying_amenities]
            return row

        x_raw = np.asarray([features(s) for s in sales], dtype=float)
        subject_raw = np.asarray(features(None), dtype=float)
        y = np.log(np.asarray([float(s.sale_price / s.area) for s in sales], dtype=float))
        means = x_raw.mean(axis=0)
        stds = x_raw.std(axis=0)
        usable = stds > 1e-9
        x = (x_raw[:, usable] - means[usable]) / stds[usable]
        subject = (subject_raw[usable] - means[usable]) / stds[usable]
        used_names = [name for name, keep in zip(feature_names, usable, strict=True) if keep]
        design = np.column_stack([np.ones(len(sales)), x])
        ridge = np.eye(design.shape[1]) * 1.0
        ridge[0, 0] = 0.0
        beta = np.linalg.solve(design.T @ design + ridge, design.T @ y)
        # Leave-one-out predictions measure generalization instead of reporting training fit.
        cv_predictions = np.empty(len(sales))
        for held_out in range(len(sales)):
            keep = np.arange(len(sales)) != held_out
            cv_design = design[keep]
            cv_beta = np.linalg.solve(
                cv_design.T @ cv_design + ridge, cv_design.T @ y[keep]
            )
            cv_predictions[held_out] = design[held_out] @ cv_beta
        residuals = y - cv_predictions
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        prediction_log = float(np.r_[1.0, subject] @ beta)
        estimate = math.exp(prediction_log)
        # Approximate 95% prediction interval on log price; deliberately includes residual uncertainty.
        low, high = math.exp(prediction_log - 1.96 * rmse), math.exp(prediction_log + 1.96 * rmse)
        actual = np.exp(y)
        mape = float(np.mean(np.abs(np.exp(cv_predictions) - actual) / actual))
        out_of_range = [
            name for name, value, lo, hi in zip(feature_names, subject_raw, x_raw.min(0), x_raw.max(0), strict=True)
            if value < lo or value > hi
        ]
        confidence = "high" if len(sales) >= 50 and not out_of_range and mape <= 0.15 else (
            "moderate" if len(sales) >= 20 and len(out_of_range) <= 1 and mape <= 0.25 else "low"
        )
        warnings = []
        if out_of_range:
            warnings.append("Subject is outside the training range for: " + ", ".join(out_of_range))
        if request.normalized_noi is None:
            warnings.append("Subject normalized NOI was not supplied; the model used the sample median and a missing-value indicator.")
        if request.occupancy_pct is None:
            warnings.append("Subject occupancy was not supplied; the model used the sample median and a missing-value indicator.")
        if len(varying_amenities) == 0:
            warnings.append("No amenity feature had enough populated, varying observations to estimate an effect.")
        coefficients = {"intercept": float(beta[0])}
        coefficients.update({name: float(value) for name, value in zip(used_names, beta[1:], strict=True)})
        return StatisticalValuationResult(
            status="ok",
            estimated_price_per_area=Decimal(str(round(estimate, 4))),
            indicated_value=Decimal(str(round(estimate * float(prop.total_area), 2))),
            prediction_low=Decimal(str(round(low * float(prop.total_area), 2))),
            prediction_high=Decimal(str(round(high * float(prop.total_area), 2))),
            observation_count=len(sales),
            feature_count=len(used_names),
            confidence=confidence,
            out_of_range_features=out_of_range,
            coefficients=coefficients,
            model_rmse_log=rmse,
            model_mape=mape,
            warnings=warnings,
        )
