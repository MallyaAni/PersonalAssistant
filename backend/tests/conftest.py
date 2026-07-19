import os

# Pytest creates several event loops, so async database uses get fresh connections.
os.environ.setdefault("DATABASE_USE_NULL_POOL", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("POSTGRES_HOST", "localhost")
