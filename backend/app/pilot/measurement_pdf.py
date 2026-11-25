"""Plain-text PDF for a stored measurement report.

This does not recalculate the angle. Older reports without coordinate
evidence still render.
"""

from __future__ import annotations


def render_measurement_pdf(report: dict[str, object]) -> bytes:
    """Return a one-page PDF. Missing evidence is stated, not invented."""
    lines = _lines(report)
    return _pdf_page(lines)


def _lines(report: dict[str, object]) -> list[str]:
    lines = [
        "2D front-knee measurement evidence",
        "Image-plane angle. Not a 3D joint angle and not an injury estimate.",
        f"Bowler {report.get('bowler_id', '')}  Delivery {report.get('delivery_id', '')}",
        f"Front leg {report.get('front_leg', '')}",
        f"Video SHA-256 {_hash(report.get('video_sha256'))}",
    ]
    for phase, key in (("FFC", "ffc"), ("Release", "release")):
        lines.append("")
        lines.extend(_phase_lines(phase, report.get(key)))
    return lines[:48]


def _phase_lines(phase: str, value: object) -> list[str]:
    if not isinstance(value, dict):
        return [f"{phase}: not stored"]
    status = value.get("status", "")
    angle = value.get("angle_degrees")
    lines = [f"{phase} frame {value.get('frame_index')}  status {status}  angle {angle}"]
    evidence = value.get("calculation_evidence")
    if not isinstance(evidence, dict):
        lines.append(f"{phase} coordinate evidence: not stored")
        if value.get("reason"):
            lines.append(f"Reason: {value.get('reason')}")
        return lines
    lines.append(
        f"Frame {evidence.get('image_width_px')} x {evidence.get('image_height_px')} px"
        f"  schema {evidence.get('schema_version')}  calculation {evidence.get('calculation')}"
    )
    lines.append(str(evidence.get("definition", "")))
    full_hash = evidence.get("video_sha256") or ""
    lines.append(f"Full video SHA-256 {full_hash}")
    for role in ("hip", "knee", "ankle"):
        point = evidence.get(role)
        if not isinstance(point, dict):
            lines.append(f"{role}: not stored")
            continue
        lines.append(
            f"{point.get('name')} px ({point.get('x_px')}, {point.get('y_px')})"
            f"  visibility {point.get('visibility')}  presence {point.get('presence')}"
        )
    return lines


def _hash(value: object) -> str:
    text = str(value or "")
    if len(text) <= 16:
        return text or "not stored"
    return f"{text[:12]}...{text[-8:]}"


def _pdf_page(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 9 Tf", "48 780 Td", "12 TL"]
    for index, line in enumerate(lines):
        if index:
            commands.append("T*")
        commands.append(f"({_escape(line)}) Tj")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
