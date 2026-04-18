/**
 * Business Spy - PayPal Payment Flow
 * Adapted from LeadIdeal v4 payment pattern.
 */

(function () {
  'use strict';

  let selectedPackage = null;
  let packages = {};
  let paypalReady = false;

  // --- Package Selection ---

  window.selectPackage = function (pkgId) {
    selectedPackage = pkgId;
    document.querySelectorAll('.package-card').forEach(function (card) {
      card.classList.toggle('selected', card.dataset.package === pkgId);
    });

    var pkg = packages[pkgId];
    if (pkg) {
      document.getElementById('summary-name').textContent = pkg.name;
      document.getElementById('summary-price').textContent = '$' + pkg.price;
    }
  };

  function validateForm() {
    var email = (document.getElementById('customer-email').value || '').trim();
    var errorEl = document.getElementById('form-error');

    if (!email || email.indexOf('@') === -1) {
      errorEl.textContent = 'Please enter a valid email address.';
      errorEl.style.display = 'block';
      return false;
    }
    if (!selectedPackage) {
      errorEl.textContent = 'Please select a package.';
      errorEl.style.display = 'block';
      return false;
    }

    errorEl.style.display = 'none';
    return true;
  }

  // --- PayPal SDK Loading ---

  function loadPayPalSDK() {
    fetch('/api/paypal-config')
      .then(function (res) { return res.json(); })
      .then(function (config) {
        packages = config.packages || {};

        if (!config.client_id) {
          document.getElementById('paypal-button-container').innerHTML =
            '<p style="color: #ff6b6b; text-align: center;">Payment is not configured yet. Please contact support.</p>';
          return;
        }

        // Auto-select pro
        window.selectPackage('pro');

        var script = document.createElement('script');
        script.src = 'https://www.paypal.com/sdk/js?client-id=' +
          encodeURIComponent(config.client_id) +
          '&currency=USD&intent=capture';
        script.onload = function () {
          paypalReady = true;
          renderPayPalButtons();
        };
        script.onerror = function () {
          document.getElementById('paypal-button-container').innerHTML =
            '<p style="color: #ff6b6b; text-align: center;">Failed to load payment provider. Please try again.</p>';
        };
        document.head.appendChild(script);
      })
      .catch(function (err) {
        console.error('Failed to fetch PayPal config:', err);
        document.getElementById('paypal-button-container').innerHTML =
          '<p style="color: #ff6b6b; text-align: center;">Unable to initialize payment. Please try again later.</p>';
      });
  }

  // --- PayPal Buttons ---

  function renderPayPalButtons() {
    if (!window.paypal) return;

    window.paypal.Buttons({
      style: {
        layout: 'vertical',
        color: 'blue',
        shape: 'rect',
        label: 'pay',
        height: 50,
      },

      createOrder: function () {
        if (!validateForm()) {
          return Promise.reject(new Error('Validation failed'));
        }

        var email = document.getElementById('customer-email').value.trim();
        var targetUrl = (document.getElementById('target-url').value || '').trim();

        return fetch('/api/paypal/create-order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            packageId: selectedPackage,
            email: email,
            targetUrl: targetUrl,
          }),
        })
          .then(function (res) { return res.json(); })
          .then(function (data) {
            if (data.error) throw new Error(data.error);
            return data.id;
          });
      },

      onApprove: function (data) {
        // Step 1: Capture payment
        return fetch('/api/paypal/capture', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ orderId: data.orderID }),
        })
          .then(function (res) { return res.json(); })
          .then(function (captureData) {
            if (!captureData.success) {
              throw new Error(captureData.error || 'Capture failed');
            }

            // Step 2: Confirm order
            var targetUrl = (document.getElementById('target-url').value || '').trim();
            return fetch('/api/orders', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                orderId: data.orderID,
                captureId: captureData.capture_id,
                packageId: selectedPackage,
                targetUrl: targetUrl,
              }),
            });
          })
          .then(function (res) { return res.json(); })
          .then(function (orderData) {
            if (!orderData.success) {
              throw new Error(orderData.error || 'Order confirmation failed');
            }

            // Show success
            document.getElementById('checkout-flow').style.display = 'none';
            document.getElementById('success-panel').style.display = 'block';
          });
      },

      onError: function (err) {
        console.error('PayPal error:', err);
        var errorEl = document.getElementById('form-error');
        errorEl.textContent = 'Payment failed. Please try again or contact support.';
        errorEl.style.display = 'block';
      },

      onCancel: function () {
        var errorEl = document.getElementById('form-error');
        errorEl.textContent = 'Payment was cancelled. You can try again when ready.';
        errorEl.style.display = 'block';
      },
    }).render('#paypal-button-container');
  }

  // --- Init ---
  loadPayPalSDK();
})();
