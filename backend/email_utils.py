# email_utils.py
import os
import smtplib
import subprocess
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr


def _get_mail_from() -> str:
    # 兼容你之前的变量名：SMTP_FROM 或 MAIL_FROM
    return os.getenv("SMTP_FROM") or os.getenv("MAIL_FROM") or "no-reply@localhost"


def _get_mail_from_name() -> str:
    return os.getenv("MAIL_FROM_NAME") or "ELN"


def _get_smtp_conf():
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()

    # 是否启用 STARTTLS（一般 587 用，25 在内网可不启用）
    # 默认策略：587 -> True，其它 -> False（你现在宿主机是 25，更符合你的需求）
    use_tls_env = os.getenv("SMTP_USE_TLS", "").strip().lower()
    if use_tls_env in ("1", "true", "yes", "on"):
        smtp_use_tls = True
    elif use_tls_env in ("0", "false", "no", "off"):
        smtp_use_tls = False
    else:
        smtp_use_tls = (smtp_port == 587)

    # 是否使用 SSL（一般 465 用）
    use_ssl_env = os.getenv("SMTP_USE_SSL", "").strip().lower()
    if use_ssl_env in ("1", "true", "yes", "on"):
        smtp_use_ssl = True
    elif use_ssl_env in ("0", "false", "no", "off"):
        smtp_use_ssl = False
    else:
        smtp_use_ssl = (smtp_port == 465)

    timeout = int(os.getenv("SMTP_TIMEOUT", "15"))

    return smtp_host, smtp_port, smtp_user, smtp_pass, smtp_use_tls, smtp_use_ssl, timeout


def _build_msg(to_email: str, subject: str, body: str) -> str:
    mail_from = _get_mail_from()
    mail_from_name = _get_mail_from_name()

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(mail_from_name, "utf-8")), mail_from))
    msg["To"] = to_email

    # 可选：Reply-To
    reply_to = os.getenv("MAIL_REPLY_TO", "").strip()
    if reply_to:
        msg["Reply-To"] = formataddr(("", reply_to))

    return msg.as_string()


def _send_via_smtp(to_email: str, msg_str: str):
    smtp_host, smtp_port, smtp_user, smtp_pass, smtp_use_tls, smtp_use_ssl, timeout = _get_smtp_conf()
    mail_from = _get_mail_from()

    if not (smtp_host and mail_from):
        raise RuntimeError("SMTP not configured: missing SMTP_HOST or SMTP_FROM")

    def _maybe_login(server):
        # 允许无认证：只要不提供 user/pass 就不登录
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)

    if smtp_use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout) as server:
            _maybe_login(server)
            server.sendmail(mail_from, [to_email], msg_str)
        return

    with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as server:
        server.ehlo()
        if smtp_use_tls:
            server.starttls()
            server.ehlo()
        _maybe_login(server)
        server.sendmail(mail_from, [to_email], msg_str)


def _send_via_sendmail(to_email: str, msg_str: str):
    mail_from = _get_mail_from()
    sendmail_path = os.getenv("SENDMAIL_PATH", "/usr/sbin/sendmail")

    p = subprocess.run(
        [sendmail_path, "-t", "-i", "-f", mail_from],
        input=msg_str.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(f"sendmail failed: {p.stderr.decode('utf-8', errors='ignore')}")


def send_reset_code(to_email: str, code: str):
    subject = "LMateLab 找回密码验证码"
    body = f"""你的验证码是：{code}

验证码有效期 10 分钟。若非本人操作，请忽略本邮件。
"""
    msg_str = _build_msg(to_email, subject, body)

    smtp_host, *_ = _get_smtp_conf()

    # 优先 SMTP（容器环境的推荐方式：走宿主机 postfix）
    if smtp_host:
        return _send_via_smtp(to_email, msg_str)

    # 否则走本机 Postfix / sendmail（更偏“宿主机直跑”的兜底）
    return _send_via_sendmail(to_email, msg_str)
