import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr


# Email Account
EMAIL_SENDER_ACCOUNT = "tribalwarsnotification@gmail.com"
EMAIL_SENDER_USERNAME = "klimekkaras@gmail.com"
EMAIL_SENDER_PASSWORD = "H5AU0dZLFYgaqEV1"
EMAIL_SMTP_SERVER = "smtp-relay.sendinblue.com"
EMAIL_SMTP_PORT = 587


def send_email(target: str | list[str], subject: str, body: str) -> None:
    """send email to provided emails with custom email subject and email message"""

    if isinstance(target, str):
        target = [target]

    # login to email server
    server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
    server.starttls()
    server.login(EMAIL_SENDER_USERNAME, EMAIL_SENDER_PASSWORD)
    # For loop, sending emails to all email recipients
    for recipient in target:
        message = MIMEMultipart("alternative")
        message["From"] = formataddr(("TribalWars (k.spec)", EMAIL_SENDER_ACCOUNT))
        message["To"] = recipient
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))
        text = message.as_string()
        server.sendmail(EMAIL_SENDER_ACCOUNT, recipient, text)
    # All emails sent, log out.
    server.quit()
