import io
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from ecoscan.aws.cache import delete_cache, get_cache, set_cache
from ecoscan.aws.s3 import create_thumbnail, delete_from_s3, upload_to_s3
from ecoscan.plant_catalog import PLANT_CARE_CATALOG, get_plant_care_guide


class AWSS3AndCacheTests(IsolatedAsyncioTestCase):
    def test_create_thumbnail_generates_valid_image(self) -> None:
        # Cria uma imagem de teste 600x600 em memória
        img = Image.new("RGB", (600, 600), color="green")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        orig_bytes = buf.getvalue()

        # Executa rescaling via create_thumbnail
        thumb_bytes = create_thumbnail(orig_bytes, max_size=(150, 150))
        self.assertIsInstance(thumb_bytes, bytes)
        self.assertGreater(len(thumb_bytes), 0)

        # Valida que as dimensões foram reduzidas para <= 150
        with Image.open(io.BytesIO(thumb_bytes)) as thumb:
            self.assertLessEqual(thumb.width, 150)
            self.assertLessEqual(thumb.height, 150)

    @patch("ecoscan.aws.s3.get_s3_client")
    def test_upload_to_s3_with_boto3(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with patch("ecoscan.aws.s3._settings") as mock_settings:
            mock_settings.AWS_S3_BUCKET_NAME = "test-bucket"
            mock_settings.AWS_REGION = "us-east-1"

            url = upload_to_s3(b"fake-bytes", "test/image.jpg", "image/jpeg")

            mock_client.put_object.assert_called_once_with(
                Bucket="test-bucket",
                Key="test/image.jpg",
                Body=b"fake-bytes",
                ContentType="image/jpeg",
            )
            self.assertEqual(url, "https://test-bucket.s3.amazonaws.com/test/image.jpg")

    @patch("ecoscan.aws.s3.get_s3_client")
    def test_delete_from_s3_with_boto3(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with patch("ecoscan.aws.s3._settings") as mock_settings:
            mock_settings.AWS_S3_BUCKET_NAME = "test-bucket"
            result = delete_from_s3("test/image.jpg")

            mock_client.delete_object.assert_called_once_with(
                Bucket="test-bucket",
                Key="test/image.jpg",
            )
            self.assertTrue(result)

    @patch("ecoscan.aws.cache.get_redis_client")
    async def test_cache_set_and_get(self, mock_get_redis: MagicMock) -> None:
        fake_redis = AsyncMock()
        mock_get_redis.return_value = fake_redis

        fake_redis.get.return_value = '{"foo": "bar"}'

        # Set cache
        saved = await set_cache("test_key", {"foo": "bar"}, ttl_seconds=60)
        self.assertTrue(saved)
        fake_redis.set.assert_called_once()

        # Get cache
        value = await get_cache("test_key")
        self.assertEqual(value, {"foo": "bar"})

        # Delete cache
        deleted = await delete_cache("test_key")
        self.assertTrue(deleted)
        fake_redis.delete.assert_called_once_with("test_key")

    def test_plant_catalog_contains_expected_species(self) -> None:
        self.assertIn("banana", PLANT_CARE_CATALOG)
        self.assertIn("coffee", PLANT_CARE_CATALOG)
        self.assertIn("coconut", PLANT_CARE_CATALOG)
        self.assertIn("mango", PLANT_CARE_CATALOG)
        self.assertIn("tomato", PLANT_CARE_CATALOG)

        guide = get_plant_care_guide("coffee")
        self.assertIsNotNone(guide)
        self.assertEqual(guide["common_name"], "Cafeeiro")
        self.assertIn("Rubiaceae", guide["family"])
