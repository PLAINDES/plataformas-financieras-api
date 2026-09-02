import os
import uuid
import json
import logging
from io import BytesIO

try:
    import boto3 # pylint: disable=import-error
    from botocore.exceptions import ClientError # pylint: disable=import-error
except Exception:  # pragma: no cover - optional dependency in local/dev
    boto3 = None

    class ClientError(Exception):
        pass
from fastapi import UploadFile
from PIL import Image

from app.core.constants import AWS_BASE_PREFIX
from app.core.config import settings

logger = logging.getLogger(__name__)

# Configuramos boto3 usando las credenciales del entorno
# Idealmente deberías definirlas en tu .env o config.py
# AWS_ACCESS_KEY_ID
# AWS_SECRET_ACCESS_KEY
# AWS_REGION_NAME
# AWS_BUCKET_NAME

class AWSS3Service:
    def __init__(self):
        # El bucket real en AWS no puede contener '/', debe ser solo el nombre
        self.bucket_name = settings.AWS_BUCKET_NAME
        # El prefijo base que simula una carpeta en S3 importado de constants.py
        self.base_prefix = AWS_BASE_PREFIX

        self.s3_client = None
        if not boto3:
            logger.warning("boto3 no está instalado. S3 quedará deshabilitado en este entorno.")
            return

        if not all([settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_ACCESS_KEY, settings.AWS_REGION_NAME, self.bucket_name]):
            logger.warning("Credenciales AWS incompletas. S3 quedará deshabilitado en este entorno.")
            return

        # Boto3 no carga automáticamente el .env de Pydantic, así que pasamos las credenciales explícitamente
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION_NAME
        )

    def _ensure_client(self):
        if not self.s3_client:
            raise RuntimeError("AWS S3 no está disponible: faltan credenciales o boto3.")

    def upload_file(self, file: UploadFile, folder: str = "uploads", custom_filename: str = None) -> dict:
        """
        Sube un archivo genérico a S3 y retorna un diccionario con la URL pública y el object key.
        Lee el archivo en memoria para poder reintentar sin problemas si el bucket bloquea ACLs.
        """
        try:
            self._ensure_client()
            if custom_filename:
                unique_filename = custom_filename
            else:
                extension = file.filename.split(".")[-1] if "." in file.filename else "bin"
                unique_filename = f"{uuid.uuid4().hex}.{extension}"
            object_key = f"{self.base_prefix}/{folder}/{unique_filename}"

            # Leer el archivo en memoria para poder reintentar sin problemas
            original_bytes = file.file.read()

            try:
                self.s3_client.upload_fileobj(
                    BytesIO(original_bytes),
                    self.bucket_name,
                    object_key,
                    ExtraArgs={
                        "ContentType": file.content_type,
                        "ACL": "public-read",
                    }
                )
            except ClientError as acl_error:
                acl_error_code = (
                    acl_error.response.get("Error", {}).get("Code", "")
                    if hasattr(acl_error, "response")
                    else ""
                )
                if acl_error_code == "AccessControlListNotSupported":
                    logger.warning("Bucket bloquea ACLs públicas; subiendo sin ACL. Asegúrate de que el bucket tenga una política pública.")
                    self.s3_client.upload_fileobj(
                        BytesIO(original_bytes),
                        self.bucket_name,
                        object_key,
                        ExtraArgs={
                            "ContentType": file.content_type,
                        }
                    )
                else:
                    raise

            region = settings.AWS_REGION_NAME
            file_url = f"https://{self.bucket_name}.s3.{region}.amazonaws.com/{object_key}"

            return {
                "file_url": file_url,
                "object_key": object_key
            }

        except ClientError as e:
            logger.error(f"Error subiendo archivo a S3 (ClientError): {e}")
            error_code = e.response.get("Error", {}).get("Code", "") if hasattr(e, "response") else ""
            if error_code in ("AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
                raise Exception("Credenciales de AWS incorrectas o sin permisos para escribir en el bucket.")
            raise Exception("No se pudo subir el archivo a S3 por permisos o configuración.")
        except Exception as e:
            logger.error(f"Error general S3: {e}")
            raise Exception(f"Revisa credenciales de S3 (boto3.client): {e}")
        finally:
            file.file.close()

    def upload_image(self, file: UploadFile, folder: str = "uploads") -> dict:
        """
        Sube una imagen a S3 convertida a WebP.
        Lee el archivo en memoria para poder reintentar sin problemas si el bucket bloquea ACLs.
        """
        try:
            self._ensure_client()
            unique_filename = f"{uuid.uuid4().hex}.webp"
            object_key = f"{self.base_prefix}/{folder}/{unique_filename}"

            # Leer el archivo original en memoria y convertir a WebP
            original_bytes = file.file.read()
            try:
                with Image.open(BytesIO(original_bytes)) as img:
                    # Convertir a RGB si es necesario (ej. PNG con transparencia)
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGBA")
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                    webp_buffer = BytesIO()
                    img.save(webp_buffer, format="WEBP", quality=85)
                    webp_buffer.seek(0)
                    webp_bytes = webp_buffer.getvalue()
            except Exception as e:
                raise Exception(f"Error convirtiendo la imagen a WebP: {str(e)}")

            try:
                self.s3_client.upload_fileobj(
                    BytesIO(webp_bytes),
                    self.bucket_name,
                    object_key,
                    ExtraArgs={
                        "ContentType": "image/webp",
                        "ACL": "public-read",
                    }
                )
            except ClientError as acl_error:
                acl_error_code = (
                    acl_error.response.get("Error", {}).get("Code", "")
                    if hasattr(acl_error, "response")
                    else ""
                )
                if acl_error_code == "AccessControlListNotSupported":
                    logger.warning("Bucket bloquea ACLs públicas; subiendo sin ACL. Asegúrate de que el bucket tenga una política pública.")
                    self.s3_client.upload_fileobj(
                        BytesIO(webp_bytes),
                        self.bucket_name,
                        object_key,
                        ExtraArgs={
                            "ContentType": "image/webp",
                        }
                    )
                else:
                    raise

            region = settings.AWS_REGION_NAME
            file_url = f"https://{self.bucket_name}.s3.{region}.amazonaws.com/{object_key}"

            return {
                "file_url": file_url,
                "object_key": object_key
            }

        except ClientError as e:
            logger.error(f"Error subiendo imagen a S3 (ClientError): {e}")
            error_code = e.response.get("Error", {}).get("Code", "") if hasattr(e, "response") else ""
            if error_code in ("AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
                raise Exception("Credenciales de AWS incorrectas o sin permisos para escribir en el bucket.")
            raise Exception("No se pudo subir la imagen a S3 por permisos o configuración.")
        except Exception as e:
            logger.error(f"Error general S3: {e}")
            raise Exception(f"{e}")
        finally:
            file.file.close()

    def delete_file(self, object_key: str) -> bool:
        """
        Elimina un archivo de S3 dado su object key.
        Nota: Si guardaste la URL completa, deberás extraer el object_key.
        """
        try:
            self._ensure_client()
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except ClientError as e:
            logger.error(f"Error eliminando archivo de S3: {e}")
            return False
        except Exception as e:
            logger.warning(f"S3 no disponible para eliminar {object_key}: {e}")
            return False

    def download_file_bytes(self, object_key: str) -> bytes:
        """Download an S3 object into memory."""
        self._ensure_client()
        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=object_key)
        return response["Body"].read()

    def generate_presigned_url(self, object_key: str, expiration: int = 3600) -> str:
        """
        Genera una URL firmada (presigned URL) para descargar un archivo privado.
        """
        try:
            self._ensure_client()
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_key},
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            logger.error(f"Error generando presigned URL: {e}")
            raise Exception("No se pudo generar el enlace temporal.")

    def list_files(self, prefix: str) -> list[dict]:
        """
        Lista archivos en S3 bajo un prefijo dado.
        Retorna lista de dicts con object_key, size, last_modified.
        """
        try:
            self._ensure_client()
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            files = []
            for obj in response.get("Contents", []):
                if obj["Key"].endswith("/"):
                    continue
                files.append({
                    "object_key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                })
            return files
        except ClientError as e:
            logger.error(f"Error listando archivos de S3: {e}")
            return []
        except Exception as e:
            logger.warning(f"S3 no disponible para listar archivos: {e}")
            return []

    def copy_object(self, source_key: str, dest_key: str) -> bool:
        """
        Copia un objeto dentro del mismo bucket S3.
        """
        try:
            self._ensure_client()
            self.s3_client.copy_object(
                CopySource={"Bucket": self.bucket_name, "Key": source_key},
                Bucket=self.bucket_name,
                Key=dest_key,
            )
            return True
        except ClientError as e:
            logger.error(f"Error copiando objeto en S3: {e}")
            return False
        except Exception as e:
            logger.warning(f"S3 no disponible para copiar objeto: {e}")
            return False

    def get_json_object(self, object_key: str) -> dict | None:
        """
        Lee y parsea un archivo JSON de S3.
        """
        try:
            self._ensure_client()
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=object_key)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                return None
            logger.error(f"Error leyendo JSON de S3: {e}")
            return None
        except Exception as e:
            logger.warning(f"S3 no disponible para leer JSON: {e}")
            return None

    def put_json_object(self, object_key: str, data: dict) -> bool:
        """
        Escribe un archivo JSON en S3.
        """
        try:
            self._ensure_client()
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=json.dumps(data).encode("utf-8"),
                ContentType="application/json",
            )
            return True
        except ClientError as e:
            logger.error(f"Error escribiendo JSON en S3: {e}")
            return False
        except Exception as e:
            logger.warning(f"S3 no disponible para escribir JSON: {e}")
            return False

    def extract_key_from_url(self, file_url: str) -> str:
        """
        Extrae el object_key de una URL pública de S3 para poder eliminarlo.
        Ej: https://mi-bucket.s3.us-east-1.amazonaws.com/uploads/123.jpg -> uploads/123.jpg
        """
        domain = f"s3.{settings.AWS_REGION_NAME}.amazonaws.com"
        if domain in file_url:
            return file_url.split(f"{domain}/")[-1]
        elif f"{self.bucket_name}.s3.amazonaws.com" in file_url:
            return file_url.split(f"{self.bucket_name}.s3.amazonaws.com/")[-1]

        # Fallback genérico si el hostname cambia
        return "/".join(file_url.split("/")[3:])


# Instancia singleton para exportar y usar en otras partes
s3_service = AWSS3Service()
