# Vintage Car Show Booking Platform

Professional event booking and entry-validation platform for **Vintage Antique Display**.

## Features

- Visitor booking form with buyer and per-attendee details
- Dynamic pricing: INR 299 x number of people
- Razorpay payment flow (demo fallback when keys are not configured)
- Google Sheets storage through Apps Script Web App webhook
- Unique QR ticket generated per attendee
- One-time QR usage enforcement at gate
- Employee login required for scanning dashboard
- Mobile-responsive design for Android and iPhone

## Run Locally

1. Install Python dependencies:
   - `pip install -r requirements.txt`
2. Add Razorpay keys in `config.json`:
   - `razorpay.key_id`
   - `razorpay.key_secret`
3. Create a Google Sheet with tabs: `bookings`, `attendees`, `employees`
4. Open **Extensions -> Apps Script**, deploy as **Web app**, and copy URL
5. Configure `config.json`:
   - `google_sheets.apps_script_webhook`
6. Start server:
   - `python app.py`
7. Open:
   - `http://127.0.0.1:5000`

## Employee Gate Access

- Login page: `http://127.0.0.1:5000/employee-login`
- Default credentials are in `config.json` under `employee`
- Change default password before production

## Project Structure

- `app.py` Flask backend
- `templates/` HTML pages
- `static/css/style.css` Styling
- `static/js/main.js` Booking and payment frontend logic
- `static/js/scanner.js` Scanner dashboard logic
- `config.json` Event and payment configuration
- `java/`, `cpp/`, `c/` Additional language modules
