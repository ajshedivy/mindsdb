from typing import Text, Dict, Optional, Any

import ibm_db_dbi
from ibm_db_sa.ibm_db import DB2Dialect_ibm_db as DB2Dialect
from mindsdb_sql.parser.ast.base import ASTNode
from mindsdb_sql.render.sqlalchemy_render import SqlalchemyRender
import pandas as pd

from mindsdb.integrations.libs.base import DatabaseHandler
from mindsdb.integrations.libs.response import (
    HandlerStatusResponse as StatusResponse,
    HandlerResponse as Response,
    RESPONSE_TYPE,
)
from mindsdb.utilities import log


logger = log.getLogger(__name__)


class DB2Handler(DatabaseHandler):
    name = "DB2"

    def __init__(self, name: Text, connection_data: Optional[Dict], **kwargs: Any) -> None:
        """
        Initializes the handler.
        Args:
            name (Text): The name of the handler instance.
            connection_data (Dict): The connection data required to connect to the IBM DB2 database.
            kwargs: Arbitrary keyword arguments.
        """
        super().__init__(name)
        self.connection_data = connection_data
        self.kwargs = kwargs

        self.connection = None
        self.is_connected = False

    def __del__(self) -> None:
        """
        Closes the connection when the handler instance is deleted.
        """
        if self.is_connected:
            self.disconnect()

    def connect(self) -> ibm_db_dbi.Connection:
        """
        Establishes a connection to a IBM DB2 database.

        Raises:
            ValueError: If the required connection parameters are not provided.
            ibm_db_dbi.OperationalError: If an error occurs while connecting to the IBM DB2 database.

        Returns:
            ibm_db_dbi.Connection: A connection object to the IBM DB2 database.
        """
        if self.is_connected:
            return self.connection
        
        # Mandatory connection parameters.
        if not all(key in self.connection_data for key in ['host', 'user', 'password', 'database']):
            raise ValueError('Required parameters (host, user, password, database) must be provided.')

        connection_string = f"DRIVER={'IBM DB2 ODBC DRIVER'};DATABASE={self.connection_data['database']};HOST={self.connection_data['host']};PROTOCOL=TCPIP;UID={self.connection_data['user']};PWD={self.connection_data['password']};"

        # Optional connection parameters.
        if 'port' in self.connection_data:
            connection_string += f"PORT={self.connection_data['port']};"

        if 'schema' in self.connection_data:
            connection_string += f"CURRENTSCHEMA={self.connection_data['schema']};"

        try:
            self.connection = ibm_db_dbi.pconnect(connection_string, "", "")
            self.is_connected = True
            return self.connection
        except Exception as e:
            logger.error(f"Error while connecting to {self.connection_data.get('database')}, {e}")

    def disconnect(self) -> None:
        """
        Closes the connection to the IBM DB2 database if it's currently open.
        """
        if not self.is_connected:
            return

        self.connection.close()
        self.is_connected = False

    def check_connection(self) -> StatusResponse:
        """
        Checks the status of the connection to the IBM DB2 database.

        Returns:
            StatusResponse: An object containing the success status and an error message if an error occurs.
        """
        responseCode = StatusResponse(False)
        need_to_close = self.is_connected is False

        try:
            self.connect()
            responseCode.success = True
        except Exception as e:
            logger.error(f"Error connecting to database {self.connection_data.get('database')}, {e}!")
            responseCode.error_message = str(e)
        finally:
            if responseCode.success is True and need_to_close:
                self.disconnect()
            if responseCode.success is False and self.is_connected is True:
                self.is_connected = False

        return responseCode

    def native_query(self, query: Text) -> Response:
        """
        Executes a SQL query on the IBM DB2 database and returns the result (if any).

        Args:
            query (str): The SQL query to be executed.

        Returns:
            Response: A response object containing the result of the query or an error message.
        """
        need_to_close = self.is_connected is False
        query = query.upper()
        conn = self.connect()
        with conn.cursor() as cur:
            try:
                cur.execute(query)

                if cur._result_set_produced:
                    result = cur.fetchall()
                    response = Response(
                        RESPONSE_TYPE.TABLE,
                        data_frame=pd.DataFrame(
                            result, columns=[x[0] for x in cur.description]
                        ),
                    )
                else:
                    response = Response(RESPONSE_TYPE.OK)
                self.connection.commit()
            except Exception as e:
                logger.error(f"Error running query: {query} on {self.connection_data.get('database')}!")
                response = Response(RESPONSE_TYPE.ERROR, error_message=str(e))
                self.connection.rollback()

        if need_to_close is True:
            self.disconnect()

        return response

    def query(self, query: ASTNode) -> Response:
        """
        Executes a SQL query represented by an ASTNode on the IBM DB2 database and retrieves the data (if any).

        Args:
            query (ASTNode): An ASTNode representing the SQL query to be executed.

        Returns:
            Response: The response from the `native_query` method, containing the result of the SQL query execution.
        """
        renderer = SqlalchemyRender(DB2Dialect)
        query_str = renderer.get_string(query, with_failback=True)
        return self.native_query(query_str)

    def get_tables(self) -> Response:
        """
        Retrieves a list of all non-system tables and views in the current schema of the IBM DB2 database.

        Returns:
            Response: A response object containing the list of tables and views, formatted as per the `Response` class.
        """
        self.connect()

        result = self.connection.tables(self.connection.current_schema)

        tables = []
        for table in result:
            tables.append(
                {
                    "TABLE_NAME": table["TABLE_NAME"],
                    "TABLE_SCHEMA": table["TABLE_SCHEM"],
                    "TABLE_TYPE": table["TABLE_TYPE"],
                }
            )

        response = Response(
            RESPONSE_TYPE.TABLE,
            data_frame=pd.DataFrame(tables)
        )

        return response

    def get_columns(self, table_name: Text) -> Response:
        """
        Retrieves column details for a specified table in the IBM DB2 database.

        Args:
            table_name (Text): The name of the table for which to retrieve column information.

        Raises:
            ValueError: If the 'table_name' is not a valid string.

        Returns:
            Response: A response object containing the column details.
        """
        if not table_name or not isinstance(table_name, str):
            raise ValueError("Invalid table name provided.")

        self.connect()

        result = self.connection.columns(table_name=table_name)
        
        columns = [column["COLUMN_NAME"] for column in result]

        response = Response(
            RESPONSE_TYPE.TABLE,
            data_frame=pd.DataFrame(columns, columns=["COLUMN_NAME"])
        )

        return response
