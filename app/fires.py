"""Static, operator-drawn demo fires. These never create caller instructions."""
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SimulatedFire(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=1000)
    simulated: Literal[True] = True

    @field_validator('label')
    @classmethod
    def valid_label(cls, value):
        if not value.strip():
            raise ValueError('Enter a fire name')
        return value.strip()

    @field_validator('polygon')
    @classmethod
    def valid_polygon(cls, points):
        if any(not (-90 <= lat <= 90 and -180 <= lng <= 180) for lat, lng in points):
            raise ValueError('Invalid coordinates')
        if points[0] == points[-1]:
            points = points[:-1]
        if len(set(points)) != len(points) or len(points) < 3:
            raise ValueError('Use at least three distinct corners')
        origin = points[0]
        area = sum((a[1] - origin[1]) * (b[0] - origin[0]) - (b[1] - origin[1]) * (a[0] - origin[0])
                   for a, b in zip(points, points[1:] + points[:1]))
        if abs(area) <= 1e-12:
            raise ValueError('Draw a fire with a nonzero area')
        def cross(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        def touches(a, b, c):
            return cross(a, b, c) == 0 and all(min(a[k], b[k]) <= c[k] <= max(a[k], b[k]) for k in (0, 1))
        edges = list(zip(points, points[1:] + points[:1]))
        for i, (a, b) in enumerate(edges):
            for j in range(i + 1, len(edges)):
                if j == i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                c, d = edges[j]
                if (cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0
                        or touches(a, b, c) or touches(a, b, d) or touches(c, d, a) or touches(c, d, b)):
                    raise ValueError('Fire edges must not cross; redraw the perimeter')
        return points


def fires(db):
    return [json.loads(row['data']) for row in db.execute('SELECT data FROM simulated_fires ORDER BY rowid')]
