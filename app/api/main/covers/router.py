# app/api/main/covers/router.py
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.db.database import get_db
from app.models.cms import Media
from app.models.main import Cover
from app.services.aws_service import s3_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/main",
    tags=["Covers"],
    dependencies=[Depends(get_current_admin)],
)


def _media_to_dict(media: Media | None) -> dict | None:
    if not media:
        return None
    return {
        "id": media.id,
        "url": media.url,
        "filename": media.filename,
        "original_name": media.original_name,
        "mime_type": media.mime_type,
        "alt_text": media.alt_text,
    }


def _cover_to_dict(cover: Cover | None) -> dict | None:
    if not cover:
        return None
    return {
        "id": cover.id,
        "nombre": cover.nombre,
        "tipo": cover.tipo.value,
        "portada": _media_to_dict(cover.portada),
        "primer_imagen_footer": _media_to_dict(cover.primer_imagen_footer),
        "segundo_imagen_footer": _media_to_dict(cover.segundo_imagen_footer),
        "logo_superior": _media_to_dict(cover.logo_superior),
        "imagen_central": _media_to_dict(cover.imagen_central),
        "logo_inferior": _media_to_dict(cover.logo_inferior),
        "imagen_fondo": _media_to_dict(cover.imagen_fondo),
    }


@router.get("/covers/{cover_id}")
def get_cover(cover_id: int, db: Session = Depends(get_db)):
    result = db.execute(
        select(Cover)
        .where(Cover.id == cover_id, Cover.deleted_at.is_(None))
        .options(
            joinedload(Cover.portada),
            joinedload(Cover.primer_imagen_footer),
            joinedload(Cover.segundo_imagen_footer),
            joinedload(Cover.logo_superior),
            joinedload(Cover.imagen_central),
            joinedload(Cover.logo_inferior),
            joinedload(Cover.imagen_fondo),
        )
    )
    cover = result.unique().scalar_one_or_none()
    if not cover:
        raise HTTPException(status_code=404, detail="Cover not found")
    return _cover_to_dict(cover)


@router.get("/covers")
def list_covers(db: Session = Depends(get_db)):
    result = db.execute(
        select(Cover)
        .where(Cover.deleted_at.is_(None))
        .options(
            joinedload(Cover.portada),
            joinedload(Cover.primer_imagen_footer),
            joinedload(Cover.segundo_imagen_footer),
            joinedload(Cover.logo_superior),
            joinedload(Cover.imagen_central),
            joinedload(Cover.logo_inferior),
            joinedload(Cover.imagen_fondo),
        )
    )
    covers = result.unique().scalars().all()
    return [_cover_to_dict(c) for c in covers]


def _create_media_from_upload(db: Session, file: UploadFile) -> Optional[int]:
    if not file or not file.filename:
        return None

    try:
        s3_result = s3_service.upload_file(file, folder="covers")
    except Exception as e:
        # Si falla AWS S3, lanzamos un 400 para que el frontend lo pueda mostrar
        # y no cause un 500 que rompe los headers CORS.
        raise HTTPException(
            status_code=400, detail=f"Error subiendo archivo a AWS S3: {str(e)}"
        )

    media = Media(
        filename=s3_result["object_key"].split("/")[-1],
        original_name=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        url=s3_result["file_url"],
        storage_path=s3_result["object_key"],
        folder="/covers",
    )
    db.add(media)
    db.flush()  # Para obtener el ID generado
    return media.id


@router.post("/covers", status_code=status.HTTP_201_CREATED)
def create_cover(
    nombre: str = Form(...),
    tipo: str = Form(...),
    portada_id: Optional[int] = Form(None),
    primer_imagen_footer_id: Optional[int] = Form(None),
    segundo_imagen_footer_id: Optional[int] = Form(None),
    logo_superior_id: Optional[int] = Form(None),
    imagen_central_id: Optional[int] = Form(None),
    logo_inferior_id: Optional[int] = Form(None),
    imagen_fondo_id: Optional[int] = Form(None),
    portada: Optional[UploadFile] = File(None),
    primer_imagen_footer: Optional[UploadFile] = File(None),
    segundo_imagen_footer: Optional[UploadFile] = File(None),
    logo_superior: Optional[UploadFile] = File(None),
    imagen_central: Optional[UploadFile] = File(None),
    logo_inferior: Optional[UploadFile] = File(None),
    imagen_fondo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    # Subir nuevos archivos a S3 y crear los Media correspondientes si existen
    if portada and portada.filename:
        portada_id = _create_media_from_upload(db, portada)
    if primer_imagen_footer and primer_imagen_footer.filename:
        primer_imagen_footer_id = _create_media_from_upload(db, primer_imagen_footer)
    if segundo_imagen_footer and segundo_imagen_footer.filename:
        segundo_imagen_footer_id = _create_media_from_upload(db, segundo_imagen_footer)
    if logo_superior and logo_superior.filename:
        logo_superior_id = _create_media_from_upload(db, logo_superior)
    if imagen_central and imagen_central.filename:
        imagen_central_id = _create_media_from_upload(db, imagen_central)
    if logo_inferior and logo_inferior.filename:
        logo_inferior_id = _create_media_from_upload(db, logo_inferior)
    if imagen_fondo and imagen_fondo.filename:
        imagen_fondo_id = _create_media_from_upload(db, imagen_fondo)

    cover = Cover(
        nombre=nombre,
        tipo=tipo,
        portada_id=portada_id,
        primer_imagen_footer_id=primer_imagen_footer_id,
        segundo_imagen_footer_id=segundo_imagen_footer_id,
        logo_superior_id=logo_superior_id,
        imagen_central_id=imagen_central_id,
        logo_inferior_id=logo_inferior_id,
        imagen_fondo_id=imagen_fondo_id,
    )
    db.add(cover)
    db.commit()
    db.refresh(cover)
    return get_cover(cover.id, db)


@router.put("/covers/{cover_id}")
def update_cover(
    cover_id: int,
    nombre: Optional[str] = Form(None),
    tipo: Optional[str] = Form(None),
    portada_id: Optional[int] = Form(None),
    primer_imagen_footer_id: Optional[int] = Form(None),
    segundo_imagen_footer_id: Optional[int] = Form(None),
    logo_superior_id: Optional[int] = Form(None),
    imagen_central_id: Optional[int] = Form(None),
    logo_inferior_id: Optional[int] = Form(None),
    imagen_fondo_id: Optional[int] = Form(None),
    portada: Optional[UploadFile] = File(None),
    primer_imagen_footer: Optional[UploadFile] = File(None),
    segundo_imagen_footer: Optional[UploadFile] = File(None),
    logo_superior: Optional[UploadFile] = File(None),
    imagen_central: Optional[UploadFile] = File(None),
    logo_inferior: Optional[UploadFile] = File(None),
    imagen_fondo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")

    now = datetime.utcnow()

    # Si vienen nuevos archivos, intentar eliminar los antiguos en S3
    # y marcar los Media existentes como borrados (soft-delete) antes de subir
    if portada and portada.filename:
        existing = getattr(cover, "portada")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.portada_id = None
        portada_id = _create_media_from_upload(db, portada)

    if primer_imagen_footer and primer_imagen_footer.filename:
        existing = getattr(cover, "primer_imagen_footer")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.primer_imagen_footer_id = None
        primer_imagen_footer_id = _create_media_from_upload(db, primer_imagen_footer)

    if segundo_imagen_footer and segundo_imagen_footer.filename:
        existing = getattr(cover, "segundo_imagen_footer")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.segundo_imagen_footer_id = None
        segundo_imagen_footer_id = _create_media_from_upload(db, segundo_imagen_footer)

    if logo_superior and logo_superior.filename:
        existing = getattr(cover, "logo_superior")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.logo_superior_id = None
        logo_superior_id = _create_media_from_upload(db, logo_superior)

    if imagen_central and imagen_central.filename:
        existing = getattr(cover, "imagen_central")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.imagen_central_id = None
        imagen_central_id = _create_media_from_upload(db, imagen_central)

    if logo_inferior and logo_inferior.filename:
        existing = getattr(cover, "logo_inferior")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.logo_inferior_id = None
        logo_inferior_id = _create_media_from_upload(db, logo_inferior)

    if imagen_fondo and imagen_fondo.filename:
        existing = getattr(cover, "imagen_fondo")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.imagen_fondo_id = None
        imagen_fondo_id = _create_media_from_upload(db, imagen_fondo)

    # Actualizar campos si se proporcionaron
    if nombre is not None:
        cover.nombre = nombre
    if tipo is not None:
        cover.tipo = tipo

    # Asociar nuevos media ids si fueron proporcionados
    if portada_id is not None:
        cover.portada_id = portada_id
    if primer_imagen_footer_id is not None:
        cover.primer_imagen_footer_id = primer_imagen_footer_id
    if segundo_imagen_footer_id is not None:
        cover.segundo_imagen_footer_id = segundo_imagen_footer_id
    if logo_superior_id is not None:
        cover.logo_superior_id = logo_superior_id
    if imagen_central_id is not None:
        cover.imagen_central_id = imagen_central_id
    if logo_inferior_id is not None:
        cover.logo_inferior_id = logo_inferior_id
    if imagen_fondo_id is not None:
        cover.imagen_fondo_id = imagen_fondo_id

    db.commit()
    db.refresh(cover)
    return get_cover(cover_id, db)


@router.delete("/covers/{cover_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cover(cover_id: int, db: Session = Depends(get_db)):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")
    now = datetime.utcnow()

    # Campos de Media relacionados con la cover
    media_fields = [
        "portada",
        "primer_imagen_footer",
        "segundo_imagen_footer",
        "logo_superior",
        "imagen_central",
        "logo_inferior",
        "imagen_fondo",
    ]

    # Intentar eliminar objetos en S3 y marcar los Media como borrados (soft-delete)
    for field in media_fields:
        media = getattr(cover, field)
        if media:
            try:
                # storage_path contiene el object key
                s3_service.delete_file(media.storage_path)
            except Exception:
                # No interrumpimos si falla la eliminación en S3; marcamos el media como borrado de todos modos
                pass

            media.deleted_at = now
            db.add(media)
            # Desasociar la media de la cover
            setattr(cover, f"{field}_id", None)

    cover.deleted_at = now
    db.commit()
    return None
