"""Email delivery via Resend (https://resend.com). Free tier: 100 emails/day."""
import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

RESEND_API_URL = "https://api.resend.com/emails"


def build_verification_email_html(code: str, ttl_minutes: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:40px 16px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;padding:32px;">
        <tr><td>
          <p style="margin:0 0 8px;font-size:20px;font-weight:600;color:#0f172a;">问津 · 注册验证码</p>
          <p style="margin:0 0 24px;font-size:14px;color:#64748b;line-height:1.6;">
            您正在注册问津账号，请使用以下验证码完成注册：
          </p>
          <p style="margin:0 0 24px;font-size:32px;font-weight:700;letter-spacing:8px;color:#1e40af;text-align:center;">
            {code}
          </p>
          <p style="margin:0 0 8px;font-size:13px;color:#64748b;line-height:1.6;">
            验证码 <strong>{ttl_minutes} 分钟</strong>内有效，请勿泄露给他人。
          </p>
          <p style="margin:0;font-size:13px;color:#94a3b8;line-height:1.6;">
            如非本人操作，请忽略此邮件。
          </p>
        </td></tr>
      </table>
      <p style="margin:16px 0 0;font-size:12px;color:#94a3b8;">问津 Agent · 高考志愿智能辅助</p>
    </td></tr>
  </table>
</body>
</html>"""


async def send_verification_code(to_email: str, code: str, ttl_minutes: int = 10) -> bool:
    """
    Send verification code email.

    Returns True if email was sent via Resend.
    Returns False in development when RESEND_API_KEY is not set (code logged instead).
    Raises RuntimeError when API key is configured but delivery fails.
    """
    if not settings.resend_api_key:
        if settings.env == "development":
            logger.warning(
                "email_skipped_no_api_key",
                email=to_email,
                code=code,
                hint="Set RESEND_API_KEY in .env — get one free at https://resend.com",
            )
            return False
        raise RuntimeError("邮件服务未配置")

    payload = {
        "from": settings.email_from,
        "to": [to_email],
        "subject": f"【问津】您的注册验证码是 {code}",
        "html": build_verification_email_html(code, ttl_minutes),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15.0,
        )

    if resp.status_code >= 400:
        logger.error(
            "resend_send_failed",
            status=resp.status_code,
            body=resp.text,
            email=to_email,
        )
        raise RuntimeError("验证码邮件发送失败，请稍后重试")

    logger.info("verification_email_sent", email=to_email)
    return True
