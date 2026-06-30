from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ScheduleRulePayload(BaseModel):
    name: str | None = None
    delivery_type: str
    rule_type: str
    enabled: bool = True
    time: str | None = None
    weekdays: list[int] | None = None
    month_dates: list[int] | None = None
    window_start: str | None = None
    window_end: str | None = None
    count_mode: str = "fixed"
    count_value: int | None = Field(default=1, ge=1)
    count_min: int | None = Field(default=None, ge=1)
    count_max: int | None = Field(default=None, ge=1)
    label: str | None = None

    @model_validator(mode="after")
    def validate_rule(self) -> "ScheduleRulePayload":
        if self.delivery_type not in {"poll", "summary"}:
            raise ValueError("delivery_type must be poll or summary")
        if self.rule_type not in {"daily_time", "weekday_time", "month_date_time", "random_window"}:
            raise ValueError("rule_type is invalid")
        if self.count_mode not in {"fixed", "range"}:
            raise ValueError("count_mode must be fixed or range")

        if self.rule_type == "daily_time":
            if not self.time:
                raise ValueError("time is required for daily_time rules")
        elif self.rule_type == "weekday_time":
            if not self.time:
                raise ValueError("time is required for weekday_time rules")
            if not self.weekdays:
                raise ValueError("weekdays are required for weekday_time rules")
        elif self.rule_type == "month_date_time":
            if not self.time:
                raise ValueError("time is required for month_date_time rules")
            if not self.month_dates:
                raise ValueError("month_dates are required for month_date_time rules")
        elif self.rule_type == "random_window" and (not self.window_start or not self.window_end):
            raise ValueError("window_start and window_end are required for random_window rules")

        if self.count_mode == "fixed" and self.count_value is None:
            raise ValueError("count_value is required for fixed count mode")
        if self.count_mode == "range":
            if self.count_min is None or self.count_max is None:
                raise ValueError("count_min and count_max are required for range count mode")
            if self.count_min > self.count_max:
                raise ValueError("count_min must be less than or equal to count_max")
        return self


class ScheduleRuleUpdatePayload(BaseModel):
    name: str | None = None
    delivery_type: str | None = None
    rule_type: str | None = None
    enabled: bool | None = None
    time: str | None = None
    weekdays: list[int] | None = None
    month_dates: list[int] | None = None
    window_start: str | None = None
    window_end: str | None = None
    count_mode: str | None = None
    count_value: int | None = Field(default=None, ge=1)
    count_min: int | None = Field(default=None, ge=1)
    count_max: int | None = Field(default=None, ge=1)
    label: str | None = None


class TextScheduleRuleAssignmentPayload(BaseModel):
    rule_id: int
