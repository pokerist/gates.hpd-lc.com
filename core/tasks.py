from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from core import db, face_match
from core import media
from core.ocr_pipeline import run_security_scan

db.init_db()


def register_person_job(raw_path: str, original_card_filename: Optional[str], placeholder_nid: Optional[str] = None) -> None:
    raw_file = Path(raw_path)
    try:
        image_bytes = raw_file.read_bytes()
    except Exception as exc:
        print(f"[RQ] Failed to read raw upload: {exc}")
        return
    try:
        scan = run_security_scan(image_bytes, skip_face_match=True)
        if scan.error:
            print(f"[RQ] OCR failed: {scan.error}")
        if scan.photo_image is None:
            print("[RQ] No face photo extracted, skipping registration.")
            return

        full_name = (scan.ocr.full_name or "").strip()
        national_id = (scan.ocr.national_id or "").strip()
        if len(national_id) != 14:
            national_id = ""

        placeholder = db.get_person_by_nid(placeholder_nid) if placeholder_nid else None
        placeholder_embedding = None
        if placeholder_nid:
            placeholder_embedding = db.get_face_embedding(placeholder_nid)

        if placeholder and placeholder.get("photo_path"):
            photo_filename = placeholder.get("photo_path")
        else:
            photo_filename = media.save_person_photo(
                scan.photo_image,
                national_id or (placeholder_nid or "temp"),
            )

        card_filename = original_card_filename
        if placeholder and placeholder.get("card_path"):
            card_filename = placeholder.get("card_path")
        if card_filename is None and scan.card_image is not None:
            card_filename = media.save_card_image(
                scan.card_image,
                national_id or (placeholder_nid or "temp"),
            )

        embedding_blob = placeholder_embedding or media.serialize_embedding(scan.face_embedding)

        if national_id:
            existing = db.get_person_by_nid(national_id)
            if existing and (not placeholder or existing.get("national_id") != placeholder_nid):
                db.increment_visit(national_id)
                db.update_name_if_missing(national_id, full_name)
                if photo_filename or card_filename or embedding_blob:
                    db.update_media(
                        national_id,
                        photo_path=photo_filename,
                        card_path=card_filename,
                        face_embedding=embedding_blob,
                    )
                    if embedding_blob:
                        face_match.mark_index_dirty()
                if placeholder:
                    db.delete_person(placeholder_nid)
                return

            if placeholder and placeholder_nid:
                try:
                    db.update_person(
                        placeholder_nid,
                        full_name=full_name or None,
                        new_national_id=national_id,
                    )
                except ValueError:
                    db.update_name_if_missing(national_id, full_name)
                    if photo_filename or card_filename or embedding_blob:
                        db.update_media(
                            national_id,
                            photo_path=photo_filename,
                            card_path=card_filename,
                            face_embedding=embedding_blob,
                        )
                    if embedding_blob:
                        face_match.mark_index_dirty()
                    if placeholder:
                        db.delete_person(placeholder_nid)
                    return
                if photo_filename or card_filename or embedding_blob:
                    db.update_media(
                        national_id,
                        photo_path=photo_filename,
                        card_path=card_filename,
                        face_embedding=embedding_blob,
                    )
                if embedding_blob:
                    face_match.mark_index_dirty()
                return

            db.add_person(
                national_id,
                full_name,
                photo_filename,
                card_filename,
                embedding_blob,
            )
            if embedding_blob:
                face_match.mark_index_dirty()
            return

        if placeholder and placeholder_nid:
            if full_name:
                db.update_name_if_missing(placeholder_nid, full_name)
            if photo_filename or card_filename or embedding_blob:
                db.update_media(
                    placeholder_nid,
                    photo_path=photo_filename,
                    card_path=card_filename,
                    face_embedding=embedding_blob,
                )
                if embedding_blob:
                    face_match.mark_index_dirty()
            return

        temp_nid = media.generate_temp_nid()
        db.add_person(
            temp_nid,
            full_name,
            photo_filename,
            card_filename,
            embedding_blob,
        )
        if embedding_blob:
            face_match.mark_index_dirty()
    finally:
        try:
            raw_file.unlink()
        except Exception:
            pass
