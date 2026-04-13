const bookingForm = document.getElementById("bookingForm");
const attendeesContainer = document.getElementById("attendeesContainer");
const peopleCountInput = document.getElementById("peopleCount");
const totalAmountText = document.getElementById("totalAmount");
const statusMessage = document.getElementById("statusMessage");

const ticketPrice = window.EVENT_DATA.ticket_price;

function updateTotal() {
  const count = Math.max(1, parseInt(peopleCountInput.value || "1", 10));
  totalAmountText.textContent = `Total: INR ${count * ticketPrice}`;
}

function renderAttendeeFields() {
  const count = Math.max(1, parseInt(peopleCountInput.value || "1", 10));
  attendeesContainer.innerHTML = "";

  for (let i = 1; i <= count; i += 1) {
    const block = document.createElement("div");
    block.className = "attendee-block";
    block.innerHTML = `
      <h4>Person ${i}</h4>
      <div class="grid">
        <input type="text" name="attendee_name_${i}" placeholder="Full Name" required />
        <input type="tel" name="attendee_mobile_${i}" placeholder="Mobile Number" required />
        <input type="number" name="attendee_age_${i}" placeholder="Age" min="1" required />
      </div>
    `;
    attendeesContainer.appendChild(block);
  }

  updateTotal();
}

function getBuyerDetails() {
  return {
    fullName: document.getElementById("buyerName").value.trim(),
    mobile: document.getElementById("buyerMobile").value.trim(),
    whatsapp: document.getElementById("buyerWhatsapp").value.trim(),
    age: document.getElementById("buyerAge").value.trim(),
  };
}

function getAttendees() {
  const count = Math.max(1, parseInt(peopleCountInput.value || "1", 10));
  const attendees = [];
  for (let i = 1; i <= count; i += 1) {
    attendees.push({
      fullName: document.querySelector(`[name="attendee_name_${i}"]`).value.trim(),
      mobile: document.querySelector(`[name="attendee_mobile_${i}"]`).value.trim(),
      age: document.querySelector(`[name="attendee_age_${i}"]`).value.trim(),
    });
  }
  return attendees;
}

async function submitBooking(event) {
  event.preventDefault();
  statusMessage.textContent = "Creating order...";

  const peopleCount = Math.max(1, parseInt(peopleCountInput.value || "1", 10));
  const payload = {
    buyer: getBuyerDetails(),
    peopleCount,
    attendees: getAttendees(),
  };

  try {
    const createOrderRes = await fetch("/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const orderData = await createOrderRes.json();
    if (!createOrderRes.ok || !orderData.ok) {
      throw new Error(orderData.message || "Order creation failed.");
    }

    if (typeof Razorpay === "undefined") {
      throw new Error("Razorpay checkout could not load. Check internet connection and try again.");
    }

    const options = {
      key: orderData.razorpayKeyId,
      amount: orderData.amount * 100,
      currency: "INR",
      name: window.EVENT_DATA.name,
      description: "Ticket Booking",
      order_id: orderData.razorpayOrderId,
      handler: async function (response) {
        const verifyRes = await fetch("/verify-payment", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            bookingId: orderData.bookingId,
            ...response,
          }),
        });
        const verifyData = await verifyRes.json();
        if (!verifyRes.ok || !verifyData.ok) {
          statusMessage.textContent = verifyData.message || "Verification failed.";
          return;
        }
        window.location.href = verifyData.redirectUrl;
      },
      prefill: {
        name: payload.buyer.fullName,
        contact: payload.buyer.mobile,
      },
      theme: {
        color: "#0f4c81",
      },
    };

    statusMessage.textContent = "Opening payment gateway...";
    const rzp = new Razorpay(options);
    rzp.on("payment.failed", function () {
      statusMessage.textContent = "Payment failed. Please try again.";
    });
    rzp.open();
  } catch (error) {
    statusMessage.textContent = error.message || "Something went wrong.";
  }
}

peopleCountInput.addEventListener("input", renderAttendeeFields);
bookingForm.addEventListener("submit", submitBooking);

renderAttendeeFields();
