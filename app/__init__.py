import os
import time
from flask import Flask, g, request
from flask_cors import CORS
from dotenv import load_dotenv
from flask_socketio import SocketIO

# from flask_login import LoginManager
from .models import db, Base, migrate
from app.routes import register_routes
# from sqlalchemy import create_engine, text
# from services.diet_version_manager import create_versioned_table_and_scheduler

if os.getenv("FLASK_ENV") != "production":
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def create_postgres_db_if_not_exists(db_name, user, password, host=os.getenv("HOST"), port=os.getenv("PORT")): # host="dpg-d11it5ffte5s7399ff3g-a", port=5432)
    try:
        # Connect to default postgres database
        conn = psycopg2.connect(dbname='postgres', user=user, password=password, host=host, port=port)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}';")
        exists = cur.fetchone()

        if not exists:
            cur.execute(f"CREATE DATABASE {db_name};")
            print(f"✅ Database '{db_name}' created.")
        else:
            print(f"⚠️ Database '{db_name}' already exists.")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ Failed to create database: {e}")

# engine = create_engine(os.getenv("DATABASE_URL"))
# engine = create_engine("postgresql://postgres:root@localhost:5432/ivyleague")  # Replace with your actual URL
# login_manager = LoginManager()

# def reset_database():
#     with engine.connect() as conn:
#         trans = conn.begin()
#
#         try:
#             # Get all table names (except protected ones)
#             result = conn.execute(text("""
#                 SELECT tablename FROM pg_tables
#                 WHERE schemaname = 'public'
#                 AND tablename NOT IN ('your_core_table1', 'your_core_table2')
#             """))
#             tables = [row[0] for row in result]
#
#             for table in tables:
#                 conn.execute(text(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE;'))
#
#             trans.commit()
#         except Exception as e:
#             trans.rollback()
#             raise e
#
#     # Recreate any missing tables
#     Base.metadata.create_all(engine)

socketio = SocketIO()

def create_app():
    load_dotenv()
    if os.getenv("FLASK_ENV") != "production":
        create_postgres_db_if_not_exists(os.getenv("DBNAME"), os.getenv("DB_USER"), os.getenv("DB_PASSWORD")) #("ivyleague", "render", "vUrYJ2HGlN7pu3kohoaNfglsujbNb1OW")
    # reset_database()
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv("FLASK_APP_SECRET_KEY")
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,  # checks if connection is alive
        "pool_recycle": 1800,  # refresh every 30 mins
    }

    db.init_app(app)
    migrate.init_app(app, db)


    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.session.remove()


    with app.app_context():
    #     # db.drop_all() # For development purposes
        db.create_all()

    # create_versioned_table_and_scheduler(app)

    # Configure CORS
    allowed_origins = [
        "http://localhost:5174",
        "http://localhost:5173",
        "https://bear-deciding-wren.ngrok-free.app",
        "https://studentportal.ivyleaguenigeria.com",
        "https://preview.lms.ivyleaguenigeria.com",
        "https://preview.staff.ivyleaguenigeria.com",
        "https://lms.ivyleaguenigeria.com",
        "https://staff.ivyleaguenigeria.com"
    ]

    CORS(app, resources={r"*": {
        "origins": allowed_origins,
        "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE", "PATCH"],
        "allow_headers": ["Content-Type", "Access", "Authorization", "ngrok-skip-browser-warning"],
        "supports_credentials": True
    }})

    @app.before_request
    def log_request_start():
        g._request_start_time = time.perf_counter()
        print(
            f"[HTTP] -> {request.method} {request.full_path.rstrip('?')} "
            f"from={request.remote_addr}"
        )

    @app.after_request
    def log_request_end(response):
        start = getattr(g, "_request_start_time", None)
        duration_ms = (
            (time.perf_counter() - start) * 1000 if start is not None else 0
        )
        print(
            f"[HTTP] <- {request.method} {request.path} "
            f"status={response.status_code} duration_ms={duration_ms:.2f}"
        )
        return response

    # Initialize SocketIO with gevent + verbose transport logs.
    socketio.init_app(
        app,
        cors_allowed_origins=allowed_origins,
        async_mode="gevent",
        logger=True,
        engineio_logger=True,
    )

    # Import and register routes
    register_routes(app)
    
    # Import socket handlers to register them (must be after SocketIO is initialized)
    from app import socket as socket_handlers  # noqa: F401

    return app
