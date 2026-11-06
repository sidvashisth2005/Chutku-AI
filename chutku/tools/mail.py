"""Email (X8), draft first: email.draft opens a ready draft in the default mail app and sends nothing; the owner
presses Send there. email.send (Gmail SMTP, app password in Windows Credential Manager) is an R3 step that asks on
screen every time, in every mode, and needs the email.send capability, which is not granted by default.

Recipients are a literal address, or a person in the owner's memory with a saved email; an unknown name is never
guessed.
"""
from __future__ import annotations

from email.message import EmailMessage
import os
import re
import smtplib
import ssl
import urllib.parse

from chutku import mind
from chutku.tools.registry import Risk, Tool, ToolResult, Verification

CREDENTIAL_TARGET = "Chutku/Email"
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
NO_ATTACHMENTS = "A mailto draft cannot attach files; add attachments in the mail app before sending."


def resolve(to):
    """(address, label) for a literal address or a remembered person with an email; ValueError otherwise."""
    to = " ".join(str(to).split())
    if mind.EMAIL.fullmatch(to):
        return to, to
    person = mind.default().find_person(to)
    if person is not None and mind.EMAIL.fullmatch(person.get("email") or ""):
        return person["email"], person["name"]
    if person is not None:
        raise ValueError(f"I know {person['name']} but not their email address. Tell me the address, or save it "
                         f"once: '{to} ka email name@example.com hai'.")
    raise ValueError(f"I don't know who {to} is, so I won't guess an email address. Tell me the address, or save it "
                     f"once: '{to} ka email name@example.com hai'.")


def store_account(address, app_password):
    from chutku.cloud_planner import store_key
    address, app_password = address.strip(), re.sub(r"\s+", "", app_password)
    if not mind.EMAIL.fullmatch(address):
        raise ValueError("That does not look like an email address.")
    if not 16 <= len(app_password) <= 64:
        raise ValueError("A Gmail app password is 16 letters (spaces do not matter).")
    store_key(f"{address}\n{app_password}", target=CREDENTIAL_TARGET)


def account():
    """(address, app password) from Windows Credential Manager, or None."""
    from chutku.cloud_planner import stored_key
    address, _, password = (stored_key(CREDENTIAL_TARGET) or "").partition("\n")
    return (address, password) if mind.EMAIL.fullmatch(address) and password else None


def mail_handler():
    """The ProgId of the default mailto app, or None when Windows has none."""
    import winreg
    for hive, path, value in ((winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations"
                               r"\UrlAssociations\mailto\UserChoice", "ProgId"),
                              (winreg.HKEY_CLASSES_ROOT, r"mailto\shell\open\command", "")):
        try:
            with winreg.OpenKey(hive, path) as key:
                found = winreg.QueryValueEx(key, value)[0]
            if found:
                return "mailto" if hive == winreg.HKEY_CLASSES_ROOT else str(found)
        except OSError:
            continue
    return None


def _draft(arguments, _context):
    try:
        address, label = resolve(arguments["to"])
    except ValueError as error:
        return ToolResult({"error": str(error), "sent": False}, Verification.FAIL)
    handler = mail_handler()
    if handler is None:
        return ToolResult({"error": "Windows has no default mail app, so no draft could open. Pick one in Settings > "
                                    "Apps > Default apps (mailto).", "sent": False}, Verification.FAIL)
    body = arguments["body"].replace("\r\n", "\n").replace("\n", "\r\n")   # mailto line breaks are CRLF (RFC 6068)
    url = (f"mailto:{urllib.parse.quote(address, safe='@')}?subject={urllib.parse.quote(arguments['subject'], safe='')}"
           f"&body={urllib.parse.quote(body, safe='')}")
    try:
        os.startfile(url)   # the default mail app; no command line is composed
    except OSError as error:
        return ToolResult({"error": f"The mail app did not open: {error}", "sent": False}, Verification.FAIL)
    # shortcut: success means Windows accepted the mailto link; the draft window itself is not observed.
    output = {"draft_opened": True, "sent": False, "to": label, "address": address, "subject": arguments["subject"],
              "opened_with": handler, "note": "Nothing was sent: check the draft and press Send in the mail app. "
              + NO_ATTACHMENTS}
    return ToolResult(output, Verification.PASS, output | {"address": "[REDACTED]", "subject": "[REDACTED]"})


def send_question(arguments):
    """The on-screen question every email send asks (no address or text here: this reason goes to the audit log)."""
    try:
        _address, label = resolve(arguments.get("to", ""))
    except ValueError as error:
        return f"{error} Nothing will be sent."
    return f"Sending an email always asks first: check that it goes to {label} and that the text is right."


def _send(arguments, context):
    if not context.approved:   # the policy asks first; this refuses even if a policy change ever let it through
        return ToolResult({"error": "Sending an email needs your on-screen OK; nothing was sent.", "sent": False},
                          Verification.FAIL)
    try:
        address, label = resolve(arguments["to"])
    except ValueError as error:
        return ToolResult({"error": str(error) + " Nothing was sent.", "sent": False}, Verification.FAIL)
    saved = account()
    if saved is None:
        return ToolResult({"error": "No email account is set up, so nothing was sent. Run once: python -m chutku.cli "
                                    "email set-account (a Gmail address and an app password).", "sent": False},
                          Verification.FAIL)
    sender, password = saved
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, address, arguments["subject"]
    message.set_content(arguments["body"])
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30, context=ssl.create_default_context()) as smtp:
            smtp.login(sender, password)
            refused = smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        return ToolResult({"error": "Gmail refused the saved app password; nothing was sent. Make a new app password "
                                    "and run: python -m chutku.cli email set-account", "sent": False}, Verification.FAIL)
    except (smtplib.SMTPException, OSError) as error:
        return ToolResult({"error": f"The email was not sent: {error}", "sent": False}, Verification.FAIL)
    if refused:
        return ToolResult({"error": f"Gmail refused the recipient {address}.", "sent": False}, Verification.FAIL)
    output = {"sent": True, "to": label, "address": address, "subject": arguments["subject"], "from": sender}
    return ToolResult(output, Verification.PASS, output | {"address": "[REDACTED]", "subject": "[REDACTED]"})


def _validator(body_limit):
    def validate(arguments):
        if set(arguments) != {"to", "subject", "body"} or not all(isinstance(v, str) for v in arguments.values()):
            raise ValueError("Give to (an email address or a remembered person), subject and body.")
        if not 1 <= len(arguments["to"].strip()) <= 254:
            raise ValueError("to must be an email address or a remembered person's name.")
        if not 1 <= len(arguments["subject"].strip()) <= 200 or re.search(r"[\r\n]", arguments["subject"]):
            raise ValueError("subject must be one line of 1-200 characters.")
        if not 1 <= len(arguments["body"].strip()) <= body_limit:
            raise ValueError(f"body must be 1-{body_limit} characters.")
    return validate


def _schema(body_limit):
    return {"type": "object", "properties": {"to": {"type": "string", "minLength": 1, "maxLength": 254},
                                             "subject": {"type": "string", "minLength": 1, "maxLength": 200},
                                             "body": {"type": "string", "minLength": 1, "maxLength": body_limit}},
            "required": ["to", "subject", "body"], "additionalProperties": False}


def register_mail_tools(registry):
    registry.register(Tool("email.draft", "Open a ready email draft (to, subject, body) in the default mail app; "
        "nothing is sent, the owner presses Send. 'to' is an email address or a remembered person with a saved email. "
        "A draft cannot attach files.",
        Risk.REVERSIBLE, _draft, _validator(1500), frozenset({"body"}), required_capability="apps.launch",
        argument_schema=_schema(1500), prerequisites=("a default mail app",), reversibility="transient",
        success_predicate="mailto_draft_handed_to_default_mail_app"))
    registry.register(Tool("email.send", "Send an email (to, subject, body) from the owner's Gmail account; always "
        "confirmed on screen. Prefer email.draft unless the owner asked to send it directly.",
        Risk.EXTERNAL_SIDE_EFFECT, _send, _validator(5000), frozenset({"body"}), required_capability="email.send",
        argument_schema=_schema(5000), prerequisites=("Gmail app password saved with: chutku.cli email set-account",),
        reversibility="none", success_predicate="smtp_server_accepted_the_message", network_egress=True))
