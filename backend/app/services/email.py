"""Email delivery via Resend (https://resend.com). Free tier: 100 emails/day."""
import asyncio

import resend
import structlog

from app.config import settings

logger = structlog.get_logger()

# Resend 测试阶段只能用此发件地址（无需验证域名）
DEFAULT_FROM = "onboarding@resend.dev"


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


def _resolve_from_address() -> str:
    """Resend 测试阶段 from 必须是 onboarding@resend.dev。"""
    configured = (settings.email_from or "").strip()
    if not configured or "@" not in configured:
        return DEFAULT_FROM
    # 用户误填个人邮箱时自动纠正
    if configured.endswith("@gmail.com") or configured.endswith("@qq.com"):
        logger.warning("email_from_invalid_using_default", configured=configured)
        return DEFAULT_FROM
    return configured


def _send_sync(to_email: str, code: str, ttl_minutes: int) -> dict:
    resend.api_key = settings.resend_api_key
    return resend.Emails.send({
        "from": _resolve_from_address(),
        "to": [to_email],
        "subject": f"【问津】您的注册验证码是 {code}",
        "html": build_verification_email_html(code, ttl_minutes),
    })


async def send_verification_code(to_email: str, code: str, ttl_minutes: int = 10) -> bool:
    """
    Send verification code email via Resend SDK.

    Returns True if email was sent.
    Returns False in development when RESEND_API_KEY is not set (code logged instead).
    Raises RuntimeError when API key is configured but delivery fails.
    """
    if not settings.resend_api_key:
        if settings.env == "development":
            logger.warning(
                "email_skipped_no_api_key",
                email=to_email,
                code=code,
                hint="Set RESEND_API_KEY in .env and recreate backend container",
            )
            return False
        raise RuntimeError("邮件服务未配置")

    try:
        result = await asyncio.to_thread(_send_sync, to_email, code, ttl_minutes)
    except Exception as exc:
        logger.error("resend_send_failed", email=to_email, error=str(exc))
        raise RuntimeError(f"验证码邮件发送失败：{exc}") from exc

    logger.info("verification_email_sent", email=to_email, resend_id=result.get("id"))
    return True
