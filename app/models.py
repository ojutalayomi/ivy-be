from typing import Dict, Any, Optional
from flask_login import UserMixin
from flask_migrate import Migrate
from datetime import datetime, date, timedelta
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Table, ForeignKey, BigInteger, Interval, TIMESTAMP
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import Integer, String, Float, Text, LargeBinary, DateTime, Boolean, Date, Column, ARRAY


# CREATE DATABASE
class Base(DeclarativeBase):
    pass
db = SQLAlchemy(model_class=Base)
migrate = Migrate()

student_paper = Table(
    "registrations",
    db.metadata,
    Column("enrollment_id", Integer, ForeignKey("enrollments.id")),
    Column("paper_id", Integer, ForeignKey("papers.id")),
    Column("registration_date", Date, default=date.today)
)

desc = "This is a course that somehow wanders through ideas like clouds drifting sideways, teaching something uncertain yet strangely fascinating to everyone involved."

# class EnrollmentPaper(db.Model):
#     __tablename__ = 'registrations_ewoo'  # or enrollment_papers
#
#     enrollment_id = Column(Integer, ForeignKey('enrollments.id'), primary_key=True)
#     paper_id = Column(Integer, ForeignKey('papers.id'), primary_key=True)
#
#     registration_date = Column(Date, default=date.today)
#     end_date = Column(Date, default=date.today)
#
#     # Optional relationships to back-reference
#     enrollment = relationship("Enrollment", back_populates="enrollment_papers")
#     paper = relationship("Paper", back_populates="enrollments")


class All(db.Model):
    __tablename__ = "all-students"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reg_no: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    year: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    diet: Mapped[list] = mapped_column(ARRAY(String), nullable=False)


class Role:
    # Role hierarchy: lower index == lower privilege
    hierarchy = {
        'tutor': 1,
        'lite_admin': 2,
        'pro_admin': 3,
        'super_admin': 4,
        'board_member': 5
    }

    @classmethod
    def has_access(cls, user_role, required_role):
        return cls.hierarchy.get(user_role, 0) >= cls.hierarchy.get(required_role, 0)


# Create a Staff table for all your registered staffs
class Staff(db.Model): #(UserMixin, db.Model):
    __tablename__ = "staffs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(5), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    password: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    last_active: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now())
    gender = mapped_column(String(10), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    house_address: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), nullable=False) #Student, assistant tutor, admin, super admin IT:optional Board Member: View-only access to performance, analytics, finance reports
    # department: Mapped[str] = mapped_column(String(30), nullable=False)
    access: Mapped[bool] = mapped_column(Boolean, default=True)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False) #Full-Time, Part-Time, Intern
    status: Mapped[str] = mapped_column(String(20), nullable=False) #Active, Inactive, Terminated, etc.
    hire_date: Mapped[date] = mapped_column(Date, nullable=True)
    photo: Mapped[str] = mapped_column(String(200), nullable=False) #nullable will be set to false before production
    joined: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())
    updated_at: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())
    activities = relationship("StaffActivity", back_populates="staff")
    #Guarantor name and phone number plus guarantor consent

    def has_role(self, required_role):
        return Role.has_access(self.role, required_role)
    # --------------------------------------
    # ADM - 00001   → Administrator
    # BRD - 00002   → Board
    # member
    # INT - 00003   → Intern
    # TUT - 00004   → Tutor


class StaffActivity(db.Model):
    __tablename__ = "staff_activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False) # Increase to 500
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    staff_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("staffs.id"), nullable=False)
    staff = relationship("Staff", back_populates="activities")
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    object_type: Mapped[str] = mapped_column(String(250), nullable=False) #What was acted upon (e.g., "student", "course", "document")


class Student(db.Model):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(5), nullable=False)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    reg_no: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    password: Mapped[str] = mapped_column(String(100), nullable=False)
    reg_date: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())
    acca_reg_no: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    profile_photo: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    gender = mapped_column(String(10), nullable=False)
    last_active: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now())
    joined: Mapped[date] = mapped_column(Date, nullable=False)
    # new_student: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # sponsored: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # sponsor: Mapped[str] = mapped_column(String(10), nullable=True)
    # sponsored_papers: Mapped[str] = mapped_column(String(30), nullable=True)
    # total_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    # amount_paid: Mapped[int] = mapped_column(Integer, nullable=False)
    # payment_status: Mapped[str] = mapped_column(String(20))
    house_address: Mapped[str] = mapped_column(String(200))
    referral_source: Mapped[str] = mapped_column(String(100)) # friend, (tiktok/insta/fb/tw) ad, flyer etc
    referrer: Mapped[str] = mapped_column(String(100), nullable=True)
    employment_status:  Mapped[str] = mapped_column(String(100))
    access: Mapped[bool] = mapped_column(Boolean, default=True)
    can_pay_partially: Mapped[bool] = mapped_column(Boolean, default=False)
    # revision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # retake: Mapped[bool] = mapped_column(Boolean, default=False)
    # discount: Mapped[float] = mapped_column(Float, default=0.0)
    # discount_papers: Mapped[list] = mapped_column(ARRAY(String), default=[])
    oxford_brookes: Mapped[str] = mapped_column(String(15), nullable=False)
    accurate_data: Mapped[bool] = mapped_column(Boolean, nullable=False)
    alp_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    terms_and_cond: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # refund: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # receivable: Mapped[int] = mapped_column(Integer, nullable=False)
    enrollments = relationship("Enrollment", back_populates="student")
    mcq_taken = relationship("McqHistory", back_populates="student")
    reviews = relationship("Review", back_populates="student")


class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # enrollment_no: [str] = mapped_column(String(10), nullable=False)
    student_reg_no: Mapped[str] = mapped_column(String(100))
    new_student: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())
    sponsored: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sponsor: Mapped[str] = mapped_column(String(30), nullable=True)
    sponsored_papers: Mapped[str] = mapped_column(String(30), nullable=True)
    total_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(20))
    revision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retake: Mapped[bool] = mapped_column(Boolean, default=False)
    discount: Mapped[float] = mapped_column(Float, default=0.0)
    discount_papers: Mapped[list] = mapped_column(ARRAY(String), default=[])
    refund: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    receivable: Mapped[int] = mapped_column(Integer, nullable=False)
    # paper = relationship("Paper", back_populates="student")
    student_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("students.id"), nullable=False)
    papers = relationship("Paper", secondary=student_paper, back_populates="students")
    payments = relationship("Payment", back_populates="enrollment")
    student = relationship("Student", back_populates="enrollments")
    diet_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("diets.id"), nullable=False)
    diet = relationship("Diet", back_populates="enrollments")


class Diet(db.Model):
    __tablename__ = "diets"
    id: Mapped[int] = mapped_column(Integer, nullable=False, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    available_papers: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    reg_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reg_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    template: Mapped[str] = mapped_column(String(40), nullable=False)
    enrollments = relationship("Enrollment", back_populates="diet")
    edited_at: Mapped[date] = mapped_column(Date, nullable=True)
    reviews = relationship("Review", back_populates="diet")


# Create a table for the comments on the blog posts
class Payment(db.Model):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    student_reg: Mapped[str] = mapped_column(String(100), nullable=False)
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    context: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    paystack_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message : Mapped[Optional[str]] = mapped_column(String(100))
    medium : Mapped[Optional[str]] = mapped_column(String(100), nullable=False)
    currency : Mapped[Optional[str]] = mapped_column(String(100), nullable=False)
    ip : Mapped[Optional[str]] = mapped_column(String(100))
    attempts: Mapped[Optional[int]] = mapped_column(Integer)
    history: Mapped[Optional[dict]] = mapped_column(db.JSON)
    fee: Mapped[int] = mapped_column(Integer, nullable=False)
    auth_data: Mapped[Optional[dict]] = mapped_column(db.JSON)
    fee_breakdown: Mapped[Optional[dict]] = mapped_column(db.JSON)
    customer_data: Mapped[Optional[dict]] = mapped_column(db.JSON)
    created_at: Mapped[date] = mapped_column(Date, nullable=False)
    paid_at: Mapped[date] = mapped_column(Date, nullable=False)
    receipt_number: Mapped[str] = mapped_column(String(100), nullable=False)
    receipt: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    enrollment_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("enrollments.id"), nullable=False)
    enrollment = relationship("Enrollment", back_populates="payments")


class Paper(db.Model):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default=desc)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    edited_at: Mapped[date] = mapped_column(Date, nullable=True)
    # student = relationship("Enrollment", back_populates="paper")
    students = relationship("Enrollment", secondary=student_paper, back_populates="papers")


class Attempt(db.Model):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    first_name: Mapped[str] = mapped_column(String(30), nullable=False)
    last_name: Mapped[str] = mapped_column(String(30), nullable=False)
    user_type: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[date] = mapped_column(DateTime(timezone=True), default=datetime.now)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    context: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    closed_at: Mapped[Optional[date]] = mapped_column(DateTime(timezone=True))
    payment_reference: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    payment_status: Mapped[str] = mapped_column(String(20), default='pending')
    failure_cause: Mapped[Optional[str]] = mapped_column(String(200))
    # Store everything else here
    other_data: Mapped[dict] = mapped_column(db.JSON, nullable=False)  # holds dob, courses, etc.
    # payment_data: Mapped[dict] = mapped_column(db.JSON)


class Signee(db.Model):
    __tablename__ = "signees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(5), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    password: Mapped[str] = mapped_column(String(100), nullable=False)
    first_name: Mapped[str] = mapped_column(String(30), nullable=False)
    last_name: Mapped[str] = mapped_column(String(30), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(15), unique=True)
    created_at = mapped_column(DateTime(timezone=True), default=datetime.now)
    email_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    gender = mapped_column(String(10), nullable=False)
    can_pay_partially: Mapped[bool] = mapped_column(Boolean, default=False)


class Sponsored(db.Model):
    __tablename__ = "sponsored"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(20), nullable=False)
    last_name: Mapped[str] = mapped_column(String(20), nullable=False)
    company: Mapped[str] = mapped_column(String(20), nullable=False)
    papers: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    token: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    diet_name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())
    edited_at: Mapped[date] = mapped_column(Date, nullable=True)
    #Account for this diet name in sponsored creation and use


class Action(db.Model):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(DateTime(timezone=True), default=datetime.now())
    actor: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class SystemData(db.Model):
    __tablename__ = "system_data"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_name: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[Dict[str, Any]] = mapped_column(db.JSON, default={})


class Scholarship(db.Model):
    __tablename__ = "scholarships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False)
    paper: Mapped[str] = mapped_column(String, nullable=False)
    user_type: Mapped[str] = mapped_column(String(15), nullable=False)
    discount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    diet_name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())
    edited_at: Mapped[date] = mapped_column(Date, nullable=True)
    # Might want to add type : {signee & student} | Done

class DietVersionMetadata(db.Model):
    __tablename__ = "diet_version_metadata"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_name: Mapped[str] =  mapped_column(String(15), nullable=False)
    current_version: Mapped[int] =  mapped_column(Integer, nullable=False)
    columns_config: Mapped[dict] =  mapped_column(db.JSON, nullable=False)
    refresh_day: Mapped[int] =  mapped_column(Integer)
    refresh_interval: Mapped[int] =  mapped_column(Integer)
    last_refreshed: Mapped[datetime] =  mapped_column(TIMESTAMP)
    updated_at: Mapped[datetime] =  mapped_column(TIMESTAMP, nullable=False) #, server_default=func.current_timestamp())


class DirectoryTemplate(db.Model):
    __tablename__ = "directory_template"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] =  mapped_column(String(30), nullable=False)
    title: Mapped[str] =  mapped_column(String(40), nullable=False)
    parent_id: Mapped[int] =  mapped_column(Integer, ForeignKey("directory_template.id"), nullable=True)
    path_template: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # parent = relationship("DirectoryTemplate", remote_side=[id], backref="children")
    parent = relationship("DirectoryTemplate", remote_side=[id], back_populates="children")
    children = relationship("DirectoryTemplate", back_populates="parent", cascade="all, delete-orphan")
    instances = relationship("DirectoryInstance", back_populates="template")


class DirectoryInstance(db.Model):
    __tablename__ = "directory_instance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("directory_template.id"), nullable=False)
    course_code: Mapped[str] = mapped_column(String(30), nullable=False)
    course_spec: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_id = Column(Integer, ForeignKey("directory_instance.id"), nullable=True)
    parent = relationship("DirectoryInstance", remote_side=[id], back_populates="children")
    children = relationship("DirectoryInstance", back_populates="parent", cascade="all, delete-orphan")
    template = relationship("DirectoryTemplate", back_populates="instances")
    files = relationship("File", back_populates="folder", cascade="all, delete-orphan")


class File(db.Model):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    folder_id: Mapped[int] = mapped_column(Integer, ForeignKey("directory_instance.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    date_uploaded: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    folder = relationship("DirectoryInstance", back_populates="files")


# class Folder(db.Model):
#     __tablename__ = "folders"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     course_id: Mapped[int] = mapped_column(Integer, nullable=False)
#     parent_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
#     name: Mapped[str] = mapped_column(String(30), nullable=False)
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now())


class McqTest(db.Model):
    __tablename__ = "mcq_tests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_name: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    diet_name: Mapped[str] = mapped_column(String(50), nullable=False)
    paper_code: Mapped[str] = mapped_column(String(40), nullable=False)
    course_spec: Mapped[str] = mapped_column(String(30), nullable=False)
    pass_mark: Mapped[int] = mapped_column(Integer, nullable=False)
    high_score: Mapped[int] = mapped_column(Integer, nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False) # In seconds
    date_uploaded: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())

    # Optional link to File (nullable=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), nullable=True)
    file: Mapped["File"] = relationship("File", lazy="joined")


class McqHistory(db.Model):
    __tablename__ = "mcq_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_spec: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    high_score: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict] =  mapped_column(db.JSON, nullable=False) # {1: ["A", "A"]}
    code: Mapped[str] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False) # passed or failed
    date_taken: Mapped[date] = mapped_column(Date, nullable=False, default=datetime.now())

    student_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("students.id"), nullable=False)
    student = relationship("Student", back_populates="mcq_taken")
    test_id: Mapped[int | None] = mapped_column(ForeignKey("mcq_tests.id"), nullable=False)
    test: Mapped["McqTest"] = relationship("McqTest", lazy="joined")


class GatewayTest(db.Model):
    __tablename__ = "gateway_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_spec: Mapped[str] = mapped_column(String(30), nullable=False)
    level: Mapped[str] = mapped_column(String(30), nullable=False) # Step 1? Step 2? beginner etc
    pass_mark: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_code: Mapped[str] = mapped_column(String(20), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)

    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), nullable=True)
    file: Mapped["File"] = relationship("File", lazy="joined")


class Review(db.Model):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("students.id"), nullable=False)
    student = relationship("Student", back_populates="reviews")
    paper_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("papers.id"), nullable=False)
    diet_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("diets.id"), nullable=False)
    diet = relationship("Diet", back_populates="reviews")
    paper_code: Mapped[str] = mapped_column(String(10), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[date] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.now())
# course, level, code, file address

# class File(db.Model):
#     __tablename__ = "files"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     folder_id: Mapped[int] = mapped_column(Integer, nullable=False)
#     name: Mapped[str] = mapped_column(String(30), nullable=False)
#     file_type: Mapped[str] = mapped_column(String(15), nullable=False)
#     file_path: Mapped[str] = mapped_column(String(15), nullable=False)
#     uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now())
# 4. folders Table (Hierarchical Structure)
# Use self-referencing foreign key to allow nested folders.
# folders (
#     id              SERIAL PRIMARY KEY,
#     course_id       INTEGER REFERENCES courses(id),
#     parent_id       INTEGER REFERENCES folders(id), -- NULL for top-level folders
#     name            VARCHAR,
#     created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
# )
# Examples:
# A folder called Step 1 for MAT would have course_id = MAT_ID, parent_id = NULL.
# A subfolder inside Step 1 would have parent_id = Step 1's ID.
# 5. files Table
# files (
#     id              SERIAL PRIMARY KEY,
#     folder_id       INTEGER REFERENCES folders(id),
#     name            VARCHAR,
#     file_type       VARCHAR, -- e.g. 'pdf', 'docx', 'video', etc.
#     file_path       TEXT, -- Actual storage URL or path
#     uploaded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
# )
# You could also add a description or uploaded_by if needed.

# class Receipt(Base):
#     __tablename__ = 'receipts'
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     receipt_number: Mapped[str] = mapped_column(String(100), nullable=False)
#     student_reg: Mapped[str] = mapped_column(String(100), nullable=False)
#     pdf_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
#     created_on: Mapped[date] = mapped_column(DateTime(timezone=True), default=datetime.now())
#     student_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("students.id"))
#     student = relationship("Student", back_populates="receipts")


# Add a last active columnn to the students and staff table | Done
# that residence address can be made in a way they can select with google map
# Change descr in create diet after making lengthy the learnt of a description | Done
# Add a access column ti the students and staff table so they can be blocked | Done
# Add phone_number column to staff | Done
# Add the functionality that stores when a person is active to thr db | Done
# THink of a view our project page, since they can't view papers without putting their details'
# YOu might need a review table
# Add date created to the scgolarsgips

#Add an Edit_date to sponsorship and scholarship
# Add the block column to student table and it's mechancs