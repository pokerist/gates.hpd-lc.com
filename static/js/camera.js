// Camera and ID verification logic

let stream = null;
let video = null;
let canvas = null;
let context = null;

document.addEventListener('DOMContentLoaded', function() {
    video = document.getElementById('video');
    canvas = document.getElementById('canvas');
    context = canvas.getContext('2d');

    // Scan button
    document.getElementById('btn-scan').addEventListener('click', startCamera);

    // Capture button
    document.getElementById('btn-capture').addEventListener('click', captureImage);

    // Cancel button
    document.getElementById('btn-cancel').addEventListener('click', stopCamera);
});

async function startCamera() {
    try {
        // Request camera access with back camera preference for mobile
        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'environment', // Use back camera on mobile
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        });

        video.srcObject = stream;

        // Show camera container, hide scan button
        document.getElementById('scan-button-container').style.display = 'none';
        document.getElementById('camera-container').style.display = 'block';

    } catch (error) {
        console.error('Error accessing camera:', error);
        showToast('❌ لا يمكن الوصول للكاميرا. تحقق من الأذونات.', 'error');
    }
}

function stopCamera() {
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }

    // Hide camera container, show scan button
    document.getElementById('camera-container').style.display = 'none';
    document.getElementById('scan-button-container').style.display = 'block';
}

async function captureImage() {
    // Set canvas size to match video
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    // Draw video frame to canvas
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Convert to base64
    const imageBase64 = canvas.toDataURL('image/jpeg', 0.9);

    // Stop camera
    stopCamera();

    // Show loading
    document.getElementById('loading-container').classList.remove('d-none');

    // Send to backend for verification
    await verifyID(imageBase64);

    // Hide loading
    document.getElementById('loading-container').classList.add('d-none');
}

async function verifyID(imageBase64) {
    try {
        const response = await fetch('/verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                image: imageBase64
            })
        });

        const result = await response.json();

        if (result.success) {
            // Show success toast
            showToast(result.message, 'success');
        } else {
            if (result.type === 'blocked') {
                // Show blocked modal
                showBlockedModal(result.person);
            } else {
                // Show error toast
                showToast(result.message, 'error');
            }
        }

    } catch (error) {
        console.error('Error verifying ID:', error);
        showToast('❌ خطأ في معالجة البطاقة. حاول مرة أخرى.', 'error');
    }
}

function showToast(message, type) {
    const toastEl = document.getElementById('toast');
    const toastMessage = document.getElementById('toast-message');
    
    toastMessage.textContent = message;

    // Set toast color based on type
    if (type === 'success') {
        toastEl.className = 'toast align-items-center border-0 bg-success text-white';
    } else if (type === 'error') {
        toastEl.className = 'toast align-items-center border-0 bg-danger text-white';
    } else {
        toastEl.className = 'toast align-items-center border-0 bg-warning text-dark';
    }

    const toast = new bootstrap.Toast(toastEl, {
        autohide: true,
        delay: 5000
    });
    toast.show();
}

function showBlockedModal(person) {
    document.getElementById('blocked-name').textContent = person.name;
    document.getElementById('blocked-id').textContent = `رقم البطاقة: ${person.id_number.substring(0, 4)}...`;
    document.getElementById('blocked-reason').textContent = person.block_reason;

    const modal = new bootstrap.Modal(document.getElementById('blockedModal'));
    modal.show();
}
