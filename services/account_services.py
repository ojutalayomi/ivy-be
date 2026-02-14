import tracemalloc
tracemalloc.start()

import os
import ssl
import jwt
import time
import socket
import resend
import base64
import smtplib
from io import BytesIO
from pathlib import Path
from datetime import date
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from app.errors import MissingDetail
from email.message import EmailMessage
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime, timedelta, timezone
# from dotenv import load_dotenv


# load_dotenv()
print(os.getenv("PY_ENV"))
MAIL_SENDER = os.getenv("EMAIL_ADDR")
PASSWORD = os.getenv("EMAIL_PASSWORD")
resend.api_key = os.getenv("RESEND_API_KEY")


def generate_confirmation_token(email, time):
    payload = {
        'email': email,
        'exp': datetime.now(timezone.utc) + timedelta(hours=time)
    }
    return jwt.encode(payload, os.getenv("FLASK_APP_SECRET_KEY"), algorithm='HS256')


def touch_letter(filename: str, name: str, link: str):
    script_path = Path(__file__).resolve()
    file_path = script_path.parent / f"../letters/{filename}"
    file_path = file_path.resolve()

    # Read the original HTML content
    with open(file_path, 'r', encoding='utf-8') as file:
        html_content = file.read()
    html_content = html_content.replace("[User's First Name]", name)
    html_content = html_content.replace("[CTA Link]", link)
    return html_content
        # html_content = html_content.replace("Thanks for", "gbas")


def verify_email(token):
    try:
        payload = jwt.decode(token, os.getenv("FLASK_APP_SECRET_KEY"), algorithms=['HS256'])
        email = payload['email']
        # Find user by email and set verified=True
        return "success", email
    except jwt.ExpiredSignatureError:
        return "expired", None
    except jwt.InvalidTokenError:
        return "invalid", None


def create_receipt_pdf2(num: str, watermark_img="resource/ivyleague-logo.jpg", **kwargs):
    # Define a receipt-size page: width = 80mm, height = 200mm
    if not num:
        return
    pdf_buffer = BytesIO()
    receipt_size = (180 * mm, 150 * mm)
    address = "3 Gray Close, off Birrel Avenue, Sabo, Yaba Lagos."

    width, height = receipt_size
    c = canvas.Canvas(pdf_buffer, pagesize=receipt_size)

    # Load and draw watermark image with low opacity
    try:
        if os.path.exists(watermark_img):
            # Use ImageReader to enable transparency
            watermark = ImageReader(watermark_img)

            # Save graphics state to apply transparency safely
            c.saveState()
            c.translate(-100, -125)  # Position the watermark
            c.setFillAlpha(0.1)  # Set transparency level (0 = fully transparent, 1 = opaque)
            c.drawImage(watermark, 0, 0, width=660, height=660, mask='auto')
            c.restoreState()
        else:
            print(f"Watermark image not found: {watermark_img}")
    except Exception as e:
        print("Error loading watermark image:", e)

    # Colors
    # cyan = colors.cyan
    dark_cyan = colors.HexColor("#008B8B")

    # Company Info
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(dark_cyan)
    c.drawString(30, height - 50, "RECEIPT")

    # Logo
    logo_path = r"resource\logo.png"  # Replace with your actual logo file path
    try:
        c.drawImage(logo_path, 30, height -85, width=50, height=50, mask='auto')
    except:
        pass  # No logo provided or not found

    # Company and customer details
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(30, height - 70, "IvyLeague Associates")
    c.drawString(30, height - 85, "Email: ivyleagueassociates@gmail.com")
    c.drawString(30, height - 100, address)

    # Receipt Info
    c.drawString(width - 210, height - 70, f"Date: {date.today().isoformat()}")
    c.drawString(width - 210, height - 85, f"Receipt No: {num}")

    # Customer Details
    c.setFillColor(colors.HexColor("#204474"))
    c.rect(30, height - 140, width - 60, 20, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(35, height - 135, "CUSTOMER DETAILS")

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    customer_y = height - 160
    c.drawString(35, customer_y, f"Name: {kwargs.get('name')}")
    c.drawString(250, customer_y, f"Phone: {kwargs.get('phone')}")
    c.drawString(35, customer_y - 15, f"Email: {kwargs.get('email')}")
    c.drawString(250, customer_y - 15, f"Reg No.: {kwargs.get('reg')}")

    # Items table
    # Curved box representing payment details
    num_lines = len(kwargs.get("transactions", [])) + 2
    line_height = 22
    min_height = 130  # or whatever you know looks fine

    box_x = 30
    box_y = height - 330 if len(kwargs.get("transactions")) < 5 else height - 338
    box_width = width - 60
    box_height = max(min_height, num_lines * line_height)#130
    corner_radius = 12

    c.setStrokeColor(colors.black)
    c.roundRect(box_x, box_y, box_width, box_height, corner_radius, stroke=1, fill=0)

    # Add headers and sample data manually
    c.setFont("Helvetica-Bold", 10)
    c.drawString(box_x + 10, box_y + box_height - 20, "PURPOSE")
    c.drawString(box_x + 90, box_y + box_height - 20, "DESCRIPTION")
    c.drawString(box_x + 360, box_y + box_height - 20, "AMOUNT")
    # c.drawString(box_x + 350, box_y + box_height - 20, "PAPER-CODE")

    c.setFont("Helvetica", 10)
    total = 0
    loops = 40
    for i in kwargs.get("transactions"):
        c.drawString(box_x + 10, box_y + box_height - loops, i.get("purpose", "--"))
        c.drawString(box_x + 90, box_y + box_height - loops, i.get("desc", "--"))
        c.drawString(box_x + 360, box_y + box_height - loops,f"# {i.get("amount", "--")}")
        # c.drawString(box_x + 350, box_y + box_height - loops, i.get("code", "--"))
        if not i.get("amount") or not i.get("amount").replace('.', '').replace('-', '').isdigit():
            return False #TO be replaced with custom error
        total += float(i.get("amount"))
        loops += 20

    c.setFont("Helvetica-Bold", 10)
    c.drawString(box_x + 10, box_y + box_height - (loops+30), "TOTAL:")
    c.drawString(box_x + 360, box_y + box_height - (loops+30), f"₦ {total}")


    current_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(current_dir)
    font_path = os.path.join(base_dir, 'resource', 'fonts')
    # Paid stamp
    if kwargs.get("sponsored"):
        pdfmetrics.registerFont(TTFont('baskvill', fr'{font_path}/BASKVILL.TTF'))
        c.setFont("baskvill", 40)
        c.setFillColor(colors.HexColor("#000000"))  # LimeGreen
        c.drawString(310, 40, "Sponsored")
    else:
        pdfmetrics.registerFont(TTFont('Castellar', fr'{font_path}/STENCIL.TTF'))
        c.setFont("Castellar", 50)
        c.setFillColor(colors.HexColor("#000000"))  # LimeGreen
        c.drawString(360, 40, "PAID")

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer


def send_signup_message(username: str, user_email: str):
    msg_subject = "Welcome to Ivy League Associates! Please Confirm Your Email"
    token = generate_confirmation_token(user_email, 24)
    link = f"{os.getenv('STUDENT_FRONTEND_URL')}/accounts/confirm-email?token={token}"
    # print(link)

#     print("Trying to read lettr. #Debug")
    try:
        html_content = touch_letter("signup-message.html", username, link)
    except FileNotFoundError:
        print(f"Error: The signup html file was not found.")
        return 0
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0

    r = resend.Emails.send({
        "from": f"Ivy League Updates <{MAIL_SENDER}>",
        "to": user_email,
        "subject": msg_subject,
        "html": html_content,
        "reply_to": "",
    })

    # 4. Send the letter generated in step 3 to that person's email address.
    # message = EmailMessage()
    # message["From"] = f"Ivy League Updates <{MAIL_SENDER}>"
    # message["To"] = user_email
    # message["Subject"] = msg_subject
    # # attach_image(images, message, image_cid)
    # # message.set_content(personalized_letter)
    # message.add_alternative(html_content, subtype='html')
    # message.add_header("Reply-to", "updates@ivyleaguenigeria.com")

#     context = ssl.create_default_context()
#     breaks = 0
#     while True:
#         print("IN while baudo send. #Debug")
#         try:
#             with smtplib.SMTP_SSL(host="smtp.ivyleaguenigeria.com", port=465, context=context) as mail:
#                 print("Logging in. #Debug")
#                 mail.login(user=MAIL_SENDER, password=PASSWORD)
#                 print("Actually sending. #Debug")
# #                 mail.sendmail(from_addr=MAIL_SENDER, to_addrs=user_email, msg=message.as_string())
#                 mail.send_message(message)
#         except smtplib.SMTPConnectError as f:
#             print("error as", f)
#         except smtplib.SMTPException as e:
#             print("Encountered smtp error :", e)
#             break
#         except ssl.SSLError as e:
#             print("Encountered ssl error :", e)
#         except socket.gaierror as e:
#             print("there is an error:", e)
#             breaks += 1
#             time.sleep(3)
#             if breaks > 4:
#                 # error404()
#                 break
#         else:
#             print("AN email has been sent")
#             break
#         break



def send_password_reset_message(username: str, user_email: str):
    msg_subject = "Reset Your Ivy League Associates LMS Password"
    token = generate_confirmation_token(user_email, 0.168) # Token expires after 10 minutes
    link = f"{os.getenv('STUDENT_FRONTEND_URL')}/accounts/reset-password?token={token}"
    print(link)

    try:
        html_content = touch_letter("reset-password.html", username, link)
    except FileNotFoundError:
        print(f"Error: The signup html file was not found.")
        return 0
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0

    # # 4. Send the letter generated in step 3 to that person's email address.
    # message = EmailMessage()
    # message["From"] = f"Ivy League Updates <{MAIL_SENDER}>"
    # message["To"] = user_email
    # message["Subject"] = msg_subject
    # message.add_alternative(html_content, subtype='html')
    # message.add_header("Reply-to", "updates@ivyleaguenigeria.com")
    #
    # context = ssl.create_default_context()
    # breaks = 0

    r = resend.Emails.send({
        "from": f"Ivy League Updates <{MAIL_SENDER}>",
        "to": user_email,
        "subject": msg_subject,
        "html": html_content,
        "reply_to": "",
    })


    # MAX_RETRIES = 3
    # for attempt in range(MAX_RETRIES):
    # # while True:
    #     try:
    #         with smtplib.SMTP_SSL(host="smtp.ivyleaguenigeria.com", port=465, context=context, timeout=10) as mail:
    #             mail.login(user=MAIL_SENDER, password=PASSWORD)
    #             mail.sendmail(from_addr=MAIL_SENDER, to_addrs=user_email, msg=message.as_string())
    #     except smtplib.SMTPConnectError as f:
    #         print("error as", f)
    #     except smtplib.SMTPException as e:
    #         print("Encountered smtp error :", e)
    #         break
    #     except ssl.SSLError as e:
    #         print("Encountered ssl error :", e)
    #     except socket.gaierror as e:
    #         print("there is an error:", e)
    #         breaks += 1
    #         time.sleep(3)
    #         if breaks > 4:
    #             break
    #     else:
    #         print("An email has been sent")
    #         break


def send_receipt(receipt_no: str, user_data: dict, details: list, spons :bool=False):
    name, phone = user_data.get("users_name"), user_data.get("phone_no")
    email, reg = user_data.get("email"), user_data.get("reg_no")
    if not (name and phone and email and reg):
        raise MissingDetail
    receipt_pdf = create_receipt_pdf2(receipt_no, transactions=details, name=name, phone=phone, email=email, reg=reg, sponsored=spons)

    msg_subject = "Payment receipt"
    html_content = touch_letter("receipt.html", name, "")
    user_email = email

    # Read and encode PDF
    pdf_bytes = receipt_pdf.read()
    encoded_pdf = base64.b64encode(pdf_bytes).decode("utf-8")

    r = resend.Emails.send({
        "from": f"Ivy League Updates <{MAIL_SENDER}>",
        "to": user_email,
        "subject": msg_subject,
        "html": html_content,
        "reply_to": "",
        "attachments": [
            {
                "filename": "receipt.pdf",
                "content": encoded_pdf
            }
        ]
    })
    # # 4. Send the letter generated in step 3 to that person's email address.
    # message = EmailMessage()
    # message["From"] = f"Ivy League Updates <{MAIL_SENDER}>"
    # message["To"] = user_email
    # message["Subject"] = msg_subject
    # message.add_alternative(html_content, subtype='html')
    # message.add_header("Reply-to", "updates@ivyleaguenigeria.com")
    #
    # # Attach the PDF
    # pdf_data = receipt_pdf.read()
    # message.add_attachment(pdf_data, maintype='application', subtype='pdf', filename='receipt.pdf')
    #
    # context = ssl.create_default_context()
    # breaks = 0
    # while True:
    #     try:
    #         with smtplib.SMTP_SSL(host="smtp.ivyleaguenigeria.com", port=465, context=context) as mail:
    #             mail.login(user=MAIL_SENDER, password=PASSWORD)
    #             mail.sendmail(from_addr=MAIL_SENDER, to_addrs=user_email, msg=message.as_string())
    #     except smtplib.SMTPConnectError as f:
    #         print("error as", f)
    #     except smtplib.SMTPException as e:
    #         print("Encountered smtp error :", e)
    #         break
    #     except ssl.SSLError as e:
    #         print("Encountered ssl error :", e)
    #     except socket.gaierror as e:
    #         print("there is an error:", e)
    #         breaks += 1
    #         time.sleep(3)
    #         if breaks > 4:
    #             break
    #     else:
    #         print("An email has been sent")
    #         break
    return receipt_pdf


def send_staff_creation_message(username: str, user_email: str, type_: str):
    token = generate_confirmation_token(user_email, 48)
    if type_ == "initialize-admin":
        msg_subject = "You've Been Chosen as an Admin!"
        link = f"{os.getenv('STAFF_FRONTEND_URL')}/accounts/complete-admin?token={token}"
    else:
        msg_subject = "Welcome to Ivy League LMS"
        link = f"{os.getenv('STAFF_FRONTEND_URL')}/accounts/dashboard"
    print(link)

    try:
        html_content = touch_letter(f"{type_}.html", username, link)
    except FileNotFoundError:
        print(f"Error: The signup html file was not found.")
        return 0
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0

    r = resend.Emails.send({
        "from": f"Ivy League Updates <{MAIL_SENDER}>",
        "to": user_email,
        "subject": msg_subject,
        "html": html_content,
        "reply_to": "",
    })

    # # 4. Send the letter generated in step 3 to that person's email address.
    # message = EmailMessage()
    # message["From"] = f"Ivy League Updates <{MAIL_SENDER}>"
    # message["To"] = user_email
    # message["Subject"] = msg_subject
    # message.add_alternative(html_content, subtype='html')
    # message.add_header("Reply-to", "updates@ivyleaguenigeria.com")
    #
    # context = ssl.create_default_context()
    # breaks = 0
    # while True:
    #     try:
    #         with smtplib.SMTP_SSL(host="smtp.ivyleaguenigeria.com", port=465, context=context) as mail:
    #             mail.login(user=MAIL_SENDER, password=PASSWORD)
    #             mail.sendmail(from_addr=MAIL_SENDER, to_addrs=user_email, msg=message.as_string())
    #     except smtplib.SMTPConnectError as f:
    #         print("error as", f)
    #     except smtplib.SMTPException as e:
    #         print("Encountered smtp error :", e)
    #         break
    #     except ssl.SSLError as e:
    #         print("Encountered ssl error :", e)
    #     except socket.gaierror as e:
    #         print("there is an error:", e)
    #         breaks += 1
    #         time.sleep(3)
    #         if breaks > 4:
    #             break
    #     else:
    #         print("An email has been sent")
    #         break


# send_signup_message("test_user", "opolopothings@gmail.com")
