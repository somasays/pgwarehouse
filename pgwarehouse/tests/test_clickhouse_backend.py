import os
import pytest
import tempfile
from unittest.mock import MagicMock, patch

from pgwarehouse.clickhouse_backend import ClickHouseBackend

# Skip all tests if clickhouse-driver is not available
clickhouse_driver = pytest.importorskip("clickhouse_driver")

@pytest.fixture
def config():
    return {
        'clickhouse_host': 'localhost',
        'clickhouse_port': 9000,
        'clickhouse_user': 'default',
        'clickhouse_password': '',
        'clickhouse_database': 'default',
        'debug': True
    }

@pytest.fixture
def mock_parent():
    parent = MagicMock()
    parent.data_dir = tempfile.mkdtemp()
    parent.debug = True
    return parent

@pytest.fixture
def mock_client():
    with patch('clickhouse_driver.Client') as mock:
        client_instance = MagicMock()
        mock.return_value = client_instance
        yield client_instance

@pytest.fixture
def clickhouse_backend(config, mock_parent, mock_client):
    with patch('clickhouse_driver.Client', return_value=mock_client):
        backend = ClickHouseBackend(config, mock_parent)
        backend.client = mock_client
        return backend

def test_initialization(config, mock_parent, mock_client):
    with patch('clickhouse_driver.Client', return_value=mock_client):
        backend = ClickHouseBackend(config, mock_parent)
        assert backend is not None
        assert backend.client is not None

def test_list_tables(clickhouse_backend, mock_client):
    mock_client.execute.return_value = [('table1',), ('table2',)]
    
    tables = clickhouse_backend.list_tables()
    
    mock_client.execute.assert_called_with('SHOW TABLES')
    assert tables == ['table1', 'table2']

def test_drop_table(clickhouse_backend, mock_client):
    clickhouse_backend._drop_table('test_table')
    
    mock_client.execute.assert_called_with('DROP TABLE IF EXISTS "test_table"')

def test_count_table(clickhouse_backend, mock_client):
    mock_client.execute.return_value = [(100,)]
    
    count = clickhouse_backend.count_table('test_table')
    
    mock_client.execute.assert_called_with('SELECT count(*) FROM "test_table"')
    assert count == 100

def test_query_table(clickhouse_backend, mock_client):
    # Setup mock response
    mock_client.execute.return_value = [
        (1, 'Alice'),
        (2, 'Bob')
    ]
    
    # Test basic query
    rows = list(clickhouse_backend._query_table('test_table', ['id', 'name']))
    
    # Verify SQL was correctly constructed
    mock_client.execute.assert_called_with('SELECT "id", "name" FROM "test_table"')
    assert len(rows) == 2
    assert rows[0] == (1, 'Alice')
    
    # Test with condition
    mock_client.execute.return_value = [(2, 'Bob')]
    rows = list(clickhouse_backend._query_table('test_table', ['id', 'name'], 'id > 1'))
    
    mock_client.execute.assert_called_with('SELECT "id", "name" FROM "test_table" WHERE id > 1')
    assert len(rows) == 1
    assert rows[0] == (2, 'Bob')

def test_load_table(clickhouse_backend, mock_parent, mock_client, tmp_path):
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
    
    # Test load_table
    clickhouse_backend.load_table("test_load")
    
    # Check that the correct SQL was executed
    create_table_call = mock_client.execute.call_args_list[0][0][0]
    assert 'CREATE TABLE "test_load"' in create_table_call
    assert '"id" Int32' in create_table_call
    assert '"name" String' in create_table_call
    assert '"age" Int32' in create_table_call
    
    # Check that the data insertion was attempted
    assert mock_client.execute.call_count >= 2

def test_update_table(clickhouse_backend, mock_parent, mock_client, tmp_path):
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
    mock_client.execute.return_value = None
    
    # Mock that table exists
    mock_client.execute.side_effect = [
        [('test_update',)],  # For SHOW TABLES LIKE
        None,  # For CREATE TEMPORARY TABLE
        None,  # For INSERT INTO TEMPORARY TABLE
        None,  # For ALTER TABLE ... DELETE
        None,  # For INSERT INTO ... SELECT
        None   # For DROP TABLE TEMPORARY
    ]
    
    # Test update_table
    clickhouse_backend.update_table("test_update", ["id"])
    
    # Check that the ALTER TABLE DELETE was called
    delete_call = [call for call in mock_client.execute.call_args_list if 'ALTER TABLE' in call[0][0] and 'DELETE' in call[0][0]]
    assert len(delete_call) > 0

def test_escape_sql_identifier(clickhouse_backend):
    # Test SQL identifier escaping
    safe_id = clickhouse_backend._escape_sql_identifier("test-table")
    assert safe_id == '"test-table"'
    
    safe_id = clickhouse_backend._escape_sql_identifier("select")
    assert safe_id == '"select"'

def test_sql_injection_prevention(clickhouse_backend, mock_client):
    # Test with potentially dangerous table name
    with pytest.raises(Exception):
        clickhouse_backend._query_table("test_table; DROP TABLE users", ["id"])
    
    # Test with potentially dangerous column name
    with pytest.raises(Exception):
        clickhouse_backend._query_table("test_table", ["id; DROP TABLE users"])
    
    # Test with potentially dangerous condition
    with pytest.raises(Exception):
        clickhouse_backend._query_table("test_table", ["id"], "1=1; DROP TABLE users")