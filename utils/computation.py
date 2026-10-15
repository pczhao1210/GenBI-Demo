import json
from decimal import Decimal, InvalidOperation, localcontext

import pandas as pd

from utils.datasources import serialize_cell
from utils.run_store import utcnow

MAX_ROWS = 10000
MAX_BYTES = 16 * 1024 * 1024


def frame(result):
    data = result.get("data", {})
    if (not isinstance(data, dict) or not isinstance(data.get("rows"), list)
            or not isinstance(data.get("columns"), list)):
        raise ValueError("Computation requires a tabular input")
    if data.get("truncated") or data.get("completeness") != "COMPLETE":
        raise ValueError("Incomplete or truncated input cannot be used for full-data computation")
    if len(data["columns"]) != len(set(data["columns"])):
        raise ValueError("Computation requires unique column names")
    if len(data["rows"]) > MAX_ROWS:
        raise ValueError("Input row budget exceeded; aggregate at the source")
    result = pd.DataFrame(data["rows"], columns=data["columns"])
    if result.memory_usage(deep=True).sum() > MAX_BYTES:
        raise ValueError("Input memory budget exceeded")
    return result, data


def decimal_value(value):
    if value is None or isinstance(value, bool):
        raise ValueError("NULL and boolean values are not numeric operands")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Invalid numeric operand: {value}") from exc
    if not result.is_finite():
        raise ValueError("Non-finite numeric operand")
    return result


def output(df, metadata, diagnostics):
    if len(df) > MAX_ROWS or df.memory_usage(deep=True).sum() > MAX_BYTES:
        raise ValueError("Computation output budget exceeded")
    rows = [[None if pd.isna(value) else serialize_cell(value) for value in row]
            for row in df.itertuples(index=False, name=None)]
    if len(json.dumps(rows, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("Serialized computation output budget exceeded")
    return {"status": "success", "evidence_class": "calculation", "data": {
        **metadata, "columns": list(df.columns), "rows": rows, "row_count": len(rows),
        "logical_types": [str(dtype) for dtype in df.dtypes], "truncated": False,
        "completeness": "COMPLETE", "collected_at": utcnow(), "diagnostics": diagnostics}}


def check_alignment(left, right, requirements):
    required = ("entity", "grain", "time_range", "timezone", "units")
    for key in required:
        if key not in left or key not in right:
            raise ValueError(f"Cross-source alignment requires explicit {key} on both inputs")
        if key != "units" and left[key] != right[key]:
            raise ValueError(f"Incompatible cross-source {key}; align explicitly before joining")
    for column in set(left["units"]) & set(right["units"]):
        if left["units"][column] != right["units"][column]:
            raise ValueError(f"Incompatible units for {column}")
    if not requirements.get("cardinality"):
        raise ValueError("Join requires an explicit cardinality contract")


def join(inputs, requirements):
    if len(inputs) != 2:
        raise ValueError("Join requires exactly two inputs")
    (left, lm), (right, rm) = [frame(item) for item in inputs]
    check_alignment(lm, rm, requirements)
    left_on, right_on = requirements.get("left_on"), requirements.get("right_on")
    if (not isinstance(left_on, list) or not left_on or not isinstance(right_on, list)
            or len(left_on) != len(right_on) or set(left_on) - set(left) or set(right_on) - set(right)):
        raise ValueError("Join keys must be explicit existing columns on both sides")
    if left[left_on].isna().any().any() or right[right_on].isna().any().any():
        raise ValueError("NULL join keys require explicit source-side treatment")
    cardinality = requirements["cardinality"]
    if cardinality not in ("one_to_one", "one_to_many", "many_to_one"):
        raise ValueError("Many-to-many joins are not supported; aggregate or map keys first")
    if cardinality in ("one_to_one", "one_to_many") and left.duplicated(left_on).any():
        raise ValueError("Left join keys violate cardinality")
    if cardinality in ("one_to_one", "many_to_one") and right.duplicated(right_on).any():
        raise ValueError("Right join keys violate cardinality")
    left_keys = [tuple(row) for row in left[left_on].itertuples(index=False, name=None)]
    right_keys = [tuple(row) for row in right[right_on].itertuples(index=False, name=None)]
    left_set, right_set = set(left_keys), set(right_keys)
    unmatched_left = sum(key not in right_set for key in left_keys) / max(len(left), 1)
    unmatched_right = sum(key not in left_set for key in right_keys) / max(len(right), 1)
    threshold = requirements.get("max_unmatched_ratio", 0)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("max_unmatched_ratio must be between zero and one")
    if max(unmatched_left, unmatched_right) > threshold:
        raise ValueError(f"Unmatched key ratio exceeds contract: left={unmatched_left}, right={unmatched_right}")
    how = requirements.get("how", "inner")
    if how not in ("inner", "left", "outer"):
        raise ValueError("Unsupported join mode")
    # Cardinality is checked before allocating the joined frame.
    predicted = ((len(left_set | right_set) if how == "outer" else len(left)) if cardinality == "one_to_one"
                 else len(right) + len(left_set - right_set) if cardinality == "one_to_many"
                 else len(left) + len(right_set - left_set))
    if predicted > MAX_ROWS:
        raise ValueError("Join output row budget exceeded; aggregate at source")
    row_bytes = (left.memory_usage(deep=True).sum() / max(len(left), 1)
                 + right.memory_usage(deep=True).sum() / max(len(right), 1))
    if predicted * row_bytes > MAX_BYTES:
        raise ValueError("Join output memory budget exceeded before allocation")
    merged = left.merge(right, how=how, left_on=left_on, right_on=right_on,
                        validate=cardinality, suffixes=("_left", "_right"))
    overlaps = set(left.columns) & set(right.columns) - set(left_on) - set(right_on)
    repeated = []
    if cardinality == "one_to_many":
        repeated = [f"{c}_left" if c in overlaps else c for c in left.columns if c not in left_on]
    elif cardinality == "many_to_one":
        repeated = [f"{c}_right" if c in overlaps else c for c in right.columns if c not in right_on]
    units = {f"{c}_left" if c in overlaps else c: v for c, v in lm["units"].items()}
    units.update({f"{c}_right" if c in overlaps else c: v for c, v in rm["units"].items()})
    metadata = {key: lm[key] for key in ("entity", "grain", "time_range", "timezone")}
    metadata.update(units=units, repeated_measures=repeated,
                    sources=[lm.get("datasource_id"), rm.get("datasource_id")],
                    source_collected_at=[lm.get("collected_at"), rm.get("collected_at")])
    diagnostics = {"left_rows": len(left), "right_rows": len(right), "output_rows": len(merged),
                   "cardinality": cardinality, "unmatched_left_ratio": unmatched_left,
                   "unmatched_right_ratio": unmatched_right,
                   "warnings": ["Independent source collection times are not a consistent cross-database snapshot."]}
    diagnostics["source_totals"] = [
        {column: str(sum((decimal_value(value) for value in df[column] if value is not None), Decimal(0)))
         for column in metadata["units"] if column in df}
        for df, metadata in ((left, lm), (right, rm))]
    diagnostics["output_totals"] = {
        column: str(sum((decimal_value(value) for value in merged[column] if not pd.isna(value)), Decimal(0)))
        for column in units if column in merged}
    return output(merged, metadata, diagnostics)


def compute(requirements, results):
    with localcontext() as context:
        context.prec = 50
        return _compute(requirements, results)


def _compute(requirements, results):
    refs = requirements.get("inputs")
    if (not isinstance(refs, list) or not refs or any(type(ref) is not int or ref not in results for ref in refs)):
        raise ValueError("Computation inputs must be exact available step IDs")
    inputs = [results[ref] for ref in refs]
    operation = requirements.get("operation")
    if operation == "join":
        return join(inputs, requirements)
    if len(inputs) != 1:
        raise ValueError("Aggregate, ratio and difference require one aligned input")
    df, metadata = frame(inputs[0])
    group_by = requirements.get("group_by", [])
    if not isinstance(group_by, list) or set(group_by) - set(df):
        raise ValueError("Invalid grouping columns")
    if group_by and df[group_by].isna().any().any():
        raise ValueError("NULL grouping keys require explicit treatment")
    if operation == "aggregate":
        columns = requirements.get("columns", [])
    elif operation in ("ratio", "difference"):
        columns = [requirements.get("numerator"), requirements.get("denominator")]
    else:
        raise ValueError(f"Unsupported deterministic operation: {operation}")
    if (not columns or any(not isinstance(c, str) or c not in df for c in columns)
            or set(columns) & set(group_by)):
        raise ValueError("Invalid numeric columns")
    if set(columns) & set(metadata.get("repeated_measures", [])):
        raise ValueError("Measure was duplicated by a join; deduplicate or aggregate the source before computing")
    if operation == "difference":
        units = metadata.get("units", {})
        if columns[0] not in units or units.get(columns[0]) != units.get(columns[1]):
            raise ValueError("Difference requires explicitly matching units")
    policy = requirements.get("null_policy", "reject")
    if policy not in ("reject", "exclude"):
        raise ValueError("Unknown NULL policy")
    null_rows = df[columns].isna().any(axis=1)
    if null_rows.any() and policy == "reject":
        raise ValueError("NULL operands cannot be silently replaced by zero")
    df = df.loc[~null_rows].copy()
    for column in set(columns):
        df[column] = df[column].map(decimal_value)
    groups = df.groupby(group_by, dropna=False, sort=False) if group_by else [((), df)]
    records, zero_divisions = [], 0
    output_name = requirements.get("output", operation)
    if not isinstance(output_name, str) or output_name in group_by:
        raise ValueError("Invalid output column name")
    for keys, group in groups:
        keys = keys if isinstance(keys, tuple) else (keys,)
        record = dict(zip(group_by, keys))
        totals = {column: sum(group[column], Decimal(0)) for column in set(columns)}
        if operation == "aggregate":
            record.update(totals)
        elif operation == "ratio":
            denominator = totals[columns[1]]
            record[output_name] = totals[columns[0]] / denominator if denominator else None
            zero_divisions += not bool(denominator)
            record.update({f"{output_name}_numerator": totals[columns[0]],
                           f"{output_name}_denominator": denominator})
        else:
            record[output_name] = totals[columns[0]] - totals[columns[1]]
        records.append(record)
    names = [*group_by, *columns] if operation == "aggregate" else [
        *group_by, output_name, *([f"{output_name}_numerator", f"{output_name}_denominator"] if operation == "ratio" else [])]
    result = pd.DataFrame(records, columns=list(dict.fromkeys(names)))
    meta = {key: value for key, value in metadata.items()
            if key not in ("columns", "rows", "diagnostics", "logical_types", "repeated_measures")}
    meta["decimal_precision"] = 50
    return output(result, meta, {"operation": operation, "input_rows": len(metadata["rows"]),
                                "excluded_null_rows": int(null_rows.sum()), "zero_denominators": int(zero_divisions),
                                "warnings": ["Zero denominator produces NULL."] if zero_divisions else []})
