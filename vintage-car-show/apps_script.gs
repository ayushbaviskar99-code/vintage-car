function doGet(e) {
  return ContentService.createTextOutput("Vintage Car Show API is running");
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents || "{}");
    const action = body.action;

    if (!action) return json({ ok: false, message: "Missing action" });
    if (action === "init") return initSheets(body);
    if (action === "create_order") return createOrder(body);
    if (action === "verify_payment") return verifyPayment(body);
    if (action === "employee_login") return employeeLogin(body);
    if (action === "scan_ticket") return scanTicket(body);
    if (action === "get_booking") return getBooking(body);
    if (action === "get_attendees_by_booking") return getAttendeesByBooking(body);
    if (action === "admin_report") return adminReport();
    return json({ ok: false, message: "Unknown action" });
  } catch (err) {
    return json({ ok: false, message: String(err) });
  }
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function getSheet(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  return sh;
}

function ensureHeaders(sheet, headers) {
  const firstRow = sheet.getRange(1, 1, 1, headers.length).getValues()[0];
  const isEmpty = firstRow.every(v => v === "");
  if (isEmpty || firstRow.join("|") !== headers.join("|")) {
    sheet.clear();
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  }
}

function allRowsAsObjects(sheet) {
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) return [];
  const headers = data[0];
  return data.slice(1).map(r => {
    const obj = {};
    headers.forEach((h, i) => (obj[h] = r[i]));
    return obj;
  });
}

function nextId(sheet, idColName) {
  const rows = allRowsAsObjects(sheet);
  let maxId = 0;
  rows.forEach(r => {
    const id = Number(r[idColName] || 0);
    if (id > maxId) maxId = id;
  });
  return maxId + 1;
}

function initSheets(body) {
  const bookings = getSheet("bookings");
  const attendees = getSheet("attendees");
  const employees = getSheet("employees");

  ensureHeaders(bookings, [
    "id", "buyer_name", "buyer_mobile", "buyer_whatsapp", "buyer_age",
    "people_count", "amount_total", "payment_status", "razorpay_order_id",
    "razorpay_payment_id", "created_at"
  ]);
  ensureHeaders(attendees, [
    "id", "booking_id", "full_name", "mobile", "age", "qr_token",
    "is_used", "scanned_by", "scanned_at"
  ]);
  ensureHeaders(employees, ["employee_id", "password"]);

  const defaultId = body.default_employee_id || "EMP001";
  const defaultPass = body.default_employee_password || "change-me-now";
  const empRows = allRowsAsObjects(employees);
  const exists = empRows.some(r => String(r.employee_id) === String(defaultId));
  if (!exists) employees.appendRow([defaultId, defaultPass]);
  return json({ ok: true });
}

function createOrder(body) {
  const bookings = getSheet("bookings");
  const attendees = getSheet("attendees");
  const bookingId = nextId(bookings, "id");
  const now = new Date().toISOString();

  bookings.appendRow([
    bookingId, body.buyer_name || "", body.buyer_mobile || "", body.buyer_whatsapp || "",
    Number(body.buyer_age || 0), Number(body.people_count || 0), Number(body.amount_total || 0),
    "pending", body.razorpay_order_id || "", "", now
  ]);

  let attendeeId = nextId(attendees, "id");
  (body.attendees || []).forEach(a => {
    attendees.appendRow([
      attendeeId++, bookingId, a.full_name || "", a.mobile || "", Number(a.age || 0),
      a.qr_token || "", 0, "", ""
    ]);
  });
  return json({ ok: true, booking_id: bookingId });
}

function verifyPayment(body) {
  const sheet = getSheet("bookings");
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) return json({ ok: false, message: "No bookings" });
  const headers = data[0];
  const idx = {};
  headers.forEach((h, i) => (idx[h] = i));

  const bookingId = Number(body.booking_id);
  for (let r = 1; r < data.length; r++) {
    if (Number(data[r][idx.id]) === bookingId) {
      sheet.getRange(r + 1, idx.payment_status + 1).setValue("paid");
      sheet.getRange(r + 1, idx.razorpay_order_id + 1).setValue(body.razorpay_order_id || "");
      sheet.getRange(r + 1, idx.razorpay_payment_id + 1).setValue(body.razorpay_payment_id || "");
      return json({ ok: true });
    }
  }
  return json({ ok: false, message: "Booking not found" });
}

function employeeLogin(body) {
  const rows = allRowsAsObjects(getSheet("employees"));
  const found = rows.find(
    r =>
      String(r.employee_id).trim() === String(body.employee_id || "").trim() &&
      String(r.password) === String(body.password || "")
  );
  return json({ ok: !!found });
}

function scanTicket(body) {
  const attendees = getSheet("attendees");
  const bookings = getSheet("bookings");
  const aData = attendees.getDataRange().getValues();
  const bData = bookings.getDataRange().getValues();
  if (aData.length < 2) return json({ ok: false, message: "No attendees" });

  const aIdx = {};
  aData[0].forEach((h, i) => (aIdx[h] = i));
  const bIdx = {};
  if (bData.length >= 1) bData[0].forEach((h, i) => (bIdx[h] = i));

  const qr = String(body.qr_token || "").trim();
  for (let r = 1; r < aData.length; r++) {
    if (String(aData[r][aIdx.qr_token]).trim() !== qr) continue;
    const bookingId = Number(aData[r][aIdx.booking_id]);

    let paymentStatus = "";
    for (let br = 1; br < bData.length; br++) {
      if (Number(bData[br][bIdx.id]) === bookingId) {
        paymentStatus = String(bData[br][bIdx.payment_status] || "");
        break;
      }
    }

    if (paymentStatus !== "paid") return json({ ok: false, message: "Payment not confirmed" });
    if (Number(aData[r][aIdx.is_used]) === 1) return json({ ok: false, message: "Already used" });

    attendees.getRange(r + 1, aIdx.is_used + 1).setValue(1);
    attendees.getRange(r + 1, aIdx.scanned_by + 1).setValue(body.scanned_by || "");
    attendees.getRange(r + 1, aIdx.scanned_at + 1).setValue(new Date().toISOString());
    return json({ ok: true, full_name: String(aData[r][aIdx.full_name] || "") });
  }
  return json({ ok: false, message: "Invalid QR token" });
}

function getBooking(body) {
  const rows = allRowsAsObjects(getSheet("bookings"));
  const booking = rows.find(r => Number(r.id) === Number(body.booking_id));
  return json({ ok: !!booking, booking: booking || null });
}

function getAttendeesByBooking(body) {
  const rows = allRowsAsObjects(getSheet("attendees"));
  const list = rows.filter(r => Number(r.booking_id) === Number(body.booking_id));
  return json({ ok: true, attendees: list });
}

function adminReport() {
  const bookings = allRowsAsObjects(getSheet("bookings"));
  const attendees = allRowsAsObjects(getSheet("attendees"));
  const bookingMap = {};
  bookings.forEach(b => (bookingMap[Number(b.id)] = b));

  const rows = attendees
    .map(a => {
      const b = bookingMap[Number(a.booking_id)];
      if (!b) return null;
      return {
        booking_id: Number(b.id),
        buyer_name: b.buyer_name,
        buyer_mobile: b.buyer_mobile,
        people_count: Number(b.people_count || 0),
        amount_total: Number(b.amount_total || 0),
        payment_status: b.payment_status,
        razorpay_payment_id: b.razorpay_payment_id,
        created_at: b.created_at,
        attendee_name: a.full_name,
        attendee_mobile: a.mobile,
        attendee_age: Number(a.age || 0),
        qr_token: a.qr_token,
        is_used: Number(a.is_used || 0),
        scanned_by: a.scanned_by,
        scanned_at: a.scanned_at
      };
    })
    .filter(Boolean);

  return json({ ok: true, rows: rows });
}
