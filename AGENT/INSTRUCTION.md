You are an expert senior software developer. Your task is to generate a complete, production-ready, and configurable SQL MCP server project using Python.

Project Requirements:

Technology: Use Python 3.10+, fastmcp for the MCP server, sqlalchemy for database connections (to handle multiple dialects), and pydantic-settings for configuration.

Configuration: The server must be configurable via environment variables for DB_TYPE (e.g., postgresql, mysql, mssql, sqlite), DB_HOST, DB_PORT, DB_USER, DB_PASS, and DB_NAME.

Core MCP Tools: The server must provide the following tools to the AI:

list_tables(): Returns a list of all table and view names in the database.

get_table_schema(table_name: str): Returns the column names, data types, and constraints for a specific table.

execute_read_only_sql(sql_query: str): Executes a SQL query and returns the results.

Security (Critical): The execute_read_only_sql tool must be strictly read-only. It must parse the incoming query and reject any query that contains keywords like INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, or REVOKE. It should only permit SELECT and WITH statements.

Testing: The project must include a full pytest test suite. The tests for the tools should run integration tests against a temporary, in-memory SQLite database to validate functionality without external setup.

Instructions:

Generate the complete project by providing the file path and content for each file in the following structure. Please ensure all code is complete, follows best practices (like using SQLAlchemy connection pooling), and includes docstrings and type hints.