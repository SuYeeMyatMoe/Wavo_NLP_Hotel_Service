from pathlib import Path
from fpdf import FPDF


def ticket_pdf(t):
    pdf = FPDF()
    pdf.set_auto_page_break(True, 16)
    pdf.add_page()

    def line(text, size=11, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", size)
        safe = str(text).encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 7, safe, new_x="LMARGIN", new_y="NEXT")

    pdf.image(
        str(Path(__file__).resolve().parents[1] / "static/wavo-w.png"),
        x=10,
        y=9,
        w=11,
    )
    pdf.set_x(24)
    line("Wavo | Request report", 18, True)
    line(t["id"], 14, True)
    for k in (
        "created",
        "source",
        "room",
        "urgency",
        "department",
        "operator",
        "status",
    ):
        line(k.capitalize() + ": " + str(t[k]))
    line("Guest complaint", 13, True)
    a = t["analysis"]
    if a.get("language", "en") != "en":
        line("English translation: " + (a.get("english") or "Awaiting staff review."))
        line("The original guest message is attached as UTF-8 text.")
        pdf.embed_file(
            bytes=t["complaint"].encode("utf-8"), basename="guest-message.txt"
        )
    else:
        line(t["complaint"])
    line("Classification", 13, True)
    line(
        a["version"] + " | " + " / ".join(x["label"] for x in a["predictions"].values())
    )
    if a["rule"]:
        line(a["rule"])
    work = t.get("work", {})
    if work:
        line("Service work", 13, True)
        for field in ("owner", "outcome", "action", "note"):
            if work.get(field):
                line(field.title() + ": " + str(work[field]))
        if work.get("extraction"):
            line("Extracted topic: " + work["extraction"]["topic"])
            for item in work["extraction"]["constraints"]:
                line(item["constraint"] + " | " + item["evidence"])
        if work.get("solution"):
            line("Suggested procedure: " + work["solution"]["next_action"])
    line("Activity", 13, True)
    for event in t["events"]:
        line(event["created"][:19] + "   " + event["action"])
    for call in t["calls"]:
        line(call["direction"] + " call | " + call["status"], 13, True)
        line(call["transcript"] or "No transcript recorded.")
    line("Follow-up", 13, True)
    line(
        "Offer a callback with current guest consent."
        if t["status"] in {"Resolved", "Closed"}
        else "Continue tracking the open request."
    )
    return bytes(pdf.output())
