import frappe
import qrcode
import base64
import json
import secrets

from io import BytesIO


@frappe.whitelist()
def generate_qr_code():

  data = frappe.form_dict

  # Generate Secure Token
  token = secrets.token_urlsafe(32)

  # Store in Redis for 5 minutes
  frappe.cache().set_value(
    f"hrms_mobile_token:{token}",
    {
      "user": frappe.session.user,
      "company": data.get("company"),
      "name": data.get("name"),
    },
    expires_in_sec=300
  )

  # Data stored inside QR
  qr_data = {
    "server_url": data.get("server_url"),
    "token": token
  }

  # Generate QR
  img = qrcode.make(json.dumps(qr_data))

  buffer = BytesIO()
  img.save(buffer, format="PNG")

  return base64.b64encode(buffer.getvalue()).decode()