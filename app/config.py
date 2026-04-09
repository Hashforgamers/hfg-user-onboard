# app/config.py

import os
from services.config_load import load_key_from_file

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URI',
        'postgresql://postgres:postgres@db:5432/vendor_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Add safe engine options for Neon / Postgres
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SEC", "1800")),
        "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "40")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT_SEC", "30")),
    }

    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'dev-jwt-secret-change-me-please-32bytes')

    # Mail server settings
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.hashforgamers.co.in")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))  # 587 for TLS
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "t")
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() in ("true", "1", "t")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")  # Your SMTP username
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")  # Your SMTP password
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@hashforgamers.co.in")

    # Firebase
    FIREBASE_KEY = os.getenv('FIREBASE_KEY') 

    # Encryption keys
    ENCRYPT_PRIVATE_KEY = load_key_from_file(os.getenv("ENCRYPT_PRIVATE_KEY_PATH"))
    ENCRYPT_PUBLIC_KEY = load_key_from_file(os.getenv("ENCRYPT_PUBLIC_KEY_PATH"))

    # API performance / observability knobs
    API_ENABLE_TIMING_HEADERS = os.getenv("API_ENABLE_TIMING_HEADERS", "true").lower() in ("true", "1", "t", "yes", "y")
    API_SLOW_REQUEST_MS = int(os.getenv("API_SLOW_REQUEST_MS", "120") or 120)
    API_PUBLIC_CACHE_CONTROL = os.getenv("API_PUBLIC_CACHE_CONTROL", "public, max-age=15, stale-while-revalidate=30")
    API_PRIVATE_CACHE_CONTROL = os.getenv("API_PRIVATE_CACHE_CONTROL", "no-store")

    # Endpoint-level microcache profiles
    API_MICROCACHE_MAX_ITEMS = int(os.getenv("API_MICROCACHE_MAX_ITEMS", "50000") or 50000)
    API_CACHE_USERS_VOUCHER_TTL_SEC = int(os.getenv("API_CACHE_USERS_VOUCHER_TTL_SEC", "20") or 20)
    API_CACHE_USERS_HASH_COINS_TTL_SEC = int(os.getenv("API_CACHE_USERS_HASH_COINS_TTL_SEC", "10") or 10)
    API_CACHE_USERS_WALLET_TTL_SEC = int(os.getenv("API_CACHE_USERS_WALLET_TTL_SEC", "20") or 20)
    API_CACHE_USERS_TRANSACTIONS_TTL_SEC = int(os.getenv("API_CACHE_USERS_TRANSACTIONS_TTL_SEC", "15") or 15)
    API_CACHE_USER_AVAILABLE_PASSES_TTL_SEC = int(os.getenv("API_CACHE_USER_AVAILABLE_PASSES_TTL_SEC", "20") or 20)
    API_CACHE_USER_ALL_PASSES_TTL_SEC = int(os.getenv("API_CACHE_USER_ALL_PASSES_TTL_SEC", "20") or 20)
    API_CACHE_USER_PASSES_TTL_SEC = int(os.getenv("API_CACHE_USER_PASSES_TTL_SEC", "10") or 10)
    API_CACHE_USER_PASSES_HISTORY_TTL_SEC = int(os.getenv("API_CACHE_USER_PASSES_HISTORY_TTL_SEC", "15") or 15)
    API_CACHE_PASS_DETAILS_TTL_SEC = int(os.getenv("API_CACHE_PASS_DETAILS_TTL_SEC", "30") or 30)
    API_CACHE_VENDOR_EXTRAS_TTL_SEC = int(os.getenv("API_CACHE_VENDOR_EXTRAS_TTL_SEC", "20") or 20)
    API_CACHE_USERS_NOTIFICATIONS_TTL_SEC = int(os.getenv("API_CACHE_USERS_NOTIFICATIONS_TTL_SEC", "20") or 20)
    USER_FID_AUTH_RESPONSE_CACHE_TTL_SEC = int(os.getenv("USER_FID_AUTH_RESPONSE_CACHE_TTL_SEC", "20") or 20)
    USER_CREATE_TIMING_LOGS = os.getenv("USER_CREATE_TIMING_LOGS", "true").lower() in ("true", "1", "t", "yes", "y")
    USER_SIGNUP_EMAIL_RECOVERY_ENABLED = os.getenv("USER_SIGNUP_EMAIL_RECOVERY_ENABLED", "false").lower() in ("true", "1", "t", "yes", "y")
    USER_SIGNUP_EMAIL_LINK_FID_ENABLED = os.getenv("USER_SIGNUP_EMAIL_LINK_FID_ENABLED", "false").lower() in ("true", "1", "t", "yes", "y")

    # Auth performance + logging controls
    AUTH_DEBUG_LOGS = os.getenv("AUTH_DEBUG_LOGS", "false").lower() in ("true", "1", "t", "yes", "y")
    AUTH_DECRYPT_CACHE_TTL_SEC = int(os.getenv("AUTH_DECRYPT_CACHE_TTL_SEC", "300") or 300)
    AUTH_ALLOW_EXPIRED_TOKENS = os.getenv("AUTH_ALLOW_EXPIRED_TOKENS", "false").lower() in ("true", "1", "t", "yes", "y")
    JWT_REQUIRE_STRONG_SECRET = os.getenv("JWT_REQUIRE_STRONG_SECRET", "true").lower() in ("true", "1", "t", "yes", "y")
