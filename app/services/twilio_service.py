"""Twilio OTP delivery via Programmable SMS or Verify API."""

import asyncio
from dataclasses import dataclass
from typing import Optional

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from app.config import settings
from app.core.logging import get_logger
from app.utils.phone_util import mask_phone_number

logger = get_logger(__name__)


@dataclass
class SMSResult:
    """Outcome of an SMS/Verify send attempt."""

    success: bool
    message_sid: Optional[str] = None
    error_message: Optional[str] = None


class TwilioService:
    """Sends OTP codes via Twilio (lazy-initialised client)."""

    def __init__(self) -> None:
        self._client: Optional[Client] = None

    @property
    def client(self) -> Client:
        if self._client is None:
            if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
                raise ValueError("Twilio credentials not configured")
            self._client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        return self._client

    async def send_otp(self, phone_number: str, otp_code: str) -> SMSResult:
        logger.info("sending_otp", phone=mask_phone_number(phone_number))

        try:
            if settings.TWILIO_VERIFY_SERVICE_SID:
                return await self._send_via_verify(phone_number)
            return await self._send_via_sms(phone_number, otp_code)

        except TwilioRestException as exc:
            logger.error("twilio_error", phone=mask_phone_number(phone_number), error=exc.msg)
            return SMSResult(success=False, error_message=f"SMS delivery failed: {exc.msg}")
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("twilio_unexpected_error", phone=mask_phone_number(phone_number))
            return SMSResult(success=False, error_message=str(exc))

    async def _send_via_sms(self, phone_number: str, otp_code: str) -> SMSResult:
        body = (
            f"Your OuroborosAI verification code is: {otp_code}\n\n"
            "This code expires in 5 minutes. Do not share it with anyone."
        )
        message = await asyncio.to_thread(
            self.client.messages.create,
            to=phone_number,
            from_=settings.TWILIO_PHONE_NUMBER,
            body=body,
        )
        logger.info("otp_sent", phone=mask_phone_number(phone_number), sid=message.sid)
        return SMSResult(success=True, message_sid=message.sid)

    async def _send_via_verify(self, phone_number: str) -> SMSResult:
        verification = await asyncio.to_thread(
            self.client.verify.v2.services(settings.TWILIO_VERIFY_SERVICE_SID).verifications.create,
            to=phone_number,
            channel="sms",
        )
        logger.info(
            "verify_otp_sent",
            phone=mask_phone_number(phone_number),
            sid=verification.sid,
            status=verification.status,
        )
        return SMSResult(success=verification.status == "pending", message_sid=verification.sid)

    async def check_verify_otp(self, phone_number: str, code: str) -> SMSResult:
        """Verify an OTP through the Twilio Verify API (only if Verify is configured)."""
        if not settings.TWILIO_VERIFY_SERVICE_SID:
            raise ValueError("Twilio Verify not configured")

        try:
            check = await asyncio.to_thread(
                self.client.verify.v2.services(settings.TWILIO_VERIFY_SERVICE_SID).verification_checks.create,
                to=phone_number,
                code=code,
            )
            approved = check.status == "approved"
            logger.info("verify_check", phone=mask_phone_number(phone_number), approved=approved)
            return SMSResult(
                success=approved,
                message_sid=check.sid,
                error_message=None if approved else "Invalid or expired code",
            )
        except TwilioRestException as exc:
            logger.warning("verify_check_failed", phone=mask_phone_number(phone_number), error=exc.msg)
            return SMSResult(success=False, error_message=exc.msg)


class _TwilioSingleton:
    """Holds the lazily-created TwilioService (avoids ``global``)."""

    instance: Optional[TwilioService] = None


def get_twilio_service() -> TwilioService:
    if _TwilioSingleton.instance is None:
        _TwilioSingleton.instance = TwilioService()
    return _TwilioSingleton.instance
