import os
import uuid
try:
    import boto3 # pylint: disable=import-error
    from botocore.exceptions import ClientError # pylint: disable=import-error
except Exception:  # pragma: no cover - optional dependency in local/dev
    boto3 = None

    class ClientError(Exception):
        pass
from fastapi import UploadFile
import logging

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

    def upload_file(self, file: UploadFile, folder: str = "uploads") -> dict:
        """
        Sube un archivo a S3 y retorna un diccionario con la URL pública y el object key.
        """
        try:
            self._ensure_client()
            # Generamos un nombre único para evitar colisiones
            extension = file.filename.split(".")[-1] if "." in file.filename else "bin"
            unique_filename = f"{uuid.uuid4().hex}.{extension}"
            
            # Incorporamos el base_prefix en la llave del objeto (ej: plataformas_financieras/uploads/archivo.jpg)
            object_key = f"{self.base_prefix}/{folder}/{unique_filename}"

            # Subimos a S3
            self.s3_client.upload_fileobj(
                file.file,
                self.bucket_name,
                object_key,
                ExtraArgs={"ContentType": file.content_type}
            )
            
            # Construimos la URL pública (asumiendo que el bucket es público para lectura)
            # O usando la estructura clásica: https://{bucket_name}.s3.{region}.amazonaws.com/{object_key}
            region = settings.AWS_REGION_NAME
            file_url = f"https://{self.bucket_name}.s3.{region}.amazonaws.com/{object_key}"
            
            return {
                "file_url": file_url,
                "object_key": object_key
            }

        except ClientError as e:
            logger.error(f"Error subiendo archivo a S3 (ClientError): {e}")
            raise Exception("No se pudo subir el archivo a S3 por permisos o configuración.")
        except Exception as e:
            logger.error(f"Error general S3: {e}")
            raise Exception(f"Revisa credenciales de S3 (boto3.client): {e}")
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
