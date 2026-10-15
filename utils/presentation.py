import csv
import io
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation


def numeric(value):
    if value is None or isinstance(value, bool):
        return False
    try:
        return Decimal(str(value)).is_finite()
    except InvalidOperation:
        return False


def chart_spec(data):
    columns, rows = data.get("columns", []), data.get("rows", [])
    if not 2 <= len(rows) <= 200 or len(columns) < 2 or any(len(row) != len(columns) for row in rows):
        return None
    measures = [column for i, column in enumerate(columns)
                if any(row[i] is not None for row in rows)
                and all(row[i] is None or numeric(row[i]) for row in rows)]
    dimensions = [column for column in columns if column not in measures]
    if len(dimensions) != 1 or not measures:
        return None
    dimension, measure = dimensions[0], measures[0]
    x, y = columns.index(dimension), columns.index(measure)
    values = [row[x] for row in rows]
    if any(value is None for value in values) or len(set(values)) != len(values):
        return None
    try:
        dates = [datetime.fromisoformat(str(value)) for value in values]
        temporal = all(date.tzinfo is not None for date in dates) or all(date.tzinfo is None for date in dates)
    except ValueError:
        temporal = False
    if any(row[y] is not None and not math.isfinite(float(Decimal(str(row[y])))) for row in rows):
        return None
    kind = "line" if temporal else "bar"
    unit = data.get("units", {}).get(measure, "")
    present = [Decimal(str(row[y])) for row in rows if row[y] is not None]
    if not temporal and len(rows) <= 12 and all(v >= 0 for v in present) and len(present) == len(rows):
        total = sum(present)
        if (unit == "%" and abs(total - 100) < Decimal("0.0001")) or (
                unit in ("ratio", "fraction") and abs(total - 1) < Decimal("0.000001")):
            kind = "pie"
    if kind == "bar" and len(rows) > 30:
        return None
    return {"kind": kind, "x": dimension, "y": measure, "unit": unit, "aggregation": "none"}


def csv_export(data):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(data["columns"])
    for row in data["rows"]:
        writer.writerow([
            "'" + value if isinstance(value, str) and value.startswith(("=", "+", "@")) else value
            for value in row])
    return stream.getvalue()


def export_run(replay, format="json", artifact_id=None):
    if format == "json":
        return json.dumps(replay, ensure_ascii=False, indent=2), "application/json", "json"
    if format == "markdown":
        state = replay["snapshot"]
        return ((f"# {state['question']}\n\n{state['status']} · {state['created_at']}\n\n"
                 f"{state.get('report', '')}\n\nAnswer sufficiency: {state.get('answer_sufficiency')}\n"),
                "text/markdown", "md")
    if format == "csv":
        payload = replay["artifacts"].get(artifact_id, {})
        if not isinstance(payload.get("data"), dict) or "rows" not in payload["data"]:
            raise ValueError("CSV export requires a tabular artifact_id")
        return csv_export(payload["data"]), "text/csv", "csv"
    raise ValueError("Export format must be json, markdown or csv")
