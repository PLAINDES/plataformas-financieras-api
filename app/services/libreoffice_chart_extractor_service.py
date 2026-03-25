import logging
# Configura logging global para mostrar INFO y superior
logging.basicConfig(level=logging.INFO)
# app/services/libreoffice_chart_extractor_service.py
"""
Servicio para extraer gráficos de archivos Excel usando LibreOffice Headless.

Estrategia: extraer cada gráfico en un XLSX aislado para garantizar
correspondencia 1:1 entre nombre del anchor e imagen exportada.
"""

import copy
import logging
import re
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional
from zipfile import ZIP_DEFLATED, ZipFile


from PIL import Image
from io import BytesIO
from app.services.aws_service import s3_service

from app.services.template_code_utils import normalize_code

logger = logging.getLogger(__name__)

NS_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"

for prefix, uri in [
    ("xdr", NS_XDR),
    ("r", NS_R),
    ("", NS_REL),
    ("m", NS_M),
    ("c", NS_C),
    ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"),
]:
    ET.register_namespace(prefix, uri)


def _norm(path: str) -> str:
    path = path.replace("\\", "/")
    parts = []
    for p in path.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/".join(parts)


class LibreOfficeChartExtractorService:
    TARGET_SHEETS = {
        "Plantilla Usuario": "valora",
        "WACC": "kapital",
    }

    def __init__(self, storage_path: Optional[str] = None, temp_path: Optional[str] = None):
        if storage_path is None:
            docker_path = Path("/app/public/master-templates-graphs")
            if docker_path.parent.parent.exists():
                storage_path = str(docker_path)
            else:
                storage_path = "./public/master-templates-graphs"

        self.storage_path = Path(storage_path)
        self.temp_path = Path(temp_path or "/tmp")

        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.temp_path.mkdir(parents=True, exist_ok=True)

        logger.info("LibreOffice Chart Extractor initialized")
        logger.info("Storage path: %s", self.storage_path)
        logger.info("Temp path: %s", self.temp_path)

    def _read_charts(self, excel_bytes: bytes) -> List[Dict]:
        # Lee la estructura XLSX (XML interno) para identificar cada gráfico
        # y su hoja origen sin depender del orden de exportación de LibreOffice.
        charts: List[Dict] = []

        with ZipFile(BytesIO(excel_bytes)) as zf:
            wb_xml = ET.fromstring(zf.read("xl/workbook.xml"))
            wb_rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            wb_map = {
                rel.get("Id"): _norm(f"xl/{rel.get('Target', '')}")
                for rel in wb_rels.findall(f"{{{NS_REL}}}Relationship")
                if rel.get("Id") and rel.get("Target")
            }

            for sheet in wb_xml.findall(f".//{{{NS_M}}}sheet"):
                sheet_name = sheet.get("name")
                if sheet_name not in self.TARGET_SHEETS:
                    continue

                rid = sheet.get(f"{{{NS_R}}}id")
                sheet_path = wb_map.get(rid)
                if not sheet_path:
                    continue

                try:
                    sheet_xml = ET.fromstring(zf.read(sheet_path))
                except Exception:
                    continue

                sheet_dir = "/".join(sheet_path.split("/")[:-1])
                sheet_rels_path = _norm(f"{sheet_dir}/_rels/{sheet_path.split('/')[-1]}.rels")
                try:
                    sheet_rels = ET.fromstring(zf.read(sheet_rels_path))
                except Exception:
                    continue

                sheet_rel_map = {
                    rel.get("Id"): _norm(f"{sheet_dir}/{rel.get('Target', '')}")
                    for rel in sheet_rels.findall(f"{{{NS_REL}}}Relationship")
                    if rel.get("Id") and rel.get("Target")
                }

                for drawing in sheet_xml.findall(f".//{{{NS_M}}}drawing"):
                    drawing_rid = drawing.get(f"{{{NS_R}}}id")
                    drawing_path = sheet_rel_map.get(drawing_rid)
                    if not drawing_path:
                        continue
                    # Sólo estas hojas son fuente oficial de gráficos para el flujo actual.
                    # Cualquier hoja distinta se ignora intencionalmente para evitar ruido.

                    try:
                        drawing_xml = ET.fromstring(zf.read(drawing_path))
                    except Exception:
                        continue

                    drawing_dir = "/".join(drawing_path.split("/")[:-1])
                    drawing_rels_path = _norm(
                            # Mapear r:id -> ruta física de cada hoja dentro del zip XLSX.
                        f"{drawing_dir}/_rels/{drawing_path.split('/')[-1]}.rels"
                    )
                    try:
                        drawing_rels = ET.fromstring(zf.read(drawing_rels_path))
                    except Exception:
                        continue

                    drawing_rel_map = {
                        rel.get("Id"): rel.get("Target", "")
                                    # Si una hoja no se puede parsear, continuamos con las demás.
                        for rel in drawing_rels.findall(f"{{{NS_REL}}}Relationship")
                        if rel.get("Id")
                    }

                    anchors = (
                        drawing_xml.findall(f"{{{NS_XDR}}}twoCellAnchor")
                        + drawing_xml.findall(f"{{{NS_XDR}}}oneCellAnchor")
                        + drawing_xml.findall(f"{{{NS_XDR}}}absoluteAnchor")
                    )

                    for anchor in anchors:
                        chart_el = anchor.find(f".//{{{NS_C}}}chart")
                        if chart_el is None:
                            continue

                        nvpr = anchor.find(f".//{{{NS_XDR}}}cNvPr")
                        name = ((nvpr.get("name") if nvpr is not None else "") or "").strip()


                                    # Cada anchor puede contener objetos distintos (formas, imágenes, charts).
                                    # Filtramos sólo los anchors que realmente referencian un chart.
                        chart_rid = chart_el.get(f"{{{NS_R}}}id")
                        chart_target = drawing_rel_map.get(chart_rid, "")

                        if not name:
                            match = re.search(r"chart(\d+)\.xml", chart_target, re.I)
                            name = f"Chart_{match.group(1)}" if match else f"Chart_{len(charts) + 1}"
                        elif name.startswith("AutoShape"):
                            continue

                                            # AutoShape suele ser ruido visual no vinculado al chart de interés.
                        charts.append(
                            {
                                "name": name,
                                "template_type": self.TARGET_SHEETS[sheet_name],
                                "sheet": sheet_name,
                                "drawing_path": drawing_path,
                                "drawing_rels_path": drawing_rels_path,
                                "drawing_xml": drawing_xml,
                                "drawing_rels": drawing_rels,
                                    # Mantener visible sólo la hoja del chart actual.
                                "anchor": anchor,
                                "chart_rid": chart_rid,
                            }
                        )

        logger.info("[Charts] Found %s charts in target sheets", len(charts))
                                    # Inyectar sólo el anchor del chart que estamos extrayendo.
        return charts

    def _build_single_chart_xlsx(self, excel_bytes: bytes, chart_info: Dict, out_path: Path) -> None:
        # Construye un XLSX temporal que contiene sólo 1 gráfico visible.
        # Así forzamos una salida 1:1 entre gráfico detectado y PNG exportado.
        sheet_name = chart_info["sheet"]
        drawing_path = chart_info["drawing_path"]
        drawing_rels_path = chart_info["drawing_rels_path"]
                                    # Conservar sólo la relación r:id del chart seleccionado.
        anchor = chart_info["anchor"]
        chart_rid = chart_info["chart_rid"]
        drawing_xml = chart_info["drawing_xml"]
        drawing_rels = chart_info["drawing_rels"]

        with ZipFile(BytesIO(excel_bytes), "r") as zin, ZipFile(out_path, "w", ZIP_DEFLATED) as zout:
            wb_xml = ET.fromstring(zin.read("xl/workbook.xml"))

            for fname in zin.namelist():
                if fname == "xl/workbook.xml":
                    new_wb = copy.deepcopy(wb_xml)
                    for sheet in new_wb.findall(f".//{{{NS_M}}}sheet"):
                                        # Vaciar otros drawings para prevenir exportaciones extra.
                        if sheet.get("name") != sheet_name:
                            sheet.set("state", "hidden")
                    xml_str = (
                        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                        + ET.tostring(new_wb, encoding="unicode")
                    )
                    zout.writestr(fname, xml_str.encode("utf-8"))

                elif fname == drawing_path:
                    new_draw = ET.Element(drawing_xml.tag, drawing_xml.attrib)
                    new_draw.append(copy.deepcopy(anchor))
                    xml_str = (
                            # Umbral simple para descartar íconos/artefactos demasiado pequeños.
                        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                        + ET.tostring(new_draw, encoding="unicode")
                    )
                    zout.writestr(fname, xml_str.encode("utf-8"))

                elif fname == drawing_rels_path:
                    new_rels = ET.Element(f"{{{NS_REL}}}Relationships")
                    for rel in drawing_rels.findall(f"{{{NS_REL}}}Relationship"):
                        if rel.get("Id") == chart_rid:
                            new_rels.append(copy.deepcopy(rel))
                    xml_str = (
                        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                                # Estandarizamos nombres para evitar caracteres problemáticos en FS/URLs.
                        + ET.tostring(new_rels, encoding="unicode")
                    )
                    zout.writestr(fname, xml_str.encode("utf-8"))

                elif (
                    fname.startswith("xl/drawings/")
                    and fname.endswith(".xml")
                    and "/_rels/" not in fname
                    and fname != drawing_path
                ):
                    try:
                        other = ET.fromstring(zin.read(fname))
                        empty = ET.Element(other.tag, other.attrib)
                        xml_str = (
                            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                            + ET.tostring(empty, encoding="unicode")
                        )
                        zout.writestr(fname, xml_str.encode("utf-8"))
                    except Exception:
                        zout.writestr(fname, zin.read(fname))

                else:
                    zout.writestr(fname, zin.read(fname))

    def _extract_single_chart(self, excel_bytes: bytes, chart_info: Dict, temp_dir: Path) -> Optional[bytes]:
        # Convierte el XLSX temporal a HTML con LibreOffice y toma el PNG más grande,
        # que suele corresponder al gráfico renderizado.
        import platform
        work_dir = temp_dir / uuid.uuid4().hex[:8]
        work_dir.mkdir(parents=True, exist_ok=True)

        single_xlsx = work_dir / "chart.xlsx"
        self._build_single_chart_xlsx(excel_bytes, chart_info, single_xlsx)

        # Verifica existencia y tamaño del archivo generado
        if not single_xlsx.exists():
            return None
        file_size = single_xlsx.stat().st_size
        if file_size == 0:
            return None

        # Detecta el ejecutable correcto según el sistema operativo
        libreoffice_cmd = "libreoffice"
        if platform.system() == "Windows":
            libreoffice_cmd = "soffice"

        # Usar rutas absolutas y formato POSIX para evitar problemas en Windows
        single_xlsx_posix = single_xlsx.resolve().as_posix()
        work_dir_posix = work_dir.resolve().as_posix()
        try:
            proc = subprocess.run(
                [
                    libreoffice_cmd,
                    "--headless",
                    "--convert-to",
                    "html",
                    single_xlsx_posix,
                    "--outdir",
                    work_dir_posix,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if proc.returncode != 0:
                logger.warning("LibreOffice exit %s: %s", proc.returncode, (proc.stderr or "")[:200])
                return None
        except subprocess.TimeoutExpired:
            logger.error("LibreOffice timeout (60s)")
            return None
        except FileNotFoundError:
            logger.error("LibreOffice not found in PATH")
            return None

        pngs = sorted(work_dir.glob("*.png"), key=lambda p: -p.stat().st_size)
        if not pngs or pngs[0].stat().st_size < 1500:
            return None

        return self._convert_png_to_jpg(pngs[0].read_bytes())

    def extract_charts_from_bytes(self, excel_bytes: bytes, sheet_names: List[str] = None) -> Dict:
        # Orquestador principal: descubre gráficos, los aísla uno por uno,
        # convierte a JPG y guarda metadatos listos para persistencia en BD.
        session_id = str(uuid.uuid4())
        temp_session = self.temp_path / session_id
        temp_session.mkdir(parents=True, exist_ok=True)

        try:
            charts_meta = self._read_charts(excel_bytes)
            if not charts_meta:
                return {
                    "success": False,
                    "total_charts": 0,
                    "charts": [],
                    "errors": ["No charts found in target sheets"],
                }

            charts: List[Dict] = []
            errors: List[str] = []

            for idx, meta in enumerate(charts_meta):
                name = meta["name"]
                template_type = meta["template_type"]
                sheet = meta["sheet"]

                logger.info(
                    "[Session %s] [%s/%s] Extracting '%s' (%s)",
                    session_id,
                    idx + 1,
                    len(charts_meta),
                    name,
                    sheet,
                )

                jpg_bytes = self._extract_single_chart(excel_bytes, meta, temp_session)
                if not jpg_bytes:
                    msg = f"No image generated for '{name}'"
                    logger.warning("[Session %s] %s", session_id, msg)
                    errors.append(msg)
                    continue

                clean_name = normalize_code(name).replace("$", "")
                jpg_filename = f"{clean_name}.jpg"
                # Subir a S3 en la carpeta 'graphs'
                s3_key = f"graphs/{jpg_filename}"

                jpg_buffer = BytesIO(jpg_bytes)
                file_size = jpg_buffer.getbuffer().nbytes  # Calcular antes de subir
                # Simular un objeto tipo UploadFile para el método upload_file
                class SimpleUploadFile:
                    def __init__(self, filename, file_bytes):
                        self.filename = filename
                        self.file = file_bytes
                        self.content_type = "image/jpeg"
                upload_file = SimpleUploadFile(jpg_filename, jpg_buffer)
                try:
                    s3_result = s3_service.upload_file(upload_file, folder="graphs")
                    file_url = s3_result["file_url"]
                    object_key = s3_result["object_key"]
                except Exception as exc:
                    file_url = None
                    object_key = None
                    errors.append(f"S3 upload failed for '{jpg_filename}': {exc}")

                charts.append(
                    {
                        "index": idx,
                        "code": f"$${clean_name}$$",
                        "filename": jpg_filename,
                        "original_name": name,
                        "template_type": template_type,
                        "sheet": sheet,
                        "path": object_key,
                        "url": file_url,
                        "size": file_size,
                        "created_at": datetime.utcnow().isoformat(),
                        "error": None if file_url else f"S3 upload failed for '{jpg_filename}'",
                    }
                )

            valora = [c for c in charts if c["template_type"] == "valora"]
            kapital = [c for c in charts if c["template_type"] == "kapital"]

            return {
                "success": len(errors) == 0,
                "total_charts": len(charts),
                "valora_count": len(valora),
                "kapital_count": len(kapital),
                "charts": charts,
                "errors": errors,
            }

        except Exception as exc:
            logger.error("[Session %s] Unexpected: %s", session_id, exc, exc_info=True)
            return {
                "success": False,
                "total_charts": 0,
                "charts": [],
                "errors": [str(exc)],
            }
        finally:
            try:
                if temp_session.exists():
                    shutil.rmtree(temp_session)
            except Exception as exc:
                logger.warning("Cleanup error: %s", exc)

    @staticmethod
    def _convert_png_to_jpg(png_bytes: bytes, quality: int = 95) -> Optional[bytes]:
        try:
            img = Image.open(BytesIO(png_bytes))
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[-1])
                else:
                    bg.paste(img)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            buf.seek(0)
            return buf.getvalue()
        except Exception as exc:
            logger.error("PNG→JPG error: %s", exc)
            return None

    def get_storage_path(self) -> Path:
        return self.storage_path

    def clear_old_charts(self, max_charts: int = 50):
        try:
            files = sorted(self.storage_path.glob("CHART*.jpg"), key=lambda p: p.stat().st_mtime)
            for file_path in files[: max(0, len(files) - max_charts)]:
                file_path.unlink()
        except Exception as exc:
            logger.warning("Error clearing old charts: %s", exc)


_instance: Optional[LibreOfficeChartExtractorService] = None


def get_libreoffice_chart_extractor(
    storage_path: Optional[str] = None,
    temp_path: Optional[str] = None,
) -> LibreOfficeChartExtractorService:
    global _instance
    if _instance is None:
        _instance = LibreOfficeChartExtractorService(storage_path, temp_path)
    return _instance
