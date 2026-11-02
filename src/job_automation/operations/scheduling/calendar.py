"""Calendar slot calculation, Europe/Berlin timezone handling, gap/fold resolution, and missed-run coalescing (AUTO-01-S04).

Enforces:
- IANA Europe/Berlin timezone evaluation with zoneinfo.
- Spring-forward gap resolution: nonexistent civil time moves forward to first valid local instant, preserving intended slot key.
- Autumn-backward fold resolution: ambiguous civil time admitted only at earlier occurrence (fold=0); second occurrence does not run.
- Missed slots coalescing: coalesces multiple missed slots within lateness window (default 24h) to single latest eligible slot.
- Expired slots: slots older than lateness window marked expired; no replay storm.
- Activation epoch: no backfill before activation epoch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from job_automation.contracts.primitives import UtcDatetime
from job_automation.operations.scheduling.records import (
    OccurrenceOutcome,
    ScheduleDefinition,
    ScheduleOccurrence,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComputedSlot:
    """Calculated local slot representation."""

    intended_slot_key: str
    intended_utc_instant: UtcDatetime
    local_offset_minutes: int
    fold: int
    is_gap_adjusted: bool
    adjusted_local_time: str | None = None


class CalendarCalculator:
    """Calculates due slots, resolves DST anomalies, and coalesces missed intervals."""

    def __init__(self, tz_name: str = "Europe/Berlin") -> None:
        self.tz_name = tz_name
        self.tz = ZoneInfo(tz_name)

    def resolve_slot(self, target_date: date, time_str: str) -> ComputedSlot:
        """Resolve a local date and HH:MM time string to a UTC instant with gap/fold handling.

        - If nonexistent (spring forward gap): moves forward to first valid instant, preserving intended slot key.
        - If ambiguous (autumn fold): uses earlier occurrence (fold=0).
        """
        parts = time_str.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0

        intended_slot_key = f"{target_date.isoformat()}T{hour:02d}:{minute:02d}:00 {self.tz_name}"

        # Test fold=0
        dt_fold0 = datetime(target_date.year, target_date.month, target_date.day, hour, minute, fold=0, tzinfo=self.tz)
        utc_instant = dt_fold0.astimezone(timezone.utc)
        round_trip = utc_instant.astimezone(self.tz)

        # Check for spring gap: does it round trip?
        if (round_trip.year, round_trip.month, round_trip.day, round_trip.hour, round_trip.minute) != (
            target_date.year, target_date.month, target_date.day, hour, minute
        ):
            # Nonexistent local time (spring-forward gap)
            # Find the first valid local instant after the gap
            # In EU/Berlin, the gap is 02:00 -> 03:00.
            # Scan forward minute by minute until round-trip succeeds
            curr = dt_fold0
            adjusted_dt = None
            for step_min in range(1, 120):
                probe = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=self.tz) + timedelta(minutes=step_min)
                probe_utc = probe.astimezone(timezone.utc)
                probe_back = probe_utc.astimezone(self.tz)
                if (probe_back.year, probe_back.month, probe_back.day, probe_back.hour, probe_back.minute) == (
                    probe.year, probe.month, probe.day, probe.hour, probe.minute
                ):
                    adjusted_dt = probe
                    break

            if adjusted_dt is None:
                # Fallback to 03:00
                adjusted_dt = datetime(target_date.year, target_date.month, target_date.day, 3, 0, tzinfo=self.tz)

            adjusted_utc = adjusted_dt.astimezone(timezone.utc)
            offset_sec = adjusted_dt.utcoffset().total_seconds() if adjusted_dt.utcoffset() else 0
            offset_min = int(offset_sec // 60)
            adj_time_str = f"{adjusted_dt.hour:02d}:{adjusted_dt.minute:02d}"

            return ComputedSlot(
                intended_slot_key=intended_slot_key,
                intended_utc_instant=adjusted_utc,
                local_offset_minutes=offset_min,
                fold=0,
                is_gap_adjusted=True,
                adjusted_local_time=adj_time_str,
            )

        # Valid or fold=0 earlier occurrence
        offset_sec = dt_fold0.utcoffset().total_seconds() if dt_fold0.utcoffset() else 0
        offset_min = int(offset_sec // 60)

        return ComputedSlot(
            intended_slot_key=intended_slot_key,
            intended_utc_instant=utc_instant,
            local_offset_minutes=offset_min,
            fold=0,
            is_gap_adjusted=False,
        )

    def generate_slots_in_range(
        self,
        definition: ScheduleDefinition,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[ComputedSlot]:
        """Generate all discrete candidate slots between start_utc and end_utc based on definition."""
        slots: list[ComputedSlot] = []
        if start_utc >= end_utc:
            return slots

        # If definition uses target wall times (e.g. ["07:00"]):
        if definition.target_times:
            # Determine date range in target timezone
            start_local = start_utc.astimezone(self.tz)
            end_local = end_utc.astimezone(self.tz)

            curr_date = start_local.date() - timedelta(days=1)
            end_date = end_local.date() + timedelta(days=1)

            seen_keys: set[str] = set()

            while curr_date <= end_date:
                for t_str in definition.target_times:
                    slot = self.resolve_slot(curr_date, t_str)
                    if start_utc <= slot.intended_utc_instant <= end_utc:
                        if slot.intended_slot_key not in seen_keys:
                            seen_keys.add(slot.intended_slot_key)
                            slots.append(slot)
                curr_date += timedelta(days=1)

        # If definition uses cadence_minutes interval:
        elif definition.cadence_minutes and definition.cadence_minutes > 0:
            step = timedelta(minutes=definition.cadence_minutes)
            curr = definition.activation_epoch
            # Fast forward to near start_utc if far behind
            if curr + step < start_utc:
                diff = (start_utc - curr).total_seconds()
                num_steps = int(diff // (definition.cadence_minutes * 60))
                curr = curr + (num_steps * step)

            while curr <= end_utc:
                if curr >= start_utc:
                    local_dt = curr.astimezone(self.tz)
                    slot_key = f"{local_dt.strftime('%Y-%m-%dT%H:%M:%S')} {self.tz_name}"
                    offset_sec = local_dt.utcoffset().total_seconds() if local_dt.utcoffset() else 0
                    slots.append(
                        ComputedSlot(
                            intended_slot_key=slot_key,
                            intended_utc_instant=curr,
                            local_offset_minutes=int(offset_sec // 60),
                            fold=local_dt.fold,
                            is_gap_adjusted=False,
                        )
                    )
                curr += step

        # Sort slots chronologically
        slots.sort(key=lambda s: s.intended_utc_instant)
        return slots

    def evaluate_due_occurrences(
        self,
        definition: ScheduleDefinition,
        existing_occurrences: list[ScheduleOccurrence],
        as_of_utc: datetime,
    ) -> tuple[ScheduleOccurrence | None, list[ScheduleOccurrence]]:
        """Evaluate schedule slots up to as_of_utc against existing occurrence records.

        Returns:
            (eligible_due_occurrence, list_of_newly_recorded_coalesced_or_expired_occurrences)
        """
        # Effective activation boundary: slots must be >= activation_epoch
        start_utc = definition.activation_epoch
        if as_of_utc <= start_utc:
            return None, []

        candidate_slots = self.generate_slots_in_range(definition, start_utc, as_of_utc)
        if not candidate_slots:
            return None, []

        existing_by_slot = {occ.intended_slot: occ for occ in existing_occurrences}

        # Filter to unrecorded slots
        unrecorded_slots: list[ComputedSlot] = []
        for slot in candidate_slots:
            if slot.intended_slot_key not in existing_by_slot:
                unrecorded_slots.append(slot)

        if not unrecorded_slots:
            return None, []

        # Classify unrecorded slots by lateness
        lateness_limit = as_of_utc - timedelta(hours=definition.max_lateness_hours)

        expired_slots: list[ComputedSlot] = []
        eligible_slots: list[ComputedSlot] = []

        for slot in unrecorded_slots:
            if slot.intended_utc_instant < lateness_limit:
                expired_slots.append(slot)
            else:
                eligible_slots.append(slot)

        newly_recorded: list[ScheduleOccurrence] = []

        # 1. Create EXPIRED occurrence records for ancient missed slots
        now_utc = datetime.now(timezone.utc)
        for exp in expired_slots:
            occ_exp = ScheduleOccurrence(
                deployment_id=definition.deployment_id,
                schedule_id=definition.schedule_id,
                definition_version=definition.version,
                work_kind=definition.work_kind,
                intended_slot=exp.intended_slot_key,
                intended_utc_instant=exp.intended_utc_instant,
                local_offset_minutes=exp.local_offset_minutes,
                fold=exp.fold,
                outcome=OccurrenceOutcome.EXPIRED,
                terminal_at=now_utc,
                details_json={"reason": "exceeded_max_lateness_window"},
                created_at=now_utc,
                updated_at=now_utc,
            )
            newly_recorded.append(occ_exp)

        if not eligible_slots:
            return None, newly_recorded

        # 2. Coalesce multiple eligible slots to the single latest slot
        # Latest eligible slot becomes the DUE candidate
        latest_slot = eligible_slots[-1]

        # Older eligible slots are COALESCED
        for coal in eligible_slots[:-1]:
            occ_coal = ScheduleOccurrence(
                deployment_id=definition.deployment_id,
                schedule_id=definition.schedule_id,
                definition_version=definition.version,
                work_kind=definition.work_kind,
                intended_slot=coal.intended_slot_key,
                intended_utc_instant=coal.intended_utc_instant,
                local_offset_minutes=coal.local_offset_minutes,
                fold=coal.fold,
                outcome=OccurrenceOutcome.COALESCED,
                terminal_at=now_utc,
                details_json={"coalesced_into_slot": latest_slot.intended_slot_key},
                created_at=now_utc,
                updated_at=now_utc,
            )
            newly_recorded.append(occ_coal)

        # 3. Create DUE occurrence for the latest slot
        due_occurrence = ScheduleOccurrence(
            deployment_id=definition.deployment_id,
            schedule_id=definition.schedule_id,
            definition_version=definition.version,
            work_kind=definition.work_kind,
            intended_slot=latest_slot.intended_slot_key,
            intended_utc_instant=latest_slot.intended_utc_instant,
            local_offset_minutes=latest_slot.local_offset_minutes,
            fold=latest_slot.fold,
            outcome=OccurrenceOutcome.DUE,
            details_json={
                "is_gap_adjusted": latest_slot.is_gap_adjusted,
                "adjusted_local_time": latest_slot.adjusted_local_time,
            } if latest_slot.is_gap_adjusted else None,
            created_at=now_utc,
            updated_at=now_utc,
        )

        return due_occurrence, newly_recorded

