
from datetime import datetime
from typing import Self

import pendulum
from peewee import Model
from playhouse.postgres_ext import DateTimeTZField as RawDateTimeTZField
from playhouse.postgres_ext import PostgresqlExtDatabase
from playhouse.shortcuts import model_to_dict

database = PostgresqlExtDatabase("sinaspider", host="localhost")


class DateTimeTZField(RawDateTimeTZField):
    def python_value(self, value):
        if value is not None:
            return pendulum.instance(value)
        return value


class BaseModel(Model):
    class Meta:
        database = database

    def __repr__(self):
        model = model_to_dict(self, recurse=False)
        for k, v in model.items():
            if isinstance(v, datetime):
                model[k] = v.strftime("%Y-%m-%d %H:%M:%S")

        return "\n".join(f'{k}: {v}' for k, v in model.items()
                         if v is not None)

    @classmethod
    def get_or_none(cls, *query, **filters) -> Self | None:
        return super().get_or_none(*query, **filters)

    @classmethod
    def get(cls, *query, **filters) -> Self:
        return super().get(*query, **filters)

    @classmethod
    def get_by_id(cls, *query, **filters) -> Self:
        return super().get_by_id(*query, **filters)
