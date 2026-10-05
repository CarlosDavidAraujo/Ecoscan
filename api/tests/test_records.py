from datetime import UTC, datetime
from io import BytesIO
from unittest import IsolatedAsyncioTestCase

from starlette.datastructures import Headers, UploadFile

from ecoscan.models import Identification, User
from ecoscan.routes.records import (
    create_history_record,
    delete_history_record,
    list_history,
    remove_from_library,
)


class FakeScalarResult:
    def __init__(self, records: list[Identification]) -> None:
        self.records = records

    def all(self) -> list[Identification]:
        return self.records


class FakeSession:
    def __init__(self) -> None:
        self.records: list[Identification] = []
        self.scalar_result: Identification | None = None

    def add(self, record: Identification) -> None:
        if record not in self.records:
            self.records.append(record)

    async def commit(self) -> None:
        return None

    async def refresh(self, record: Identification) -> None:
        if record.created_at is None:
            record.created_at = datetime.now(UTC)

    async def scalars(self, statement: object) -> FakeScalarResult:
        return FakeScalarResult(self.records)

    async def scalar(self, statement: object) -> Identification | None:
        return self.scalar_result

    async def delete(self, record: Identification) -> None:
        self.records.remove(record)


def create_user() -> User:
    return User(
        name="test-user",
        email="test@example.com",
        password="hashed-password",
    )


def create_upload() -> UploadFile:
    return UploadFile(
        file=BytesIO(b"fake-image"),
        filename="plant.png",
        headers=Headers({"content-type": "image/png"}),
    )


class RecordRouteTests(IsolatedAsyncioTestCase):
    async def test_creates_and_lists_authenticated_history_record(self) -> None:
        session = FakeSession()
        user = create_user()

        response = await create_history_record(
            session=session,
            current_user=user,
            image=create_upload(),
            plant_name="Mangueira",
            confidence=0.93,
            recognized=True,
            plant_slug="mango",
            add_to_library=True,
        )
        records = await list_history(session=session, current_user=user)

        self.assertEqual(response.plant_name, "Mangueira")
        self.assertEqual(response.confidence, 0.93)
        self.assertTrue(response.image_url)
        self.assertTrue(response.thumbnail_url)
        self.assertEqual(session.records[0].image_data, b"fake-image")
        self.assertEqual(session.records[0].user_id, user.id)
        self.assertTrue(session.records[0].in_library)
        self.assertEqual(len(records), 1)

    async def test_removes_from_library_without_deleting_history(self) -> None:
        session = FakeSession()
        user = create_user()
        await create_history_record(
            session=session,
            current_user=user,
            image=create_upload(),
            plant_name="Bananeira",
            confidence=0.81,
            recognized=True,
            plant_slug="banana",
            add_to_library=True,
        )
        session.scalar_result = session.records[0]

        response = await remove_from_library(
            identification_id=session.records[0].id,
            session=session,
            current_user=user,
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(session.records[0].in_library)
        self.assertEqual(len(session.records), 1)

    async def test_deletes_history_record(self) -> None:
        session = FakeSession()
        user = create_user()
        await create_history_record(
            session=session,
            current_user=user,
            image=create_upload(),
            plant_name="Cafe",
            confidence=0.72,
            recognized=True,
            plant_slug="coffee",
            add_to_library=False,
        )
        session.scalar_result = session.records[0]

        response = await delete_history_record(
            identification_id=session.records[0].id,
            session=session,
            current_user=user,
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(session.records, [])
