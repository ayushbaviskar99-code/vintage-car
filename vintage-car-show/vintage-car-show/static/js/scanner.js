const resultBox = document.getElementById("scanResult");
const cameraStatus = document.getElementById("cameraStatus");
const manualScanForm = document.getElementById("manualScanForm");
const manualTokenInput = document.getElementById("manualToken");
let isProcessingScan = false;
let lastScannedToken = "";
let lastScannedAt = 0;

function extractToken(rawText) {
  const text = (rawText || "").trim();
  const match = text.match(/VCS-[A-Za-z0-9-]+/);
  return match ? match[0] : text;
}

async function validateToken(qrToken) {
  try {
    const token = extractToken(qrToken);
    if (!token) {
      resultBox.textContent = "QR detected but token is invalid.";
      resultBox.className = "status error";
      return;
    }

    resultBox.textContent = "Validating ticket...";
    resultBox.className = "status";

    const res = await fetch("/scan-ticket", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ qrToken: token }),
    });

    let data = {};
    try {
      data = await res.json();
    } catch (err) {
      data = {};
    }

    if (!res.ok || !data.ok) {
      resultBox.textContent = data.message || "Ticket validation failed.";
      resultBox.className = "status error";
      return;
    }

    resultBox.textContent = data.message;
    resultBox.className = "status success";
  } catch (error) {
    resultBox.textContent = "Scan request failed. Check network and try again.";
    resultBox.className = "status error";
  }
}

manualScanForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = manualTokenInput.value.trim();
  if (!token) {
    return;
  }
  await validateToken(token);
  manualTokenInput.value = "";
});

function startCameraScanner() {
  if (typeof Html5Qrcode === "undefined") {
    cameraStatus.textContent = "Camera scanner library not loaded.";
    cameraStatus.className = "status error";
    return;
  }

  const scanner = new Html5Qrcode("reader");
  cameraStatus.textContent = "Starting camera...";
  cameraStatus.className = "status";
  scanner
    .start(
      { facingMode: "environment" },
      { fps: 10, qrbox: { width: 220, height: 220 } },
      async (decodedText) => {
        const token = extractToken(decodedText);
        const now = Date.now();

        if (isProcessingScan) {
          return;
        }
        if (token === lastScannedToken && now - lastScannedAt < 3000) {
          return;
        }

        isProcessingScan = true;
        lastScannedToken = token;
        lastScannedAt = now;
        cameraStatus.textContent = "QR detected. Validating...";
        cameraStatus.className = "status";
        await validateToken(token);
        cameraStatus.textContent = "Camera is ON. Ready for next scan.";
        cameraStatus.className = "status success";
        isProcessingScan = false;
      },
      () => {}
    )
    .catch(() => {
      cameraStatus.textContent = "Camera is OFF or blocked. Allow camera permission, or use manual token entry below.";
      cameraStatus.className = "status error";
    });
}

window.addEventListener("load", startCameraScanner);
