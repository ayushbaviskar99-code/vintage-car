import io
import json
import secrets
import base64
from pathlib import Path

import qrcode
import razorpay
import requests
from qrcode.image.svg import SvgImage
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).parent

with open(BASE_DIR / "config.json", "r", encoding="utf-8") as config_file:
    CONFIG = json.load(config_file)

EVENT = CONFIG["event"]
RAZORPAY_KEY_ID = CONFIG["razorpay"]["key_id"]
RAZORPAY_KEY_SECRET = CONFIG["razorpay"]["key_secret"]
APPS_SCRIPT_WEBHOOK = CONFIG["google_sheets"]["apps_script_webhook"].strip()
GOOGLE_SHEET_VIEW_URL = CONFIG["google_sheets"].get("sheet_view_url", "").strip()

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

razorpay_client = None
if RAZORPAY_KEY_ID.strip() and RAZORPAY_KEY_SECRET.strip():
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def sheets_api(action: str, payload: dict):
    if not APPS_SCRIPT_WEBHOOK:
        raise ValueError("Google Sheets webhook is missing in config.json")

    body = {"action": action, **payload}
    response = requests.post(APPS_SCRIPT_WEBHOOK, json=body, timeout=20)
    response.raise_for_status()
    return response.json()


try:
    sheets_api(
        "init",
        {
            "default_employee_id": CONFIG["employee"]["default_id"],
            "default_employee_password": CONFIG["employee"]["default_password"],
        },
    )
except Exception:
    # Keep app booting even if the webhook is not yet configured.
    pass


def generate_qr_svg(qr_token: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(qr_token)
    qr.make(fit=True)

    img = qr.make_image(image_factory=SvgImage)
    output = io.BytesIO()
    img.save(output)
    return output.getvalue().decode("utf-8")


def generate_qr_svg_base64(qr_token: str) -> str:
    svg = generate_qr_svg(qr_token)
    return base64.b64encode(svg.encode("utf-8")).decode("utf-8")


def build_attendee_payload(booking_id: int):
    result = sheets_api("get_attendees_by_booking", {"booking_id": booking_id})
    attendees = result.get("attendees", [])
    payload = []
    for attendee in attendees:
        qr_token = str(attendee.get("qr_token", ""))
        payload.append(
            {
                "full_name": attendee.get("full_name", ""),
                "mobile": attendee.get("mobile", ""),
                "age": attendee.get("age", ""),
                "qr_token": qr_token,
                "qr_svg_base64": generate_qr_svg_base64(qr_token),
            }
        )
    return payload


@app.route("/")
def index():
    return render_template("index.html", event=EVENT, razorpay_key_id=RAZORPAY_KEY_ID)


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json(force=True)

    people_count = int(data.get("peopleCount", 0))
    attendees = data.get("attendees", [])
    buyer = data.get("buyer", {})

    if people_count < 1:
        return jsonify({"ok": False, "message": "At least 1 ticket is required."}), 400

    if len(attendees) != people_count:
        return jsonify({"ok": False, "message": "Attendee details count must match number of people."}), 400

    for attendee in attendees:
        if not attendee.get("fullName") or not attendee.get("mobile") or not attendee.get("age"):
            return jsonify({"ok": False, "message": "All attendee fields are mandatory."}), 400

    if not buyer.get("fullName") or not buyer.get("mobile") or not buyer.get("whatsapp") or not buyer.get("age"):
        return jsonify({"ok": False, "message": "Buyer details are mandatory."}), 400

    amount_total = EVENT["ticket_price"] * people_count
    if razorpay_client is None:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Payment gateway is not configured. Add valid Razorpay keys in config.json.",
                }
            ),
            503,
        )

    try:
        preview_booking_id = secrets.randbelow(900000) + 100000

        razorpay_order_id = ""
        try:
            order = razorpay_client.order.create(
                {
                    "amount": amount_total * 100,
                    "currency": "INR",
                    "receipt": f"booking_{preview_booking_id}",
                    "payment_capture": 1,
                },
                timeout=12,
            )
            razorpay_order_id = order["id"]
        except razorpay.errors.BadRequestError:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": "Razorpay authentication failed. Check key_id and key_secret in config.json.",
                    }
                ),
                400,
            )
        except Exception:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": "Unable to connect to Razorpay right now. Check internet or try again in a moment.",
                    }
                ),
                503,
            )

        attendees_payload = []
        for attendee in attendees:
            attendees_payload.append(
                {
                    "full_name": attendee["fullName"],
                    "mobile": attendee["mobile"],
                    "age": int(attendee["age"]),
                    "qr_token": f"VCS-{secrets.token_hex(8)}",
                }
            )

        create_result = sheets_api(
            "create_order",
            {
                "buyer_name": buyer["fullName"],
                "buyer_mobile": buyer["mobile"],
                "buyer_whatsapp": buyer["whatsapp"],
                "buyer_age": int(buyer["age"]),
                "people_count": people_count,
                "amount_total": amount_total,
                "razorpay_order_id": razorpay_order_id,
                "attendees": attendees_payload,
            }
        )
        booking_id = int(create_result.get("booking_id", 0) or 0)
        if booking_id < 1:
            return jsonify({"ok": False, "message": "Could not create order in Google Sheets."}), 500
    except Exception:
        return jsonify({"ok": False, "message": "Could not create order. Please try again."}), 500

    return jsonify(
        {
            "ok": True,
            "bookingId": booking_id,
            "amount": amount_total,
            "razorpayOrderId": razorpay_order_id,
            "razorpayKeyId": RAZORPAY_KEY_ID,
        }
    )


@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    data = request.get_json(force=True)
    booking_id = int(data.get("bookingId"))
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")

    try:
        booking_result = sheets_api("get_booking", {"booking_id": booking_id})
    except Exception:
        return jsonify({"ok": False, "message": "Google Sheets connection failed."}), 503

    booking = booking_result.get("booking")
    if not booking:
        return jsonify({"ok": False, "message": "Booking not found."}), 404

    if razorpay_client is None:
        return jsonify({"ok": False, "message": "Payment gateway not configured."}), 503

    is_verified = False
    try:
        razorpay_client.utility.verify_payment_signature(
            {
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
            }
        )
        is_verified = True
    except razorpay.errors.SignatureVerificationError:
        is_verified = False

    if not is_verified:
        return jsonify({"ok": False, "message": "Payment verification failed."}), 400

    try:
        sheets_api(
            "verify_payment",
            {
                "booking_id": booking_id,
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
            },
        )
    except Exception:
        return jsonify({"ok": False, "message": "Unable to update Google Sheets payment status."}), 503

    return jsonify({"ok": True, "redirectUrl": url_for("success", booking_id=booking_id)})


@app.route("/success/<int:booking_id>")
def success(booking_id: int):
    try:
        booking_result = sheets_api("get_booking", {"booking_id": booking_id})
    except Exception:
        return redirect(url_for("index"))
    booking = booking_result.get("booking")

    if not booking or booking.get("payment_status") != "paid":
        return redirect(url_for("index"))

    attendees = build_attendee_payload(booking_id)
    return render_template("success.html", booking=booking, attendees=attendees, event=EVENT)


@app.route("/employee-login", methods=["GET", "POST"])
def employee_login():
    if request.method == "GET":
        return render_template("employee-login.html", error=None)

    employee_id = request.form.get("employee_id", "").strip()
    password = request.form.get("password", "").strip()

    try:
        login_result = sheets_api("employee_login", {"employee_id": employee_id, "password": password})
    except Exception:
        return render_template("employee-login.html", error="Google Sheets connection failed.")

    if not login_result.get("ok"):
        return render_template("employee-login.html", error="Invalid employee ID or password.")

    session["employee_id"] = employee_id
    return redirect(url_for("scanner"))


@app.route("/scanner")
def scanner():
    if "employee_id" not in session:
        return redirect(url_for("employee_login"))
    return render_template(
        "scanner.html",
        employee_id=session["employee_id"],
        event=EVENT,
        sheet_view_url=GOOGLE_SHEET_VIEW_URL,
    )


@app.route("/scan-ticket", methods=["POST"])
def scan_ticket():
    if "employee_id" not in session:
        return jsonify({"ok": False, "message": "Unauthorized access."}), 401

    qr_token = request.get_json(force=True).get("qrToken", "").strip()
    if not qr_token:
        return jsonify({"ok": False, "message": "QR token is required."}), 400

    try:
        scan_result = sheets_api(
            "scan_ticket",
            {"qr_token": qr_token, "scanned_by": session["employee_id"]},
        )
    except Exception:
        return jsonify({"ok": False, "message": "Google Sheets connection failed."}), 503

    if not scan_result.get("ok"):
        message = scan_result.get("message", "Invalid ticket QR code.")
        if "already" in message.lower():
            return jsonify({"ok": False, "message": message}), 409
        if "payment" in message.lower():
            return jsonify({"ok": False, "message": message}), 400
        return jsonify({"ok": False, "message": message}), 404

    return jsonify(
        {
            "ok": True,
            "message": f"Entry allowed for {scan_result.get('full_name', 'Guest')}. Ticket marked as used and cannot be scanned again.",
        }
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("employee_login"))


@app.route("/admin-report")
def admin_report():
    try:
        report_result = sheets_api("admin_report", {})
    except Exception:
        return render_template(
            "admin-report.html",
            rows=[],
            total_paid=0,
            total_entries=0,
            pending_entries=0,
        )
    rows = report_result.get("rows", [])
    rows.sort(key=lambda row: (-int(row.get("booking_id", 0) or 0), str(row.get("qr_token", ""))))
    total_paid = sum(1 for row in rows if row["payment_status"] == "paid")
    total_entries = sum(1 for row in rows if int(row.get("is_used", 0) or 0) == 1)
    pending_entries = sum(
        1 for row in rows if row["payment_status"] == "paid" and int(row.get("is_used", 0) or 0) == 0
    )

    return render_template(
        "admin-report.html",
        rows=rows,
        total_paid=total_paid,
        total_entries=total_entries,
        pending_entries=pending_entries,
    )


@app.route("/terms-and-conditions")
def terms_and_conditions():
    return render_template("terms-and-conditions.html", event=EVENT)


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy-policy.html", event=EVENT)


@app.route("/refund-policy")
def refund_policy():
    return render_template("refund-policy.html", event=EVENT)


@app.route("/contact-us")
def contact_us():
    return render_template("contact-us.html", event=EVENT)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
