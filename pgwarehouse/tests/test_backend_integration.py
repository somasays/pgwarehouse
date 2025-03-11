import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from pgwarehouse.backend import Backend
from pgwarehouse.duckdb_backend import DuckDBBackend
from pgwarehouse.clickhouse_backend import ClickHouseBackend
from pgwarehouse.snowflake_backend import SnowflakeBackend

# Skip tests if implementations not available
clickhouse_driver_available = pytest.importorskip("clickhouse_driver", reason="clickhouse-driver not installed")
snowflake_available = pytest.importorskip("snowflake.connector", reason="snowflake-connector-python not installed")

@pytest.fixture
def mock_parent():
    parent = MagicMock()
    parent.data_dir = tempfile.mkdtemp()
    parent.debug = True
    
    # Create mock schema and data
    schema = {
        "columns": [
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "value", "type": "double precision"}
        ]
    }
    parent.extract.return_value = schema
    
    return parent

@pytest.fixture
def backends(mock_parent):
    # Create configurations for each backend
    configs = {
        "duckdb": {
            "duckdb_path": ":memory:",
            "debug": True
        },
        "clickhouse": {
            "clickhouse_host": "localhost",
            "clickhouse_database": "default",
            "debug": True
        },
        "snowflake": {
            "snowflake_account": "test_account",
            "snowflake_user": "test_user",
            "snowflake_password": "test_password",
            "snowflake_database": "test_db",
            "snowflake_schema": "public",
            "snowflake_warehouse": "test_warehouse",
            "debug": True
        }
    }
    
    # Initialize DuckDB backend
    duckdb_backend = DuckDBBackend(configs["duckdb"], mock_parent)
    
    # Mock ClickHouse and Snowflake backends
    with patch('clickhouse_driver.Client') as ch_mock:
        ch_client = MagicMock()
        ch_mock.return_value = ch_client
        
        clickhouse_backend = ClickHouseBackend(configs["clickhouse"], mock_parent)
        clickhouse_backend.client = ch_client
        
        with patch('snowflake.connector.connect') as sf_mock:
            sf_conn = MagicMock()
            sf_cursor = MagicMock()
            sf_conn.cursor.return_value = sf_cursor
            sf_cursor.__enter__.return_value = sf_cursor
            sf_mock.return_value = sf_conn
            
            snowflake_backend = SnowflakeBackend(configs["snowflake"], mock_parent)
            snowflake_backend.conn = sf_conn
            
            return {
                "duckdb": duckdb_backend,
                "clickhouse": clickhouse_backend,
                "snowflake": snowflake_backend
            }

class TestBackendIntegration:
    """Integration tests for backends"""
    
    @pytest.mark.parametrize("backend_name", ["duckdb", "clickhouse", "snowflake"])
    def test_create_and_query(self, backends, backend_name, tmp_path, mock_parent):
        backend = backends[backend_name]
        
        # Create test table
        table_name = "test_table"
        
        # Setup CSV data
        csv_dir = os.path.join(tmp_path, f"{table_name}_data")
        os.makedirs(csv_dir, exist_ok=True)
        
        with open(os.path.join(csv_dir, "data.csv"), "w") as f:
            f.write("id,name,value\n")
            f.write("1,Alice,10.5\n")
            f.write("2,Bob,20.7\n")
            f.write("3,Charlie,30.9\n")
        
        # Mock csv_dir method
        mock_parent.csv_dir.return_value = csv_dir
        
        # Test operations common to all backends
        # 1. Drop table if exists
        backend._drop_table(table_name)
        
        # 2. Load table
        if backend_name == "snowflake":
            # Handle file operations for Snowflake
            with patch('builtins.open', MagicMock()):
                backend.load_table(table_name)
        else:
            backend.load_table(table_name)
        
        # 3. Count rows
        if backend_name == "duckdb":
            # For DuckDB, we can actually run the query
            count = backend.count_table(table_name)
            assert count == 3
        elif backend_name == "clickhouse":
            # Mock ClickHouse response
            backend.client.execute.return_value = [(3,)]
            count = backend.count_table(table_name)
            assert count == 3
        elif backend_name == "snowflake":
            # Mock Snowflake response
            cursor = backend.conn.cursor.return_value
            cursor.fetchone.return_value = (3,)
            count = backend.count_table(table_name)
            assert count == 3
        
        # 4. Query table
        if backend_name == "duckdb":
            # For DuckDB, we can actually run the query
            rows = list(backend._query_table(table_name, ["id", "name"]))
            assert len(rows) == 3
            assert rows[0][0] == 1
            assert rows[0][1] == "Alice"
        elif backend_name == "clickhouse":
            # Mock ClickHouse response
            backend.client.execute.return_value = [
                (1, "Alice"),
                (2, "Bob"),
                (3, "Charlie")
            ]
            rows = list(backend._query_table(table_name, ["id", "name"]))
            assert len(rows) == 3
            assert rows[0] == (1, "Alice")
        elif backend_name == "snowflake":
            # Mock Snowflake response
            cursor = backend.conn.cursor.return_value
            cursor.fetchall.return_value = [
                (1, "Alice"),
                (2, "Bob"),
                (3, "Charlie")
            ]
            rows = list(backend._query_table(table_name, ["id", "name"]))
            assert len(rows) == 3
            assert rows[0] == (1, "Alice")
    
    @pytest.mark.parametrize("backend_name", ["duckdb", "clickhouse", "snowflake"])
    def test_update_operations(self, backends, backend_name, tmp_path, mock_parent):
        backend = backends[backend_name]
        
        # Create and update test table
        table_name = "test_update"
        
        # First setup the table
        if backend_name == "duckdb":
            backend.conn.execute("""
                CREATE TABLE test_update (
                    id INTEGER, 
                    name VARCHAR,
                    value DOUBLE
                )
            """)
            backend.conn.execute("""
                INSERT INTO test_update VALUES 
                (1, 'Alice', 10.5),
                (2, 'Bob', 20.7)
            """)
        
        # Setup CSV data for update
        csv_dir = os.path.join(tmp_path, f"{table_name}_data")
        os.makedirs(csv_dir, exist_ok=True)
        
        with open(os.path.join(csv_dir, "data.csv"), "w") as f:
            f.write("id,name,value\n")
            f.write("2,Bob,25.0\n")  # Updated value
            f.write("3,Charlie,30.9\n")  # New row
        
        # Mock csv_dir method
        mock_parent.csv_dir.return_value = csv_dir
        
        # Test update operations
        if backend_name == "duckdb":
            # For DuckDB, we can actually run the update
            backend.update_table(table_name, ["id"])
            
            # Verify the update
            rows = {row[0]: row for row in backend._query_table(table_name, ["id", "name", "value"])}
            assert len(rows) == 3
            assert rows[1] == (1, "Alice", 10.5)  # Unchanged
            assert rows[2] == (2, "Bob", 25.0)    # Updated value
            assert rows[3] == (3, "Charlie", 30.9)  # New row
        elif backend_name == "clickhouse":
            # Just verify the SQL operations were called
            backend.update_table(table_name, ["id"])
            
            # Check that temporary table and MERGE operations were called
            create_temp_calls = [call for call in backend.client.execute.call_args_list 
                                if 'CREATE TEMPORARY TABLE' in str(call)]
            assert len(create_temp_calls) >= 1
            
            alter_calls = [call for call in backend.client.execute.call_args_list 
                          if 'ALTER TABLE' in str(call) and 'DELETE' in str(call)]
            assert len(alter_calls) >= 1
        elif backend_name == "snowflake":
            # Handle file operations for Snowflake
            with patch('builtins.open', MagicMock()):
                backend.update_table(table_name, ["id"])
            
            # Check that MERGE operation was called
            cursor = backend.conn.cursor.return_value
            merge_calls = [call for call in cursor.execute.call_args_list 
                          if 'MERGE INTO' in str(call)]
            assert len(merge_calls) >= 1