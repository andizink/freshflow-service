"""Parser tests: header validation, row numbering, and cell coercion.

Covers :func:`app.ingest.parser.read_rows` — the gate every uploaded file
passes through before any rule (N1-N7 / Q1-Q5) is applied.
"""

import io

import pytest

from app.common.enums import DatasetKind
from app.ingest.parser import REQUIRED_HEADERS, HeaderError, read_rows

INVENTORY_HEADER = "store_id,item_number,day,quantity"


def _stream(text: str, *, encoding: str = "utf-8") -> io.BytesIO:
    """Wrap CSV text as the binary stream the parser expects."""
    return io.BytesIO(text.encode(encoding))


def test_reads_rows_with_row_numbers_starting_at_two() -> None:
    csv_text = f"{INVENTORY_HEADER}\nstore_a,1001,2024-01-01,16\nstore_b,1002,2024-01-02,17\n"

    rows = list(read_rows(_stream(csv_text), DatasetKind.INVENTORY))

    assert [row_number for row_number, _ in rows] == [2, 3]
    assert rows[0][1] == {
        "store_id": "store_a",
        "item_number": "1001",
        "day": "2024-01-01",
        "quantity": "16",
    }


def test_header_only_file_yields_no_rows() -> None:
    assert list(read_rows(_stream(f"{INVENTORY_HEADER}\n"), DatasetKind.INVENTORY)) == []


@pytest.mark.parametrize("dataset", list(DatasetKind))
def test_every_dataset_accepts_its_own_header(dataset: DatasetKind) -> None:
    header = ",".join(REQUIRED_HEADERS[dataset])

    assert list(read_rows(_stream(f"{header}\n"), dataset)) == []


def test_bom_prefixed_header_is_accepted() -> None:
    """A spreadsheet export's UTF-8 BOM must not corrupt the first column name."""
    csv_text = f"{INVENTORY_HEADER}\nstore_a,1001,2024-01-01,16\n"

    rows = list(read_rows(_stream(csv_text, encoding="utf-8-sig"), DatasetKind.INVENTORY))

    assert rows[0][1]["store_id"] == "store_a"


def test_column_order_is_irrelevant() -> None:
    csv_text = "quantity,day,item_number,store_id\n16,2024-01-01,1001,store_a\n"

    _, raw = next(iter(read_rows(_stream(csv_text), DatasetKind.INVENTORY)))

    assert raw == {
        "store_id": "store_a",
        "item_number": "1001",
        "day": "2024-01-01",
        "quantity": "16",
    }


@pytest.mark.parametrize(
    ("case", "csv_text"),
    [
        ("empty file", ""),
        ("misspelled column", "store_id,item_number,date,quantity\n"),
        ("extra column", f"{INVENTORY_HEADER},extra\n"),
        ("missing column", "store_id,item_number,day\n"),
        ("duplicate column", "store_id,item_number,day,day\n"),
        ("untrimmed column name", "store_id ,item_number,day,quantity\n"),
        ("other dataset's header", "item_number,name,category,is_bio\n"),
    ],
)
def test_bad_header_raises(case: str, csv_text: str) -> None:
    with pytest.raises(HeaderError) as excinfo:
        list(read_rows(_stream(csv_text), DatasetKind.INVENTORY))

    expected_header = REQUIRED_HEADERS[DatasetKind.INVENTORY]
    assert excinfo.value.expected == expected_header
    assert sorted(excinfo.value.found) != sorted(expected_header), case


def test_header_error_reports_expected_and_found() -> None:
    with pytest.raises(HeaderError) as excinfo:
        list(read_rows(_stream(""), DatasetKind.ITEMS))

    error = excinfo.value
    assert error.expected == REQUIRED_HEADERS[DatasetKind.ITEMS]
    assert error.found == ()
    assert "expected columns" in str(error)


def test_short_row_missing_cells_become_empty_strings() -> None:
    """Missing cells arrive as ``""``, so rules see a blank, never ``None``."""
    csv_text = f"{INVENTORY_HEADER}\nstore_a,1001\n"

    _, raw = next(iter(read_rows(_stream(csv_text), DatasetKind.INVENTORY)))

    assert raw == {"store_id": "store_a", "item_number": "1001", "day": "", "quantity": ""}


def test_extra_cells_beyond_the_header_are_dropped() -> None:
    csv_text = f"{INVENTORY_HEADER}\nstore_a,1001,2024-01-01,16,junk\n"

    _, raw = next(iter(read_rows(_stream(csv_text), DatasetKind.INVENTORY)))

    assert set(raw) == set(REQUIRED_HEADERS[DatasetKind.INVENTORY])


def test_values_are_yielded_unmodified() -> None:
    """The parser never normalizes; that is the rules layer's job."""
    csv_text = f"{INVENTORY_HEADER}\n STORE_A ,1001.0,23/01/2024,16.4\n"

    _, raw = next(iter(read_rows(_stream(csv_text), DatasetKind.INVENTORY)))

    assert raw["store_id"] == " STORE_A "
    assert raw["item_number"] == "1001.0"
    assert raw["day"] == "23/01/2024"
    assert raw["quantity"] == "16.4"


def test_crlf_line_endings_are_handled() -> None:
    csv_text = f"{INVENTORY_HEADER}\r\nstore_a,1001,2024-01-01,16\r\n"

    rows = list(read_rows(_stream(csv_text), DatasetKind.INVENTORY))

    assert rows == [
        (2, {"store_id": "store_a", "item_number": "1001", "day": "2024-01-01", "quantity": "16"})
    ]


def test_quoted_newline_counts_as_one_row() -> None:
    """Row numbers count CSV records, not physical lines."""
    csv_text = (
        "item_number,name,category,is_bio,purchase_price,suggested_retail_price\n"
        '1001,"Two\nLines",Fruits,False,0.89,1.49\n'
        "1002,Apple,Fruits,False,1.2,1.99\n"
    )

    rows = list(read_rows(_stream(csv_text), DatasetKind.ITEMS))

    assert [row_number for row_number, _ in rows] == [2, 3]
    assert rows[0][1]["name"] == "Two\nLines"


def test_parsing_is_lazy_and_streams() -> None:
    """Generator semantics: nothing is read until the first ``next``."""
    stream = _stream(f"{INVENTORY_HEADER}\nstore_a,1001,2024-01-01,16\n")
    rows = read_rows(stream, DatasetKind.INVENTORY)

    assert stream.tell() == 0
    next(iter(rows))
    assert stream.tell() > 0
