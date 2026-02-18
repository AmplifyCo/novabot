"""Email tool - Read and send emails using IMAP/SMTP (works with Gmail, Outlook, etc.)"""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class EmailTool(BaseTool):
    """Tool for reading and sending emails via IMAP/SMTP.

    Works with any email provider:
    - Gmail (imap.gmail.com / smtp.gmail.com)
    - Outlook (outlook.office365.com)
    - Yahoo (imap.mail.yahoo.com / smtp.mail.yahoo.com)
    - Any other IMAP/SMTP provider
    """

    name = "email"
    description = "Read, send, reply to emails. Check inbox, unread messages, search emails."
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation: 'check_inbox', 'read_email', 'send_email', 'reply', 'search'",
            "enum": ["check_inbox", "read_email", "send_email", "reply", "search"]
        },
        "to": {
            "type": "string",
            "description": "Recipient email address (for send_email)"
        },
        "subject": {
            "type": "string",
            "description": "Email subject (for send_email, reply, search)"
        },
        "body": {
            "type": "string",
            "description": "Email body/content (for send_email, reply)"
        },
        "email_id": {
            "type": "string",
            "description": "Email ID to read or reply to"
        },
        "limit": {
            "type": "integer",
            "description": "Number of emails to fetch (default: 10)",
            "default": 10
        },
        "unread_only": {
            "type": "boolean",
            "description": "Only fetch unread emails (default: true)",
            "default": True
        }
    }

    def __init__(
        self,
        imap_server: str,
        smtp_server: str,
        email_address: str,
        password: str,
        imap_port: int = 993,
        smtp_port: int = 587
    ):
        """Initialize Email tool.

        Args:
            imap_server: IMAP server (e.g., imap.gmail.com)
            smtp_server: SMTP server (e.g., smtp.gmail.com)
            email_address: Your email address
            password: Email password or app-specific password
            imap_port: IMAP port (default: 993 for SSL)
            smtp_port: SMTP port (default: 587 for TLS)
        """
        self.imap_server = imap_server
        self.smtp_server = smtp_server
        self.email_address = email_address
        self.password = password
        self.imap_port = imap_port
        self.smtp_port = smtp_port

    async def execute(
        self,
        operation: str,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        email_id: Optional[str] = None,
        limit: int = 10,
        unread_only: bool = True
    ) -> ToolResult:
        """Execute email operation.

        Args:
            operation: Operation to perform
            to: Recipient email
            subject: Email subject
            body: Email body
            email_id: Email ID for read/reply
            limit: Number of emails to fetch
            unread_only: Only fetch unread emails

        Returns:
            ToolResult with operation result
        """
        try:
            if operation == "check_inbox":
                return await self._check_inbox(limit, unread_only)
            elif operation == "read_email":
                return await self._read_email(email_id)
            elif operation == "send_email":
                return await self._send_email(to, subject, body)
            elif operation == "reply":
                return await self._reply_to_email(email_id, body)
            elif operation == "search":
                return await self._search_emails(subject, limit)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown operation: {operation}"
                )

        except Exception as e:
            logger.error(f"Email operation error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"Email operation failed: {str(e)}"
            )

    async def _check_inbox(self, limit: int, unread_only: bool) -> ToolResult:
        """Check inbox and return summary of emails."""
        try:
            # Connect to IMAP server
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_address, self.password)
            mail.select('INBOX')

            # Search for emails
            search_criteria = '(UNSEEN)' if unread_only else 'ALL'
            status, messages = mail.search(None, search_criteria)

            if status != 'OK':
                return ToolResult(success=False, error="Failed to fetch emails")

            email_ids = messages[0].split()
            email_ids = email_ids[-limit:]  # Get last N emails

            emails = []
            for email_id in reversed(email_ids):  # Most recent first
                status, msg_data = mail.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue

                email_message = email.message_from_bytes(msg_data[0][1])

                # Decode subject
                subject = self._decode_header(email_message['Subject'])
                sender = email_message['From']
                date = email_message['Date']

                emails.append({
                    'id': email_id.decode(),
                    'from': sender,
                    'subject': subject,
                    'date': date
                })

            mail.close()
            mail.logout()

            if not emails:
                return ToolResult(
                    success=True,
                    output=f"📭 No {'unread ' if unread_only else ''}emails found"
                )

            # Format output
            output = f"📬 Found {len(emails)} {'unread ' if unread_only else ''}email(s):\n\n"
            for i, email_info in enumerate(emails, 1):
                output += f"{i}. **From**: {email_info['from']}\n"
                output += f"   **Subject**: {email_info['subject']}\n"
                output += f"   **Date**: {email_info['date']}\n"
                output += f"   **ID**: {email_info['id']}\n\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error(f"Error checking inbox: {e}")
            return ToolResult(success=False, error=str(e))

    async def _read_email(self, email_id: str) -> ToolResult:
        """Read full email content."""
        try:
            if not email_id:
                return ToolResult(success=False, error="email_id required")

            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_address, self.password)
            mail.select('INBOX')

            status, msg_data = mail.fetch(email_id.encode(), '(RFC822)')
            if status != 'OK':
                return ToolResult(success=False, error="Email not found")

            email_message = email.message_from_bytes(msg_data[0][1])

            # Extract email details
            subject = self._decode_header(email_message['Subject'])
            sender = email_message['From']
            date = email_message['Date']

            # Get body
            body = self._get_email_body(email_message)

            mail.close()
            mail.logout()

            output = f"**From**: {sender}\n"
            output += f"**Subject**: {subject}\n"
            output += f"**Date**: {date}\n\n"
            output += f"**Message**:\n{body}"

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error(f"Error reading email: {e}")
            return ToolResult(success=False, error=str(e))

    async def _send_email(self, to: str, subject: str, body: str) -> ToolResult:
        """Send an email."""
        try:
            if not to or not subject or not body:
                return ToolResult(
                    success=False,
                    error="to, subject, and body are required"
                )

            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = to
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            # Connect to SMTP server
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_address, self.password)

            # Send email
            server.send_message(msg)
            server.quit()

            return ToolResult(
                success=True,
                output=f"✅ Email sent to {to}\nSubject: {subject}"
            )

        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return ToolResult(success=False, error=str(e))

    async def _reply_to_email(self, email_id: str, reply_body: str) -> ToolResult:
        """Reply to an email."""
        try:
            if not email_id or not reply_body:
                return ToolResult(
                    success=False,
                    error="email_id and body required"
                )

            # First, read the original email
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_address, self.password)
            mail.select('INBOX')

            status, msg_data = mail.fetch(email_id.encode(), '(RFC822)')
            if status != 'OK':
                return ToolResult(success=False, error="Original email not found")

            original_email = email.message_from_bytes(msg_data[0][1])
            original_subject = self._decode_header(original_email['Subject'])
            original_sender = original_email['From']

            mail.close()
            mail.logout()

            # Prepare reply
            reply_subject = f"Re: {original_subject}" if not original_subject.startswith('Re:') else original_subject

            # Send reply
            return await self._send_email(
                to=original_sender,
                subject=reply_subject,
                body=reply_body
            )

        except Exception as e:
            logger.error(f"Error replying to email: {e}")
            return ToolResult(success=False, error=str(e))

    async def _search_emails(self, query: str, limit: int) -> ToolResult:
        """Search emails by subject."""
        try:
            if not query:
                return ToolResult(success=False, error="search query required")

            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_address, self.password)
            mail.select('INBOX')

            # Search by subject
            status, messages = mail.search(None, f'(SUBJECT "{query}")')

            if status != 'OK':
                return ToolResult(success=False, error="Search failed")

            email_ids = messages[0].split()
            email_ids = email_ids[-limit:]

            if not email_ids:
                return ToolResult(
                    success=True,
                    output=f"🔍 No emails found matching '{query}'"
                )

            emails = []
            for email_id in reversed(email_ids):
                status, msg_data = mail.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue

                email_message = email.message_from_bytes(msg_data[0][1])
                subject = self._decode_header(email_message['Subject'])
                sender = email_message['From']
                date = email_message['Date']

                emails.append({
                    'id': email_id.decode(),
                    'from': sender,
                    'subject': subject,
                    'date': date
                })

            mail.close()
            mail.logout()

            output = f"🔍 Found {len(emails)} email(s) matching '{query}':\n\n"
            for i, email_info in enumerate(emails, 1):
                output += f"{i}. **From**: {email_info['from']}\n"
                output += f"   **Subject**: {email_info['subject']}\n"
                output += f"   **ID**: {email_info['id']}\n\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return ToolResult(success=False, error=str(e))

    def _decode_header(self, header_value: str) -> str:
        """Decode email header."""
        if not header_value:
            return ""

        decoded_parts = decode_header(header_value)
        decoded_header = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                try:
                    decoded_header += part.decode(encoding or 'utf-8')
                except:
                    decoded_header += part.decode('utf-8', errors='ignore')
            else:
                decoded_header += str(part)

        return decoded_header

    def _get_email_body(self, email_message) -> str:
        """Extract email body from message."""
        body = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode()
                        break
                    except:
                        pass
        else:
            try:
                body = email_message.get_payload(decode=True).decode()
            except:
                body = str(email_message.get_payload())

        return body.strip()
