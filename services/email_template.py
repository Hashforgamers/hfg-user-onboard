import html
import os


def build_hfg_email_html(subject: str, body_text: str) -> str:
    safe_subject = html.escape(subject or "Hash For Gamers Update")
    safe_body = html.escape(body_text or "").replace("\n", "<br/>")
    logo_url = (
        os.getenv("HASH_EMAIL_LOGO_URL")
        or "https://dashboard.hashforgamers.com/whitehashlogo.png"
    ).strip()
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{safe_subject}</title>
  </head>
  <body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
            <tr>
              <td style="padding:20px 24px;background:#0b1220;color:#ffffff;">
                <img src="{html.escape(logo_url)}" alt="Hash For Gamers" style="display:block;height:42px;width:auto;margin:0 0 10px 0;" />
                <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#22c55e;font-weight:700;">Hash For Gamers</div>
                <div style="margin-top:8px;font-size:22px;font-weight:700;line-height:1.35;">{safe_subject}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:24px;font-size:14px;line-height:1.7;color:#111827;">
                {safe_body}
              </td>
            </tr>
            <tr>
              <td style="padding:14px 24px;border-top:1px solid #e5e7eb;background:#f9fafb;color:#6b7280;font-size:12px;">
                Need help? Contact <a href="mailto:support@hashforgamers.co.in" style="color:#2563eb;text-decoration:none;">support@hashforgamers.co.in</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
