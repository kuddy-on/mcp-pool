import os

# Configure the database before application modules are imported during test collection.
# This keeps tests isolated from the developer's real SQLite database.
os.environ["MCP_POOL_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["MCP_POOL_ENVIRONMENT"] = "test"
os.environ["MCP_POOL_SECRET_KEY"] = "test-only-secret-key"
