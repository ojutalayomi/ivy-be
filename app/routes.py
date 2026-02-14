import io
import os
# import jwt
import uuid
# import base64
# from zoneinfo import available_timezones

import requests
# import pandas as pd
from io import BytesIO
from config import Config
from flasgger import Swagger
from threading import Thread
from collections import defaultdict
from datetime import datetime, timezone
from .errors import UserNotFoundError
from sqlalchemy.exc import IntegrityError, OperationalError
from flask import jsonify, request, send_file
# from services.diet_version_manager import get_current_diet
from services.other_services import check_api, auth_required, authenticate_signin, generate_token, role_required, store_pfp, store_file, download_file, validate_questions, generate_code, read_mcq
# from flask_login import login_user, logout_user, login_required
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from services.db_services import insert_sponsored_row, is_valid_password, staff_activities, folder_access
from services.db_services import post_payment_executions, post_webhook_process, exists_in_models, log_staff_activity
from .models import db, All, Payment, Signee, Student, Sponsored, Paper, SystemData, Scholarship, Attempt, Enrollment, McqTest, GatewayTest, McqHistory
from services.db_services import move_signee, update_action, update_payment, initialize_payment, generate_student_data, platform_access
from services.account_services import send_signup_message, verify_email, send_password_reset_message, send_staff_creation_message
from .models import Diet, Staff, DirectoryTemplate, DirectoryInstance, File, Review
# t = get_current_diet()

# from flask import Blueprint
# from flask_login import login_required, current_user
# from functools import wraps
# from flask import jsonify
# from app.models import Role
#
# bp = Blueprint('routes', __name__)


def register_routes(app):

    swagger = Swagger(app)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    # -----------------------------
    # Verify Payment
    # -----------------------------
    @app.route("/api/v1/verify/<reference>", methods=["GET"])
    @auth_required
    def verify_payment(reference):
        print("Verifying Payment")
        verified = db.session.execute(db.select(Payment).where(Payment.payment_reference==reference)).scalar()
        if verified:
            user = verified.enrollment.student
            # currently_enrolled = [paper for entry in user.enrollments if entry.diet.completion_date > datetime.now(timezone.utc) for paper in entry.papers]
            currently_enrolled = [
                (paper, entry.diet)
                for entry in user.enrollments
                for paper in entry.papers
                if entry.diet.completion_date > datetime.now(timezone.utc)
            ]
            return jsonify({
                "title": user.title,
                "firstname": user.first_name,
                "lastname": user.last_name,
                "email": user.email,
                "gender": user.gender,
                "profile_pic": user.profile_photo, #base64.b64encode(user.profile_photo).decode('utf-8'),
                "reg_no": user.reg_no,
                "acca_reg_no": user.acca_reg_no,
                "papers": [{paper[0].code: (paper[0].name, paper[1].name)} for paper in currently_enrolled],
                "user_status": "student",
            }), 200

        headers = {
            "Authorization": f"Bearer {Config.PAYSTACK_SECRET_KEY}"
        }

        try:
            response = requests.get(f"{Config.BASE_URL}/transaction/verify/{reference}", headers=headers)
        except ConnectionError as e:
            return jsonify(
                error={
                    "Connection Error": "Failed to connect to paystack"
                }
            )

        if response.status_code != 200 or not response.json().get("status"):
            return jsonify(error={"error": "Verification failed"}), 500
        else:
            from pprint import pprint
            feedback = response.json()["data"]
            # pprint(feedback)
            if feedback.get("status") == "success":
                exec_response = post_payment_executions(reference, feedback)
                if exec_response[1] != 200:
                    # key = list(exec_response[0].json["error"].keys())[0]
                    key, value = list(exec_response[0].json["error"].items())[0]
                    return jsonify(
                        error = {
                            "message": "Payment confirmed but internal db error, na gbese be this.",
                            "paystack_says": response.json()["message"],
                            key: value #exec_response[0].json["error"][key]
                        }
                    ), exec_response[1]
                return jsonify(     # Code will run if response is 200
                    {
                        "status": "success",
                        "message": "Payment confirmed",
                        "paystack_says": response.json()["message"],
                        "user_data": exec_response[0].json
                    }
                ), 200
            elif feedback.get("status") in ["ongoing", "pending", "processing", "queued"]:
                return jsonify(
                    {
                        "status": "patience",
                        "message": "Payment underway, exercise patience bros.",
                        "paystack_says": response.json()["message"],
                    }
                ), 202
            elif feedback.get("status") == "abandoned":
                return jsonify(
                    {
                        "status": "some patience needed",
                        "message": "Payment underway, it probably hasn't started.",
                        "paystack_says": response.json()["message"],
                    }
                ), 202
            elif feedback.get("status") in ["failed", "reversed"]:
                attempt = db.session.execute(db.select(Attempt).where(Attempt.payment_reference == reference)).scalar()
                attempt.closed_at = datetime.now(timezone.utc)
                attempt.payment_status = "failed"
                attempt.failure_cause = "Transaction declined or reversed"
                db.session.commit()
                return jsonify(
                    {
                        "status": "obliterated",
                        "message": "The payment is either failed or reversed.",
                        "paystack_says": response.json()["message"],
                    }
                ),410
        # data = response.json()
        # return jsonify(data), 200


    # -----------------------------
    # Webhook
    # -----------------------------
    @app.route("/api/v1/webhook", methods=["POST"])
    # @auth_required
    def handle_webhook():
        print("They don call webhook oo")
        event = request.json
        event_type = event.get("event")
        reference = event.get("data", {}).get("reference")

        print(f"Webhook event: {event_type} for reference: {reference}")

        # Here you’d typically update the DB
        # Example:
        # if event_type == 'charge.success':
        #     update_payment_status(reference, status='completed')
        # with app.app_context():
        thread = Thread(target=post_webhook_process, args=(app, reference, event.get("data", {})))
        thread.start()

        return jsonify({"status": "received"}), 200


    @app.route("/api/v1/signup", methods=["POST"])
    # @auth_required
    @authenticate_signin
    def sign_up():
        print("i dey come")
        # if request.args.get("api-key") != api_key:
        #     # g = request.args.get("api-key")
        #     return jsonify(
        #         error={
        #             "Access Denied": f"You do not have access to this resource"  # \n type:{type(g)}. it is {g}",
        #         }
        #     ), 403
        data = request.get_json()

        # Check if they are already signed up
        already_exists = [False]
        if exists_in_models("email", data.get("email"), Signee, Student, Staff, All):
            already_exists = [True, "Email"]
        elif exists_in_models("phone", data.get("phone"), Signee, Student, Staff):
            already_exists = [True, "Phone number"]
        if already_exists[0]:
            return jsonify(
                error={
                    "Tautology,": f"{already_exists[1]} already in use!"
                }
            ), 403
        if isinstance(data.get("dob"), str):
            try:
                d_o_b = datetime.fromisoformat(data.get("dob").replace("Z", "+00:00"))
            except:
                d_o_b = datetime.strptime(data.get("dob"), "%d/%m/%Y")
        else:
            d_o_b = data.get("dob")
        ver_pword = is_valid_password(data.get("password"))
        if not ver_pword[0]:
            return jsonify(
                error={
                    "Invalid Password": f"Error cause: [{ver_pword[1]}]",
                }
            ), 400
        if len(data.get("phone")) > 15:
            return jsonify(
                error={
                    "Invalid PhoneNUmber": f"{data.get('phone')} is not a valid number!",
                }
            ), 400

        hash_and_salted_password = generate_password_hash(
            data.get("password"),
            method='pbkdf2:sha256',
            salt_length=8
        )

        try:
            print(f"data is {request.method}")
            new_signee = Signee(
                # id=random.randint(3, 9),
                title=data.get("title"),
                email=data.get("email"),
                first_name=data.get("firstname").title(),
                last_name=data.get("lastname").title(),
                phone_number=data.get("phone"),
                birth_date=d_o_b,
                gender=data.get("gender").lower(),
                password=hash_and_salted_password
            )
            with app.app_context():
                db.session.add(new_signee)
                db.session.commit()
            send_signup_message(data.get("firstname").title(), data.get("email"))
        except IntegrityError as e:
            print(str(e))
            # print(data)
            return jsonify(
                error={
                    "DB Integrity Compromise": f"User email or phone number already exists",
                }
            ), 409
        except AttributeError as e:
            print(type(data), data)
            return jsonify(
                error={
                    "Invalid Key": f"You missed a key.\n{e} required keys: [firstname, lastname, title, email, gender, dob, phone, password",
                }
            ), 409
        except Exception as e:
            return jsonify(
                error={
                    "Uncaught Error": f"This error wasn't expected or planned for.\n{e}",
                }
            ), 422
        else:
            return jsonify({
                "status": "success",
                "message": "Signup successful",
            }), 201


    @app.route("/api/v1/signin", methods=["POST"])
    @authenticate_signin
    def sign_in():
        data = request.get_json()
        login_type = data.get("type")

        if login_type == "email":
            # First check if user is an admin/staff
            staff = db.session.execute(db.select(Staff).where(Staff.email == data.get("email"))).scalar() #ACCount for operational error
            if staff: # User is a staff
                password = data.get("password")
                if check_password_hash(staff.password, password):
                    token = generate_token(staff.id, staff.role)
                    staff.last_active = datetime.now(timezone.utc)
                    db.session.commit()
                    # login_user(user)
                    return jsonify({
                        "title": staff.title,
                        "firstname": staff.first_name,
                        "lastname": staff.last_name,
                        "email": staff.email,
                        "email_verified": True,
                        "code": staff.code,
                        "gender": staff.gender,
                        "role": staff.role,
                        "user_status": "staff",
                        # "phone_no": staff.phone_number,
                        "address": staff.house_address,
                        "status": staff.status,
                        "bearer_token": token
                        # "profile_pic": base64.b64encode(staff.photo).decode('utf-8')
                    })
                else:
                    return jsonify(
                        error={
                            "Incorrect Input": f"Email or Password incorrect"
                        }
                    ), 403
            result = db.session.execute(db.select(Student).where(Student.email == data.get("email")))
            user = result.scalar()

            if not user:  # User is not a registered student
                result = db.session.execute(db.select(Signee).where(Signee.email == data.get("email")))
                user = result.scalar()
                if user and check_password_hash(user.password, data.get("password")):  # User is not a signee either
                    token = generate_token(user.id, "signee")
                    return jsonify({
                        "title": user.title,
                        "firstname": user.first_name,
                        "lastname": user.last_name,
                        "email": user.email,
                        "gender": user.gender,
                        "user_status": "signee",
                        "dob": user.birth_date,
                        "phone_no": user.phone_number,
                        "email_verified": user.email_confirmed,
                        "bearer_token": token,
                        "address": "",
                        "reg_no": "",
                        "acca_reg": ""
                    })
                else:
                    return jsonify(
                        error={
                            "Incorrect Input": f"Email or password incorrect"  # \n type:{type(g)}. it is {g}",
                        }
                    ), 403
            else:
                password = data.get("password")
                currently_enrolled = [
                    (paper, entry.diet)
                    for entry in user.enrollments
                    for paper in entry.papers
                    if entry.diet.completion_date > datetime.now(timezone.utc)
                ]
                if check_password_hash(user.password, password):
                    token = generate_token(user.id, "student")
                    user.last_active = datetime.now(timezone.utc)
                    db.session.commit()
                    return jsonify({
                        "title": user.title,
                        "firstname": user.first_name,
                        "lastname": user.last_name,
                        "email": user.email,
                        "gender": user.gender,
                        "dob": user.birth_date,
                        "phone_no": user.phone_number,
                        "email_verified": True, # temporarily
                        "address": user.house_address,
                        "reg_no": user.reg_no,
                        "acca_reg": user.acca_reg_no,
                        "papers": [{paper[0].code: (paper[0].name, paper[1].name)} for paper in currently_enrolled],
                        "profile_pic": user.profile_photo, #base64.b64encode(user.profile_photo).decode('utf-8'),
                        "blocked": not user.access,
                        "user_status": "student",
                        "bearer_token": token,
                    })
                else:
                    password_incorrect = True
            if password_incorrect:
                # print(data.get("password"))
                return jsonify(
                    error={
                        "Incorrect Input": f"Email or Password incorrect"  # \n type:{type(g)}. it is {g}",
                    }
                ), 403

        elif login_type == "reg":
            result = db.session.execute(db.select(Student).where(Student.reg_no == data.get("reg_no")))
            user = result.scalar()

            if not user:  # User is not a registered student
                return jsonify(
                    error={
                        "Incorrect Input": f"Registration number or password incorrect"
                        # \n type:{type(g)}. it is {g}",
                    }
                ), 403

            password = data.get("password")
            currently_enrolled = [
                (paper, entry.diet)
                for entry in user.enrollments
                for paper in entry.papers
                if entry.diet.completion_date > datetime.now(timezone.utc)
            ]
            if check_password_hash(user.password, password):
                    token = generate_token(user.id, "student")
                    user.last_active = datetime.now(timezone.utc)
                    db.session.commit()
                    return jsonify({
                        "title": user.title,
                        "firstname": user.first_name,
                        "lastname": user.last_name,
                        "email": user.email,
                        "gender": user.gender,
                        "dob": user.birth_date,
                        "phone_no": user.phone_number,
                        "email_verified": True, # temporarily
                        "address": user.house_address,
                        "reg_no": user.reg_no,
                        "acca_reg": user.acca_reg_no,
                        "papers": [{paper[0].code: (paper[0].name, paper[1].name)} for paper in currently_enrolled],
                        "profile_pic": user.profile_photo, #base64.b64encode(user.profile_photo).decode('utf-8'),
                        "blocked": not user.access,
                        "user_status": "student",
                        "bearer_token": token,
                    })
            else:
                return jsonify(
                    error={
                        "Incorrect Input": f"Registration number or Password incorrect"
                        # \n type:{type(g)}. it is {g}",
                    }
                ), 403
        else:
            return jsonify(
                error={
                    "Unknown Login Type": f"Log-in type {login_type} is not accepted",
                }
            ), 409


    @app.route("/api/v1/refresh", methods=["GET"])
    @auth_required
    def send_data():
        # Remember to add one for staff.
        output = db.session.execute(db.select(Student).where(Student.email == request.args.get("email")))
        person = output.scalar()
        if not person:
            output = db.session.execute(db.select(Staff).where(Staff.email == request.args.get("email")))
            person = output.scalar()
            if person:
                person.last_active = datetime.now(timezone.utc)
                db.session.commit()
                return jsonify({
                    "title": person.title,
                    "firstname": person.first_name,
                    "lastname": person.last_name,
                    "email": person.email,
                    "gender": person.gender,
                    "dob": person.birth_date,
                    "profile_pic": person.photo, #base64.b64encode(person.profile_photo).decode('utf-8'),
                    "phone_no": person.phone_number,
                    "email_verified": True,  # temporarily
                    "address": person.house_address,
                    "staff_code": person.code,
                    "user_status": "staff",
                    "role": person.role,
                })

        if not person:  # User is not a registered student
            output = db.session.execute(db.select(Signee).where(Signee.email == request.args.get("email")))
            person = output.scalar()
            if not person:  # User is not a signee either
                return jsonify(
                    error={
                        "Incorrect Input": "Account does not exist"
                        # f"Email or password incorrect"  # \n type:{type(g)}. it is {g}",
                    }
                ), 403
            return jsonify({
                "title": person.title,
                "firstname": person.first_name,
                "lastname": person.last_name,
                "email": person.email,
                "gender": person.gender,
                "user_status": "signee",
                "dob": person.birth_date,
                "phone_no": person.phone_number,
                "email_verified": person.email_confirmed,
                "address": "",
                "reg_no": "",
                "acca_reg": ""
                })
        # currently_enrolled = [paper for entry in person.enrollments if entry.diet.completion_date > datetime.now(timezone.utc) for paper in entry.papers]
        # print("enrororo", person.enrollments)
        currently_enrolled = [
            (paper, entry.diet)
            for entry in person.enrollments
            for paper in entry.papers
            if entry.diet.completion_date > datetime.now(timezone.utc)
        ]
        # print("enrororo", person.enrollments, currently_enrolled)
        # for entry in person.enrollments:
        #     print(entry.diet.completion_date, entry.diet.completion_date > datetime.now(timezone.utc))
        person.last_active = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({
            "title": person.title,
            "firstname": person.first_name,
            "lastname": person.last_name,
            "email": person.email,
            "gender": person.gender,
            "dob": person.birth_date,
            "profile_pic": person.profile_photo, #base64.b64encode(person.profile_photo).decode('utf-8'),
            "phone_no": person.phone_number,
            "email_verified": True,  # temporarily
            "address": person.house_address,
            "reg_no": person.reg_no,
            "acca_reg": person.acca_reg_no,
            "papers": [{paper[0].code: (paper[0].name, paper[1].name)} for paper in currently_enrolled],
            "blocked": not person.access,
            "user_status": "student",
        })

    @app.route("/api/v1/register", methods=["POST"])
    @auth_required
    @role_required("student")
    def register(user_id):
        data = request.get_json()
        print("Amount received:", data.get("amount"))
        keys = ["email", "firstname", "lastname", "sponsored", "user_status", "user_data"] #reg_no
        keys += ["amount", "phone"] if not data.get("sponsored") else []
        nested = {
            "user_data": []
        }
        nested["user_data"] += ["employed", "acca_reg", "address", "referral_source", "oxford", "accuracy", "alp_consent", "terms"] if data.get("user_status") == "signee" else []
        nested["user_data"] += ["papers", "discount", "discount_papers", "diet_name"] if not data.get("sponsored") else []
        valid, error_info, res_code = check_api(data=data, required_fields=keys, nested_fields=nested)
        # print(error_info)
        if not valid:
            return jsonify(
                error={
                    error_info[0]: error_info[1]
                }
            ), res_code
        # Each diet has its own tables that would be named as such, the table to open will be determined by the diet
        # This is for future updates purposes
        # print("tiypiee:", type(data.get("diet")))
        user_type = data.get("user_status", "None")
        if user_type.lower() != "signee" and user_type.lower() != "student":
            return jsonify(
                error={
                    "Unknown User Type": f"User type {user_type} is not accepted"
                }
            ), 400
        if data.get("sponsored"):  # User is sponsored by an organization
            sponsorship = db.session.execute(db.select(Sponsored).where(Sponsored.token == data.get("token"))).scalar()
            if not sponsorship:
                return jsonify(
                    error={
                        "Invalid Token": f"The code is invalid, try again.", # code refers to token in db # {(data.get("token"), Sponsored.token)}",
                    }
                ), 409
            elif not (sponsorship.first_name.title() == data.get("firstname") and sponsorship.last_name.title() == data.get("lastname")):
                # hello = (sponsorship.first_name.title(), data.get("firstname"), sponsorship.last_name.title(), data.get("lastname"))
                return jsonify(
                    error={
                        "Name Mismatch": f"Your registered name contrasts with our records.", # {hello}.",
                    }
                ), 409
            elif sponsorship.used:
                return jsonify(
                    error={
                        "Expired Token": "The inputted code is used, try again.",
                    }
                ), 409
            sponsored_papers = db.session.execute(db.select(Paper).where(Paper.code.in_(sponsorship.papers))).scalars().all()

            if user_type.lower() == "signee":
                try:
                    if not data.get("user_data"):
                        return jsonify(
                            error={
                                "Error": f"Missing user data.",
                            }
                        ), 400
                    move_signee(data.get("user_data"), sponsored=True, paid=None, spons_details=sponsorship,
                                email=data.get("email"))
                    operation_details = f"User registered their first ever course, courses are sponsored, [{sponsorship.papers}]"
                    update_action(data.get("email"), "Became a student.", operation_details)
                    student = db.session.execute(db.select(Student).where(Student.email == data.get("email"))).scalar()
                    update_payment(sponsored=True,
                                   email=data.get("email"),
                                   spons_details=sponsorship,
                                   context=sponsorship.papers,
                                   purpose="Tuition",
                                   user_info=[student.first_name, student.last_name, student.phone_number,
                                              data.get("email"), student.reg_no],
                                   )
                except UserNotFoundError as e:
                    return jsonify(
                        error={
                            "In-Existent User": f"User not found [{e}].",
                        }
                    ), 409
                # else:
                #     return jsonify({
                #         "status": "success",
                #         "message": "Registration successful",
                #     }), 201
            elif user_type.lower() == "student":
                if not platform_access(user_id):
                    return jsonify({"Access Denied": "Student access has been restricted."})
                try:
                    student = db.session.execute(db.select(Student).where(Student.reg_no == data.get("reg_no"))).scalar()
                    stmt = (
                        db.select(Enrollment)
                        .join(Diet)  # Explicit join to the related Diet table
                        .where(Diet.name == sponsorship.diet_name)
                    )
                    enrollment = db.session.execute(stmt).scalar()
                    currently_enrolled = [paper for entry in student.enrollments if entry.diet.completion_date > datetime.now(timezone.utc) for paper in entry.papers]
                    for j in sponsorship.papers:
                        if j in [paper.code for paper in currently_enrolled]:
                            return  jsonify(
                                error={
                                    "User Error": f"You are already taking {j}, you can't take it twice concurrently. Contact Admin for support."
                                }
                            ), 404
                    if (len(sponsorship.papers) + len(currently_enrolled)) > 4:
                        return jsonify(
                            error={
                                "Error": "User cannot register more than four papers in a diet.",
                            }
                        ), 409
                    enrollment.sponsored = True
                    enrollment.sponsors = sponsorship.company
                    enrollment.sponsored_papers = ",".join([sponsored_paper.split("-")[0] for sponsored_paper in sponsorship.papers])
                    enrollment.employment_status = "Fully/Self employed"
                    enrollment.papers.extend(sponsored_papers)  # Relevant ones in the absence of sponsors
                    enrollment.total_fee += sum([sponsored_paper.price for sponsored_paper in sponsored_papers])  # Relevant ones in the absence of sponsors
                    enrollment.amount_paid += sum(
                        [sponsored_paper.price for sponsored_paper in sponsored_papers])  # Relevant ones in the absence of sponsors
                    sponsorship.used = True
                    db.session.commit()
                    operation_details = f"User registered a new course, they were a student already, courses are sponsored, [{sponsorship.papers}]"
                    update_payment(sponsored=True,
                                   email=data.get("email"),
                                   spons_details=sponsorship,
                                   context=sponsorship.papers,
                                   purpose="Tuition",
                                   user_info=[student.first_name, student.last_name, student.phone_number,
                                              data.get("email"), student.reg_no],
                                   )
                    update_action(data.get("email"), "Registered a course.", operation_details)
                    student.last_active = datetime.now(timezone.utc)
                    db.session.commit()
                except Exception as e:
                    print(e)
                    return jsonify(
                        error={
                            "Unknown Error": f"Error message: [{e}].",
                        }
                    ), 409
                # else:
            elif user_type == "old student":
                pass


            fresh_student = db.session.execute(db.select(Student).where(Student.email == data.get("email"))).scalar()
            # Get current taken scholarships and papers
            currently_enrolled = [paper for entry in fresh_student.enrollments if entry.diet.completion_date > datetime.now(timezone.utc) for paper in entry.papers]
            scholarships = [p.discount_papers for p in fresh_student.enrollments if not p.discount > 0 and p.diet.completion_date > datetime.now(timezone.utc)]
            if fresh_student and user_type != "old student":
                return jsonify({
                    "status": "success",
                    "message": "Registration successful",
                    "user_status": "student",
                    "reg_no": fresh_student.reg_no,
                    "acca_reg_no": fresh_student.acca_reg_no,
                    "papers": [{paper.code: paper.name} for paper in currently_enrolled],
                    "fee": 0,
                    "scholarship": scholarships
                }), 201
            else:
                return jsonify(
                    error={
                        "Intense Confusion": f"😕 | 😵 | 💫 | 🤔 |  😶☁.",
                    }
                ), 409
        else:  # User is sponsoring themselves
            if data.get("user_status").lower() == "student":
                done_list = []
                student = db.session.execute(db.select(Student).where(Student.email == data.get("email"))).scalar()
                currently_enrolled = [paper for entry in student.enrollments if entry.diet.completion_date > datetime.now(timezone.utc) for paper in entry.papers]
                for i in data.get("user_data")["papers"]:
                    if i in [paper.code for paper in currently_enrolled]:
                        done_list.append(i)
                if done_list:
                    return jsonify(
                        error={
                        "Error": "User cannot register a paper they are already taking."
                    }
                    ), 403
                if len(data.get("user_data")["papers"])+ len(currently_enrolled) > 4:
                    return jsonify(
                        error={
                            "Error": "User cannot register more than four papers in a diet."
                        }
                    ), 409

            return initialize_payment(data, "Tuition REG")


    @app.route("/api/v1/required-info", methods=["GET"])
    @auth_required
    def needed_info():
        data_name = request.args.get("title")
        data = db.session.execute(db.select(SystemData).where(SystemData.data_name == data_name)).scalar()
        if data:
            return jsonify(data.data), 200
        else:
            return jsonify(
                error={
                    "Inexistent Data": f"The requested data {data_name} does not exist."
                }
            ), 400

    @app.route("/api/v1/courses", methods=["GET"])
    @auth_required
    def get_courses():
        # Implement accounting for diet
        try:
            user_type = request.args.get("user_status").lower()
            if user_type.lower() not in ["signee", "student", "staff"]:
                return jsonify(
                    error={
                        "Unknown User Type": f"User type {user_type} is not accepted"
                    }
                ), 400
        except AttributeError as e:
            return jsonify(
                error={
                    "Missing Data": "User status not found!!"
                }
            ), 400
        details = {}
        if request.args.get("reg", "").lower() in ["true", 1, "t", "y", "yes", "yeah"]:
            scholarships = db.session.execute(db.select(Scholarship).where(Scholarship.email == request.args.get("email"))).scalars().all()
            details["scholarships"] = [{"paper": i.paper[:-4], "percentage": i.discount} for i in scholarships]
            details["fee"] = [{"amount":5000, "reason": "One time student registration."}] if user_type == "signee" else []
            acca_reg_no = request.args.get("acca_reg")
            if user_type ==  "signee":
                signee = db.session.execute(db.select(Signee).where(Signee.email == request.args.get("email"))).scalar()
                if db.session.execute(db.select(Student).where(Student.acca_reg_no == acca_reg_no)).scalar() and acca_reg_no != "001" and acca_reg_no:
                    return jsonify(
                        error={
                            "Tautology": f"ACCA registration number already used."
                        }
                    ), 400
                elif (len(acca_reg_no) < 7 or len(acca_reg_no) > 7) and acca_reg_no != "001":
                    return jsonify(
                        error={
                            "Invalid Error": f"ACCA registration number invalid."
                        }
                    ), 400
                elif not signee:
                    print(request.args)
                    return jsonify(
                        error={
                            "Error": f"User doesn't exist."
                        }
                    ), 400
                details["course_limit"] = 4
                details["partial_payment"] = signee.can_pay_partially
            elif user_type == "student":
                student = db.session.execute(db.select(Student).where(Student.email == request.args.get("email"))).scalar()
                if not student:
                    return jsonify(
                        error={
                            "Some Kinda Error": "Student not found!!"
                        }
                    ), 400
                currently_enrolled = [paper for entry in student.enrollments if entry.diet.completion_date > datetime.now(timezone.utc) for paper in entry.papers]
                money_owed = sum([entry.receivable for entry in student.enrollments if entry.receivable > 0])
                details["current_papers"] = [paper.code for paper in currently_enrolled]
                details["course_limit"] = 4 - len(currently_enrolled)
                if money_owed > 0:
                        details["fee"].append({"amount": money_owed, "reason": "Dey owe."})
                details["partial_payment"] = student.can_pay_partially
            #if student is scholarship qualified
            try:
                # exam_month = request.args.get("diet_name", "None").split("_")
                # if exam_month in ["March", "September"]:
                #     type_ = "Intensive"
                # else:
                #     type_ = "Standard"
                diet = db.session.execute(db.select(Diet).where(Diet.name == request.args.get("diet_name", "None"))).scalar()
                papers = db.session.execute(db.select(Paper).where(Paper.code.in_(diet.available_papers))).scalars().all()
                # papers = db.session.query(Paper).where(Paper.name.ilike(f"%{type_}%")).all()
                # papers.extend(db.session.query(Paper).where(Paper.price > 69_000).all())
                print(papers)
                paper_details = []
                taken_papers = []
                for i in papers:
                    if not i.available:
                        continue
                    # paper_name = " ".join(i.name.split()[:-1]) if "Standard" in i.name or "Intensive"in i.name else i.name
                    # if paper_name in taken_papers:
                    #     continue
                    # taken_papers.append(paper_name)
                    # if paper_name == i.name:
                    #     # paper_types = []
                    #     prices = [i.price]
                    #     paper_codes = [i.code]
                    # else:
                    #     # paper_types = [item.name.split()[-1] for item in papers if paper_name in item.name and len(item.name.split()) == len(paper_name.split())+1]
                    #     paper_codes = [item.code for item in papers if paper_name in item.name and len(item.name.split()) == len(paper_name.split())+1]
                    #     prices = [item.price for item in papers if paper_name in item.name and len(item.name.split()) == len(paper_name.split())+1]
                    paper_details.append(
                        {
                            "name": i.name,
                            # "name": paper_name,
                            "category": i.category,
                            "type": ["Standard"],
                            # "type": paper_types,
                            # "code": paper_codes,
                            "code": [i.code],
                            "price": [i.price], #Sent as list because they might want to go back to the old diet style
                            # "price": prices,
                        }
                    )
                details["papers"] = paper_details
            except AttributeError as e:
                return jsonify(
                    error={
                        "Error": f"Selected Diet does not exist.",
                    }
                ), 400
            except Exception as e:
                return jsonify(
                    error={
                        "Internal Error": f"Error message: [{e}]",
                    }
                ), 500
            else:
                return jsonify(details), 200
        else:
            all_papers = db.session.execute(db.select(Paper)).scalars().all()
            paper_details = []
            for pp in all_papers:
                paper_details.append(
                    {
                        "name": pp.name,
                        "category": pp.category,
                        "code": pp.code,
                        "price": pp.price
                    }
                )
            return jsonify(paper_details), 200


    @app.route("/api/v1/diets", methods=["GET"])
    @auth_required
    def get_diet():
        available_diets = db.session.execute(db.select(Diet).where(Diet.reg_deadline>datetime.now(timezone.utc))).scalars().all()
        # available_diets = db.session.execute(db.select(Diet).where(datetime.now(timezone.utc) < Diet.reg_deadline)).all()
        diets_data = [{"title": diet.title,
                       "diet_name": diet.name,
                       "available": True if datetime.now(timezone.utc) > diet.reg_start else False,
                       "description": diet.description,
                       "papers": diet.available_papers if request.args.get("user_status", "").lower() == "staff" else ["Forbidden"],
                       "reg_starts": diet.reg_start,
                       "reg_ends": diet.reg_deadline,
                       "revision_starts": diet.revision_start,
                       "revision_deadline": diet.revision_deadline,
                       "diet_ends": diet.completion_date} for diet in available_diets]
        return jsonify(diets_data), 200


    @app.route("/api/v1/confirm-email", methods=["POST"])
    # @auth_required
    def confirm_email():
        # if request.args.get("api-key") != api_key:
        #     return jsonify(
        #         error={
        #             "Access Denied": f"You do not have access to this resource",
        #         }
        #     ), 403
        data = request.get_json()
        token = data.get("token") # New and untested
        # token = request.args.get("token") # New and untested
        if token is None:
            print("TOken is none and confirm email has been called. #Debug")
            # data = request.get_json()
            user = db.session.execute(db.select(Signee).where(Signee.email == data.get("email"))).scalar()
            if not user:
                print("No User found. #Debug")
                return jsonify(error={"In-Existent User": "Email doesn't exist"}), 400
            print("User found and email is a to be drafted. #Debug")
            send_signup_message("User", data.get("email"))
            return jsonify({"message": "Check your email to confirm your account."}), 200
        else:
            res = verify_email(token)
            if res[0] == "success":
                user = db.session.execute(db.select(Signee).where(Signee.email == res[1])).scalar()
                user.email_confirmed = True
                db.session.commit()
                return jsonify({
                    "status": "success",
                    "message": "Email verified successfully!"
                }), 200
            else:
                return jsonify(
                    error={
                    "Verification Failed": f"Email unverified, token is {res[0]}!"
                }
                ), 400

    @app.route("/api/v1/reset-password", methods=["POST"])
    @auth_required
    def reset_password():
        # if request.args.get("api-key") != api_key:
        #     return jsonify(
        #         error={
        #             "Access Denied": f"You do not have access to this resource",
        #         }
        #     ), 403
        token = request.args.get("token")
        data = request.get_json()
        if token:
            ver_pword = is_valid_password(data.get("password"))
            if not ver_pword[0]:
                return jsonify(
                    error={
                        "Invalid Password": f"Error cause: [{ver_pword[1]}]",
                    }
                ), 400
            res = verify_email(token)
            if res[0] == "success":
                user = db.session.execute(db.select(Signee).where(Signee.email == res[1])).scalar()
                user = db.session.execute(db.select(Student).where(Student.email == res[1])).scalar() if not user else user
                hash_and_salted_password = generate_password_hash(
                    data.get("password"),
                    method='pbkdf2:sha256',
                    salt_length=8
                )
                user.password = hash_and_salted_password
                user.last_active = datetime.now(timezone.utc)
                db.session.commit()
                return jsonify({
                    "status": "success",
                    "message": "Password updated successfully!"
                }), 200
            else:
                return jsonify(
                    error={
                    "Update Failed": f"Password not updated, token is {res[0]}!"
                }
                ), 400
        else:
            user = db.session.execute(db.select(Signee).where(Signee.email == data.get("email"))).scalar()
            user = db.session.execute(db.select(Student).where(Student.email == data.get("email"))).scalar() if not user else user
            if not user:
                return jsonify(error={"In-Existent User": "Email doesn't exist"}), 400
            send_password_reset_message("there", data.get("email"))
            return jsonify({"message": "Check your email to change your account password."}), 200


    @app.route("/api/v1/temp", methods=["GET"])
    @auth_required
    def gy():
        s = request.args.get("api-key").lower() == "true"
        print(type(s), s)
        return jsonify({"res": s})

    @app.route("/api/v1/receipt", methods=["GET"])
    @auth_required
    def get_receipt():
        print("in get receipt")
        receipt_no = request.args.get("receipt_no")
        payment = db.session.execute(db.select(Payment).where(Payment.receipt_number == receipt_no)).first()
        if not payment:
            print("receipt not found", receipt_no)
            return jsonify(
                error={
                    "MissingData Error": f"Receipt file not found."
                }
            ), 404
        return send_file(
            BytesIO(payment.receipt),
            mimetype='application/pdf',
            download_name=f"receipt_{payment.receipt_number}.pdf"
        )


    @app.route("/api/v1/all-payments", methods=["GET"])
    @auth_required
    def all_payments():
        reg_no = request.args.get("reg_no")
        if not reg_no:
            print("no reg no")
            return jsonify(
                error={
                    "Missing Argument": f"No registration number found."
                }
            ), 404
        payments = db.session.execute(db.select(Payment).where(Payment.student_reg == reg_no)).scalars().all()
        if not payments:
            print(reg_no)
            return jsonify(
                error={
                    "In-Existent Data": f"No payment history found for this user."
                }
            ), 404
        response = []
        for payment in payments:
            response.append({
                "papers": payment.context,
                "ref_id": payment.payment_reference,
                "amount": payment.amount,
                "date": payment.paid_at
            })
        return jsonify(response), 200

    @app.route("/api/v1/receipts", methods=["GET"])
    @auth_required
    def all_receipts():
        reg_no = request.args.get("reg_no")
        payments = db.session.execute(db.select(Payment).where(Payment.student_reg == reg_no)).scalars().all()
        response = []
        for payment in payments:
            response.append({
                "receipt_no": payment.receipt_number,
                "papers": payment.context,
                "amount": payment.amount,
                "date": payment.paid_at #Change after editing db
            })
        return response, 200

    #----------------------- Admin Endpoints --------------------------------#
    @app.route("/api/v1/list-students", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def list_students(user_id):
        criteria = request.args.get("criteria")
        key = request.args.get("key", "")
        student_details = []
        if criteria == "all":
            all_students = db.session.execute(db.select(Student)).scalars().all()
            for student in all_students:
                student_details.append(
                    {
                        "title": student.title,
                        "firstname": student.first_name,
                        "lastname": student.last_name,
                        "email": student.email,
                        "reg_no": student.reg_no,
                        "profile_pic": student.profile_photo, #base64.b64encode(student.user.profile_photo, #).decode('utf-8'),
                        "blocked": not student.access
                    }
                )
        elif criteria == "diet":
            diet = db.session.execute(db.select(Diet).where(Diet.name == key)).scalar()
            seen = []
            for enrollment in diet.enrollments:
                if enrollment.student.email not in seen:
                    student_details.append(
                        {
                            "title": enrollment.student.title,
                            "firstname": enrollment.student.first_name,
                            "lastname": enrollment.student.last_name,
                            "email": enrollment.student.email,
                            "reg_no": enrollment.student.reg_no,
                            "profile_pic": enrollment.stiudent.profile_photo, #base64.b64encode(enrollment.student.profile_photo).decode('utf-8'),
                            "blocked": not enrollment.student.access
                        }
                    )
                    seen.append(enrollment.student.email)
        elif criteria == "gender":
            some_students = db.session.execute(db.select(Student).where(Student.gender == key.lower())).scalars().all()
            for student in some_students:
                student_details.append(
                    {
                        "title": student.title,
                        "firstname": student.first_name,
                        "lastname": student.last_name,
                        "email": student.email,
                        "reg_no": student.reg_no,
                        "profile_pic": student.profile_photo, #base64.b64encode(student.profile_photo).decode('utf-8'),
                        "blocked": not student.access
                    }
                )
        elif criteria == "payment":
            all_students = db.session.execute(db.select(Student)).scalars().all()
            owing = False
            if key == "full":
                for student in all_students:
                    for enrollment in student.enrollments:
                        if enrollment.receivable > 0:
                            owing = True
                            break
                    if not owing:
                        student_details.append(
                            {
                                "title": student.title,
                                "firstname": student.first_name,
                                "lastname": student.last_name,
                                "email": student.email,
                                "reg_no": student.reg_no,
                                "profile_pic": student.profile_photo, #base64.b64encode(student.profile_photo).decode('utf-8'),
                        "blocked": not student.access
                            }
                        )
            elif key == "part":
                for student in all_students:
                    for enrollment in student.enrollments:
                        if enrollment.receivable > 0:
                            owing = True
                            break
                    if owing:
                        student_details.append(
                            {
                                "title": student.title,
                                "firstname": student.first_name,
                                "lastname": student.last_name,
                                "email": student.email,
                                "reg_no": student.reg_no,
                                "profile_pic": student.profile_photo, #base64.b64encode(student.profile_photo).decode('utf-8'),
                        "blocked": not student.access
                            }
                        )
        elif criteria == "sponsored":
            enrollments = db.session.execute(db.select(Enrollment).where(Enrollment.sponsored == True)).scalar()
            seen = []
            for enrollment in enrollments:
                if enrollment.student_reg_no not in seen and enrollment.diet.completion_date < datetime.now(timezone.utc):
                    student_details.append(
                        {
                            "title": enrollment.student.title,
                            "firstname": enrollment.student.first_name,
                            "lastname": enrollment.student.last_name,
                            "email": enrollment.student.email,
                            "reg_no": enrollment.student.reg_no,
                            "profile_pic": enrollment.student.profile_photo, #base64.b64encode(enrollment.student.profile_photo).decode('utf-8'),
                            "blocked": not enrollment.student.access
                        }
                    )
                    seen.append(enrollment.student.email)
        elif criteria == "signee":
            all_signees = db.session.execute(db.select(Signee)).scalars().all()
            for signee in all_signees:
                student_details.append(
                    {
                        "title": signee.title,
                        "firstname": signee.first_name,
                        "lastname": signee.last_name,
                        "email": signee.email,
                        "phone_number": signee.phone_number,
                    }
                )
        elif criteria == "acca_reg":
            students = db.session.execute(db.select(Student).where(db.func.length(Student.acca_reg_no) > 8)).scalars().all()
            for student in students:
                student_details.append(
                    {
                        "title": student.title,
                        "firstname": student.first_name,
                        "lastname": student.last_name,
                        "email": student.email,
                        "acca_reg_no": student.acca_reg_no,
                        "profile_pic": student.profile_photo, #base64.b64encode(student.profile_photo).decode('utf-8')
                        "blocked": not student.access
                    }
                )
        elif criteria == "paper":
            pass #T.B.Cz
        else:
            pass
        staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
        staff.last_active = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(student_details), 200


    @app.route("/api/v1/view-student", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def view_student(user_id):
        reg_no = request.args.get("reg_no")
        student = db.session.execute(db.select(Student).where(Student.reg_no == reg_no)).scalar()
        if student:
            currently_enrolled = [paper for entry in student.enrollments if entry.diet.completion_date > datetime.now(timezone.utc) for
                                  paper in entry.papers]
            res = {
                "title": student.title,
                "firstname": student.first_name,
                "lastname": student.last_name,
                "email": student.email,
                "reg_no": student.reg_no,
                "acca_reg": student.acca_reg_no,
                "phone_no": student.phone_number,
                "dob": student.birth_date,
                "profile_pic": student.profile_photo, #base64.b64encode(student.profile_photo).decode('utf-8'),
                "gender": student.gender,
                "address": student.house_address,
                "date_joined": student.joined,
                "partial_payment": student.can_pay_partially,
                "blocked": not student.access,
                # "owing":
                "papers": [{paper.code: paper.name} for paper in currently_enrolled],
                "terms": {"oxford": student.oxford_brookes}
            }
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(res), 200
        else:
            return  jsonify(
                {"Error": "Student not Found!"}
            ), 400


    @app.route("/api/v1/edit-student", methods=["PATCH"])
    @auth_required
    @role_required("pro_admin")
    def edit_student(user_id):
        reg_no = request.args.get("reg_no")
        criterias = request.args.get("changes")
        criterias = criterias.split()
        student = db.session.execute(db.select(Student).where(Student.reg_no == reg_no)).scalar()
        if student and criterias:
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            print(type(criterias), criterias)
            for item in criterias:
                if item.lower() == "name":
                    student.first_name = request.get_json().get("firstname", student.first_name)
                    student.last_name = request.get_json().get("lastname", student.last_name)
                    log_staff_activity(title="Student Details Edited.",
                                       desc="""The administrator updated the student’s full name in the system records 
                                       to reflect corrected or revised personal information.""",
                                       staff=staff,
                                       object_id=2,
                                       obj=f"Student: {student.reg_no}")
                elif item.lower() == "acca_reg":
                    student.acca_reg_no = request.get_json().get("acca_reg")
                    log_staff_activity(title="Student Details Edited.",
                                       desc="""The administrator modified the student's ACCA registration number.""",
                                       staff=staff,
                                       object_id=2,
                                       obj=f"Student: {student.reg_no}")
                elif item.lower() ==  "partial_payment":
                    if not isinstance(request.get_json().get("partial_payment"), bool):
                        return jsonify({"Error":"partial_payment must be a boolean"}), 400
                    student.can_pay_partially = request.get_json().get("partial_payment")
                    log_staff_activity(title="Student Details Edited.",
                                       desc="""The administrator changed the student’s settings related to partial 
                                       payment eligibility, either enabling or disabling the option based on updated
                                       policy or request.""",
                                       staff=staff,
                                       object_id=2,
                                       obj=f"Student: {student.reg_no}")
                staff.last_active = datetime.now(timezone.utc)
                db.session.commit()
            return jsonify({"Success": "Student edited successfuly"}), 200
        elif not criterias:
            return jsonify(
                {"Res": "No item was provided, so no changes were made.."}
            ), 200
        else:
            return jsonify(
                {"Error": "User not found."}
            ), 400


    @app.route("/api/v1/find-student", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def find_student(user_id):
        try:
            criteria = request.args.get("criteria", "").lower()
            substring = request.args.get("string", "").lower()
            student_details = []
            if criteria == "reg_no":
                students = db.session.execute(db.select(Student).where(Student.reg_no.ilike(f"%{substring}%"))).scalars().all()
            elif criteria == "name":
                full_name = db.func.concat(Student.first_name, db.literal(' '), Student.last_name)
                students = db.session.execute(db.select(Student).where(full_name.ilike(f"%{substring}%"))).scalars().all()
            else:
                return jsonify(
                    {"See you": f"This criteria is invalid!!"}
                ), 404
            for student in students:
                print(student)
                student_details.append(
                    {
                        "title": student.title,
                        "firstname": student.first_name,
                        "lastname": student.last_name,
                        "email": student.email,
                        "reg_no": student.reg_no,
                        "profile_pic": student.profile_photo,
                        "blocked": not student.access
                    }
                )
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            print(user_id)
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(student_details), 200
        except ZeroDivisionError as  e:
            return jsonify(
                {"Error": f"An error occured during operation {e}"}
            )


    @app.route("/api/v1/create-diet", methods=["POST"])
    @auth_required
    @role_required("pro_admin")
    def create_diet(user_id):
        request_data = request.get_json()
        try:
            # Ensure everything needed is sent
            name = request_data.get("exam_year") + "_" + request_data.get("exam_month")
            new_diet = Diet(
                name=name,
                title=request_data.get("title"),
                description=request_data.get("description"),
                available_papers=request_data.get("papers"),
                reg_start=request_data.get("reg_starts"),
                reg_deadline=request_data.get("reg_ends"),
                revision_start=request_data.get("revision_starts"),
                revision_deadline=request_data.get("revision_ends"),
                completion_date=request_data.get("diet_ends")
                # reg_start=dsnip andion_date=datetime.now(timezone.utc)
            )
            db.session.add(new_diet)

            # pps = db.session.execute(db.select(Paper).where(Paper.code.in_(request_data.get("papers")))).scalars().all()
            # all_templates = db.session.execute(db.select(DirectoryTemplate)).scalars().all()
            # new_instances = [] # New and untested
            # for paper in pps:
            #     for template in all_templates:
            #         instance_path = f"/{paper.code} {name}{template.path_template}"
            #         new_instance = DirectoryInstance(
            #             template_id=template.id,
            #             course_code=paper.code,
            #             course_spec=f"{paper.code} {name}",
            #             name=template.name,
            #             path=instance_path if not instance_path.endswith("/") else instance_path[:-1],
            #             parent_id=None,
            #             template=template,
            #         )
            #         db.session.add(new_instance)
            #         new_instances.append(new_instance) # New and untested
            # # new_instances = db.session.execute(
            # #     db.select(DirectoryInstance).where(DirectoryInstance.course_spec.ilike(f"%{name}%"))).scalars().all()
            # # db.session.commit()
            # for instance in new_instances:
            #     if not instance.parent_id:
            #         parent_path = "/".join(instance.path.split("/")[:-1])
            #         if parent_path == "":
            #             continue
            #         print(f"Parent path is {parent_path} fromm {instance.path}")
            #         parent = db.session.execute(
            #             db.select(DirectoryInstance).where(DirectoryInstance.path == parent_path)).scalar_one_or_none()
            #         instance.parent_id = parent.id
            #         instance.parent = parent
            # db.session.commit()
            pps = db.session.scalars(
                db.select(Paper).where(Paper.code.in_(request_data.get("papers")))
            ).all()

            templates = db.session.scalars(
                db.select(DirectoryTemplate).where(DirectoryTemplate.title == request_data.get("diet_template"))
            ).all()
            if not templates:
                return jsonify(
                    error={
                        "Operation Failure": f"Template doesn't exist."
                    }
                 ), 400

            instances = []
            path_map = {}

            for paper in pps:
                course_spec = f"{paper.code} {name}"
                for template in templates:
                    if template.title in template.path_template:
                        path = template.path_template.replace(f"${template.title}$", course_spec)
                    else:
                        path = f"/{course_spec}{template.path_template}".rstrip("/").replace("$course$", paper.code)

                    inst = DirectoryInstance(
                        template_id=template.id,
                        course_code=paper.code,
                        course_spec=course_spec,
                        name=template.name.replace(f"${template.title}$", ""),
                        path=path,
                        parent_id=None,
                        template=template,
                    )

                    instances.append(inst)
                    path_map[path] = inst

            # Resolve parents WITHOUT querying DB
            for path, inst in path_map.items():
                parent_path = "/".join(path.split("/")[:-1])
                if parent_path and parent_path in path_map:
                    inst.parent = path_map[parent_path]

            # Bulk insert (fast!)
            db.session.add_all(instances)
            # db.session.commit()
            db.session.flush()  # IDs now exist

            for path, inst in path_map.items():
                parent_path = "/".join(path.split("/")[:-1])
                if parent_path in path_map:
                    inst.parent_id = path_map[parent_path].id
                    print(path_map[parent_path].id)
            db.session.commit()
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Creation of a new Diet",
                               desc="""A new academic term was created and configured by specifying its name, dates,
                                and other essential details. This serves as the foundation for all academic activities
                                 during the selected period.""",#"""A new academic term was created and configured by specifying its name, dates,
                                #and other essential details..""",
                               staff=staff,
                               object_id=1,
                               obj=f"Diet {new_diet.name}")
        except IntegrityError:
            y, m = request_data.get("exam_year"), request_data.get("exam_month")
            return jsonify(
                error={
                    "Operation Failure": f"Failed to create diet, error:  a diet for {m} of {y} exists already."
                }
            ), 400
        except Exception as e:
            return jsonify(
                error={
                    "Operation Failure": f"Failed to create diet, error: {e}."
                }
            ), 400
        else:
            # with app.app_context():
            #     db.session.commit() # Already commited in log_staff_activity
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"{request_data.get("title")} has been created successfully."
                }
            ), 200


    @app.route("/api/v1/all-diets", methods=["GET"])
    @auth_required
    def get_all_diet():
        # available_diets = db.session.execute(db.select(Diet)).scalars().all()
        available_diets = db.session.execute(db.select(Diet).where(datetime.now(timezone.utc) < Diet.completion_date)).scalars().all()
        diets_data = [{"title": diet.title,
                       "diet_name": diet.name,
                       "available": True if datetime.now(timezone.utc) > diet.reg_start else False,
                       "description": diet.description,
                       "papers": diet.available_papers if request.args.get("user_status", "").lower() == "staff" else ["Forbidden"],
                       "diet_template": diet.template,
                       "reg_starts": diet.reg_start,
                       "reg_ends": diet.reg_deadline,
                       "revision_starts": diet.revision_start,
                       "revision_deadline": diet.revision_deadline,
                       "diet_ends": diet.completion_date} for diet in available_diets]
        return jsonify(diets_data), 200


    @app.route("/api/v1/edit-diet", methods=["PUT"])
    @auth_required
    @role_required("pro_admin")
    def edit_diets(user_id):
        try:
            request_data = request.get_json()
            # if request_data.get("purpose").lower() == "show":
            #     diets = db.session.execute(Diet).where(Diet.)
            diet = db.session.execute(db.select(Diet).where(Diet.name == request_data.get("diet_name"))).scalar()

            diet.title = request_data.get("title")
            diet.available_papers = request_data.get("papers")
            diet.reg_start=request_data.get("reg_starts") # Consider implementing mechanism to ensure certain dates aren't editable after a while.
            diet.reg_deadline=request_data.get("reg_ends")
            diet.revision_start=request_data.get("revision_starts")
            diet.revision_deadline=request_data.get("revision_ends")
            diet.completion_date=request_data.get("diet_ends")
            diet.edited_at=datetime.now(timezone.utc)

            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Diet Details Edited.",
                               desc="""The details of an existing academic diet was modified, including updates to key attributes such as name, registration dates, revision period, or completion date.""",
                               staff=staff,
                               object_id=2,
                               obj=f"Diet: {diet.name}")
            # db.session.commit() # Already commited in log_staff_activity
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"Details of {diet.title} has been edited successfully."
                }
            ), 200
        except Exception as e:
            return jsonify(
                error={
                    "Operation Failure": f"Failed to edit diet, error: {e}."
                }
            ), 400


    @app.route("/api/v1/create-paper", methods=["POST"])
    @auth_required
    @role_required("pro_admin")
    def create_paper(user_id):
        """
            Get a single user by ID (https://documenter.getpostman.com/view/33001364/2sB3dHUsc5)
            ---
            tags:
              - Users
            summary: Retrieve user information
            description: Retrieve detailed information about a user by their unique ID.
            parameters:
              - name: user_id
                in: path
                type: integer
                required: true
                description: The unique ID of the user
              - name: verbose
                in: query
                type: boolean
                required: false
                description: Whether to include extended information
            responses:
              200:
                description: Successful response with user details
                schema:
                  type: object
                  properties:
                    id:
                      type: integer
                      example: 123
                    name:
                      type: string
                      example: John Doe
                    email:
                      type: string
                      example: john@example.com
                    created_at:
                      type: string
                      format: date-time
                      example: "2025-11-21T15:30:00Z"
              404:
                description: User not found
              400:
                description: Invalid request
            """
        try:
            request_data = request.get_json()
            new_paper = Paper(
                name=request_data.get("name").title(),
                code=request_data.get("code").upper(),
                description=request_data.get("desc"),
                price=request_data.get("price"),
                revision=request_data.get("revision"),
                category=request_data.get("category").title(),
            )
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Created New Paper.",
                               desc="""A new paper has been created, paper code, price and revision price has been set.""",
                               staff=staff,
                               object_id=2,
                               obj=f"Paper: {request_data.get("name")}")
            staff.last_active = datetime.now(timezone.utc)
            with app.app_context():
                db.session.add(new_paper)
                db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"{request_data.get("name")} has been created successfully."
                }
            ), 200
        except IntegrityError:
            return jsonify(
                error={
                    "Operation Failure": "Failed to create paper, error:  paper name or code already exists."
                }
            ), 400
        except Exception as e:
            return jsonify(
                error={
                    "Operation Failure": f"Failed to create paper, error: {e}."
                }
            ), 400


    @app.route("/api/v1/all-papers", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def get_all_paper(user_id):
        available_papers = db.session.execute(db.select(Paper).order_by(Paper.id.asc())).scalars().all()
        # available_diets = db.session.execute(db.select(Diet).where(datetime.now(timezone.utc) < Diet.reg_deadline)).all()
        papers_data = [{"name": paper.name,
                       "code": paper.code,
                       "description": paper.description,
                       "price": paper.price,
                       "category": paper.category,
                       "availability": paper.available,} for paper in available_papers]
        return jsonify(papers_data), 200


    @app.route("/api/v1/view-paper", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def view_paper(user_id):
        paper = db.session.execute(db.select(Paper).where(Paper.code == request.args.get("paper_code"))).scalar()
        if not paper:
            return jsonify({"Error": "Paper not found"}), 400
        paper_details = {"name": paper.name,
                        "code": paper.code,
                        "description": paper.description,
                        "price": paper.price,
                        "revision": paper.revision,
                        "category": paper.category,
                        "availability": paper.available,
                        "edit_code": False} # Set this in a db table later e.g SystemData
        return jsonify(paper_details), 200

    @app.route("/api/v1/edit-paper", methods=["PATCH"])
    @auth_required
    @role_required("pro_admin")
    def edit_papers(user_id):
        try:
            request_data = request.get_json()
            paper = db.session.execute(db.select(Paper).where(Paper.code == request_data.get("real_code").upper())).scalar()
            paper.name = request_data.get("name", paper.name).title()
            # paper.code = request_data.get("code", paper.code).upper()
            paper.description = request_data.get("desc", paper.description)
            paper.price = request_data.get("price", paper.price)
            paper.revision = request_data.get("revision", paper.revision)
            paper.category = request_data.get("category", paper.category).title()
            paper.available = request_data.get("available", paper.available)
            paper.edited_at = datetime.now(timezone.utc)

            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Paper Details Edited.",
                               desc="""The details of an existing paper was modified, including updates to key
                                            attributes such as paper code, revision prices, revision period, or completion date.""",
                               staff=staff,
                               object_id=2,
                               obj=f"Paper: {request_data.get("name", paper.name)}")
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"Details of {paper.name} has been edited successfully."
                }
            ), 200
        except Exception as e:
            return jsonify(
                error={
                    "Operation Failure": f"Failed to edit paper, error: {e}."
                }
            ), 400


    @app.route("/api/v1/award-scholarship", methods=["POST"])
    @auth_required
    @role_required("super_admin")
    def award_scholarship(user_id):
        try:
            request_data = request.get_json()
            email = request_data.get("email", "")
            student = db.session.execute(db.select(Student).where(Student.email == email)).scalar()
            if not student:
                signee = db.session.execute(db.select(Signee).where(Signee.email == email)).scalar()
                if not signee:
                    return jsonify(
                        {"Error": "Benefactor not found."}
                    ), 404
            user = student if student else signee
            for scholarship in request_data.get("scholarships", []):
                if not isinstance(scholarship.get("discount"), int) or scholarship.get("discount") > 100:
                    return jsonify({"Error": "Invalid scholarship discount"}), 400
                new_scholarship = Scholarship(
                    email=user.email,
                    paper=scholarship.get("paper"),
                    discount=scholarship.get("discount"),
                    user_type="student" if student else "signee",
                    diet_name=scholarship.get("diet_name")
                )
                db.session.add(new_scholarship)
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Scholarship Awarded.",
                               desc="""A scholarship has been freshly awarded to a student.""",
                               staff=staff,
                               object_id=2,
                               obj=f"Benefactor: {email}")
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"A new scholarship has been created successfully."
                }
            ), 200
        except Exception as e:
            return  jsonify(
                {"Error": f"Error while awarding scholarship: {e}"}
            )


    @app.route("/api/v1/scholarships", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def scholarships(user_id):
        scholarships = db.session.execute(db.select(Scholarship).order_by(Scholarship.email.asc())).scalars().all()
        scholarship_data = [{"id": scholarship.id,
                             "email": scholarship.email,
                             "paper": scholarship.paper,
                             "discount": scholarship.discount,
                             "used": scholarship.used,
                             "diet_name": scholarship.diet_name,
                             "created_at": scholarship.created_at} for scholarship in scholarships]
        return jsonify(scholarship_data), 200


    @app.route("/api/v1/edit-scholarship", methods=["PATCH"])
    @auth_required
    @role_required("pro_admin")
    def edit_scholarship(user_id):
        try:
            request_data = request.get_json()
            scholarship = db.session.execute(db.select(Scholarship).where(Scholarship.id == request_data.get("id"))).scalar()
            scholarship.paper = request_data.get("paper", scholarship.paper)
            scholarship.discount = request_data.get("discount", scholarship.discount)
            scholarship.diet_name = request_data.get("diet_name", scholarship.diet_name)
            scholarship.edited_at = datetime.now(timezone.utc)

            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Scholarship Details Edited.",
                               desc="""The details of an existing scholarship was modified, including updates to key
                                            attributes such as paper code, discount percentage and diet name.""",
                               staff=staff,
                               object_id=2,
                               obj=f"Scholarship: {request_data.get("id", scholarship.id)}")
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"Details of scholarship {scholarship.id} has been edited successfully."
                }
            ), 200
        except Exception as e:
            return jsonify(
                error={
                    "Operation Failure": f"Failed to edit paper, error: {e}."
                }
            ), 400


    @app.route("/api/v1/create-sponsorship", methods=["POST"])
    @auth_required
    @role_required("pro_admin")
    def create_sponsorship(user_id):
        try:
            request_data = request.get_json()
            code = request_data.get("company_name")[:4].upper() + uuid.uuid4().hex[:5]
            new_sponsored = Sponsored(
                first_name=request_data.get("first_name"),
                last_name=request_data.get("last_name"),
                company=request_data.get("company_name").title(),
                papers=request_data.get("papers"),
                token=code,
                diet_name=request_data.get("diet_name"),
            )
            db.session.add(new_sponsored)
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            # print(f"Staff is {staff.first_name}")
            log_staff_activity(title="Sponsorship Created.",
                               desc="""A sponsorship entry has been created for a student""",
                               staff=staff,
                               object_id=2,
                               obj=f"Student: {request_data.get("first_name")} {request_data.get("last_name")}")
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"A new sponsorship entry has been created successfully."
                }
            ), 200
        except ZeroDivisionError as e: #Exception as e:
            return jsonify(
                {"Error": f"Error creating sponsorship: {e}"}
            ), 400


    @app.route("/api/v1/sponsorships", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def sponsorships(user_id):
        sponsorships = db.session.execute(db.select(Sponsored).order_by(Sponsored.first_name.asc())).scalars().all()
        sponsorship_data = [{"first_name": sponsorship.first_name,
                             "last_name": sponsorship.last_name,
                             "company_name": sponsorship.company,
                             "papers": sponsorship.papers,
                             "token": sponsorship.token,
                             "used": sponsorship.used,
                             "diet_name": sponsorship.diet_name,
                             "created_at": sponsorship.created_at} for sponsorship in sponsorships]
        return jsonify(sponsorship_data), 200


    @app.route("/api/v1/edit-sponsorship", methods=["PATCH"])
    @auth_required
    @role_required("pro_admin")
    def edit_sponsorship(user_id):
        try:
            request_data = request.get_json()
            sponsorship = db.session.execute(db.select(Sponsored).where(Sponsored.token == request_data.get("token"))).scalar()
            if sponsorship.used:
                return jsonify(
                    error={
                        "Operation Failure": f"Sponsorship already used."
                    }
                ), 400
            sponsorship.first_name = request_data.get("firstname", sponsorship.first_name)
            sponsorship.last_name = request_data.get("lastname", sponsorship.last_name)
            sponsorship.company = request_data.get("company_name", sponsorship.company)
            sponsorship.papers = request_data.get("papers", sponsorship.papers)
            sponsorship.diet_name = request_data.get("diet_name", sponsorship.diet_name)
            sponsorship.edited_at = datetime.now(timezone.utc)
            #ADD DATE EDITED

            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Sponsorship Details Edited.",
                               desc="""The details of an existing sponsorship were modified, including updates to key 
                               attributes such as sponsored papers, sponsoring company, and associated diet name.""",
                               staff=staff,
                               object_id=2,
                               obj=f"Sponsorship: {sponsorship.id}")
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"Details of Sponsorship {sponsorship.id} has been edited successfully."
                }
            ), 200
        except Exception as e:
            return jsonify(
                error={
                    "Operation Failure": f"Failed to edit paper, error: {e}."
                }
            ), 400


    @app.route("/api/v1/block-student", methods=["PATCH"])
    @auth_required
    @role_required("super_admin")
    def block_students(user_id):
        request_data = request.get_json()
        reg_no = request_data.get("reg_no")
        student = db.session.execute(db.select(Student).where(Student.reg_no == reg_no)).scalar()
        if not student:
            return jsonify(
                {"Error": "Student not found."}
            ), 404
        student.access = False
        staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
        log_staff_activity(title="Blocked Student.",
                           desc=f"""A student's access to certain functionality has been restricted. Reason: {request_data.get('reason')}""",
                           staff=staff,
                           object_id=2,
                           obj=f"Student: {reg_no}")
        # db.session.commit()
        staff.last_active = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(
            {
                "Operation Success": f"You don block this one successfully."
            }
        ), 200


    @app.route("/api/v1/create-admin", methods=["POST"])
    @auth_required
    @role_required("super_admin")
    def create_admin(user_id):
        try:
            def generate_code(role):
                prefixes = {"admin": "ADM", "board": "BRD", "tutor": "TUT", "intern": "INT"}
                if "_" in role:
                    role = "admin"
                prefix = prefixes.get(role)
                admins = db.session.execute(
                    db.select(Staff).where(Staff.code.ilike(f"%{prefix}%"))).scalars().all()
                code_num = [int(admin.code.split("-")[1].strip()) for admin in admins]
                new_num = max(code_num) + 1
                new_code = f"{prefix} - {new_num:05}"

                return new_code

            request_data = request.get_json()
            if exists_in_models("email", request_data.get("email"), Signee, Student, Staff):
                return jsonify(
                    {
                        "Operation Error": "User is already registered as a signee, student or staff."
                    }
                ), 400
            # if db.session.execute(db.select(Signee).where(Signee.email == request_data.get("email"))).scalar():
            #     return jsonify(
            #         {
            #             "Operation Error": "User is already registered as a signee."
            #         }
            #     ), 400
            # elif db.session.execute(db.select(Student).where(Student.email == request_data.get("email"))).scalar():
            #     return jsonify(
            #         {
            #             "Operation Error": "User is already registered as a student."
            #         }
            #     ), 400
            # elif db.session.execute(db.select(Staff).where(Staff.email == request_data.get("email"))).scalar():
            #     return jsonify(
            #         {
            #             "Operation Error": "User is already registered as a staff."
            #         }
            #     ), 400
            gender = request_data.get("gender").lower()
            new_staff = Staff(
                title="XXX" if gender == "female" else "Mr",
                first_name=request_data.get("firstname"),
                last_name=request_data.get("lastname"),
                email=request_data.get("email"),
                phone_number=request_data.get("phone"),
                password="xxxxxxxxx",
                birth_date=datetime.now(timezone.utc),
                house_address="Place holder",
                photo="Place holder",
                code=generate_code(request_data.get("role")),
                gender=gender,
                role=request_data.get("role"),
                employment_type=request_data.get("type"),
                status="Inactive",
                hire_date=request_data.get("hiredate"),
            )
            db.session.add(new_staff)
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="Initiated New Admin.",
                               desc="""A new admin account creation has just been initiated but is yet to be completed..""",
                               staff=staff,
                               object_id=2,
                               obj=f"Staff: {staff.code}")
            send_staff_creation_message(request_data.get("firstname"), request_data.get("email"), "initialize-admin")
            staff.last_active = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify(
                {
                    "Operation Success": f"You have successfully initiated the creation of a(n) {request_data.get("role")}."
                }
            ), 200
        except ZeroDivisionError as e: #Exception as e:
            return jsonify(
                {
                    "Operation Error": f"An error occurred {e}."
                }
            ), 400
        # phone_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
        # password: Mapped[str] = mapped_column(String(100), nullable=False)
        # birth_date: Mapped[date] = mapped_column(Date, nullable=False)
        # house_address: Mapped[str] = mapped_column(String(200))
        # status: Mapped[str] = mapped_column(String(20), nullable=False)  # Active, Inactive, Terminated, etc.
        # hire_date: Mapped[date] = mapped_column(Date, nullable=True)
        # photo: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)


    @app.route("/api/v1/complete-admin", methods=["PATCH"])
    @auth_required
    @role_required("tutor")
    def complete_admin(user_id):
        request_data = request.get_json()
        email = verify_email(request_data.get("token", ""))
        staff = db.session.execute(db.select(Staff).where(Staff.email == email[1])).scalar()

        if isinstance(request_data.get("dob"), str):
            try:
                d_o_b = datetime.fromisoformat(request_data.get("dob").replace("Z", "+00:00"))
            except:
                d_o_b = datetime.strptime(request_data.get("dob"), "%d/%m/%Y")
        else:
            d_o_b = request_data.get("dob")
        # with open("pfp.jpg", mode="rb") as f:
        #     image_binary = f.read() # VERY VERY TEMP
        hash_and_salted_password = generate_password_hash(
            request_data.get("password"),
            method='pbkdf2:sha256',
            salt_length=8
        )
        pfp_url = store_pfp(request_data.get("profile_pic"), email[1])

        staff.phone_number = request_data.get("phone")
        staff.password = hash_and_salted_password
        staff.birth_date = d_o_b
        staff.house_address = request_data.get("address")
        staff.status = "Active"
        staff.photo = pfp_url #image_binary
        log_staff_activity(title="New Admin Created.",
                           desc="""The incomplete creation process of initializing a new admin user has been completed
                            and a new admin has been successfully created""",
                           staff=staff,
                           object_id=2,
                           obj=f"Staff: {staff.code}")
        send_staff_creation_message(request_data.get("firstname"), email[1], "complete-admin")
        staff.last_active = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(
            {
                "Operation Success": f"You have successfully completed your admin account creation."
            }
        ), 200



    @app.route('/api/v1/export-students', methods=['GET'])
    @auth_required
    @role_required("pro_admin")
    def export_students(user_id):
        output = generate_student_data()
        staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
        staff.last_active = datetime.now(timezone.utc)
        db.session.commit()
        # Send the file back as a response
        return send_file(
            output,
            download_name="students.xlsx",
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        ), 200


    @app.route('/api/v1/staff-activities', methods=['GET'])
    @auth_required
    @role_required("super_admin")
    def staff_doings(user_id):
        print("Yeah it is enterionh")
        activities = staff_activities()
        return jsonify(activities), 200


    @app.route('/api/v1/create-template', methods=['POST'])
    @auth_required
    @role_required("super_admin")
    def create_course_template(user_id):
        def json_to_paths(data, prefix=""):
            """Recursively convert nested dicts to 'path|path|path' strings."""
            paths = []
            for key, value in data.items():
                new_prefix = f"{prefix}|{key}" if prefix else key  # build hierarchical prefix
                if isinstance(value, dict) and value:
                    # Recursively go deeper
                    sub_paths = json_to_paths(value, new_prefix)
                    paths.extend(sub_paths)
                else:
                    # Leaf node — add path to list
                    paths.append(new_prefix)
            return paths

        request_data = request.get_json()
        template_title = request_data.get("title")
        current_template = db.session.execute(db.select(DirectoryTemplate).where(DirectoryTemplate.title == template_title)).scalars().first()
        if current_template:
            return jsonify(
                {
                    "Operation Error": f"Template creation failed, template title already exists."
                }
            ), 400
        template = request_data.get("template")
        # with open("resource/foldertemplate.json", mode="r") as file:
        #     template = json.load(file)
        full_paths = json_to_paths(template, prefix="")

        with (app.app_context()):
            print(full_paths[3]) if len(full_paths) == 4 else print(full_paths)
            for a_path in full_paths:
                a_path_split = a_path.split("|")
                # print(a_path_split)
                for i, v in enumerate(a_path_split):
                    print(a_path_split)
                    print("Iv:", i, v)
                    pair = []
                    if i > 0:
                        parent = "/".join(a_path_split[0:i]) #"/" + "/".join(a_path_split[0:i])
                        path = parent + v if parent[-1] == "/" else parent + "/" + v
                        print("pp: ", parent, path)
                        existing_folders = {
                            d.path_template for d in db.session.scalars(
                                db.select(DirectoryTemplate).where(DirectoryTemplate.path_template.in_([parent, path]))
                            )
                        }
                        print("ex: ", existing_folders)

                        if parent not in existing_folders:
                            pre = "/".join(parent.split("/")[:-1])
                            print("oya", parent, pre)
                            pre = db.session.execute(
                                db.select(DirectoryTemplate).where(DirectoryTemplate.path_template == pre)
                            ).scalar_one_or_none()
                            new_template_folder = DirectoryTemplate(
                                name=parent.split("/")[-1],
                                title=template_title,
                                parent_id=pre.id,
                                path_template=parent,
                                parent=pre
                            )
                            # pair.append(parent)
                            db.session.add(new_template_folder)
                        if path not in existing_folders:
                            pre = db.session.execute(
                                db.select(DirectoryTemplate).where(DirectoryTemplate.path_template == parent)
                            ).scalar_one_or_none()
                            new_template_folder = DirectoryTemplate(
                                name=path.split("/")[-1],
                                title=template_title,
                                parent_id=pre.id,
                                path_template=path,
                                parent=pre
                            )
                            db.session.add(new_template_folder)
                    else:
                        root = db.session.execute(
                                db.select(DirectoryTemplate).where(DirectoryTemplate.path_template == v)
                            ).scalar_one_or_none()
                        if not root:
                            print("NOT ROOZT")
                            new_template_folder = DirectoryTemplate(
                                name=v,
                                title=template_title,
                                parent_id=None,
                                path_template=v,
                            )
                            db.session.add(new_template_folder)
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
            log_staff_activity(title="New File Structure Created.",
                               desc=f"""A new file template has been created with the name : {template_title}.""",
                               staff=staff,
                               object_id=0,
                               obj=f"Template: {template_title}")
            db.session.commit()
        return jsonify(
            {
                "Operation Success": f"You have successfully created a new course template."
            }
        ), 200


    @app.route('/api/v1/course-templates', methods=['GET'])
    @auth_required
    @role_required("super_admin")
    def view_course_template(user_id):
        ROOT_PARENT_ID = 1

        if request.args.get("purpose"):
            with app.app_context():
                 return jsonify(db.session.execute(db.select(DirectoryTemplate.title).distinct()).scalars().all()), 200

        with app.app_context():
            rows = db.session.execute(db.select(DirectoryTemplate)).scalars().all()

        # Group by template title
        templates_by_title = defaultdict(list)
        for row in rows:
            templates_by_title[row.title].append(row)

        results = []

        for title, rows in templates_by_title.items():
            # Build lookup tables
            id_map = {r.id: r for r in rows}
            children_map = defaultdict(list)
            roots = []

            for r in rows:
                if r.parent_id == ROOT_PARENT_ID or r.parent_id not in id_map:
                    roots.append(r)
                else:
                    children_map[r.parent_id].append(r)

            def build_tree(node):
                return {
                    child.name: build_tree(child)
                    for child in children_map.get(node.id, [])
                }

            template_tree = {
                root.name: build_tree(root)
                for root in roots
            }

            results.append({
                "title": title,
                "template": template_tree
            })

        return jsonify(results), 200


    @app.route('/api/v1/add-video', methods=['POST'])
    @auth_required
    @role_required("pro_admin")
    def add_video(user_id):
        request_data = request.get_json()
        file_path = request_data.get("path")
        link = request_data.get("video_link")
        video_name = request_data.get("name")

        with app.app_context():
            directory = db.session.execute(
                db.select(DirectoryInstance).where(DirectoryInstance.path == file_path)
            ).scalar_one_or_none()
            new_file = File(
                folder_id=directory.id,
                name=video_name,
                mime_type="text/link", # I know there is no mime type like this
                size=0,
                file_type="link",
                file_url=link,
                folder=directory
            )
            # with app.app_context():
            db.session.add(new_file)
            db.session.commit()
            staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
        log_staff_activity(title="Video Link Added.",
                           desc=f"""A new video link has been added to the set of student materials stored..""",
                           staff=staff,
                           object_id=0,
                           obj=f"Video: {video_name}")
        # Might need to add db.session.commit
        return jsonify(
            {
                "Operation Success": f"You have successfully added a new video."
            }
        ), 200


    @app.route('/api/v1/upload-file', methods=['POST'])
    @auth_required
    @role_required("tutor")
    def upload_file(user_id):
        # request_data = request.get_json()
        # file_path = request_data.get("path")
        file_path = request.form.get("path")
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files["file"]

        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        mime_type = file.content_type

        file_key = secure_filename(file.filename)

        name, ext = os.path.splitext(file_key)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H-%M-%S_%f")
        new_filekey = f"{name}_{timestamp}{ext}"

        url = store_file(new_filekey, file)
        if url[1] != 200:
            return jsonify({"error": url[0]["error"]}), url[1]

        directory = db.session.execute(
            db.select(DirectoryInstance).where(DirectoryInstance.path == file_path)
        ).scalar_one_or_none()

        new_file = File(
            folder_id=directory.id,
            name=new_filekey,
            mime_type=mime_type,
            size=file_size,
            file_type="regular",
            file_url=url[2],
            folder=directory
        )
        # with app.app_context():
        db.session.add(new_file)
        staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
        log_staff_activity(title="File Added.",
                           desc=f"""A new file has been added to the set of student materials stored..""",
                           staff=staff,
                           object_id=0, #temp
                           obj=f"File: {file_key}")
        return jsonify(
            {
                "Operation Success": f"You have successfully uploaded a file."
            }
        ), 200


    @app.route('/api/v1/view-file', methods=['GET'])
    @auth_required
    @role_required("student")
    def view_file(user_id):
        if not platform_access(user_id):
            return jsonify({"Access Denied": "Student access has been restricted."})
        file_key = request.args.get("file_name")
        try:
            file_stream = download_file(file_key)
            return send_file(
                file_stream,
                as_attachment=True,
                download_name=file_key.split("/")[-1]
            ), 200
        except ZeroDivisionError: #Exception as e:
            return jsonify({"error": str("e")}), 404


    @app.route('/api/v1/view-dir', methods=['GET'])
    @auth_required
    @role_required("student")
    def view_dir(user_id):
        # I should not forget to check if the student has passed the last step question
        if not platform_access(user_id):
            return jsonify({"Access Denied": "Student access has been restricted."})
        file_path = request.args.get("path")
        try:
            directory = db.session.execute(
                db.select(DirectoryInstance).where(DirectoryInstance.path == file_path)
            ).scalar_one_or_none()
            print(file_path, directory.children)
            subfolders = []
            res = folder_access(directory, user_id)
            print(res)
            if not res[0]:
                return jsonify({"Access Denied": res[1]}), 400

            # children = db.session.execute(db.select(DirectoryInstance).where(DirectoryInstance.parent_id == directory.id)).scalars().all()
            for child in directory.children:
                subfolders.append({"name": child.name, "path": child.path, "type":"dir"})
            for file in directory.files:
                if file.file_type == "gateway":
                    subfolders.append(
                        {"name": f"{file_path.split('/')[2]} Gateway",
                         "path": f"{file.folder.path}/{file.name}", "type": "test"}
                    )
                elif file.file_type == "test":
                    print(file.name)
                    test = db.session.execute(db.select(McqTest).where(McqTest.file_name == file.name)).scalar()
                    subfolders.append(
                        {"name": file.name, "path": f"{file.folder.path}/{test.file_name}", "type": "test"}
                    )
                elif file.file_type == "link":
                    subfolders.append(
                        {"name": file.name, "path": f"{file.folder.path}/{file.name}", "type": "url", "url": file.file_url}
                    )
                else:
                    subfolders.append({"name": file.name, "path": f"{file.folder.path}/{file.name}", "mime_type": file.mime_type, "type": "file"})
        except ZeroDivisionError: #AttributeError:
            return jsonify({"Error":f"Nonexistent file path {file_path}!"}), 400
        else:
            return jsonify(subfolders), 200


    @app.route('/api/v1/upload-mcq', methods=['POST'])
    @auth_required
    @role_required("tutor")
    def upload_mcq(user_id):
        file_path = request.form.get("path")
        mcq_name = request.form.get("name")
        paper = request.form.get("paper")
        diet = request.form.get("diet")
        gateway = request.form.get("gateway")
        high_score = request.form.get("high_score")
        pass_mark = request.form.get("pass")
        duration = request.form.get("duration")

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        if db.session.execute(db.select(GatewayTest).where(GatewayTest.level == file_path.split("/")[2])).scalar():
            return jsonify({"Error Uploading Test": "A Gateway test already exists for this level."})


        file = request.files["file"]

        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        mime_type = file.content_type
        original_name = secure_filename(file.filename)

        name, ext = os.path.splitext(original_name)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H-%M-%S_%f")
        new_filename = f"{name}_{timestamp}{ext}"

        file.seek(0)
        data = file.read()
        file = io.BytesIO(data)
        response = validate_questions(file, paper, diet)
        if not response[0]:
            return jsonify({"error": response[1]}), 400

        directory = db.session.execute(
            db.select(DirectoryInstance).where(DirectoryInstance.path == file_path)
        ).scalar_one_or_none()
        if not directory:
            return jsonify({"Error": "Nonexistent file path!"}), 400
        url = store_file(new_filename, file)# store_file(mcq_name, file)
        if url[1] != 200:
            return jsonify({"error": url[0]["error"]}), url[1]

        new_file = File(
            folder_id=directory.id,
            name=new_filename, #mcq_name,
            mime_type=mime_type,
            size=file_size,
            file_type="gateway" if gateway.lower() != "false" else "test",
            file_url=url[2],
            folder=directory
        )
        new_test = McqTest(
            test_name=mcq_name,
            file_name=new_filename,
            diet_name=directory.course_spec.split()[1],
            paper_code=directory.course_spec.split()[0],
            course_spec=directory.course_spec,
            pass_mark=pass_mark,
            high_score=high_score,
            duration=duration,
            file=new_file
        )
        if gateway:
            new_gateway = GatewayTest(
                course_spec=directory.course_spec,
                level=file_path.split("/")[2],
                pass_mark=pass_mark,
                gateway_code="gtway-" + generate_code(),
                duration=duration,
                file=new_file
            )
            db.session.add(new_gateway)
        db.session.add_all([new_file, new_test])
        staff = db.session.execute(db.select(Staff).where(Staff.id == user_id)).scalar()
        log_staff_activity(title="Test Added.",
                           desc=f"""A new test has been added, more details later..""",
                           staff=staff,
                           object_id=0, #temp
                           obj=f"File: {mcq_name}")
        return jsonify({"success": "Test uploaded"}), 200


    @app.route('/api/v1/get-mcq', methods=['GET'])
    @auth_required
    @role_required("student")
    def get_test(user_id):
        try:
            if not platform_access(user_id):
                return jsonify({"Access Denied": "Student access has been restricted."})
            file_path = request.args.get("path")
            filename = file_path.split("/")[-1]

            test = db.session.execute(db.select(McqTest).where(McqTest.file_name == filename)).scalar()
            if not test:
                return jsonify({"error": "Test not found!"}), 400
            elif test.course_spec != file_path.split("/")[1]:
                print(test.course_spec, "--", file_path.split("/")[0], file_path.split("/")[1], file_path.split("/"))
                return jsonify({"error": "Critical and unexpected database conflict!"}), 500
            file = db.session.execute(db.select(File).where(File.id == test.file_id)).scalar()
            test_details = {
                "metadata": {"diet_name": test.diet_name,
                             "paper": test.paper_code,
                             "test_name": test.test_name,
                             "high_score": test.high_score,
                             "duration": test.duration,
                             "gateway": True if file.file_type else False}
            }
            file = download_file(filename=filename)
            file.seek(0)
            with open("well.xlsx", "wb") as f:
                f.write(file.read())
            print("file is:", file)
            questions = read_mcq(file, "que")
            test_details["questions"] = questions
        except OperationalError:
            return jsonify({"Error": "Operational error, please try again."})
        else:
            return jsonify(test_details), 200


    @app.route('/api/v1/submit-mcq', methods=['POST'])
    @auth_required
    @role_required("student")
    def submit_test(user_id):
        request_data = request.get_json()
        file_path = request_data.get("path")
        email = request_data.get("email")
        test_name = request_data.get("test_name")
        gateway = request_data.get("gateway")
        selections = request_data.get("answers", {})
        score = 0
        result = {}

        try:
            if not platform_access(user_id):
                return jsonify({"Access Denied": "Student access has been restricted."})
            test = db.session.execute(db.select(McqTest).where(McqTest.test_name == test_name)).scalar()
            if not test:
                return jsonify({"error": "Test not found!"}), 400
            file = download_file(filename=test.file_name)
            answers = read_mcq(file, "ans")
            # for key, value in selections.items():
            #     if key != value["No"]:
            #         return jsonify({"error": "Corrupted answers!"}), 400
            print(selections)
            marks_per_question = test.high_score / len(answers)
            for i in range(1, len(answers) + 1):
                if selections[str(i)] == answers[i]:
                    score += int(marks_per_question)
                result[str(i)] = [selections[str(i)], answers[i]]

            if gateway:
                course_spec = file_path.split("/")[1]
                level = file_path.split("/")[2]
                gateway_test = db.session.execute(db.select(GatewayTest).where(
                    (GatewayTest.course_spec == course_spec) & (GatewayTest.level == level))
                ).scalar()
                if not gateway_test:
                    return jsonify({"error": "No such gateway."}), 400

            outcome = "passed" if score > test.pass_mark else "failed"
            new_test_history = McqHistory(
                course_spec=test.course_spec,
                score=score,
                high_score=test.high_score,
                result=result,
                code=gateway_test.gateway_code if gateway else None,
                status="passed" if score > test.pass_mark else "failed",
                student_id=user_id,
                test_id=test.id
            )
            db.session.add(new_test_history)
            operation_details = f"User just took an mcq test, results has been marked and saved , [{test.course_spec, test.test_name}]"
            update_action(email, "Took a mcq.", operation_details)
            result["score"] = score
            result["status"] = outcome
            if gateway:
                # Do not send the answers
                for key in result.keys():
                    result[key] = [result[key][0], result[key][0] == result[key][1]]
            else:
                pass
        except IntegrityError:
            return jsonify({"Error": "Integrity Error, please contact the application developers."})
        except Exception:
            return jsonify({"Error": "Unknown Error, contact the application developers."})
        else:
            return jsonify(result), 200


    @app.route("/api/v1/payments", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def payments(user_id):
        payments = db.session.execute(db.select(Payment).order_by(Payment.id.asc())).scalars().all()
        payments_data = [{"reg_no": payment.student_reg,
                        "reference": payment.payment_reference,
                        "sponsored": payment.sponsored,
                        "amount": payment.amount,
                        "purpose": payment.purpose,
                        "date": payment.paid_at, } for payment in payments]
        return jsonify(payments_data), 200


    @app.route("/api/v1/view-payment", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def view_payment(user_id):
        payment = db.session.execute(db.select(Payment).where(Payment.payment_reference == request.args.get("reference"))).scalar()
        if not payment:
            return jsonify({"Error": "Payment not found"}), 400
        paper_details = {"student_reg": payment.student_reg,
                        "amount": payment.amount,
                        "payment_reference": payment.payment_reference,
                        "paid_for": payment.purpose,
                        "medium": payment.medium,
                        "date_paid": payment.paid_at,
                        "receipt_no": payment.receipt_number,} # Set this in a db table later e.g SystemData
        return jsonify(paper_details), 200


    @app.route("/api/v1/reviews", methods=["GET"])
    @auth_required
    @role_required("lite_admin")
    def reviews(user_id):
        paper_code = request.args.get("paper", "all").upper() #Should be .lower(), should look into that and affirm consistency
        diet_name = request.args.get("diet") # Diet can't be "all" for now.
        if paper_code ==  "all":
            diet_reviews = db.session.execute(db.select(Review).where(Review.diet.has(name=diet_name))).scalars().all()
        else:
            diet_reviews = db.session.execute(db.select(Review).where(Review.diet.has(name=diet_name))).scalars().all()
            diet_reviews = [review for review in diet_reviews if review.paper_code == paper_code]
        reviews = [{
            "paper": review.paper_code,
            "rating": review.rating,
            "comment": review.comment,
            "created_at": review.created_at,
        } for review in diet_reviews]
        return jsonify(reviews), 200


    # def update_mcq():

    @app.route('/api/v1/get-token', methods=['GET'])
    def give():
        print(request.args.get("paper"))
        return jsonify({"oi": 3})
        # return jsonify({"toks": generate_token(None, None, True)})

    # with app.app_context():
    #     directory = db.session.execute(
    #         db.select(DirectoryInstance).where(DirectoryInstance.path == "/CSS 2026_July/200/First Semester")
    #     ).scalar_one_or_none()
    #     folder_access(directory)

# Do not forget to add a view admin endpoint

    # try:
    #     with app.app_context():
    #         print("Creating paper entries")
    #         papers = pd.read_excel("resource/ivy pricing.xlsx")
    #         """"""
    #         for i, paper in papers.iterrows():
    #             if not isinstance(paper["Knowledge papers"], float):
    #                 print("Paper not float")
    #                 print(f"At index {i} paper:", " ".join(paper['Knowledge papers'].split()[:-1])) #, paper['Knowledge papers'])
    #                 if "papers" in paper["Knowledge papers"].lower():
    #                     continue
    #                 variations = [(" Standard", "std"), (" Intensive", "int")]
    #                 for j in range(2):
    #                     print("IN 2 rnage for PP")
    #                     code = paper["Knowledge papers"].split()[-1]
    #                     # if code in ["BT", "FA", "MA", "CBL", "OBU", "DipIFRS"] and j != 0:
    #                     #     print("Continuing as BT is not in intensive")
    #                     if j != 0:
    #                         print("Continue as we are no longer dealing with intensive")
    #                         continue
    #                     if code in ["OBU", "DipIFRS"]:
    #                         revision = 0
    #                         extension = ""
    #                         category = "Additional"
    #                         price = paper.Standard
    #                     else:
    #                         if code in ["BT", "FA", "MA"]:
    #                             category = "Knowledge"
    #                         elif code in ["PM", "FR", "AA", "TAX", "FM", "CBL"]:
    #                             category = "Skill"
    #                         else:
    #                             category = "Professional"
    #                         code = "TX" if code == "TAX" else code
    #                         # code = f"{code}-{variations[i][1]}"
    #                         extension = variations[j][0]
    #                         price = paper.Standard + (paper.revision if code[-3:] == "std" else 0)
    #                         revision = 20_000 if code[-3:] == "std" else 0
    #
    #                     new_paper = Paper(
    #                         name=" ".join(paper["Knowledge papers"].split()[:-1]).title(), # + extension,
    #                         code=code,
    #                         price=40_000, #int(price),
    #                         revision=20_000, #revision,
    #                         category=category
    #                     )
    #                     print("Reach before adding")
    #                     db.session.add(new_paper)
    #             print("Reach before commiting")
    #             db.session.commit()
    #             print(f"At index {i} DONE!!!")
    #
    #     with app.app_context():
    #         with open("resource/questions.json", mode="r") as file:
    #             data = json.load(file)
    #         new_data = SystemData(
    #             data_name="reg_form_info",
    #             data=data
    #         )
    #         new_data2 = SystemData(
    #             data_name="levels",
    #             data={"acca": ["step 1", "step 2", "step 3", "step 4", "step 5", "step 6"]}
    #         )
    #         db.session.add_all([new_data, new_data2])
    #         db.session.commit()
    #
    #     with app.app_context():
    #         insert_sponsored_row("John", "Doe", "KPMG", ["APM-std", "BT-int"], "KPMG12345", "2026_March")
    #         insert_sponsored_row("Ayomide", "Ojutalayo", "Deloitte", ["AFM-std", "SBL-int"], "Deloitte789", "2026_March")
    #         insert_sponsored_row("Ayomide", "Ojutalayo", "AGBA", ["AFM-std", "PM-int"], "AGBA123", "2026_June")
    #         insert_sponsored_row("Jane", "Doe", "PWC", ["FM-std", "MA-int"], "PWC12345", "2026_March")
    #
    #     for pp in ["TX", "CBL"]:
    #         with app.app_context():
    #             new_schols = Scholarship(
    #                 email="Jan@samp.com",
    #                 paper=pp,
    #                 discount=15,
    #                 diet_name="2025_March"
    #             )
    #             db.session.add(new_schols)
    #             db.session.commit()
    #
    #     with app.app_context():
    #         new_schols2 = Scholarship(
    #             email="ojutalayoayomide21@gmail.com",
    #             paper="TX",
    #             discount=20,
    #             diet_name="2025_March"
    #         )
    #         db.session.add(new_schols2)
    #         db.session.commit()
    #     # dt_1 = datetime(2025, 9, 1, 15, 30, 0)
    #     # dt_1_b = datetime(2025, 11, 1, 15, 30, 0)
    #     # dt_2 = datetime(2026, 1, 1, 15, 30, 0)
    #     # dt_2_b = datetime(2026, 3, 27, 15, 30, 0)
    #     # dt_3 = datetime(2026, 5, 1, 15, 30, 0)
    #     # dt_3_b = datetime(2026, 6, 26, 15, 30, 0)
    #     # dt_4 = datetime(2026, 7, 8, 15, 30, 0)
    #     # dt_4_b = datetime(2026, 8, 29, 15, 30, 0)
    #     # dts = [dt_1, dt_2, dt_3, dt_4]
    #     # dtl = [dt_1_b, dt_2_b, dt_3_b, dt_4_b]
    #     # for i, month in enumerate(["March", "June", "September", "December"]):
    #     #     with app.app_context():
    #     #         new_diet = Diet(
    #     #             name=f"{datetime.now().year}_{month}",
    #     #             reg_start=dts[i],
    #     #             reg_deadline=dtl[i],
    #     #             revision_start=datetime(2026, 8, 29, 15, 30, 0),
    #     #             revision_deadline=datetime(2026, 8, 29, 15, 30, 0),
    #     #             completion_date=datetime(2026, 8, 29, 15, 30, 0),
    #     #         )
    #     #         db.session.add(new_diet)
    #     #         db.session.commit()
    #     with app.app_context():
    #         print("doing staff")
    #         new_staff = Staff(
    #             title="Mr",
    #             first_name="Ayomide",
    #             last_name="Ojutalayo",
    #             email="ojutalayoayomide21@gmail.com",
    #             phone_number="08012345667",
    #             password="pbkdf2:sha256:1000000$pjWHjSTC$31dab95672358c4626cda6521d8f195606edbe58f6facc350eb06b3c8a616edb",
    #             # password=generate_password_hash(
    #             #         "acca1234",
    #             #         method='pbkdf2:sha256',
    #             #         salt_length=8
    #             #     ),
    #             code="ADM - 00001",
    #             photo="ad sfjnfs",
    #             gender="Male",
    #             birth_date=datetime.now(),
    #             house_address="sdbgs dwvdbyh fiws ss",
    #             role="super_admin",
    #             employment_type="Full-Time",
    #             status="Active"
    #         )
    #         new_staff_2 = Staff(
    #             title="Mr",
    #             first_name="John",
    #             last_name="Doe",
    #             email="ivyleagueassociates@gmail.com",
    #             phone_number="08034566789",
    #             password=generate_password_hash(
    #                     "Acca1234",
    #                     method='pbkdf2:sha256',
    #                     salt_length=8
    #                 ),
    #             code="ADM - 00001",
    #             photo="ad sfjnfs",
    #             gender="Male",
    #             birth_date=datetime.now(),
    #             house_address="sdbgs dwvdbyh fiws ss",
    #             role="super_admin",
    #             employment_type="Full-Time",
    #             status="Active"
    #         )
    #         db.session.add_all([new_staff, new_staff_2])
    #         db.session.commit()
    #         # print(generate_token(1, "super_admin"))
    #
    #     # with app.app_context():
    #     #     def json_to_paths(data, prefix=""):
    #     #         """Recursively convert nested dicts to 'path|path|path' strings."""
    #     #         paths = []
    #     #         for key, value in data.items():
    #     #             new_prefix = f"{prefix}|{key}" if prefix else key  # build hierarchical prefix
    #     #             if isinstance(value, dict) and value:
    #     #                 # Recursively go deeper
    #     #                 sub_paths = json_to_paths(value, new_prefix)
    #     #                 paths.extend(sub_paths)
    #     #             else:
    #     #                 # Leaf node — add path to list
    #     #                 paths.append(new_prefix)
    #     #         return paths
    #     #
    #     #     with open("resource/foldertemplate.json", mode="r") as file:
    #     #         template = json.load(file)
    #     #     full_paths = json_to_paths(template, prefix="")
    #     #     print(full_paths[3])
    #     #     for a_path in full_paths:
    #     #         a_path_split = a_path.split("|")
    #     #         # print(a_path_split)
    #     #         for i, v in enumerate(a_path_split):
    #     #             pair = []
    #     #             if i > 0:
    #     #                 parent = "/" + "/".join(a_path_split[1:i])
    #     #                 path = parent + v if parent[-1] == "/" else parent + "/" + v
    #     #                 existing_folders = {
    #     #                     d.path_template for d in db.session.scalars(
    #     #                         db.select(DirectoryTemplate).where(DirectoryTemplate.path_template.in_([parent, path]))
    #     #                     )
    #     #                 }
    #     #
    #     #                 if parent not in existing_folders:
    #     #                     pre = "/".join(parent.split("/")[:-1])
    #     #                     pre = db.session.execute(
    #     #                         db.select(DirectoryTemplate).where(DirectoryTemplate.path_template == pre)
    #     #                     ).scalar_one_or_none()
    #     #                     new_template_folder = DirectoryTemplate(
    #     #                         name=parent.split("/")[-1],
    #     #                         title="Gbaskole",
    #     #                         parent_id=pre.id,
    #     #                         path_template=parent,
    #     #                         parent=pre
    #     #                     )
    #     #                     # pair.append(parent)
    #     #                     db.session.add(new_template_folder)
    #     #                 if path not in existing_folders:
    #     #                     pre = db.session.execute(
    #     #                         db.select(DirectoryTemplate).where(DirectoryTemplate.path_template == parent)
    #     #                     ).scalar_one_or_none()
    #     #                     new_template_folder = DirectoryTemplate(
    #     #                         name=path.split("/")[-1],
    #     #                         title="Gbaskole",
    #     #                         parent_id=pre.id,
    #     #                         path_template=path,
    #     #                         parent=pre
    #     #                     )
    #     #                     db.session.add(new_template_folder)
    #     #             else:
    #     #                 root = db.session.execute(
    #     #                         db.select(DirectoryTemplate).where(DirectoryTemplate.path_template == "/")
    #     #                     ).scalar_one_or_none()
    #     #                 if not root:
    #     #                     new_template_folder = DirectoryTemplate(
    #     #                         name=v,
    #     #                         title="Gbaskole",
    #     #                         parent_id=None,
    #     #                         path_template=v,
    #     #                     )
    #     #                     db.session.add(new_template_folder)
    #     #     db.session.commit()
    #
    # except Exception as e:
    #     print(f"The expected error don show, i catch the werey. {e}")


#     try:
#         start = datetime.now()
#         with app.app_context():
#             pps = db.session.scalars(
#                 db.select(Paper).where(Paper.code.in_(["AAA"]))
#             ).all()
#
#             templates = db.session.scalars(
#                 db.select(DirectoryTemplate)
#             ).all()
#             print(pps, "\n\n\n", templates)
#
#             instances = []
#             path_map = {}
#
#             for paper in pps:
#                 course_spec = f"{paper.code} 2021_July"
#                 for template in templates:
#                     path = f"/{course_spec}{template.path_template}".rstrip("/")
#
#                     inst = DirectoryInstance(
#                         template_id=template.id,
#                         course_code=paper.code,
#                         course_spec=course_spec,
#                         name=template.name,
#                         path=path,
#                         parent_id=None,
#                         template=template,
#                     )
#
#                     instances.append(inst)
#                     path_map[path] = inst
#                     print("ID here is,", inst.id)
#
#             # Resolve parents WITHOUT querying DB
#             for path, inst in path_map.items():
#                 # print("PATH AND INST:", path, inst)
#                 parent_path = "/".join(path.split("/")[:-1])
# #                 print("PARENT PATH", parent_path)
#                 if parent_path and parent_path in path_map:
#                     inst.parent = path_map[parent_path]
#                     # inst.parent_id = path_map[parent_path].id
# #                 print("PAR ON INST", inst.parent)
#
#             # Bulk insert (fast!)
#             db.session.add_all(instances)
#             # db.session.commit()
#             db.session.flush()  # IDs now exist
#
#             for path, inst in path_map.items():
#                 parent_path = "/".join(path.split("/")[:-1])
#                 if parent_path in path_map:
#                     inst.parent_id = path_map[parent_path].id
#                     print(path_map[parent_path].id)
#
#
#             # db.session.bulk_save_objects(instances)
#             db.session.commit()
#
#         print("DUration:", datetime.now()-start)
#     except ZeroDivisionError: #Exception as e:
#         pass


    # start = datetime.now()
    # with app.app_context():
    #     pps = db.session.execute(db.select(Paper).where(Paper.code.in_(["ABC"]))).scalars().all()
    #     all_templates = db.session.execute(db.select(DirectoryTemplate)).scalars().all()
    #     new_instances = [] # New and untested
    #     for paper in pps:
    #         for template in all_templates:
    #             instance_path = f"/{paper.code} 2021_July{template.path_template}"
    #             new_instance = DirectoryInstance(
    #                 template_id=template.id,
    #                 course_code=paper.code,
    #                 course_spec=f"{paper.code} 2021_July",
    #                 name=template.name,
    #                 path=instance_path if not instance_path.endswith("/") else instance_path[:-1],
    #                 parent_id=None,
    #                 template=template,
    #             )
    #             db.session.add(new_instance)
    #             new_instances.append(new_instance) # New and untested
    #     # new_instances = db.session.execute(
    #     #     db.select(DirectoryInstance).where(DirectoryInstance.course_spec.ilike(f"%{name}%"))).scalars().all()
    #     db.session.commit()
    #     for instance in new_instances:
    #         if not instance.parent_id:
    #             parent_path = "/".join(instance.path.split("/")[:-1])
    #             if parent_path == "":
    #                 continue
    #             print(f"Parent path is {parent_path} fromm {instance.path}")
    #             parent = db.session.execute(
    #                 db.select(DirectoryInstance).where(DirectoryInstance.path == parent_path)).scalar_one_or_none()
    #             instance.parent_id = parent.id
    #             instance.parent = parent
    #     db.session.commit()
    # print("DUration:", datetime.now() - start)

    # with app.app_context():
    #     student = db.session.execute(db.select(Student).where(Student.reg_no == "133170952400")).scalar()
    #     student2 = db.session.execute(db.select(Student).where(Student.reg_no == "133170952611")).scalar()
    #     diet = db.session.execute(db.select(Diet).where(Diet.name == "2026_July")).scalar()
    #     good_review = Review(
    #         student=student,
    #         paper_id=109,
    #         diet=diet,
    #         paper_code="CSS",
    #         rating=5,
    #         comment="Great paper! Clear questions, fair difficulty, and actually tested what we studied. Loved it.",
    #         created_at=datetime.now(timezone.utc)
    #     )
    #
    #     # Disrespectfully funny bad review
    #     bad_review = Review(
    #         student=student2,
    #         paper_id=109,
    #         diet=diet,
    #         paper_code="CSS",
    #         rating=1,
    #         comment=(
    #             "This paper emotionally damaged me. "
    #             "I walked in confident and walked out questioning my life choices. "
    #             "Pretty sure question 3 was written by a sleep-deprived raccoon."
    #         ),
    #         created_at=datetime.now(timezone.utc)
    #     )
    #
    #     # Insert into DB
    #     db.session.add_all([good_review, bad_review])
    #     db.session.commit()

