"""One runnable check for the parts that would silently corrupt data if they broke:
type inference, cell coercion, header cleaning, and the read-only SQL guard.

Run it with:  .venv/bin/python test_pipeline.py
"""

from app import analysis
from app.etl import clean_name, coerce, infer_type, norm_cell, parse_records


def test_header_cleaning():
    taken: set[str] = set()
    assert clean_name("Order Date", taken) == "order_date"
    assert clean_name("Discount %", taken) == "discount"
    assert clean_name("2024 Total", taken) == "c_2024_total"
    assert clean_name("Order Date", taken) == "order_date_2"  # collision gets a suffix
    assert clean_name("!!!", taken) == "column"


def test_null_tokens():
    for token in ["", "  ", "N/A", "null", "NaN", "-", "unknown"]:
        assert norm_cell(token) is None, token
    assert norm_cell("  North ") == "North"
    assert norm_cell(0) == "0"


def test_type_inference():
    assert infer_type(["1", "2", "3"], "quantity", 3) == "integer"
    assert infer_type(["1.5", "2,300.10", "$4.00"], "price", 3) == "numeric"
    assert infer_type(["Yes", "No", "yes"], "returned", 3) == "boolean"
    assert infer_type(["2024-01-01", "2024-06-30"], "order_date", 2) == "datetime"
    assert infer_type(["North", "South", "North", "East"], "region", 4) == "categorical"
    # a 0/1 column stays numeric - it must not be silently turned into a boolean
    assert infer_type(["0", "1", "1", "0"], "flag", 4) == "integer"


def test_coercion_quarantines_bad_cells():
    values, lost = coerce(["10", "oops", None, "12"], "integer")
    assert values == [10, None, None, 12]
    assert lost == 1  # only "oops" was lost; the pre-existing null is not counted
    assert coerce(["(1,200.50)"], "numeric")[0] == [-1200.5]
    assert coerce(["Y", "n"], "boolean")[0] == [True, False]


def test_json_shapes():
    assert list(parse_records([{"a": 1}, {"a": 2}]).columns) == ["a"]
    assert list(parse_records({"data": [{"b": 1}]}).columns) == ["b"]
    assert len(parse_records([["h1", "h2"], [1, 2], [3, 4]])) == 2


def test_sql_guard_blocks_writes():
    blocked = [
        "DROP TABLE core.datasets",
        "SELECT 1; DELETE FROM core.datasets",
        "UPDATE core.datasets SET name='x'",
        "SELECT pg_read_file('/etc/passwd')",
        "INSERT INTO core.datasets VALUES (1)",
    ]
    for sql in blocked:
        try:
            analysis.guard(sql)
        except analysis.SQLError:
            continue
        raise AssertionError(f"guard let this through: {sql}")

    # legitimate reads survive, and a LIMIT is added when one is missing
    assert analysis.guard('SELECT * FROM data."t"').endswith("LIMIT 500")
    assert analysis.guard('SELECT * FROM data."t" LIMIT 5').endswith("LIMIT 5")
    # a column literally named "update" must not trip the keyword scan
    analysis.guard('SELECT "update" FROM data."t"')
    analysis.guard('WITH x AS (SELECT 1 AS n) SELECT n FROM x')


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nAll checks passed.")
