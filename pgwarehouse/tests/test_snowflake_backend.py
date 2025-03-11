import os
import pytest
import tempfile
from unittest.mock import MagicMock, patch

from pgwarehouse.snowflake_backend import SnowflakeBackend

# Skip all tests if snowflake-connector-python is not available
snowflake = pytest.importorskip("snowflake.connector")

@pytest.fixture
def config():
    return {
        'snowflake_account': 'test_account',
        'snowflake_user': 'test_user',
        'snowflake_password': 'test_password',
        'snowflake_database': 'test_db',
        'snowflake_schema': 'public',
        'snowflake_warehouse': 'test_warehouse',
        'debug': True
    }

@pytest.fixture
def mock_parent():
    parent = MagicMock()
    parent.data_dir = tempfile.mkdtemp()
    parent.debug = True
    return parent

@pytest.fixture
def mock_connection():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    
    # Configure cursor context manager
    cursor.__enter__.return_value = cursor
    
    return conn, cursor

@pytest.fixture
def snowflake_backend(config, mock_parent, mock_connection):
    conn, cursor = mock_connection
    with patch('snowflake.connector.connect', return_value=conn):
        backend = SnowflakeBackend(config, mock_parent)
        backend.conn = conn
        return backend, cursor

def test_initialization(config, mock_parent, mock_connection):
    conn, _ = mock_connection
    with patch('snowflake.connector.connect', return_value=conn):
        backend = SnowflakeBackend(config, mock_parent)
        assert backend is not None
        assert backend.conn is not None
        
        # Check that the settings were applied
        assert backend.database == 'test_db'
        assert backend.schema == 'public'
        assert backend.warehouse == 'test_warehouse'

def test_list_tables(snowflake_backend):
    backend, cursor = snowflake_backend
    
    # Setup mock response
    cursor.fetchall.return_value = [('table1',), ('table2',)]
    
    tables = backend.list_tables()
    
    # Verify correct SQL was executed
    cursor.execute.assert_called_with(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    assert tables == ['table1', 'table2']

def test_drop_table(snowflake_backend):
    backend, cursor = snowflake_backend
    
    backend._drop_table('test_table')
    
    cursor.execute.assert_called_with('DROP TABLE IF EXISTS "test_table"')

def test_count_table(snowflake_backend):
    backend, cursor = snowflake_backend
    
    # Setup mock response
    cursor.fetchone.return_value = (100,)
    
    count = backend.count_table('test_table')
    
    cursor.execute.assert_called_with('SELECT count(*) FROM "test_table"')
    assert count == 100

def test_query_table(snowflake_backend):
    backend, cursor = snowflake_backend
    
    # Setup mock response for basic query
    cursor.fetchall.return_value = [
        (1, 'Alice'),
        (2, 'Bob')
    ]
    
    # Test basic query
    rows = list(backend._query_table('test_table', ['id', 'name']))
    
    # Verify SQL was correctly constructed
    cursor.execute.assert_called_with('SELECT "id", "name" FROM "test_table"')
    assert len(rows) == 2
    assert rows[0] == (1, 'Alice')
    
    # Setup mock response for query with condition
    cursor.fetchall.return_value = [(2, 'Bob')]
    
    # Test with condition
    rows = list(backend._query_table('test_table', ['id', 'name'], 'id > 1'))
    
    cursor.execute.assert_called_with('SELECT "id", "name" FROM "test_table" WHERE id > 1')
    assert len(rows) == 1
    assert rows[0] == (2, 'Bob')

def test_load_table(snowflake_backend, mock_parent, tmp_path):
    backend, cursor = snowflake_backend
    
    # Create a test CSV file
    csv_dir = os.path.join(tmp_path, "test_load_data")
    os.makedirs(csv_dir, exist_ok=True)
    
    with open(os.path.join(csv_dir, "data.csv"), "w") as f:
        f.write("id,name,age\n")
        f.write("1,Alice,30\n")
        f.write("2,Bob,25\n")
    
    schema = {
        "columns": [
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "age", "type": "integer"}
        ]
    }
    
    # Mock methods
    mock_parent.csv_dir.return_value = csv_dir
    mock_parent.extract.return_value = schema
    
    # Mock file operations
    with patch('builtins.open', MagicMock()):
        backend.load_table("test_load")
    
    # Check that CREATE TABLE was called with correct types
    create_calls = [call for call in cursor.execute.call_args_list 
                    if 'CREATE TABLE' in call[0][0]]
    assert len(create_calls) >= 1
    create_sql = create_calls[0][0][0]
    assert 'CREATE TABLE "test_load"' in create_sql
    assert '"id" NUMBER' in create_sql
    assert '"name" VARCHAR' in create_sql
    assert '"age" NUMBER' in create_sql
    
    # Check that PUT and COPY commands were executed
    put_calls = [call for call in cursor.execute.call_args_list 
                if 'PUT' in call[0][0]]
    assert len(put_calls) >= 1
    
    copy_calls = [call for call in cursor.execute.call_args_list 
                if 'COPY INTO' in call[0][0]]
    assert len(copy_calls) >= 1

def test_update_table(snowflake_backend, mock_parent, tmp_path):
    backend, cursor = snowflake_backend
    
    # Create a test CSV file
    csv_dir = os.path.join(tmp_path, "test_update_data")
    os.makedirs(csv_dir, exist_ok=True)
    
    with open(os.path.join(csv_dir, "data.csv"), "w") as f:
        f.write("id,name,age\n")
        f.write("2,Bob,26\n")
        f.write("3,Charlie,35\n")
    
    schema = {
        "columns": [
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "age", "type": "integer"}
        ]
    }
    
    # Mock methods
    mock_parent.csv_dir.return_value = csv_dir
    mock_parent.extract.return_value = schema
    
    # Mock file operations
    with patch('builtins.open', MagicMock()):
        backend.update_table("test_update", ["id"])
    
    # Check that a temporary table was created
    temp_table_calls = [call for call in cursor.execute.call_args_list 
                        if 'CREATE TEMPORARY TABLE' in call[0][0]]
    assert len(temp_table_calls) >= 1
    
    # Check that MERGE command was executed
    merge_calls = [call for call in cursor.execute.call_args_list 
                  if 'MERGE INTO' in call[0][0]]
    assert len(merge_calls) >= 1
    merge_sql = merge_calls[0][0][0]
    assert 'MERGE INTO "test_update"' in merge_sql
    assert 'WHEN MATCHED THEN UPDATE' in merge_sql
    assert 'WHEN NOT MATCHED THEN INSERT' in merge_sql

def test_escape_sql_identifier(snowflake_backend):
    backend, _ = snowflake_backend
    
    # Test SQL identifier escaping
    safe_id = backend._escape_sql_identifier("test-table")
    assert safe_id == '"test-table"'
    
    safe_id = backend._escape_sql_identifier("order")
    assert safe_id == '"order"'

def test_sql_injection_prevention(snowflake_backend):
    backend, _ = snowflake_backend
    
    # Test with potentially dangerous table name
    with pytest.raises(Exception):
        backend._query_table("test_table; DROP TABLE users", ["id"])
    
    # Test with potentially dangerous column name
    with pytest.raises(Exception):
        backend._query_table("test_table", ["id; DROP TABLE users"])
    
    # Test with potentially dangerous condition
    with pytest.raises(Exception):
        backend._query_table("test_table", ["id"], "1=1; DROP TABLE users")