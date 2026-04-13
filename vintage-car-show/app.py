import io
import json
import secrets
import base64
from pathlib import Path

import qrcode
import razorpay
from qrcode.image.svg import SvgImage
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from database import get_connection, init_db

BASE_DIR = Path(__file__).parent

with open(BASE_DIR / "config.json", "r", encoding="utf-8") as config_file:
    CONFIG = json.load(config_file)

EVENT = CONFIG["event"]
RAZORPAY_KEY_ID = CONFIG["razorpay"]["key_id"]
RAZORPAY_KEY_SECRET = CONFIG["razorpay"]["key_secret"]

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

init_db(CONFIG["employee"]["default_id"], CONFIG["employee"]["default_password"])

razorpay_client = None
if (
    RAZORPAY_KEY_ID != "YOUR_RAZORPAY_KEY_ID"
    and RAZORPAY_KEY_SECRET != "YOUR_RAZORPAY_KEY_SECRET"
):
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


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
    conn = get_connection()
    attendees = conn.execute(
        """
        SELECT id, full_name, mobile, age, qr_token
        FROM attendees
        WHERE booking_id = ?
        ORDER BY id ASC
        """,
        (booking_id,),
    ).fetchall()
    conn.close()

    payload = []
    for attendee in attendees:
        payload.append(
            {
                "full_name": attendee["full_name"],
                "mobile": attendee["mobile"],
                "age": attendee["age"],
                "qr_token": attendee["qr_token"],
                "qr_svg_base64": generate_qr_svg_base64(attendee["qr_token"]),
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

    conn = None
    booking_id = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO bookings (
                buyer_name, buyer_mobile, buyer_whatsapp, buyer_age,
                people_count, amount_total, payment_status
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                buyer["fullName"],
                buyer["mobile"],
                buyer["whatsapp"],
                int(buyer["age"]),
                people_count,
                amount_total,
            ),
        )
        booking_id = cursor.lastrowid

        for attendee in attendees:
            qr_token = f"VCS-{booking_id}-{secrets.token_hex(8)}"
            cursor.execute(
                """
                INSERT INTO attendees (booking_id, full_name, mobile, age, qr_token)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    booking_id,
                    attendee["fullName"],
                    attendee["mobile"],
                    int(attendee["age"]),
                    qr_token,
                ),
            )

        razorpay_order_id = ""
        try:
            order = razorpay_client.order.create(
                {
                    "amount": amount_total * 100,
                    "currency": "INR",
                    "receipt": f"booking_{booking_id}",
                    "payment_capture": 1,
                }
            )
            razorpay_order_id = order["id"]
        except razorpay.errors.BadRequestError:
            conn.rollback()
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": "Razorpay authentication failed. Check key_id and key_secret in config.json.",
                    }
                ),
                400,
            )

        cursor.execute(
            "UPDATE bookings SET razorpay_order_id = ? WHERE id = ?",
            (razorpay_order_id, booking_id),
        )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        return jsonify({"ok": False, "message": "Could not create order. Please try again."}), 500
    finally:
        if conn:
            conn.close()

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

    conn = get_connection()
    booking = conn.execute(
        "SELECT * FROM bookings WHERE id = ?",
        (booking_id,),
    ).fetchone()

    if not booking:
        conn.close()
        return jsonify({"ok": False, "message": "Booking not found."}), 404

    if razorpay_client is None:
        conn.close()
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
        conn.close()
        return jsonify({"ok": False, "message": "Payment verification failed."}), 400

    conn.execute(
        """
        UPDATE bookings
        SET payment_status = 'paid',
            razorpay_order_id = ?,
            razorpay_payment_id = ?
        WHERE id = ?
        """,
        (razorpay_order_id, razorpay_payment_id, booking_id),
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "redirectUrl": url_for("success", booking_id=booking_id)})


@app.route("/success/<int:booking_id>")
def success(booking_id: int):
    conn = get_connection()
    booking = conn.execute(
        "SELECT * FROM bookings WHERE id = ?",
        (booking_id,),
    ).fetchone()
    conn.close()

    if not booking or booking["payment_status"] != "paid":
        return redirect(url_for("index"))

    attendees = build_attendee_payload(booking_id)
    return render_template("success.html", booking=booking, attendees=attendees, event=EVENT)


@app.route("/employee-login", methods=["GET", "POST"])
def employee_login():
    if request.method == "GET":
        return render_template("employee-login.html", error=None)

    employee_id = request.form.get("employee_id", "").strip()
    password = request.form.get("password", "").strip()

    conn = get_connection()
    employee = conn.execute(
        "SELECT employee_id FROM employees WHERE employee_id = ? AND password = ?",
        (employee_id, password),
    ).fetchone()
    conn.close()

    if not employee:
        return render_template("employee-login.html", error="Invalid employee ID or password.")

    session["employee_id"] = employee_id
    return redirect(url_for("scanner"))


@app.route("/scanner")
def scanner():
    if "employee_id" not in session:
        return redirect(url_for("employee_login"))
    return render_template("scanner.html", employee_id=session["employee_id"], event=EVENT)


@app.route("/scan-ticket", methods=["POST"])
def scan_ticket():
    if "employee_id" not in session:
        return jsonify({"ok": False, "message": "Unauthorized access."}), 401

    qr_token = request.get_json(force=True).get("qrToken", "").strip()
    if not qr_token:
        return jsonify({"ok": False, "message": "QR token is required."}), 400

    conn = get_connection()
    attendee = conn.execute(
        """
        SELECT a.id, a.full_name, a.is_used, b.payment_status
        FROM attendees a
        JOIN bookings b ON b.id = a.booking_id
        WHERE a.qr_token = ?
        """,
        (qr_token,),
    ).fetchone()

    if not attendee:
        conn.close()
        return jsonify({"ok": False, "message": "Invalid ticket QR code."}), 404

    if attendee["payment_status"] != "paid":
        conn.close()
        return jsonify({"ok": False, "message": "Payment not confirmed for this ticket."}), 400

    if attendee["is_used"] == 1:
        conn.close()
        return jsonify({"ok": False, "message": "This QR code has already been used."}), 409

    conn.execute(
        """
        UPDATE attendees
        SET is_used = 1,
            scanned_by = ?,
            scanned_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (session["employee_id"], attendee["id"]),
    )
    conn.commit()
    conn.close()

    return jsonify(
        {
            "ok": True,
            "message": f"Entry allowed for {attendee['full_name']}. Ticket marked as used and cannot be scanned again.",
        }
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("employee_login"))


@app.route("/admin-report")
def admin_report():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            b.id AS booking_id,
            b.buyer_name,
            b.buyer_mobile,
            b.people_count,
            b.amount_total,
            b.payment_status,
            b.razorpay_payment_id,
            b.created_at,
            a.full_name AS attendee_name,
            a.mobile AS attendee_mobile,
            a.age AS attendee_age,
            a.qr_token,
            a.is_used,
            a.scanned_by,
            a.scanned_at
        FROM bookings b
        JOIN attendees a ON a.booking_id = b.id
        ORDER BY b.id DESC, a.id ASC
        """
    ).fetchall()
    conn.close()

    total_paid = sum(1 for row in rows if row["payment_status"] == "paid")
    total_entries = sum(1 for row in rows if row["is_used"] == 1)
    pending_entries = sum(1 for row in rows if row["payment_status"] == "paid" and row["is_used"] == 0)

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
