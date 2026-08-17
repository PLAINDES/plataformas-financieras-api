from app.models.main import ReportPayment
from app.models.user import User


def test_user_phone_is_optional() -> None:
    column = User.__table__.c.phone_number

    assert column.nullable is True
    assert column.type.length == 30


def test_report_payment_required_fields_and_indexes() -> None:
    table = ReportPayment.__table__

    required_columns = {
        "external_reference_id",
        "report_id",
        "calculation_id",
        "user_id",
        "amount",
        "currency",
        "description",
        "status",
        "customer_email",
        "customer_first_name",
        "customer_phone",
        "created_at",
        "updated_at",
    }
    assert all(table.c[name].nullable is False for name in required_columns)
    assert table.c.customer_last_name.nullable is True
    assert table.c.session_token.nullable is True
    assert table.c.checkout_url.nullable is True
    assert table.c.transaction_id.nullable is True
    assert table.c.expires_at.nullable is True
    assert table.c.paid_at.nullable is True

    indexed_columns = {
        column.name
        for index in table.indexes
        for column in index.columns
    }
    assert {
        "external_reference_id",
        "report_id",
        "calculation_id",
        "user_id",
        "status",
        "transaction_id",
    }.issubset(indexed_columns)


def test_report_payment_foreign_keys() -> None:
    table = ReportPayment.__table__
    targets = {foreign_key.target_fullname for foreign_key in table.foreign_keys}

    assert targets == {
        "main_reports.id",
        "main_calculations.id",
        "sys_users.id",
    }
