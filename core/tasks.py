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

import cv2
import numpy as np

db.init_db()


def register_person_job(
    raw_path: str,
    original_card_filename: Optional[str],
    placeholder_nid: Optional[str] = None,
    gate_number: Optional[int] = None,
) -> None:
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
        placeholder_gate = placeholder.get("gate_number") if placeholder else None
        effective_gate = placeholder_gate if placeholder_gate is not None else gate_number
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
                db.update_gate_number_if_missing(national_id, effective_gate)
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
                    db.update_gate_number_if_missing(national_id, effective_gate)
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
                db.update_gate_number_if_missing(national_id, effective_gate)
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
                gate_number=effective_gate,
            )
            if embedding_blob:
                face_match.mark_index_dirty()
            return

        if placeholder and placeholder_nid:
            if full_name:
                db.update_name_if_missing(placeholder_nid, full_name)
            db.update_gate_number_if_missing(placeholder_nid, effective_gate)
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
            gate_number=effective_gate,
        )
        if embedding_blob:
            face_match.mark_index_dirty()
    finally:
        try:
            raw_file.unlink()
        except Exception:
            pass


def reprocess_person_job(national_id: str, direction: str) -> None:
    if not national_id:
        return
    person = db.get_person_by_nid(national_id)
    if not person:
        print(f"[REPROCESS] Person not found: {national_id}")
        return
    card_path = person.get("card_path")
    if not card_path:
        print(f"[REPROCESS] No card image for: {national_id}")
        return
    card_file = media.CARD_DIR / card_path
    if not card_file.exists():
        print(f"[REPROCESS] Card image missing: {card_file}")
        return

    try:
        image_bytes = card_file.read_bytes()
    except Exception as exc:
        print(f"[REPROCESS] Failed to read card image: {exc}")
        return

    data = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        print(f"[REPROCESS] Failed to decode card image: {card_file}")
        return

    if direction == "cw":
        rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif direction == "ccw":
        rotated = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        print(f"[REPROCESS] Invalid direction: {direction}")
        return

    ok, buffer = cv2.imencode(".jpg", rotated, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        print("[REPROCESS] Failed to encode rotated image.")
        return
    rotated_bytes = buffer.tobytes()

    scan = run_security_scan(rotated_bytes, skip_face_match=True)
    if scan.error:
        print(f"[REPROCESS] OCR failed: {scan.error}")

    full_name = (scan.ocr.full_name or "").strip() if scan.ocr else ""
    ocr_nid = (scan.ocr.national_id or "").strip() if scan.ocr else ""
    valid_nid = ocr_nid.isdigit() and len(ocr_nid) == 14

    update_nid = False
    if valid_nid and ocr_nid != national_id:
        existing = db.get_person_by_nid(ocr_nid)
        if existing and existing.get("national_id") != national_id:
            print(f"[REPROCESS] NID conflict for {national_id}: {ocr_nid}")
            update_nid = False
        else:
            update_nid = True

    target_nid = national_id
    if update_nid:
        try:
            db.update_person(
                national_id,
                full_name=full_name or None,
                new_national_id=ocr_nid,
            )
            target_nid = ocr_nid
        except ValueError:
            print(f"[REPROCESS] NID update failed for {national_id}: {ocr_nid}")
            update_nid = False
            target_nid = national_id
            if full_name:
                db.update_person(national_id, full_name=full_name)
    elif full_name:
        db.update_person(national_id, full_name=full_name)

    new_card_filename = media.save_card_image(rotated, target_nid)
    new_photo_filename = None
    embedding_blob = None
    if scan.photo_image is not None:
        new_photo_filename = media.save_person_photo(scan.photo_image, target_nid)
        embedding = face_match.extract_face_embedding(scan.photo_image)
        embedding_blob = media.serialize_embedding(embedding)

    db.update_media(
        target_nid,
        photo_path=new_photo_filename,
        card_path=new_card_filename,
        face_embedding=embedding_blob,
    )
    db.update_gate_number_if_missing(target_nid, 1)

    if embedding_blob:
        face_match.mark_index_dirty()
